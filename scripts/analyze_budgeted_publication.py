#!/usr/bin/env python3
"""Claim-aware paired analysis for absolute-release B25 experiments.

The independent unit is a root seed.  All map/workload cells belonging to a
root seed stay together in the cluster bootstrap and sign-flip test.  The
primary comparison is intentionally fixed to ``proposed_cohort_B25`` versus
``exact_even_B25``; changing either arm requires a new preregistration rather
than a command-line switch.

Development and validation artifacts are always exploratory.  A locked-test
quality claim is considered only for a correctly labelled, 30-root-seed
artifact that also passes the preregistered performance, breadth, safety,
budget, and workload-fingerprint checks.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
ANALYSIS_SCHEMA = "dai.absolute-budget-publication-analysis/v1"
PROPOSED = "proposed_cohort_B25"
BASELINE = "exact_even_B25"
TARGET_METHODS = (PROPOSED, BASELINE)
VALID_SPLITS = frozenset({"development", "validation", "locked_test"})

BOOTSTRAP_SEED = 20260714
DEFAULT_BOOTSTRAP_SAMPLES = 10_000
DEFAULT_SIGN_FLIP_SAMPLES = 100_000
MAX_EXACT_NONZERO_PAIRS = 20
CONFIRMATORY_ROOT_SEEDS = 30
PUBLICATION_FRACTION = 0.25
FORMAL_SCORED_HORIZON = 2000
FORMAL_DECISION_WINDOW = 20


class ArtifactValidationError(ValueError):
    """The runner artifact does not satisfy the structural contract."""


def _required(mapping: Mapping[str, Any], field: str, context: str) -> Any:
    if field not in mapping:
        raise ArtifactValidationError(f"{context}.{field} is required")
    return mapping[field]


def _plain_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactValidationError(f"{field} must be a JSON integer")
    if minimum is not None and value < minimum:
        raise ArtifactValidationError(f"{field} must be >= {minimum}")
    return value


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{field} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ArtifactValidationError(f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise ArtifactValidationError(f"{field} must be >= {minimum}")
    return result


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactValidationError(f"{field} must be a JSON boolean")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{field} must be a non-empty string")
    return value


def _unique(values: Iterable[Any], field: str) -> list[Any]:
    result = list(values)
    if len(result) != len(set(result)):
        raise ArtifactValidationError(f"{field} must not contain duplicates")
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sequence")
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


def cluster_bootstrap_mean_ci(
    root_effects: Sequence[float],
    *,
    samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> list[float]:
    """Percentile CI resampling root-seed clusters, never individual cells."""

    if not root_effects:
        raise ValueError("cluster bootstrap needs at least one root seed")
    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    rng = random.Random(seed)
    n = len(root_effects)
    means = [
        math.fsum(root_effects[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(samples)
    ]
    means.sort()
    return [_percentile(means, 0.025), _percentile(means, 0.975)]


def one_sided_sign_flip(
    root_effects: Sequence[float],
    *,
    monte_carlo_samples: int = DEFAULT_SIGN_FLIP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired sign-flip test for H1: mean(root effect) > 0.

    Up to 20 non-zero root pairs are enumerated exactly.  Larger samples use
    a fixed-seed Monte Carlo randomization test with the standard plus-one
    correction, so a simulated p-value is never reported as zero.
    """

    nonzero = [float(value) for value in root_effects if value != 0.0]
    if not nonzero:
        return {
            "method": "exact",
            "alternative": "greater",
            "statistic": "mean root-seed relative effect",
            "nonzero_root_seeds": 0,
            "extreme_assignments": 1,
            "total_assignments": 1,
            "p_value": 1.0,
        }
    observed = math.fsum(nonzero)
    if len(nonzero) <= MAX_EXACT_NONZERO_PAIRS:
        total = 1 << len(nonzero)
        extreme = 0
        signed_sum = -observed
        previous_gray = 0
        for assignment in range(total):
            gray = assignment ^ (assignment >> 1)
            if assignment:
                changed = gray ^ previous_gray
                index = (changed & -changed).bit_length() - 1
                if gray & changed:
                    signed_sum += 2.0 * nonzero[index]
                else:
                    signed_sum -= 2.0 * nonzero[index]
            if signed_sum >= observed - 1e-15:
                extreme += 1
            previous_gray = gray
        return {
            "method": "exact",
            "alternative": "greater",
            "statistic": "mean root-seed relative effect",
            "nonzero_root_seeds": len(nonzero),
            "extreme_assignments": extreme,
            "total_assignments": total,
            "p_value": extreme / total,
        }
    if monte_carlo_samples <= 0:
        raise ValueError("Monte Carlo sign-flip samples must be positive")
    rng = random.Random(seed)
    extreme = 0
    for _ in range(monte_carlo_samples):
        signed_sum = math.fsum(
            value if rng.getrandbits(1) else -value for value in nonzero
        )
        if signed_sum >= observed - 1e-15:
            extreme += 1
    return {
        "method": "monte_carlo_plus_one",
        "alternative": "greater",
        "statistic": "mean root-seed relative effect",
        "nonzero_root_seeds": len(nonzero),
        "extreme_draws": extreme,
        "monte_carlo_draws": monte_carlo_samples,
        "seed": seed,
        "p_value": (extreme + 1) / (monte_carlo_samples + 1),
    }


