#!/usr/bin/env python3
"""Audit and screen the development-only context dual-cap dev10 experiment.

This analyzer accepts one completed ``development`` artifact containing exactly
ten root seeds, the three registered workloads, one map, and four method arms.
It is intentionally read-only.  All inference clusters the three workload
observations belonging to one root seed; the 30 paired cells are never treated
as 30 independent observations.

Passing this screen can only nominate ``context_dualcap_G4S5`` for a new,
untouched validation run.  Development data cannot support a paper-result,
locked-test, or SOTA claim.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any, Iterable, Mapping, Sequence


SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
ANALYSIS_SCHEMA = "dai.context-dualcap-dev10-analysis/v1"
BOOTSTRAP_SEED = 20260714
DEFAULT_BOOTSTRAP_SAMPLES = 10_000
EXPECTED_ROOT_SEEDS = 10
EXPECTED_WORKLOADS = ("stationary", "abrupt", "recurrent")

EXACT = "exact_even_B25"
BOOTSTRAP = "bootstrap_only"
CONTEXT = "context_memory_B25"
DUALCAP = "context_dualcap_G4S5"
TARGET_METHODS = (EXACT, BOOTSTRAP, CONTEXT, DUALCAP)
COMPARATORS = (CONTEXT, EXACT, BOOTSTRAP)

DUALCAP_POST_GENERATION_CAP = 4
DUALCAP_POST_SWITCH_CAP = 5
DUALCAP_TOTAL_CALL_CAP = 5
ALLOWED_ROUTE_BUILD_REASONS = frozenset(
    {"init_pp", "task_change", "inherited_goal_route"}
)


class DualCapArtifactError(ValueError):
    """The source artifact is not the strict paired dev10 design."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DualCapArtifactError(f"{field} must be an integer >= {minimum}")
    return int(value)


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DualCapArtifactError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise DualCapArtifactError(f"{field} must be finite and >= {minimum}")
    return result


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DualCapArtifactError(f"{field} must be a non-empty string")
    return value


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(
        sorted_values[lower] * (1.0 - weight)
        + sorted_values[upper] * weight
    )


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
    if detail is not None:
        item["detail"] = detail
    failures.append(item)


def _validate_top_level(artifact: Mapping[str, Any]) -> tuple[list[int], str]:
    if artifact.get("schema") != SOURCE_SCHEMA:
        raise DualCapArtifactError(f"artifact.schema must equal {SOURCE_SCHEMA!r}")
    if artifact.get("status") != "complete":
        raise DualCapArtifactError("artifact.status must be 'complete'")
    if artifact.get("split") != "development":
        raise DualCapArtifactError("artifact.split must be 'development'")
    if artifact.get("evidence_class") != "development":
        raise DualCapArtifactError("artifact.evidence_class must be 'development'")

    methods = artifact.get("methods")
    if (
        not isinstance(methods, list)
        or len(methods) != len(set(methods))
        or set(methods) != set(TARGET_METHODS)
    ):
        raise DualCapArtifactError(
            "artifact.methods must contain exactly the four dev10 method arms"
        )
    seeds_raw = artifact.get("seeds")
    if (
        not isinstance(seeds_raw, list)
        or len(seeds_raw) != EXPECTED_ROOT_SEEDS
        or len(seeds_raw) != len(set(seeds_raw))
    ):
        raise DualCapArtifactError("artifact.seeds must contain 10 unique root seeds")
    seeds = [
        _integer(seed, f"artifact.seeds[{index}]")
        for index, seed in enumerate(seeds_raw)
    ]
    workloads = artifact.get("workloads")
    if (
        not isinstance(workloads, list)
        or len(workloads) != len(set(workloads))
        or set(workloads) != set(EXPECTED_WORKLOADS)
    ):
        raise DualCapArtifactError(
            "artifact.workloads must contain stationary, abrupt, and recurrent"
        )
    map_id = _string(artifact.get("map_id"), "artifact.map_id")
    return seeds, map_id


