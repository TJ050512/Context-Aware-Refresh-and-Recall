#!/usr/bin/env python3
"""Read-only audit and screening analysis for the six-method v4 smoke run.

The script never edits the source artifact.  It checks the paired-cell,
budget, safety, and route-attribution contracts before computing exploratory
throughput effects.  A one-seed smoke can only authorize a larger development
run; it can never support a paper or SOTA claim.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence


SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
ANALYSIS_SCHEMA = "dai.new-method-smoke-analysis/v1"
TARGET_METHODS = (
    "exact_even_B25",
    "bootstrap_only",
    "js_B25",
    "js_cap_B25",
    "causal_block_B25",
    "proposed_no_cohort_B25",
)
BASELINE_EXACT = "exact_even_B25"
BASELINE_BOOTSTRAP = "bootstrap_only"
EXACT_B25_METHODS = frozenset(
    {
        "exact_even_B25",
        "js_B25",
        "causal_block_B25",
        "proposed_no_cohort_B25",
    }
)
ALLOWED_ROUTE_REASONS = frozenset(
    {"init_pp", "task_change", "inherited_goal_route"}
)

# These are screening thresholds, not confirmatory claim thresholds.
MIN_AGGREGATE_RELATIVE_GAIN = 0.01
MAX_WORST_WORKLOAD_REGRESSION = -0.01
NONSTATIONARY_WORKLOADS = ("abrupt", "recurrent")


class SmokeArtifactError(ValueError):
    """The artifact cannot be safely compared."""


def _canonical(value: Any) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _as_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if not _is_int(value) or value < minimum:
        raise SmokeArtifactError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _as_number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SmokeArtifactError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise SmokeArtifactError(f"{name} must be a finite number >= {minimum}")
    return result


def _require(mapping: Mapping[str, Any], field: str, context: str) -> Any:
    if field not in mapping:
        raise SmokeArtifactError(f"{context}.{field} is required")
    return mapping[field]


def _run_key(run: Mapping[str, Any]) -> tuple[int, str, str]:
    return (int(run["seed"]), str(run["map_id"]), str(run["workload"]))


def _failure(
    failures: list[dict[str, Any]],
    category: str,
    check: str,
    run: Mapping[str, Any] | None = None,
    detail: str | None = None,
) -> None:
    item: dict[str, Any] = {"category": category, "check": check}
    if run is not None:
        item["cell"] = {
            "method": run.get("method"),
            "seed": run.get("seed"),
            "map_id": run.get("map_id"),
            "workload": run.get("workload"),
        }
    if detail:
        item["detail"] = detail
    failures.append(item)


def _validate_top_level(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema") != SOURCE_SCHEMA:
        raise SmokeArtifactError(
            f"schema must be {SOURCE_SCHEMA!r}, got {artifact.get('schema')!r}"
        )
    if artifact.get("status") != "complete":
        raise SmokeArtifactError("artifact.status must be 'complete'")
    if artifact.get("split") != artifact.get("evidence_class"):
        raise SmokeArtifactError("split and evidence_class must match")
    methods = artifact.get("methods")
    if not isinstance(methods, list) or len(methods) != len(set(methods)):
        raise SmokeArtifactError("artifact.methods must be a unique list")
    missing = set(TARGET_METHODS) - set(methods)
    if missing:
        raise SmokeArtifactError(f"missing target methods: {sorted(missing)}")
    seeds = artifact.get("seeds")
    workloads = artifact.get("workloads")
    if not isinstance(seeds, list) or not seeds or len(seeds) != len(set(seeds)):
        raise SmokeArtifactError("artifact.seeds must be a non-empty unique list")
    if not all(_is_int(seed) for seed in seeds):
        raise SmokeArtifactError("artifact.seeds values must be integers")
    if (
        not isinstance(workloads, list)
        or not workloads
        or len(workloads) != len(set(workloads))
        or not all(isinstance(item, str) and item for item in workloads)
    ):
        raise SmokeArtifactError("artifact.workloads must be a non-empty unique list")


def _normalize_runs(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_runs = artifact.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise SmokeArtifactError("artifact.runs must be a non-empty list")
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for index, raw in enumerate(raw_runs):
        if not isinstance(raw, dict):
            raise SmokeArtifactError(f"runs[{index}] must be an object")
        if raw.get("method") not in TARGET_METHODS:
            continue
        context = f"runs[{index}]"
        method = str(_require(raw, "method", context))
        seed = _as_int(_require(raw, "seed", context), f"{context}.seed")
        root_seed = _as_int(raw.get("root_seed", seed), f"{context}.root_seed")
        if root_seed != seed:
            raise SmokeArtifactError(f"{context}.root_seed must equal seed")
        map_id = _require(raw, "map_id", context)
        workload = _require(raw, "workload", context)
        if not isinstance(map_id, str) or not map_id:
            raise SmokeArtifactError(f"{context}.map_id must be non-empty")
        if not isinstance(workload, str) or not workload:
            raise SmokeArtifactError(f"{context}.workload must be non-empty")
        tasks = _as_int(
            _require(raw, "num_task_finished", context),
            f"{context}.num_task_finished",
        )
        horizon = _as_int(
            _require(raw, "scored_horizon", context),
            f"{context}.scored_horizon",
            minimum=1,
        )
        decision_window = _as_int(
            _require(raw, "decision_window", context),
            f"{context}.decision_window",
            minimum=1,
        )
        windows = _as_int(
            _require(raw, "window_count", context),
            f"{context}.window_count",
            minimum=2,
        )
        throughput = _as_number(
            _require(raw, "throughput_per_timestep", context),
            f"{context}.throughput_per_timestep",
        )
        if horizon % decision_window or windows != horizon // decision_window:
            raise SmokeArtifactError(f"{context} has inconsistent horizon/window fields")
        if not math.isclose(throughput, tasks / horizon, rel_tol=1e-12, abs_tol=1e-12):
            raise SmokeArtifactError(f"{context}.throughput is inconsistent with tasks/H")
        key = (method, seed, map_id, workload)
        if key in seen:
            raise SmokeArtifactError(f"duplicate target run cell: {key}")
        seen.add(key)
        normalized = dict(raw)
        normalized.update(
            {
                "method": method,
                "seed": seed,
                "map_id": map_id,
                "workload": workload,
                "num_task_finished": tasks,
                "scored_horizon": horizon,
                "decision_window": decision_window,
                "window_count": windows,
                "throughput_per_timestep": throughput,
            }
        )
        selected.append(normalized)
    return selected


def _complete_grid(
    artifact: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> tuple[list[int], list[str], list[str]]:
    seeds = [int(seed) for seed in artifact["seeds"]]
    workloads = [str(workload) for workload in artifact["workloads"]]
    maps = sorted({str(run["map_id"]) for run in runs})
    actual = {
        (str(run["method"]), int(run["seed"]), str(run["map_id"]), str(run["workload"]))
        for run in runs
    }
    expected = set(itertools.product(TARGET_METHODS, seeds, maps, workloads))
    if actual != expected:
        raise SmokeArtifactError(
            "target runs must form a complete method×seed×map×workload grid; "
            f"missing={sorted(expected - actual)[:8]}, "
            f"extra={sorted(actual - expected)[:8]}"
        )
    return seeds, maps, workloads


def _audit_pairing(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> None:
    grouped: dict[tuple[int, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[_run_key(run)].append(run)
    fields = (
        "scored_horizon",
        "decision_window",
        "window_count",
        "manifest_id",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    )
    for cell_runs in grouped.values():
        reference = cell_runs[0]
        for run in cell_runs:
            for field in fields:
                value = run.get(field)
                if value is None or (isinstance(value, str) and not value):
                    _failure(failures, "pairing", f"required_{field}", run)
            if not isinstance(run.get("task_tape_identity"), dict):
                _failure(failures, "pairing", "task_tape_identity_present", run)
            prefixes = run.get("final_task_tape_prefixes")
            if not isinstance(prefixes, dict) or not isinstance(
                prefixes.get("released_prefix_lengths"), list
            ):
                _failure(failures, "pairing", "released_prefixes_present", run)
        for run in cell_runs[1:]:
            for field in fields:
                if run.get(field) != reference.get(field):
                    _failure(failures, "pairing", f"paired_{field}", run)
            if _canonical(run.get("task_tape_identity")) != _canonical(
                reference.get("task_tape_identity")
            ):
                _failure(failures, "pairing", "paired_task_tape_identity", run)
            # Assigned/completed prefixes are outcomes and may differ across
            # methods.  Only the exogenous released prefix must be paired.
            run_released = run.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            )
            ref_released = reference.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            )
            if run_released != ref_released:
                _failure(failures, "pairing", "paired_released_prefixes", run)
            ref_count = reference.get("invariants", {}).get("release_projection_count")
            run_count = run.get("invariants", {}).get("release_projection_count")
            if ref_count != run_count:
                _failure(failures, "pairing", "paired_release_projection_count", run)


def _audit_budget(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> None:
    for run in runs:
        method = str(run["method"])
        budget = run.get("budget")
        if not isinstance(budget, dict):
            _failure(failures, "budget", "budget_object_present", run)
            continue
        try:
            mandatory = _as_int(
                _require(budget, "mandatory_bootstrap_calls", "budget"),
                "budget.mandatory_bootstrap_calls",
            )
            reported_budget = _as_int(
                _require(budget, "post_bootstrap_budget", "budget"),
                "budget.post_bootstrap_budget",
            )
            publications = _as_int(
                _require(budget, "post_bootstrap_publication_count", "budget"),
                "budget.post_bootstrap_publication_count",
            )
            calls = _as_int(
                _require(budget, "total_generator_calls", "budget"),
                "budget.total_generator_calls",
            )
            attempted = _as_int(
                _require(budget, "budget_violation_attempts", "budget"),
                "budget.budget_violation_attempts",
            )
        except SmokeArtifactError as error:
            _failure(failures, "budget", "required_numeric_budget_fields", run, str(error))
            continue
        expected_b25 = math.ceil(0.25 * (int(run["window_count"]) - 1))
        expected_budget = 0 if method == BASELINE_BOOTSTRAP else expected_b25
        expected_semantics = "at_most" if method == "js_cap_B25" else "exact"
        semantics = budget.get("budget_semantics")
        cap_satisfied = budget.get("cap_satisfied")
        exact_required = budget.get("exact_quota_required")
        exact_satisfied = budget.get("exact_quota_satisfied")
        checks = {
            "one_mandatory_bootstrap_call": mandatory == 1,
            "registered_budget": reported_budget == expected_budget,
            "generator_call_conservation": calls == mandatory + publications,
            "flat_generator_calls_match": run.get("generator_calls") == calls,
            "flat_publication_count_match": (
                run.get("post_bootstrap_publication_count") == publications
            ),
            "flat_publication_budget_match": run.get("publication_budget") == reported_budget,
            "zero_budget_violation_attempts": attempted == 0,
            "zero_flat_budget_violations": run.get("budget_violation_count") == 0,
            "budget_semantics": semantics == expected_semantics,
            "cap_satisfied": cap_satisfied is True and publications <= reported_budget,
        }
        if method in EXACT_B25_METHODS or method == BASELINE_BOOTSTRAP:
            checks.update(
                {
                    "exact_publication_spend": publications == reported_budget,
                    "exact_quota_required": exact_required is True,
                    "exact_quota_satisfied": exact_satisfied is True,
                }
            )
        else:
            checks.update(
                {
                    "at_most_publication_spend": publications <= reported_budget,
                    "exact_quota_not_required": exact_required is False,
                }
            )
        for name, passed in checks.items():
            if not passed:
                _failure(failures, "budget", name, run)


def _audit_safety_and_attribution(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    reason_totals: Counter[str] = Counter()
    timeout_total = 0
    unexposed_total = 0
    exposed_total = 0
    for run in runs:
        safety = run.get("safety")
        if not isinstance(safety, dict):
            _failure(failures, "safety", "safety_object_present", run)
            continue
        for field in (
            "collision_count",
            "edge_swap_count",
            "invalid_move_count",
            "route_trace_invalid_count",
        ):
            if safety.get(field) != 0:
                _failure(failures, "safety", f"zero_{field}", run)
        if safety.get("passed") is not True:
            _failure(failures, "safety", "runner_safety_passed", run)
        timeout = safety.get("planner_timeout_count")
        if not _is_int(timeout) or timeout < 0:
            _failure(failures, "safety", "valid_planner_timeout_count", run)
        else:
            timeout_total += timeout
        invariants = run.get("invariants")
        if not isinstance(invariants, dict):
            _failure(failures, "safety", "invariants_object_present", run)
        else:
            expected_flags = {
                "passed": True,
                "online_workload_rng_draws": 0,
                "tape_not_exhausted": True,
                "reward_sum_matches_completed": True,
                "unexposed_completions_excluded_from_cohorts": True,
            }
            for field, expected in expected_flags.items():
                if invariants.get(field) != expected:
                    _failure(failures, "safety", f"invariant_{field}", run)

        audit = run.get("cohort_attribution_audit")
        if not isinstance(audit, dict):
            _failure(failures, "attribution", "cohort_audit_present", run)
            continue
        exposed = audit.get("route_exposed_completion_count")
        unexposed = audit.get("unexposed_zero_route_completion_count")
        if not _is_int(exposed) or exposed < 0:
            _failure(failures, "attribution", "valid_route_exposed_count", run)
        else:
            exposed_total += exposed
        if not _is_int(unexposed) or unexposed < 0:
            _failure(failures, "attribution", "valid_unexposed_count", run)
        else:
            unexposed_total += unexposed
        if audit.get("unexposed_zero_route_completions_excluded") is not True:
            _failure(failures, "attribution", "unexposed_completions_excluded", run)
        reasons = run.get("route_build_reason_counts")
        nested_reasons = audit.get("route_build_reason_counts")
        if not isinstance(reasons, dict) or not reasons:
            _failure(failures, "attribution", "route_reason_counts_present", run)
            continue
        if reasons != nested_reasons:
            _failure(failures, "attribution", "route_reason_counts_agree", run)
        for reason, count in reasons.items():
            if reason not in ALLOWED_ROUTE_REASONS:
                _failure(
                    failures,
                    "attribution",
                    "recognized_route_reason",
                    run,
                    str(reason),
                )
            if not _is_int(count) or count < 0:
                _failure(failures, "attribution", "valid_route_reason_count", run)
            else:
                reason_totals[str(reason)] += count
    return {
        "planner_timeout_count": timeout_total,
        "route_exposed_completion_count": exposed_total,
        "unexposed_zero_route_completion_count": unexposed_total,
        "route_build_reason_counts": dict(sorted(reason_totals.items())),
        "inherited_goal_route_observed": reason_totals["inherited_goal_route"] > 0,
    }


def _mean(values: Iterable[float]) -> float:
    data = list(values)
    return statistics.fmean(data) if data else 0.0


def _metric_summary(
    runs: Sequence[Mapping[str, Any]], workloads: Sequence[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    indexed = {
        (str(run["method"]), *_run_key(run)): run
        for run in runs
    }
    effects: list[dict[str, Any]] = []
    for run in runs:
        key = _run_key(run)
        exact = indexed[(BASELINE_EXACT, *key)]
        bootstrap = indexed[(BASELINE_BOOTSTRAP, *key)]
        throughput = float(run["throughput_per_timestep"])

        def relative(reference: Mapping[str, Any]) -> float:
            baseline = float(reference["throughput_per_timestep"])
            return (throughput - baseline) / baseline if baseline > 0 else 0.0

        effects.append(
            {
                "method": run["method"],
                "seed": run["seed"],
                "map_id": run["map_id"],
                "workload": run["workload"],
                "throughput": throughput,
                "num_task_finished": run["num_task_finished"],
                "generator_calls": run["budget"]["total_generator_calls"],
                "post_bootstrap_publications": run["budget"][
                    "post_bootstrap_publication_count"
                ],
                "relative_vs_exact": relative(exact),
                "relative_vs_bootstrap": relative(bootstrap),
                "absolute_tasks_vs_exact": (
                    int(run["num_task_finished"]) - int(exact["num_task_finished"])
                ),
                "absolute_tasks_vs_bootstrap": (
                    int(run["num_task_finished"]) - int(bootstrap["num_task_finished"])
                ),
            }
        )

    summaries: dict[str, Any] = {}
    groups = ["all", *workloads]
    for group in groups:
        summaries[group] = {}
        for method in TARGET_METHODS:
            selected = [
                effect for effect in effects
                if effect["method"] == method
                and (group == "all" or effect["workload"] == group)
            ]
            rel_exact = [float(item["relative_vs_exact"]) for item in selected]
            rel_bootstrap = [
                float(item["relative_vs_bootstrap"]) for item in selected
            ]
            summaries[group][method] = {
                "n_paired_cells": len(selected),
                "mean_throughput": _mean(item["throughput"] for item in selected),
                "mean_num_task_finished": _mean(
                    item["num_task_finished"] for item in selected
                ),
                "mean_generator_calls": _mean(
                    item["generator_calls"] for item in selected
                ),
                "mean_post_bootstrap_publications": _mean(
                    item["post_bootstrap_publications"] for item in selected
                ),
                "mean_paired_relative_vs_exact": _mean(rel_exact),
                "mean_paired_relative_vs_bootstrap": _mean(rel_bootstrap),
                "mean_absolute_tasks_vs_exact": _mean(
                    item["absolute_tasks_vs_exact"] for item in selected
                ),
                "mean_absolute_tasks_vs_bootstrap": _mean(
                    item["absolute_tasks_vs_bootstrap"] for item in selected
                ),
                "wins_ties_losses_vs_exact": [
                    sum(value > 0 for value in rel_exact),
                    sum(value == 0 for value in rel_exact),
                    sum(value < 0 for value in rel_exact),
                ],
            }
    return summaries, effects


def _screening_decision(
    summaries: Mapping[str, Any],
    workloads: Sequence[str],
    failures: Sequence[Mapping[str, Any]],
    attribution: Mapping[str, Any],
) -> dict[str, Any]:
    category_counts = Counter(str(item["category"]) for item in failures)
    hard_invariants = not failures
    clean_runtime = attribution["planner_timeout_count"] == 0
    clean_unexposed = attribution["unexposed_zero_route_completion_count"] == 0
    inherited_observed = bool(attribution["inherited_goal_route_observed"])

    def rel(group: str, method: str, baseline: str) -> float:
        return float(summaries[group][method][f"mean_paired_relative_vs_{baseline}"])

    causal_aggregate = rel("all", "causal_block_B25", "exact")
    available_nonstationary = [
        workload for workload in NONSTATIONARY_WORKLOADS if workload in workloads
    ]
    causal_workload_effects = {
        workload: rel(workload, "causal_block_B25", "exact")
        for workload in workloads
    }
    causal_signal = (
        causal_aggregate >= MIN_AGGREGATE_RELATIVE_GAIN
        and len(available_nonstationary) == len(NONSTATIONARY_WORKLOADS)
        and all(causal_workload_effects[item] > 0 for item in available_nonstationary)
        and min(causal_workload_effects.values()) >= MAX_WORST_WORKLOAD_REGRESSION
    )

    cap_aggregate_exact = rel("all", "js_cap_B25", "exact")
    cap_aggregate_bootstrap = rel("all", "js_cap_B25", "bootstrap")
    cap_calls = float(summaries["all"]["js_cap_B25"]["mean_generator_calls"])
    exact_calls = float(summaries["all"][BASELINE_EXACT]["mean_generator_calls"])
    cap_signal = (
        cap_aggregate_exact >= MIN_AGGREGATE_RELATIVE_GAIN
        and cap_aggregate_bootstrap > 0
        and cap_calls < exact_calls
    )

    evidence_ready = (
        hard_invariants and clean_runtime and clean_unexposed and inherited_observed
    )
    if not hard_invariants:
        recommendation = "NO_GO_FIX_INVARIANTS"
    elif not (clean_runtime and clean_unexposed and inherited_observed):
        recommendation = "NO_GO_FIX_RUNTIME_OR_ATTRIBUTION_EVIDENCE"
    elif causal_signal or cap_signal:
        recommendation = "GO_DEV10_SCREEN_ONLY"
    else:
        recommendation = "NO_GO_REDIRECT_OR_RETUNE_METHOD"
    return {
        "recommendation": recommendation,
        "one_seed_smoke_never_supports_paper_or_sota_claim": True,
        "hard_invariants_passed": hard_invariants,
        "invariant_failure_counts": dict(sorted(category_counts.items())),
        "clean_runtime_zero_timeouts": clean_runtime,
        "clean_attribution_zero_unexposed_completions": clean_unexposed,
        "inherited_goal_route_observed": inherited_observed,
        "evidence_ready_for_signal_screen": evidence_ready,
        "thresholds": {
            "minimum_aggregate_relative_gain": MIN_AGGREGATE_RELATIVE_GAIN,
            "maximum_worst_workload_regression": MAX_WORST_WORKLOAD_REGRESSION,
            "causal_block_requires_positive_abrupt_and_recurrent": True,
            "js_cap_requires_positive_vs_bootstrap_and_fewer_calls_than_exact": True,
        },
        "causal_block_track": {
            "aggregate_relative_vs_exact": causal_aggregate,
            "workload_relative_vs_exact": causal_workload_effects,
            "passes_signal_screen": causal_signal,
        },
        "js_cap_track": {
            "aggregate_relative_vs_exact": cap_aggregate_exact,
            "aggregate_relative_vs_bootstrap": cap_aggregate_bootstrap,
            "mean_generator_calls": cap_calls,
            "exact_mean_generator_calls": exact_calls,
            "passes_signal_screen": cap_signal,
        },
        "proposed_no_cohort_reference": {
            "aggregate_relative_vs_exact": rel(
                "all", "proposed_no_cohort_B25", "exact"
            ),
            "aggregate_relative_vs_bootstrap": rel(
                "all", "proposed_no_cohort_B25", "bootstrap"
            ),
        },
    }


def analyze(artifact: Mapping[str, Any], *, source_sha256: str) -> dict[str, Any]:
    _validate_top_level(artifact)
    runs = _normalize_runs(artifact)
    seeds, maps, workloads = _complete_grid(artifact, runs)
    failures: list[dict[str, Any]] = []
    _audit_pairing(runs, failures)
    _audit_budget(runs, failures)
    attribution = _audit_safety_and_attribution(runs, failures)
    summaries, effects = _metric_summary(runs, workloads)
    screening = _screening_decision(
        summaries, workloads, failures, attribution
    )
    return {
        "schema": ANALYSIS_SCHEMA,
        "source_schema": artifact["schema"],
        "source_sha256": source_sha256,
        "source_split": artifact["split"],
        "source_evidence_class": artifact["evidence_class"],
        "target_methods": list(TARGET_METHODS),
        "seeds": seeds,
        "maps": maps,
        "workloads": workloads,
        "n_target_runs": len(runs),
        "audit": {
            "passed": not failures,
            "failure_count": len(failures),
            "failures": failures,
            "attribution_totals": attribution,
        },
        "summaries": summaries,
        "paired_cell_effects": effects,
        "screening": screening,
    }


def _markdown(report: Mapping[str, Any], source: Path) -> str:
    lines = [
        "# New-method smoke analysis",
        "",
        f"- Source: `{source}`",
        f"- SHA-256: `{report['source_sha256']}`",
        f"- Target runs: {report['n_target_runs']}",
        f"- Audit: {'PASS' if report['audit']['passed'] else 'FAIL'}",
        f"- Recommendation: **{report['screening']['recommendation']}**",
        "",
        "The recommendation is an exploratory screen only; it is not paper or SOTA evidence.",
        "",
    ]
    for group in ["all", *report["workloads"]]:
        lines.extend(
            [
                f"## {'Aggregate' if group == 'all' else group}",
                "",
                "| method | throughput | finished | calls | post pubs | paired vs exact | paired vs bootstrap | W/T/L vs exact |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for method in TARGET_METHODS:
            item = report["summaries"][group][method]
            wtl = "/".join(str(value) for value in item["wins_ties_losses_vs_exact"])
            lines.append(
                f"| {method} | {item['mean_throughput']:.5f} | "
                f"{item['mean_num_task_finished']:.1f} | "
                f"{item['mean_generator_calls']:.2f} | "
                f"{item['mean_post_bootstrap_publications']:.2f} | "
                f"{item['mean_paired_relative_vs_exact']:+.2%} | "
                f"{item['mean_paired_relative_vs_bootstrap']:+.2%} | {wtl} |"
            )
        lines.append("")
    attr = report["audit"]["attribution_totals"]
    screen = report["screening"]
    lines.extend(
        [
            "## Invariant and screening gates",
            "",
            f"- Pairing/budget/safety/attribution audit failures: {report['audit']['failure_count']}",
            f"- Planner timeouts: {attr['planner_timeout_count']}",
            f"- Unexposed zero-route completions: {attr['unexposed_zero_route_completion_count']}",
            f"- Route reasons: `{json.dumps(attr['route_build_reason_counts'], sort_keys=True)}`",
            f"- inherited_goal_route observed: {attr['inherited_goal_route_observed']}",
            f"- causal_block signal screen: {screen['causal_block_track']['passes_signal_screen']}",
            f"- js_cap signal screen: {screen['js_cap_track']['passes_signal_screen']}",
            "",
        ]
    )
    if report["audit"]["failures"]:
        lines.extend(["## Failures", ""])
        for item in report["audit"]["failures"]:
            lines.append(f"- `{item['category']}/{item['check']}`: `{item.get('cell', {})}`")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    source = args.artifact.resolve()
    try:
        artifact = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(artifact, dict):
            raise SmokeArtifactError("top-level JSON value must be an object")
        report = analyze(artifact, source_sha256=_sha256(source))
    except (OSError, json.JSONDecodeError, SmokeArtifactError) as error:
        raise SystemExit(f"ERROR: {error}") from error

    rendered = _markdown(report, source)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