def _evidence_contract(artifact: Mapping[str, Any]) -> tuple[str, str]:
    split = _nonempty_string(_required(artifact, "split", "artifact"), "split")
    evidence = _nonempty_string(
        _required(artifact, "evidence_class", "artifact"), "evidence_class"
    )
    if split not in VALID_SPLITS:
        raise ArtifactValidationError(
            f"split must be one of {sorted(VALID_SPLITS)}, got {split!r}"
        )
    if evidence not in VALID_SPLITS:
        raise ArtifactValidationError(
            "evidence_class must be development, validation, or locked_test"
        )
    if evidence != split:
        raise ArtifactValidationError(
            f"evidence_class={evidence!r} does not match split={split!r}"
        )
    if split != "locked_test":
        locked_markers = {
            "sota_claim_permitted": artifact.get("sota_claim_permitted", False),
            "locked_test_claim": artifact.get("locked_test_claim", False),
            "confirmatory_claim_permitted": artifact.get(
                "confirmatory_claim_permitted", False
            ),
        }
        asserted = [
            name for name, value in locked_markers.items()
            if value is True
        ]
        claim_type = artifact.get("claim_type")
        if isinstance(claim_type, str) and (
            "locked" in claim_type.lower() or "confirm" in claim_type.lower()
        ):
            asserted.append("claim_type")
        protocol = artifact.get("protocol", {})
        if isinstance(protocol, dict):
            protocol_claim = protocol.get("claim_split")
            if protocol_claim == "locked_test":
                asserted.append("protocol.claim_split")
        if asserted:
            raise ArtifactValidationError(
                f"{split} evidence is falsely marked as a locked-test claim: "
                + ", ".join(asserted)
            )
    return split, evidence