def _normalize_runs(
    artifact: Mapping[str, Any], seeds: Sequence[int], map_id: str
) -> list[dict[str, Any]]:
    raw_runs = artifact.get("runs")
    if not isinstance(raw_runs, list):
        raise DualCapArtifactError("artifact.runs must be a list")
    expected = set(itertools.product(TARGET_METHODS, seeds, EXPECTED_WORKLOADS))
    seen: set[tuple[str, int, str]] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_runs):
        context = f"runs[{index}]"
        if not isinstance(raw, dict):
            raise DualCapArtifactError(f"{context} must be an object")
        method = raw.get("method")
        seed = raw.get("root_seed", raw.get("seed"))
        workload = raw.get("workload")
        key = (method, seed, workload)
        if key not in expected:
            raise DualCapArtifactError(f"{context} has an undeclared cell key {key!r}")
        if key in seen:
            raise DualCapArtifactError(f"duplicate method/root/workload cell {key!r}")
        seen.add(key)
        if raw.get("seed") != seed:
            raise DualCapArtifactError(f"{context}.seed must equal root_seed")
        if raw.get("split") != "development" or raw.get("evidence_class") != "development":
            raise DualCapArtifactError(f"{context} must be development evidence")
        if raw.get("map_id") != map_id:
            raise DualCapArtifactError(f"{context}.map_id differs from artifact.map_id")

        tasks = _integer(raw.get("num_task_finished"), f"{context}.num_task_finished")
        horizon = _integer(raw.get("scored_horizon"), f"{context}.scored_horizon", minimum=1)
        decision_window = _integer(
            raw.get("decision_window"), f"{context}.decision_window", minimum=1
        )
        window_count = _integer(raw.get("window_count"), f"{context}.window_count", minimum=2)
        if horizon % decision_window or window_count != horizon // decision_window:
            raise DualCapArtifactError(f"{context} has inconsistent horizon/window fields")
        throughput = _number(
            raw.get("throughput_per_timestep"),
            f"{context}.throughput_per_timestep",
            minimum=0.0,
        )
        if not math.isclose(throughput, tasks / horizon, rel_tol=1e-12, abs_tol=1e-12):
            raise DualCapArtifactError(f"{context}.throughput_per_timestep != tasks/H")
        for field in (
            "manifest_id",
            "reset_causal_fingerprint",
            "release_projection_fingerprint",
            "distribution_update_fingerprint",
        ):
            _string(raw.get(field), f"{context}.{field}")
        if not isinstance(raw.get("task_tape_identity"), dict) or not raw["task_tape_identity"]:
            raise DualCapArtifactError(f"{context}.task_tape_identity is required")
        prefixes = raw.get("final_task_tape_prefixes")
        if not isinstance(prefixes, dict):
            raise DualCapArtifactError(f"{context}.final_task_tape_prefixes is required")
        released_prefixes = prefixes.get("released_prefix_lengths")
        if (
            not isinstance(released_prefixes, list)
            or not released_prefixes
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in released_prefixes
            )
        ):
            raise DualCapArtifactError(f"{context}.released_prefix_lengths is invalid")
        for field in ("budget", "safety", "invariants", "cohort_attribution_audit"):
            if not isinstance(raw.get(field), dict):
                raise DualCapArtifactError(f"{context}.{field} must be an object")
        if not isinstance(raw.get("publication_timeline"), list):
            raise DualCapArtifactError(f"{context}.publication_timeline must be a list")

        item = dict(raw)
        item.update(
            {
                "method": str(method),
                "seed": int(seed),
                "root_seed": int(seed),
                "workload": str(workload),
                "tasks": tasks,
                "throughput": throughput,
                "scored_horizon": horizon,
                "decision_window": decision_window,
                "window_count": window_count,
            }
        )
        normalized.append(item)
    if seen != expected:
        raise DualCapArtifactError(
            "artifact must contain exactly 120 runs (4 methods × 10 roots × 3 workloads); "
            f"missing={sorted(expected - seen)[:8]}, extra={sorted(seen - expected)[:8]}"
        )
    return normalized