def _validate_run(run: Mapping[str, Any], index: int) -> dict[str, Any]:
    context = f"runs[{index}]"
    method = _nonempty_string(_required(run, "method", context), f"{context}.method")
    if "seed" not in run and "root_seed" not in run:
        raise ArtifactValidationError(
            f"{context}.seed (or its root_seed alias) is required"
        )
    seed = _plain_int(
        run.get("seed", run.get("root_seed")), f"{context}.seed"
    )
    root_seed = _plain_int(
        run.get("root_seed", seed), f"{context}.root_seed"
    )
    if root_seed != seed:
        raise ArtifactValidationError(
            f"{context}.root_seed must equal seed for root-level pairing"
        )
    map_id = _nonempty_string(_required(run, "map_id", context), f"{context}.map_id")
    map_path = _nonempty_string(
        _required(run, "map_path", context), f"{context}.map_path"
    )
    workload = _nonempty_string(
        _required(run, "workload", context), f"{context}.workload"
    )
    manifest_id = _nonempty_string(
        _required(run, "manifest_id", context), f"{context}.manifest_id"
    )
    tasks = _plain_int(
        _required(run, "num_task_finished", context),
        f"{context}.num_task_finished",
        minimum=0,
    )
    throughput_key = (
        "throughput_per_timestep"
        if "throughput_per_timestep" in run
        else "throughput"
    )
    throughput = _number(
        _required(run, throughput_key, context),
        f"{context}.{throughput_key}",
        minimum=0.0,
    )
    scored_horizon = _plain_int(
        _required(run, "scored_horizon", context),
        f"{context}.scored_horizon",
        minimum=1,
    )
    decision_window = _plain_int(
        _required(run, "decision_window", context),
        f"{context}.decision_window",
        minimum=1,
    )
    if scored_horizon % decision_window != 0:
        raise ArtifactValidationError(
            f"{context}.scored_horizon must be divisible by decision_window"
        )
    expected_throughput = tasks / scored_horizon
    if not math.isclose(throughput, expected_throughput, rel_tol=1e-9, abs_tol=1e-12):
        raise ArtifactValidationError(
            f"{context}.{throughput_key} is inconsistent with "
            "num_task_finished/scored_horizon"
        )
    window_count = _plain_int(
        _required(run, "window_count", context),
        f"{context}.window_count",
        minimum=2,
    )
    expected_window_count = scored_horizon // decision_window
    if window_count != expected_window_count:
        raise ArtifactValidationError(
            f"{context}.window_count must equal "
            "scored_horizon/decision_window"
        )

    budget = _required(run, "budget", context)
    if not isinstance(budget, dict):
        raise ArtifactValidationError(f"{context}.budget must be an object")
    budget_fields = {
        "mandatory_bootstrap_calls": _plain_int(
            _required(budget, "mandatory_bootstrap_calls", f"{context}.budget"),
            f"{context}.budget.mandatory_bootstrap_calls", minimum=0,
        ),
        "post_bootstrap_budget": _plain_int(
            _required(budget, "post_bootstrap_budget", f"{context}.budget"),
            f"{context}.budget.post_bootstrap_budget", minimum=0,
        ),
        "post_bootstrap_publication_count": _plain_int(
            _required(
                budget, "post_bootstrap_publication_count", f"{context}.budget"
            ),
            f"{context}.budget.post_bootstrap_publication_count", minimum=0,
        ),
        "total_generator_calls": _plain_int(
            _required(budget, "total_generator_calls", f"{context}.budget"),
            f"{context}.budget.total_generator_calls", minimum=0,
        ),
        "budget_violation_attempts": _plain_int(
            _required(budget, "budget_violation_attempts", f"{context}.budget"),
            f"{context}.budget.budget_violation_attempts", minimum=0,
        ),
        "exact_quota_required": _boolean(
            _required(budget, "exact_quota_required", f"{context}.budget"),
            f"{context}.budget.exact_quota_required",
        ),
        "exact_quota_satisfied": _boolean(
            _required(budget, "exact_quota_satisfied", f"{context}.budget"),
            f"{context}.budget.exact_quota_satisfied",
        ),
    }
    flat_post_count = _plain_int(
        _required(run, "post_bootstrap_publication_count", context),
        f"{context}.post_bootstrap_publication_count", minimum=0,
    )
    flat_budget = _plain_int(
        _required(run, "publication_budget", context),
        f"{context}.publication_budget", minimum=0,
    )
    actual_budget_violations = _plain_int(
        _required(run, "budget_violation_count", context),
        f"{context}.budget_violation_count", minimum=0,
    )

    safety = _required(run, "safety", context)
    if not isinstance(safety, dict):
        raise ArtifactValidationError(f"{context}.safety must be an object")
    safety_counts = {
        field: _plain_int(
            _required(safety, field, f"{context}.safety"),
            f"{context}.safety.{field}", minimum=0,
        )
        for field in (
            "collision_count", "edge_swap_count", "invalid_move_count",
            "planner_timeout_count", "route_trace_invalid_count",
        )
    }
    safety_passed = _boolean(
        _required(safety, "passed", f"{context}.safety"),
        f"{context}.safety.passed",
    )

    invariant_object = _required(run, "invariants", context)
    if not isinstance(invariant_object, dict):
        raise ArtifactValidationError(f"{context}.invariants must be an object")
    runner_invariants_passed = _boolean(
        _required(invariant_object, "passed", f"{context}.invariants"),
        f"{context}.invariants.passed",
    )
    online_rng_draws = _plain_int(
        _required(
            invariant_object, "online_workload_rng_draws", f"{context}.invariants"
        ),
        f"{context}.invariants.online_workload_rng_draws", minimum=0,
    )
    release_projection_count = _plain_int(
        _required(
            invariant_object, "release_projection_count", f"{context}.invariants"
        ),
        f"{context}.invariants.release_projection_count", minimum=0,
    )

    tape = _required(run, "task_tape_identity", context)
    if not isinstance(tape, dict):
        raise ArtifactValidationError(
            f"{context}.task_tape_identity must be an object"
        )
    tape_normalized = {
        "mode": _nonempty_string(
            _required(tape, "mode", f"{context}.task_tape_identity"),
            f"{context}.task_tape_identity.mode",
        ),
        "schema_version": _required(
            tape, "schema_version", f"{context}.task_tape_identity"
        ),
        "manifest_sha256": _nonempty_string(
            _required(tape, "manifest_sha256", f"{context}.task_tape_identity"),
            f"{context}.task_tape_identity.manifest_sha256",
        ),
        "content_fnv1a64": _nonempty_string(
            _required(tape, "content_fnv1a64", f"{context}.task_tape_identity"),
            f"{context}.task_tape_identity.content_fnv1a64",
        ),
        "start_locations": _required(
            tape, "start_locations", f"{context}.task_tape_identity"
        ),
        "per_agent_lengths": _required(
            tape, "per_agent_lengths", f"{context}.task_tape_identity"
        ),
        "total_tasks": _plain_int(
            _required(tape, "total_tasks", f"{context}.task_tape_identity"),
            f"{context}.task_tape_identity.total_tasks", minimum=0,
        ),
    }
    if not isinstance(tape_normalized["start_locations"], list):
        raise ArtifactValidationError(
            f"{context}.task_tape_identity.start_locations must be a list"
        )
    if not isinstance(tape_normalized["per_agent_lengths"], list):
        raise ArtifactValidationError(
            f"{context}.task_tape_identity.per_agent_lengths must be a list"
        )

    prefixes = _required(run, "final_task_tape_prefixes", context)
    if not isinstance(prefixes, dict):
        raise ArtifactValidationError(
            f"{context}.final_task_tape_prefixes must be an object"
        )
    released_prefixes = _required(
        prefixes, "released_prefix_lengths", f"{context}.final_task_tape_prefixes"
    )
    if not isinstance(released_prefixes, list):
        raise ArtifactValidationError(
            f"{context}.final_task_tape_prefixes.released_prefix_lengths "
            "must be a list"
        )

    fingerprints = {
        field: _nonempty_string(_required(run, field, context), f"{context}.{field}")
        for field in (
            "reset_causal_fingerprint", "release_projection_fingerprint",
            "distribution_update_fingerprint",
        )
    }
    return {
        "raw": run,
        "method": method,
        "seed": seed,
        "root_seed": root_seed,
        "map_id": map_id,
        "map_path": map_path,
        "workload": workload,
        "manifest_id": manifest_id,
        "tasks": tasks,
        "throughput": throughput,
        "scored_horizon": scored_horizon,
        "decision_window": decision_window,
        "window_count": window_count,
        "budget": budget_fields,
        "flat_post_count": flat_post_count,
        "flat_budget": flat_budget,
        "actual_budget_violations": actual_budget_violations,
        "safety_counts": safety_counts,
        "safety_passed": safety_passed,
        "runner_invariants_passed": runner_invariants_passed,
        "online_rng_draws": online_rng_draws,
        "release_projection_count": release_projection_count,
        "tape": tape_normalized,
        "released_prefixes": released_prefixes,
        "fingerprints": fingerprints,
    }


def _structural_validation(
    artifact: Mapping[str, Any],
) -> tuple[str, str, list[int], list[str], list[dict[str, Any]]]:
    if artifact.get("schema") != SOURCE_SCHEMA:
        raise ArtifactValidationError(
            f"schema must be {SOURCE_SCHEMA!r}, got {artifact.get('schema')!r}"
        )
    if artifact.get("status") != "complete":
        raise ArtifactValidationError("artifact.status must be 'complete'")
    split, evidence = _evidence_contract(artifact)
    raw_seeds = _required(artifact, "seeds", "artifact")
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise ArtifactValidationError("artifact.seeds must be a non-empty list")
    seeds = _unique(
        (_plain_int(value, "artifact.seeds[]") for value in raw_seeds),
        "artifact.seeds",
    )
    raw_methods = _required(artifact, "methods", "artifact")
    if not isinstance(raw_methods, list) or not raw_methods:
        raise ArtifactValidationError("artifact.methods must be a non-empty list")
    methods = _unique(
        (_nonempty_string(value, "artifact.methods[]") for value in raw_methods),
        "artifact.methods",
    )
    missing_targets = set(TARGET_METHODS) - set(methods)
    if missing_targets:
        raise ArtifactValidationError(
            f"primary comparison methods are missing: {sorted(missing_targets)}"
        )
    raw_runs = _required(artifact, "runs", "artifact")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ArtifactValidationError("artifact.runs must be a non-empty list")
    runs = []
    for index, raw_run in enumerate(raw_runs):
        if not isinstance(raw_run, dict):
            raise ArtifactValidationError(f"runs[{index}] must be an object")
        run = _validate_run(raw_run, index)
        if run["seed"] not in seeds:
            raise ArtifactValidationError(
                f"runs[{index}].seed is not declared in artifact.seeds"
            )
        if run["method"] not in methods:
            raise ArtifactValidationError(
                f"runs[{index}].method is not declared in artifact.methods"
            )
        runs.append(run)

    maps = sorted({run["map_id"] for run in runs})
    workloads = sorted({run["workload"] for run in runs})
    by_key: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for run in runs:
        key = (run["method"], run["seed"], run["map_id"], run["workload"])
        if key in by_key:
            raise ArtifactValidationError(f"duplicate run cell {key!r}")
        by_key[key] = run
    expected = set(itertools.product(methods, seeds, maps, workloads))
    actual = set(by_key)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ArtifactValidationError(
            "runs must form a complete method×seed×map×workload grid; "
            f"missing={missing[:8]}, extra={extra[:8]}"
        )
    for map_id in maps:
        paths = {run["map_path"] for run in runs if run["map_id"] == map_id}
        if len(paths) != 1:
            raise ArtifactValidationError(
                f"map_id={map_id!r} resolves to multiple map paths"
            )
    return split, evidence, seeds, methods, runs