def _audit_pairing(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> None:
    grouped: dict[tuple[int, str], list[Mapping[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[(int(run["seed"]), str(run["workload"]))].append(run)
    paired_fields = (
        "manifest_id",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    )
    for cell, arms in grouped.items():
        if {str(run["method"]) for run in arms} != set(TARGET_METHODS):
            _failure(failures, "pairing", "complete_four_method_cell", detail=str(cell))
            continue
        reference = arms[0]
        for run in arms[1:]:
            for field in paired_fields:
                if run.get(field) != reference.get(field):
                    _failure(failures, "pairing", f"paired_{field}", run)
            if _canonical(run.get("task_tape_identity")) != _canonical(
                reference.get("task_tape_identity")
            ):
                _failure(failures, "pairing", "paired_task_tape_identity", run)
            if run.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            ) != reference.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            ):
                _failure(failures, "pairing", "paired_released_prefixes", run)
            if (
                run["scored_horizon"],
                run["decision_window"],
                run["window_count"],
            ) != (
                reference["scored_horizon"],
                reference["decision_window"],
                reference["window_count"],
            ):
                _failure(failures, "pairing", "paired_evaluation_horizon", run)


def _timeline_counts(run: Mapping[str, Any]) -> dict[str, int]:
    timeline = run["publication_timeline"]
    if len(timeline) != int(run["window_count"]):
        raise DualCapArtifactError(
            f"timeline length differs from window_count for "
            f"{run['method']}:{run['seed']}:{run['workload']}"
        )
    decision_indices: list[int] = []
    post = []
    for index, raw in enumerate(timeline):
        if not isinstance(raw, dict):
            raise DualCapArtifactError("publication_timeline entries must be objects")
        decision_index = _integer(
            raw.get("decision_index"), f"publication_timeline[{index}].decision_index"
        )
        decision_indices.append(decision_index)
        if decision_index > 0:
            post.append(raw)
    if decision_indices != list(range(int(run["window_count"]))):
        raise DualCapArtifactError("publication_timeline decision indices must be 0..N-1")
    return {
        "switches": sum(item.get("accepted") is True for item in post),
        "charged_switches": sum(
            item.get("charged_to_post_bootstrap_budget") is True for item in post
        ),
        "generations": sum(item.get("executed_operation") == "generate" for item in post),
        "charged_generations": sum(
            item.get("charged_to_generator_budget") is True for item in post
        ),
        "reactivations": sum(
            item.get("executed_operation") == "reactivate" for item in post
        ),
        "candidate_suppressions": sum(
            item.get("generation_cap_candidate_suppressed") is True for item in post
        ),
        "bindings": sum(item.get("generation_cap_binding") is True for item in post),
        "blocked": sum(item.get("generation_cap_blocked") is True for item in post),
        "invalid_binding_implications": sum(
            item.get("generation_cap_binding") is True
            and not (
                item.get("generation_cap_candidate_suppressed") is True
                and item.get("generation_cap_blocked") is True
                and item.get("executed_operation") == "hold"
                and item.get("accepted") is False
            )
            for item in post
        ),
    }


def _audit_budget(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> None:
    for run in runs:
        method = str(run["method"])
        budget = run["budget"]
        timeline = _timeline_counts(run)
        mandatory = _integer(
            budget.get("mandatory_bootstrap_calls"), "budget.mandatory_bootstrap_calls"
        )
        registered = _integer(
            budget.get("post_bootstrap_budget"), "budget.post_bootstrap_budget"
        )
        publications = _integer(
            budget.get("post_bootstrap_publication_count"),
            "budget.post_bootstrap_publication_count",
        )
        generations = _integer(
            budget.get("post_bootstrap_generation_count"),
            "budget.post_bootstrap_generation_count",
        )
        reactivations = _integer(
            budget.get("post_bootstrap_reactivation_count"),
            "budget.post_bootstrap_reactivation_count",
        )
        calls = _integer(budget.get("total_generator_calls"), "budget.total_generator_calls")
        violations = _integer(
            budget.get("budget_violation_attempts"), "budget.budget_violation_attempts"
        )
        expected_b25 = math.ceil(0.25 * (int(run["window_count"]) - 1))
        expected_budget = (
            0 if method == BOOTSTRAP else DUALCAP_POST_SWITCH_CAP if method == DUALCAP else expected_b25
        )
        checks = {
            "one_mandatory_bootstrap_call": mandatory == 1,
            "registered_budget_matches_method": registered == expected_budget,
            "operation_partition": generations + reactivations == publications,
            "generator_call_conservation": calls == mandatory + generations,
            "flat_generator_calls_match": run.get("generator_calls") == calls,
            "flat_publication_count_match": run.get("post_bootstrap_publication_count") == publications,
            "flat_generation_count_match": run.get("post_bootstrap_generation_count") == generations,
            "flat_reactivation_count_match": run.get("post_bootstrap_reactivation_count") == reactivations,
            "flat_publication_budget_match": run.get("publication_budget") == registered,
            "flat_effective_switch_count_match": run.get("effective_guidance_switch_count") == publications,
            "timeline_switch_count_match": timeline["switches"] == publications,
            "timeline_charged_switch_count_match": timeline["charged_switches"] == publications,
            "timeline_generation_count_match": timeline["generations"] == generations,
            "timeline_charged_generation_count_match": timeline["charged_generations"] == generations,
            "timeline_reactivation_count_match": timeline["reactivations"] == reactivations,
            "zero_budget_violation_attempts": violations == 0,
            "zero_flat_budget_violation_count": run.get("budget_violation_count") == 0,
            "runner_cap_satisfied": budget.get("cap_satisfied") is True,
            "runner_switch_cap_satisfied": budget.get("switch_cap_satisfied", True) is True,
            "runner_generation_cap_satisfied": budget.get("generation_cap_satisfied") is True,
            "runner_total_call_cap_satisfied": budget.get("total_generator_call_cap_satisfied") is True,
        }
        if method in {EXACT, BOOTSTRAP}:
            checks.update(
                {
                    "exact_publication_quota": publications == registered,
                    "exact_quota_required": budget.get("exact_quota_required") is True,
                    "exact_quota_satisfied": budget.get("exact_quota_satisfied") is True,
                    "exact_budget_semantics": budget.get("budget_semantics") == "exact",
                }
            )
        elif method == CONTEXT:
            checks.update(
                {
                    "context_at_most_b25_switches": publications <= expected_b25,
                    "context_at_most_b25_generations": generations <= expected_b25,
                    "context_quota_not_exact": budget.get("exact_quota_required") is False,
                    "context_budget_semantics": (
                        budget.get("budget_semantics") == "at_most_switch_and_generator"
                    ),
                }
            )
        else:
            candidates = _integer(
                budget.get("generation_cap_candidate_suppression_count"),
                "budget.generation_cap_candidate_suppression_count",
            )
            bindings = _integer(
                budget.get("generation_cap_binding_count"),
                "budget.generation_cap_binding_count",
            )
            blocks = _integer(
                budget.get("generation_cap_block_count"),
                "budget.generation_cap_block_count",
            )
            checks.update(
                {
                    "dualcap_switches_at_most_5": publications <= DUALCAP_POST_SWITCH_CAP,
                    "dualcap_generations_at_most_4": generations <= DUALCAP_POST_GENERATION_CAP,
                    "dualcap_total_calls_at_most_5": calls <= DUALCAP_TOTAL_CALL_CAP,
                    "dualcap_switch_cap_declared_5": budget.get("effective_guidance_switch_cap") == DUALCAP_POST_SWITCH_CAP,
                    "dualcap_generation_cap_declared_4": budget.get("post_bootstrap_generation_cap") == DUALCAP_POST_GENERATION_CAP,
                    "dualcap_total_call_cap_declared_5": budget.get("total_generator_call_cap") == DUALCAP_TOTAL_CALL_CAP,
                    "dualcap_quota_not_exact": budget.get("exact_quota_required") is False,
                    "dualcap_budget_semantics": budget.get("budget_semantics") == "generation_cap_4_switch_cap_5",
                    "binding_not_greater_than_candidate": bindings <= candidates,
                    "binding_equals_block_count": bindings == blocks,
                    "runner_binding_audit_satisfied": budget.get("generation_cap_binding_audit_satisfied") is True,
                    "timeline_candidate_count_match": timeline["candidate_suppressions"] == candidates,
                    "timeline_binding_count_match": timeline["bindings"] == bindings,
                    "timeline_block_count_match": timeline["blocked"] == blocks,
                    "timeline_binding_implications_valid": timeline["invalid_binding_implications"] == 0,
                }
            )
        for check, passed in checks.items():
            if not passed:
                _failure(failures, "budget", check, run)


def _audit_safety_and_attribution(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    totals = {
        "collision_count": 0,
        "edge_swap_count": 0,
        "endpoint_mismatch_count": 0,
        "invalid_move_count": 0,
        "planner_timeout_count": 0,
        "route_trace_invalid_count": 0,
        "budget_violation_attempt_count": 0,
        "unexposed_zero_route_completion_count": 0,
    }
    route_reason_totals: dict[str, int] = defaultdict(int)
    for run in runs:
        safety = run["safety"]
        invariants = run["invariants"]
        cohort = run["cohort_attribution_audit"]
        counts: dict[str, int] = {}
        for field in (
            "collision_count",
            "edge_swap_count",
            "endpoint_mismatch_count",
            "invalid_move_count",
            "planner_timeout_count",
            "route_trace_invalid_count",
        ):
            counts[field] = _integer(safety.get(field, 0), f"safety.{field}")
            totals[field] += counts[field]
        route_reasons = run.get("route_build_reason_counts")
        nested_reasons = cohort.get("route_build_reason_counts")
        valid_reasons = (
            isinstance(route_reasons, dict)
            and bool(route_reasons)
            and route_reasons == nested_reasons
            and all(
                reason in ALLOWED_ROUTE_BUILD_REASONS
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 0
                for reason, count in route_reasons.items()
            )
        )
        if isinstance(route_reasons, dict):
            for reason, count in route_reasons.items():
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    route_reason_totals[str(reason)] += count
        exposed = _integer(
            cohort.get("route_exposed_completion_count"),
            "cohort_attribution_audit.route_exposed_completion_count",
        )
        unexposed = _integer(
            cohort.get("unexposed_zero_route_completion_count"),
            "cohort_attribution_audit.unexposed_zero_route_completion_count",
        )
        totals["unexposed_zero_route_completion_count"] += unexposed
        violations = _integer(
            run["budget"].get("budget_violation_attempts"),
            "budget.budget_violation_attempts",
        )
        totals["budget_violation_attempt_count"] += violations
        checks = {
            "runner_safety_passed": safety.get("passed") is True,
            "zero_collisions": counts["collision_count"] == 0,
            "zero_edge_swaps": counts["edge_swap_count"] == 0,
            "zero_endpoint_mismatches": counts["endpoint_mismatch_count"] == 0,
            "zero_invalid_moves": counts["invalid_move_count"] == 0,
            "zero_planner_timeouts": counts["planner_timeout_count"] == 0,
            "zero_route_trace_invalid": counts["route_trace_invalid_count"] == 0,
            "runner_invariants_passed": invariants.get("passed") is True,
            "zero_online_workload_rng_draws": invariants.get("online_workload_rng_draws") == 0,
            "tape_not_exhausted": invariants.get("tape_not_exhausted") is True,
            "reward_sum_matches_completed": invariants.get("reward_sum_matches_completed") is True,
            "unexposed_completions_excluded": invariants.get("unexposed_completions_excluded_from_cohorts") is True,
            "cohort_exclusion_flag": cohort.get("unexposed_zero_route_completions_excluded") is True,
            "recognized_matching_route_reasons": valid_reasons,
            "zero_budget_violation_attempts": violations == 0,
        }
        for check, passed in checks.items():
            if not passed:
                _failure(failures, "integrity", check, run)
    return {**totals, "route_build_reason_counts": dict(sorted(route_reason_totals.items()))}


def _cluster_bootstrap(
    root_relative: Sequence[float],
    root_absolute: Sequence[float],
    *,
    samples: int,
) -> dict[str, Any]:
    if samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    if len(root_relative) != EXPECTED_ROOT_SEEDS or len(root_absolute) != EXPECTED_ROOT_SEEDS:
        raise ValueError("cluster bootstrap requires ten aligned root effects")
    rng = random.Random(BOOTSTRAP_SEED)
    relative_draws: list[float] = []
    absolute_draws: list[float] = []
    for _ in range(samples):
        selected = [rng.randrange(EXPECTED_ROOT_SEEDS) for _ in range(EXPECTED_ROOT_SEEDS)]
        relative_draws.append(_mean(root_relative[index] for index in selected))
        absolute_draws.append(_mean(root_absolute[index] for index in selected))
    relative_draws.sort()
    absolute_draws.sort()
    return {
        "method": "root_seed_cluster_percentile_bootstrap",
        "independent_unit": "root_seed",
        "samples": samples,
        "rng_seed": BOOTSTRAP_SEED,
        "confidence_level": 0.95,
        "mean_relative_effect_ci": [
            _percentile(relative_draws, 0.025),
            _percentile(relative_draws, 0.975),
        ],
        "mean_absolute_task_delta_ci": [
            _percentile(absolute_draws, 0.025),
            _percentile(absolute_draws, 0.975),
        ],
    }


def _exact_sign_flip(root_effects: Sequence[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in root_effects if value != 0.0]
    observed = math.fsum(nonzero)
    assignments = 1 << len(nonzero)
    if not nonzero:
        return {
            "method": "exact_root_seed_sign_flip",
            "nonzero_root_seeds": 0,
            "assignments": 1,
            "p_greater": 1.0,
            "p_two_sided": 1.0,
        }
    greater = 0
    two_sided = 0
    tolerance = 1e-15
    for bits in range(assignments):
        statistic = math.fsum(
            value if bits & (1 << index) else -value
            for index, value in enumerate(nonzero)
        )
        greater += statistic >= observed - tolerance
        two_sided += abs(statistic) >= abs(observed) - tolerance
    return {
        "method": "exact_root_seed_sign_flip",
        "nonzero_root_seeds": len(nonzero),
        "assignments": assignments,
        "p_greater": greater / assignments,
        "p_two_sided": two_sided / assignments,
    }


def _direction_summary(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    relative = [float(cell["relative_effect"]) for cell in cells]
    absolute = [float(cell["absolute_task_delta"]) for cell in cells]
    return {
        "n_paired_cells": len(cells),
        "mean_relative_effect": _mean(relative),
        "mean_relative_effect_percent": 100.0 * _mean(relative),
        "mean_absolute_task_delta": _mean(absolute),
        "win_tie_loss": {
            "wins": sum(value > 0 for value in relative),
            "ties": sum(value == 0 for value in relative),
            "losses": sum(value < 0 for value in relative),
        },
    }


def _comparison(
    comparator: str,
    indexed: Mapping[tuple[str, int, str], Mapping[str, Any]],
    seeds: Sequence[int],
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    relative_by_root: dict[int, list[float]] = defaultdict(list)
    absolute_by_root: dict[int, list[float]] = defaultdict(list)
    for seed, workload in itertools.product(seeds, EXPECTED_WORKLOADS):
        candidate_run = indexed[(DUALCAP, seed, workload)]
        comparator_run = indexed[(comparator, seed, workload)]
        denominator = float(comparator_run["tasks"])
        if denominator <= 0:
            raise DualCapArtifactError(
                f"{comparator} has zero tasks for seed={seed}, workload={workload}"
            )
        absolute = float(candidate_run["tasks"]) - denominator
        relative = float(candidate_run["tasks"]) / denominator - 1.0
        item = {
            "seed": seed,
            "workload": workload,
            "candidate_tasks": int(candidate_run["tasks"]),
            "comparator_tasks": int(comparator_run["tasks"]),
            "absolute_task_delta": absolute,
            "relative_effect": relative,
            "relative_effect_percent": 100.0 * relative,
        }
        cells.append(item)
        relative_by_root[seed].append(relative)
        absolute_by_root[seed].append(absolute)
    root_relative = [_mean(relative_by_root[seed]) for seed in seeds]
    root_absolute = [_mean(absolute_by_root[seed]) for seed in seeds]
    workload_strata = {
        workload: _direction_summary(
            [cell for cell in cells if cell["workload"] == workload]
        )
        for workload in EXPECTED_WORKLOADS
    }
    return {
        "name": f"dualcap_vs_{comparator}",
        "candidate": DUALCAP,
        "comparator": comparator,
        "independent_unit": "root_seed",
        "n_paired_cells": len(cells),
        "n_root_seed_clusters": len(seeds),
        "cells_per_root_seed_cluster": len(EXPECTED_WORKLOADS),
        "mean_relative_effect": _mean(root_relative),
        "mean_relative_effect_percent": 100.0 * _mean(root_relative),
        "mean_absolute_task_delta": _mean(root_absolute),
        "median_root_relative_effect": statistics.median(root_relative),
        "paired_cells": cells,
        "root_seed_relative_effects": {
            str(seed): value for seed, value in zip(seeds, root_relative)
        },
        "root_seed_absolute_task_deltas": {
            str(seed): value for seed, value in zip(seeds, root_absolute)
        },
        "root_seed_win_tie_loss": {
            "wins": sum(value > 0 for value in root_relative),
            "ties": sum(value == 0 for value in root_relative),
            "losses": sum(value < 0 for value in root_relative),
        },
        "cell_win_tie_loss": {
            "wins": sum(float(cell["relative_effect"]) > 0 for cell in cells),
            "ties": sum(float(cell["relative_effect"]) == 0 for cell in cells),
            "losses": sum(float(cell["relative_effect"]) < 0 for cell in cells),
        },
        "workload_strata": workload_strata,
        "cluster_bootstrap": _cluster_bootstrap(
            root_relative, root_absolute, samples=bootstrap_samples
        ),
        "exact_sign_flip": _exact_sign_flip(root_relative),
    }


def _method_summaries(runs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for method in TARGET_METHODS:
        selected = [run for run in runs if run["method"] == method]
        result[method] = {
            "n_cells": len(selected),
            "mean_tasks": _mean(float(run["tasks"]) for run in selected),
            "mean_throughput": _mean(float(run["throughput"]) for run in selected),
            "mean_generator_calls": _mean(float(run["generator_calls"]) for run in selected),
            "mean_post_bootstrap_switches": _mean(
                float(run["post_bootstrap_publication_count"]) for run in selected
            ),
            "mean_post_bootstrap_generations": _mean(
                float(run["post_bootstrap_generation_count"]) for run in selected
            ),
            "mean_post_bootstrap_reactivations": _mean(
                float(run["post_bootstrap_reactivation_count"]) for run in selected
            ),
        }
    return result


def _reduction(candidate: float, comparator: float) -> float:
    if comparator <= 0:
        raise DualCapArtifactError("resource-reduction comparator must be positive")
    return 1.0 - candidate / comparator


def _screen(
    audit: Mapping[str, Any],
    comparisons: Mapping[str, Mapping[str, Any]],
    summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    versus_bootstrap = comparisons[BOOTSTRAP]
    versus_exact = comparisons[EXACT]
    versus_context = comparisons[CONTEXT]
    bootstrap_wtl = versus_bootstrap["root_seed_win_tie_loss"]
    calls_reduction_exact = _reduction(
        float(summaries[DUALCAP]["mean_generator_calls"]),
        float(summaries[EXACT]["mean_generator_calls"]),
    )
    checks = {
        "audit_all_passed": audit["passed"] is True,
        "vs_bootstrap_all_10_root_directions_positive": (
            bootstrap_wtl == {"wins": 10, "ties": 0, "losses": 0}
        ),
        "vs_bootstrap_cluster_95ci_lower_strictly_positive": (
            float(versus_bootstrap["cluster_bootstrap"]["mean_relative_effect_ci"][0]) > 0.0
        ),
        "vs_exact_mean_at_least_minus_1pct": (
            float(versus_exact["mean_relative_effect"]) >= -0.01
        ),
        "vs_exact_cluster_95ci_lower_strictly_above_minus_1pct": (
            float(versus_exact["cluster_bootstrap"]["mean_relative_effect_ci"][0]) > -0.01
        ),
        "vs_context_mean_noninferior_minus_1pct": (
            float(versus_context["mean_relative_effect"]) >= -0.01
        ),
        "vs_context_cluster_95ci_lower_strictly_above_minus_1pct": (
            float(versus_context["cluster_bootstrap"]["mean_relative_effect_ci"][0]) > -0.01
        ),
        "generator_calls_reduction_vs_exact_at_least_80pct": calls_reduction_exact >= 0.80,
        "mean_post_bootstrap_switches_at_most_5": (
            float(summaries[DUALCAP]["mean_post_bootstrap_switches"]) <= 5.0
        ),
    }
    if not checks["audit_all_passed"]:
        recommendation = "NO_GO_FIX_DEV10_AUDIT"
    elif all(checks.values()):
        recommendation = "GO_FREEZE_CANDIDATE_FOR_FRESH_VALIDATION_ONLY"
    else:
        recommendation = "NO_GO_DUALCAP_DEVELOPMENT_SCREEN_FAILED"
    return {
        "recommendation": recommendation,
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": {
            "bootstrap_all_root_directions_positive": True,
            "bootstrap_cluster_ci_lower": 0.0,
            "exact_near_margin": -0.01,
            "context_noninferiority_margin": -0.01,
            "minimum_generator_call_reduction_vs_exact": 0.80,
            "maximum_mean_post_bootstrap_switches": 5.0,
        },
        "resource_effects": {
            "generator_call_reduction_vs_exact": calls_reduction_exact,
            "generator_call_reduction_vs_context": _reduction(
                float(summaries[DUALCAP]["mean_generator_calls"]),
                float(summaries[CONTEXT]["mean_generator_calls"]),
            ),
            "post_bootstrap_switch_reduction_vs_exact": _reduction(
                float(summaries[DUALCAP]["mean_post_bootstrap_switches"]),
                float(summaries[EXACT]["mean_post_bootstrap_switches"]),
            ),
            "post_bootstrap_switch_reduction_vs_context": _reduction(
                float(summaries[DUALCAP]["mean_post_bootstrap_switches"]),
                float(summaries[CONTEXT]["mean_post_bootstrap_switches"]),
            ),
        },
        "development_only_no_paper_or_sota_claim": True,
        "next_step_if_passed": (
            "Freeze the unique candidate and evaluate it on a new untouched "
            "validation seed vector before any locked test or claim language."
        ),
    }


def analyze(
    artifact: Mapping[str, Any],
    *,
    source_sha256: str,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    seeds, map_id = _validate_top_level(artifact)
    runs = _normalize_runs(artifact, seeds, map_id)
    failures: list[dict[str, Any]] = []
    _audit_pairing(runs, failures)
    _audit_budget(runs, failures)
    totals = _audit_safety_and_attribution(runs, failures)
    audit = {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "totals": totals,
        "paired_exogenous_inputs_match": not any(
            item["category"] == "pairing" for item in failures
        ),
        "budget_and_dualcap_contracts_passed": not any(
            item["category"] == "budget" for item in failures
        ),
        "safety_timeout_route_and_invariants_passed": not any(
            item["category"] == "integrity" for item in failures
        ),
    }
    indexed = {
        (str(run["method"]), int(run["seed"]), str(run["workload"])): run
        for run in runs
    }
    comparisons = {
        comparator: _comparison(
            comparator,
            indexed,
            seeds,
            bootstrap_samples=bootstrap_samples,
        )
        for comparator in COMPARATORS
    }
    summaries = _method_summaries(runs)
    screening = _screen(audit, comparisons, summaries)
    return {
        "schema": ANALYSIS_SCHEMA,
        "source": {
            "schema": artifact["schema"],
            "sha256": source_sha256,
            "split": artifact["split"],
            "evidence_class": artifact["evidence_class"],
        },
        "evidence_warning": (
            "Development-only exploratory evidence: this result cannot support "
            "a paper-result, locked-test, or SOTA claim."
        ),
        "design": {
            "map_id": map_id,
            "n_maps": 1,
            "root_seeds": list(seeds),
            "n_root_seed_clusters": len(seeds),
            "workloads": list(EXPECTED_WORKLOADS),
            "methods": list(TARGET_METHODS),
            "paired_cells_per_method": len(seeds) * len(EXPECTED_WORKLOADS),
            "cells_per_root_seed_cluster": len(EXPECTED_WORKLOADS),
            "total_runs": len(runs),
            "independent_unit": "root_seed",
            "pseudoreplication_guard": (
                "The three workload cells sharing a root seed remain one cluster."
            ),
        },
        "audit": audit,
        "method_summaries": summaries,
        "comparisons": comparisons,
        "screening": screening,
    }


def render_markdown(report: Mapping[str, Any], source: Path) -> str:
    design = report["design"]
    audit = report["audit"]
    screen = report["screening"]
    lines = [
        "# Context dual-cap dev10 screen",
        "",
        f"> **Scope:** {report['evidence_warning']}",
        "",
        f"- Source: `{source}`",
        f"- Source SHA-256: `{report['source']['sha256']}`",
        f"- Design: {design['n_root_seed_clusters']} root clusters × 3 workloads = "
        f"{design['paired_cells_per_method']} paired cells per method on one map",
        f"- Audit: **{'PASS' if audit['passed'] else 'FAIL'}**",
        f"- Recommendation: **`{screen['recommendation']}`**",
        "",
        "## Paired throughput effects",
        "",
        "| Comparator | Mean Δ tasks | Mean Δ% | Root-cluster 95% CI | Root W/T/L | Exact sign-flip p> |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for comparator in COMPARATORS:
        comparison = report["comparisons"][comparator]
        ci = comparison["cluster_bootstrap"]["mean_relative_effect_ci"]
        wtl = comparison["root_seed_win_tie_loss"]
        lines.append(
            f"| `{comparator}` | {comparison['mean_absolute_task_delta']:+.2f} | "
            f"{comparison['mean_relative_effect_percent']:+.2f}% | "
            f"[{100 * ci[0]:+.2f}%, {100 * ci[1]:+.2f}%] | "
            f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} | "
            f"{comparison['exact_sign_flip']['p_greater']:.4g} |"
        )
    lines.extend(
        [
            "",
            "## Resource summary",
            "",
            "| Method | Mean tasks | Generator calls | Post generations | Post switches |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for method in TARGET_METHODS:
        row = report["method_summaries"][method]
        lines.append(
            f"| `{method}` | {row['mean_tasks']:.2f} | "
            f"{row['mean_generator_calls']:.2f} | "
            f"{row['mean_post_bootstrap_generations']:.2f} | "
            f"{row['mean_post_bootstrap_switches']:.2f} |"
        )
    lines.extend(["", "## Screen gates", ""])
    for name, passed in screen["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    resources = screen["resource_effects"]
    lines.extend(
        [
            "",
            f"Generator-call reduction vs exact: {resources['generator_call_reduction_vs_exact']:.2%}.",
            f"Generator-call reduction vs original context: {resources['generator_call_reduction_vs_context']:.2%}.",
            f"Switch reduction vs original context: {resources['post_bootstrap_switch_reduction_vs_context']:.2%}.",
            "",
            "Even a complete PASS here only licenses freezing the candidate for fresh validation; it is not paper or SOTA evidence.",
            "",
        ]
    )
    if audit["failures"]:
        lines.extend(["## Audit failures", ""])
        for item in audit["failures"]:
            lines.append(
                f"- `{item['category']}/{item['check']}`: `{item.get('cell', item.get('detail', {}))}`"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    source = args.artifact.resolve()
    try:
        artifact = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(artifact, dict):
            raise DualCapArtifactError("top-level JSON value must be an object")
        report = analyze(
            artifact,
            source_sha256=_sha256(source),
            bootstrap_samples=args.bootstrap_samples,
        )
    except (OSError, json.JSONDecodeError, DualCapArtifactError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(report, source), encoding="utf-8")
    print(
        json.dumps(
            {
                "audit_passed": report["audit"]["passed"],
                "recommendation": report["screening"]["recommendation"],
                "output_json": str(args.output_json.resolve()),
                "output_md": str(args.output_md.resolve()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