def _invariant_report(
    runs: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    maps: Sequence[str],
    workloads: Sequence[str],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    def check(ok: bool, name: str, run: Mapping[str, Any] | None = None) -> None:
        if ok:
            return
        record: dict[str, Any] = {"check": name}
        if run is not None:
            record["cell"] = {
                "method": run["method"], "root_seed": run["root_seed"],
                "map_id": run["map_id"], "workload": run["workload"],
            }
        failures.append(record)

    target_runs = [run for run in runs if run["method"] in TARGET_METHODS]
    for run in runs:
        safety = run["safety_counts"]
        zero_safety = all(
            safety[field] == 0
            for field in (
                "collision_count", "edge_swap_count", "invalid_move_count",
                "route_trace_invalid_count",
            )
        )
        check(zero_safety, "zero_collision_edge_swap_invalid_move_or_route", run)
        check(run["safety_passed"] == zero_safety, "runner_safety_flag_consistent", run)
        check(run["runner_invariants_passed"], "runner_invariants_passed", run)
        check(run["online_rng_draws"] == 0, "zero_online_workload_rng_draws", run)
        check(
            run["tape"]["mode"] == "absolute_release_queue_per_agent",
            "absolute_release_tape_mode", run,
        )
        check(
            sum(run["tape"]["per_agent_lengths"]) == run["tape"]["total_tasks"],
            "task_tape_length_conservation", run,
        )
        check(
            len(run["tape"]["start_locations"])
            == len(run["tape"]["per_agent_lengths"]),
            "one_start_per_agent_tape", run,
        )
    for run in target_runs:
        budget = run["budget"]
        eligible = run["window_count"] - 1
        expected_budget = math.ceil(PUBLICATION_FRACTION * eligible)
        check(budget["mandatory_bootstrap_calls"] == 1,
              "exactly_one_mandatory_bootstrap_call", run)
        check(budget["post_bootstrap_budget"] == expected_budget,
              "nested_post_bootstrap_budget_matches_fraction", run)
        check(run["flat_budget"] == expected_budget,
              "flat_publication_budget_matches_fraction", run)
        check(budget["post_bootstrap_publication_count"] == expected_budget,
              "nested_exact_fractional_budget_spend", run)
        check(run["flat_post_count"] == expected_budget,
              "flat_exact_fractional_budget_spend", run)
        check(
            run["flat_post_count"] == budget["post_bootstrap_publication_count"],
            "flat_and_nested_publication_counts_match", run,
        )
        check(
            budget["total_generator_calls"]
            == budget["mandatory_bootstrap_calls"]
            + budget["post_bootstrap_publication_count"],
            "generator_call_conservation", run,
        )
        check(budget["exact_quota_required"], "exact_quota_required", run)
        check(budget["exact_quota_satisfied"], "exact_quota_satisfied", run)
        check(run["actual_budget_violations"] == 0,
              "zero_actual_budget_violations", run)

    indexed = {
        (run["method"], run["seed"], run["map_id"], run["workload"]): run
        for run in runs
    }
    for seed, map_id, workload in itertools.product(seeds, maps, workloads):
        cell_runs = [
            indexed[(method, seed, map_id, workload)]
            for method in sorted({run["method"] for run in runs})
        ]
        reference = cell_runs[0]
        for run in cell_runs[1:]:
            check(run["scored_horizon"] == reference["scored_horizon"],
                  "paired_scored_horizon", run)
            check(run["decision_window"] == reference["decision_window"],
                  "paired_decision_window", run)
            check(run["window_count"] == reference["window_count"],
                  "paired_window_count", run)
            check(run["manifest_id"] == reference["manifest_id"],
                  "paired_manifest_id", run)
            check(_canonical(run["tape"]) == _canonical(reference["tape"]),
                  "paired_task_tape_identity", run)
            check(run["released_prefixes"] == reference["released_prefixes"],
                  "paired_released_prefixes", run)
            check(
                run["fingerprints"]["reset_causal_fingerprint"]
                == reference["fingerprints"]["reset_causal_fingerprint"],
                "paired_reset_causal_fingerprint", run,
            )
            check(
                run["fingerprints"]["release_projection_fingerprint"]
                == reference["fingerprints"]["release_projection_fingerprint"],
                "paired_release_projection_fingerprint", run,
            )
            check(
                run["fingerprints"]["distribution_update_fingerprint"]
                == reference["fingerprints"]["distribution_update_fingerprint"],
                "paired_distribution_update_fingerprint", run,
            )
            check(
                run["release_projection_count"]
                == reference["release_projection_count"],
                "paired_release_projection_count", run,
            )

    attempted = sum(run["budget"]["budget_violation_attempts"] for run in target_runs)
    eligible_decisions = sum(run["window_count"] - 1 for run in target_runs)
    actual = sum(run["actual_budget_violations"] for run in target_runs)
    timeout_count = sum(
        run["safety_counts"]["planner_timeout_count"] for run in target_runs
    )
    return {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "target_budget": {
            "publication_fraction": PUBLICATION_FRACTION,
            "expected_post_bootstrap_publications": sorted({
                math.ceil(PUBLICATION_FRACTION * (run["window_count"] - 1))
                for run in target_runs
            }),
            "budget_violation_attempts": attempted,
            "post_bootstrap_eligible_decisions": eligible_decisions,
            "budget_violation_attempt_rate": attempted / eligible_decisions,
            "actual_budget_violations": actual,
        },
        "planner_timeouts_are_outcomes_not_exclusions": timeout_count,
    }


def _group_summary(cell_effects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    relative = [float(cell["relative_throughput_delta"]) for cell in cell_effects]
    throughput = [float(cell["absolute_throughput_delta"]) for cell in cell_effects]
    tasks = [float(cell["absolute_task_delta"]) for cell in cell_effects]
    return {
        "n_paired_cells": len(cell_effects),
        "mean_absolute_task_delta": statistics.fmean(tasks),
        "mean_absolute_throughput_delta": statistics.fmean(throughput),
        "mean_relative_throughput_delta": statistics.fmean(relative),
        "median_relative_throughput_delta": statistics.median(relative),
        "win_tie_loss_cells": {
            "wins": sum(value > 0 for value in relative),
            "ties": sum(value == 0 for value in relative),
            "losses": sum(value < 0 for value in relative),
        },
    }


def analyze_artifact(
    artifact: Mapping[str, Any],
    *,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    sign_flip_samples: int = DEFAULT_SIGN_FLIP_SAMPLES,
    source_path: str = "<in-memory>",
    source_sha256: str = "",
) -> dict[str, Any]:
    split, evidence, seeds, methods, runs = _structural_validation(artifact)
    maps = sorted({run["map_id"] for run in runs})
    workloads = sorted({run["workload"] for run in runs})
    indexed = {
        (run["method"], run["seed"], run["map_id"], run["workload"]): run
        for run in runs
    }

    cell_effects: list[dict[str, Any]] = []
    for seed, map_id, workload in itertools.product(seeds, maps, workloads):
        proposed = indexed[(PROPOSED, seed, map_id, workload)]
        baseline = indexed[(BASELINE, seed, map_id, workload)]
        if baseline["throughput"] <= 0:
            raise ArtifactValidationError(
                "exact_even_B25 throughput must be positive in every paired cell; "
                f"failed at seed={seed}, map={map_id}, workload={workload}"
            )
        cell_effects.append({
            "root_seed": seed,
            "map_id": map_id,
            "workload": workload,
            "proposed_num_task_finished": proposed["tasks"],
            "baseline_num_task_finished": baseline["tasks"],
            "absolute_task_delta": proposed["tasks"] - baseline["tasks"],
            "proposed_throughput": proposed["throughput"],
            "baseline_throughput": baseline["throughput"],
            "absolute_throughput_delta": (
                proposed["throughput"] - baseline["throughput"]
            ),
            "relative_throughput_delta": (
                proposed["throughput"] - baseline["throughput"]
            ) / baseline["throughput"],
        })

    by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_workload: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in cell_effects:
        by_seed[int(cell["root_seed"])].append(cell)
        by_map[str(cell["map_id"])].append(cell)
        by_workload[str(cell["workload"])].append(cell)
    seed_summaries = {str(seed): _group_summary(by_seed[seed]) for seed in seeds}
    root_relative = [
        float(seed_summaries[str(seed)]["mean_relative_throughput_delta"])
        for seed in seeds
    ]
    root_absolute_throughput = [
        float(seed_summaries[str(seed)]["mean_absolute_throughput_delta"])
        for seed in seeds
    ]
    root_absolute_tasks = [
        float(seed_summaries[str(seed)]["mean_absolute_task_delta"])
        for seed in seeds
    ]
    wins = sum(value > 0 for value in root_relative)
    ties = sum(value == 0 for value in root_relative)
    losses = sum(value < 0 for value in root_relative)
    relative_ci = cluster_bootstrap_mean_ci(
        root_relative, samples=bootstrap_samples, seed=BOOTSTRAP_SEED
    )
    throughput_ci = cluster_bootstrap_mean_ci(
        root_absolute_throughput, samples=bootstrap_samples, seed=BOOTSTRAP_SEED
    )
    task_ci = cluster_bootstrap_mean_ci(
        root_absolute_tasks, samples=bootstrap_samples, seed=BOOTSTRAP_SEED
    )
    sign_flip = one_sided_sign_flip(
        root_relative, monte_carlo_samples=sign_flip_samples, seed=BOOTSTRAP_SEED
    )
    map_summaries = {name: _group_summary(cells) for name, cells in by_map.items()}
    workload_summaries = {
        name: _group_summary(cells) for name, cells in by_workload.items()
    }
    if "stationary" not in workload_summaries:
        raise ArtifactValidationError(
            "a workload named exactly 'stationary' is required for the "
            "preregistered degradation check"
        )
    stationary_effect = float(
        workload_summaries["stationary"]["mean_relative_throughput_delta"]
    )
    stationary_degradation = max(0.0, -stationary_effect)
    invariants = _invariant_report(runs, seeds, maps, workloads)

    mean_relative = statistics.fmean(root_relative)
    win_rate = wins / len(seeds)
    positive_maps = sum(
        summary["mean_relative_throughput_delta"] > 0
        for summary in map_summaries.values()
    )
    positive_workloads = sum(
        summary["mean_relative_throughput_delta"] > 0
        for summary in workload_summaries.values()
    )
    attempts_ok = (
        invariants["target_budget"]["budget_violation_attempt_rate"] <= 0.05
    )
    checks = {
        "locked_test_split": split == "locked_test",
        "at_least_30_root_seeds": len(seeds) >= CONFIRMATORY_ROOT_SEEDS,
        "formal_scored_horizon_is_2000": all(
            run["scored_horizon"] == FORMAL_SCORED_HORIZON for run in runs
        ),
        "formal_decision_window_is_20": all(
            run["decision_window"] == FORMAL_DECISION_WINDOW for run in runs
        ),
        "mean_relative_improvement_at_least_2pct": mean_relative >= 0.02,
        "cluster_bootstrap_95pct_lower_bound_above_zero": relative_ci[0] > 0.0,
        "one_sided_sign_flip_p_below_0_05": sign_flip["p_value"] < 0.05,
        "root_seed_win_rate_at_least_60pct": win_rate >= 0.60,
        "at_least_two_maps": len(maps) >= 2,
        "every_tested_map_positive": positive_maps == len(maps),
        "at_least_four_workload_families": len(workloads) >= 4,
        "at_least_three_workload_families_positive": positive_workloads >= 3,
        "stationary_degradation_at_most_1pct": stationary_degradation <= 0.01,
        "budget_violation_attempt_rate_at_most_5pct": attempts_ok,
        "all_safety_budget_and_fingerprint_invariants_pass": invariants["passed"],
    }
    exploratory_reasons: list[str] = []
    if split != "locked_test":
        exploratory_reasons.append(f"{split} split cannot support a locked-test claim")
    if len(seeds) < CONFIRMATORY_ROOT_SEEDS:
        exploratory_reasons.append(
            f"only {len(seeds)} root seeds; preregistration requires "
            f"{CONFIRMATORY_ROOT_SEEDS}"
        )
    confirmatory_eligible = not exploratory_reasons
    performance_and_invariants_pass = all(
        value for name, value in checks.items()
        if name not in {
            "locked_test_split", "at_least_30_root_seeds",
            "formal_scored_horizon_is_2000", "formal_decision_window_is_20",
        }
    )
    quality_gate_passed = all(checks.values()) and confirmatory_eligible
    if quality_gate_passed:
        recommendation = "GO_LOCKED_TEST_QUALITY_CLAIM"
    elif confirmatory_eligible:
        recommendation = "NO_GO_LOCKED_TEST_QUALITY_CLAIM"
    else:
        recommendation = (
            "EXPLORATORY_SCREEN_PASS" if performance_and_invariants_pass
            else "EXPLORATORY_SCREEN_FAIL"
        )

    return {
        "schema": ANALYSIS_SCHEMA,
        "status": "complete",
        "source": {"path": source_path, "sha256": source_sha256},
        "comparison": {"proposed": PROPOSED, "baseline": BASELINE},
        "evidence": {
            "source_split": split,
            "source_evidence_class": evidence,
            "analysis_evidence_class": (
                "locked_test_confirmatory"
                if confirmatory_eligible
                else "exploratory"
            ),
            "exploratory": not confirmatory_eligible,
            "exploratory_reasons": exploratory_reasons,
            "locked_test_claim_permitted": confirmatory_eligible,
            "sota_claim_permitted": False,
            "interpretation": (
                "Passing this gate supports only the preregistered, narrow "
                "same-backbone throughput-publication claim. It is not by "
                "itself a field-wide LMAPF SOTA result."
            ),
        },
        "design": {
            "root_seeds": seeds,
            "num_root_seeds": len(seeds),
            "maps": maps,
            "workloads": workloads,
            "num_cells_per_method": len(seeds) * len(maps) * len(workloads),
            "methods_in_source": methods,
            "scored_horizons": sorted({run["scored_horizon"] for run in runs}),
            "decision_windows": sorted({run["decision_window"] for run in runs}),
            "cluster_unit": "root_seed",
            "cell_weighting": "equal within root seed",
        },
        "effects": {
            "mean_absolute_task_delta": statistics.fmean(root_absolute_tasks),
            "median_absolute_task_delta": statistics.median(root_absolute_tasks),
            "cluster_bootstrap_95_ci_mean_absolute_task_delta": task_ci,
            "mean_absolute_throughput_delta": statistics.fmean(
                root_absolute_throughput
            ),
            "median_absolute_throughput_delta": statistics.median(
                root_absolute_throughput
            ),
            "cluster_bootstrap_95_ci_mean_absolute_throughput_delta": throughput_ci,
            "mean_relative_throughput_delta": mean_relative,
            "median_relative_throughput_delta": statistics.median(root_relative),
            "cluster_bootstrap_95_ci_mean_relative_throughput_delta": relative_ci,
            "win_tie_loss_root_seeds": {
                "wins": wins, "ties": ties, "losses": losses,
            },
            "root_seed_win_rate": win_rate,
            "one_sided_paired_sign_flip": sign_flip,
            "bootstrap": {
                "method": "percentile cluster bootstrap",
                "unit": "root_seed",
                "samples": bootstrap_samples,
                "seed": BOOTSTRAP_SEED,
                "confidence_level": 0.95,
            },
        },
        "root_seed_summaries": seed_summaries,
        "map_summaries": map_summaries,
        "workload_summaries": workload_summaries,
        "stationary_control": {
            "mean_relative_effect": stationary_effect,
            "degradation": stationary_degradation,
            "maximum_allowed_degradation": 0.01,
        },
        "invariants": invariants,
        "cell_effects": cell_effects,
        "preregistered_quality_gate": {
            "checks": checks,
            "performance_and_invariants_pass": performance_and_invariants_pass,
            "confirmatory_eligible": confirmatory_eligible,
            "passed": quality_gate_passed,
            "recommendation": recommendation,
        },
    }


def _print_summary(analysis: Mapping[str, Any]) -> None:
    evidence = analysis["evidence"]
    effects = analysis["effects"]
    gate = analysis["preregistered_quality_gate"]
    ci = effects["cluster_bootstrap_95_ci_mean_relative_throughput_delta"]
    wtl = effects["win_tie_loss_root_seeds"]
    print(
        f"evidence={evidence['analysis_evidence_class']} "
        f"split={evidence['source_split']} "
        f"n={analysis['design']['num_root_seeds']}"
    )
    print(
        f"{PROPOSED} vs {BASELINE}: "
        f"relative={effects['mean_relative_throughput_delta']:+.4%} "
        f"CI95=[{ci[0]:+.4%}, {ci[1]:+.4%}] "
        f"W/T/L={wtl['wins']}/{wtl['ties']}/{wtl['losses']} "
        f"p={effects['one_sided_paired_sign_flip']['p_value']:.8g}"
    )
    print(
        f"stationary_degradation="
        f"{analysis['stationary_control']['degradation']:.4%} "
        f"invariants={'PASS' if analysis['invariants']['passed'] else 'FAIL'}"
    )
    print(f"decision={gate['recommendation']}")
    for name, passed in gate["checks"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="claim-aware runner JSON")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES
    )
    parser.add_argument(
        "--sign-flip-samples", type=int, default=DEFAULT_SIGN_FLIP_SAMPLES
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.bootstrap_samples <= 0 or args.sign_flip_samples <= 0:
        raise SystemExit("bootstrap and sign-flip samples must be positive")
    raw = args.input.read_bytes()
    try:
        artifact = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {args.input}: {exc}") from exc
    if not isinstance(artifact, dict):
        raise SystemExit("input JSON root must be an object")
    output = args.output or args.input.with_name(
        args.input.stem + ".budgeted-analysis.json"
    )
    try:
        analysis = analyze_artifact(
            artifact,
            bootstrap_samples=args.bootstrap_samples,
            sign_flip_samples=args.sign_flip_samples,
            source_path=str(args.input.resolve()),
            source_sha256=hashlib.sha256(raw).hexdigest(),
        )
    except (ArtifactValidationError, ValueError) as exc:
        raise SystemExit(f"analysis refused: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(analysis, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _print_summary(analysis)
    print(f"analysis={output}")


if __name__ == "__main__":
    main()
