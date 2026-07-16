#!/usr/bin/env python3
"""Analyze the four-cell validation-v2 matrix without pseudoreplication.

The command consumes exactly four runner artifacts forming two maps by two
agent-density settings.  A root seed, not any of its 12 scenario cells, is
the independent sampling unit.  Every bootstrap draw and sign-flip therefore
keeps all map/density/workload observations from one root seed together.

The registered validation comparisons are ``causal_block_B25`` against
``exact_even_B25`` and ``random_B25``, plus ``context_memory_B25`` against
``bootstrap_only`` and ``exact_even_B25``.  Other methods are included in
rankings and Pareto frontiers only.  The current formal lock rejects the
development-only ``random_memory_B25`` method; contaminated legacy diagnostics
can still rank it without turning it into validation evidence.
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
ANALYSIS_SCHEMA = "dai.combined-validation-v2-analysis/v1"
BOOTSTRAP_SEED = 20260714
DEFAULT_BOOTSTRAP_SAMPLES = 10_000
EXPECTED_ROOT_SEEDS = 10
EXPECTED_MAPS = 2
EXPECTED_DENSITIES = 2
EXPECTED_WORKLOADS = ("stationary", "abrupt", "recurrent")
EXPECTED_HORIZON = 2000
EXPECTED_DECISION_WINDOW = 20
EXPECTED_VALIDATION_V2_SEEDS = (
    320019,
    241771,
    827130,
    693142,
    741084,
    12102,
    133633,
    876480,
    50620,
    131545,
)
EXPECTED_CONTAMINATED_SEEDS = tuple(range(101, 111))
EXPECTED_SOURCE_DEVELOPMENT_SHA256 = (
    "d971c23983bb9e2b1bc517cea0db19fd5da5bc97a16b6a2aa3a777c06b7ff9f7"
)
EXPECTED_CHECKPOINT_FILE_SHA256 = (
    "e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d"
)
EXPECTED_CHECKPOINT_PARAMS_SHA256 = (
    "6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac"
)
EXPECTED_SIMULATOR_SHA256 = (
    "9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5"
)
EXPECTED_SCENARIOS = frozenset(
    {
        (
            "warehouse_small_narrow_kiva",
            "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
            218,
        ),
        (
            "warehouse_small_narrow_kiva",
            "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
            382,
        ),
        (
            "warehouse_small_kiva",
            "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
            255,
        ),
        (
            "warehouse_small_kiva",
            "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
            447,
        ),
    }
)

CAUSAL = "causal_block_B25"
EXACT = "exact_even_B25"
RANDOM = "random_B25"
CONTEXT = "context_memory_B25"
BOOTSTRAP = "bootstrap_only"
REQUIRED_METHODS = frozenset({CAUSAL, EXACT, RANDOM, CONTEXT, BOOTSTRAP})
EXPECTED_FORMAL_METHODS = (
    "uniform",
    "bootstrap_only",
    "always",
    "exact_even_B25",
    "period_80",
    "random_B25",
    "js_B25",
    "js_cap_B25",
    "context_memory_B25",
    "throughput_drop_B25",
    "causal_block_B25",
    "proposed_cohort_B25",
    "proposed_no_cohort_B25",
)
ALLOWED_ROUTE_BUILD_REASONS = frozenset(
    {"init_pp", "task_change", "inherited_goal_route"}
)
FORMAL_EXACT_B25_METHODS = frozenset(
    {
        "exact_even_B25",
        "random_B25",
        "js_B25",
        "throughput_drop_B25",
        "causal_block_B25",
        "proposed_cohort_B25",
        "proposed_no_cohort_B25",
    }
)
COMPARISONS = (
    ("causal_vs_exact", CAUSAL, EXACT, "causal_primary"),
    ("causal_vs_random", CAUSAL, RANDOM, "causal_primary"),
    ("context_vs_bootstrap", CONTEXT, BOOTSTRAP, "context_secondary"),
    ("context_vs_exact", CONTEXT, EXACT, "context_secondary"),
)


class CombinedValidationError(ValueError):
    """The four artifacts cannot support a combined paired analysis."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CombinedValidationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise CombinedValidationError(f"{field} must be finite and >= {minimum}")
    return result


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CombinedValidationError(f"{field} must be an integer >= {minimum}")
    return int(value)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CombinedValidationError(f"{field} must be a non-empty string")
    return value


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("percentile needs at least one value")
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


def _canonical_evidence_class(artifact: Mapping[str, Any], label: str) -> str:
    split = artifact.get("split")
    evidence = artifact.get("evidence_class")
    if split == "validation_v2" and evidence == "validation_v2":
        return "validation_v2"
    # Seeds 101--110 and the old split name were exposed during development.
    # They may still be summarized, but never authorize the validation gate.
    if split == "validation" and evidence == "validation":
        return "contaminated_pilot_validation"
    if (
        split == "contaminated_pilot_validation"
        and evidence == "contaminated_pilot_validation"
    ):
        return "contaminated_pilot_validation"
    raise CombinedValidationError(
        f"{label} must have matching split/evidence_class equal to "
        "'validation_v2' (or legacy 'validation', which is contaminated)"
    )


def _protocol_signature(protocol: Mapping[str, Any]) -> str:
    # Agent count defines the density cell.  Execution parallelism is not a
    # controller parameter and may differ across otherwise paired artifacts.
    ignored = {
        "agents",
        "jobs",
        "exclusive_timing_declared",
        "timing_evidence_valid",
    }
    return _canonical({key: value for key, value in protocol.items() if key not in ignored})


def _checkpoint_signature(generator: Mapping[str, Any], label: str) -> tuple[str, str]:
    return (
        _string(generator.get("file_sha256"), f"{label}.generator.file_sha256"),
        _string(generator.get("params_sha256"), f"{label}.generator.params_sha256"),
    )


def _validate_validation_v2_lock(
    artifact: Mapping[str, Any],
    *,
    context: str,
    methods: set[str],
    seeds_in_artifact_order: Sequence[int],
    workloads: set[str],
    map_id: str,
    map_sha256: str,
    agents: int,
    protocol: Mapping[str, Any],
    checkpoint: tuple[str, str],
    simulator_sha256: str,
) -> None:
    """Enforce the frozen protocol, not merely a shape-compatible matrix."""

    if tuple(seeds_in_artifact_order) != EXPECTED_VALIDATION_V2_SEEDS:
        raise CombinedValidationError(
            f"{context}.seeds differs from the frozen validation-v2 seed vector"
        )
    if methods != set(EXPECTED_FORMAL_METHODS):
        missing = sorted(set(EXPECTED_FORMAL_METHODS) - methods)
        extra = sorted(methods - set(EXPECTED_FORMAL_METHODS))
        raise CombinedValidationError(
            f"{context}.methods differs from the frozen 13-method family; "
            f"missing={missing}, extra={extra}"
        )
    if workloads != set(EXPECTED_WORKLOADS):
        raise CombinedValidationError(f"{context}.workloads differs from the frozen family")
    if (map_id, map_sha256, agents) not in EXPECTED_SCENARIOS:
        raise CombinedValidationError(
            f"{context} map/hash/agents is not a frozen validation-v2 scenario"
        )
    if checkpoint != (
        EXPECTED_CHECKPOINT_FILE_SHA256,
        EXPECTED_CHECKPOINT_PARAMS_SHA256,
    ):
        raise CombinedValidationError(f"{context} does not use the frozen 10k checkpoint")
    if simulator_sha256 != EXPECTED_SIMULATOR_SHA256:
        raise CombinedValidationError(f"{context} simulator binary SHA-256 is not frozen")

    expected_protocol_scalars = {
        "warmup_time": 200,
        "scored_horizon": EXPECTED_HORIZON,
        "decision_window": EXPECTED_DECISION_WINDOW,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
    }
    for field, expected in expected_protocol_scalars.items():
        if protocol.get(field) != expected:
            raise CombinedValidationError(
                f"{context}.protocol.{field} must equal frozen value {expected!r}"
            )
    expected_derived = {
        "num_scored_windows": 100,
        "eligible_post_bootstrap_decisions": 99,
        "b25_budget": 25,
    }
    for field, expected in expected_derived.items():
        if protocol.get(field) != expected:
            raise CombinedValidationError(
                f"{context}.protocol.{field} must equal frozen value {expected!r}"
            )
    context_protocol = protocol.get("context_memory_B25")
    if not isinstance(context_protocol, dict):
        raise CombinedValidationError(f"{context}.protocol.context_memory_B25 is required")
    expected_context = {
        "recall_threshold": 0.05,
        "recall_margin": 0.02,
        "absolute_score_gate": 0.10,
        "min_gap_windows": 6,
        "maintenance_age_windows": 25,
        "maintenance_stability_gate": 0.20,
    }
    for field, expected in expected_context.items():
        if context_protocol.get(field) != expected:
            raise CombinedValidationError(
                f"{context}.protocol.context_memory_B25.{field} must equal "
                f"frozen value {expected!r}"
            )

    split_protocol = artifact.get("split_protocol")
    if not isinstance(split_protocol, dict):
        raise CombinedValidationError(f"{context}.split_protocol is required")
    split_checks = {
        "canonical_name": "validation_v2",
        "classification": "fresh_validation_v2",
        "preregistered_seeds": list(EXPECTED_VALIDATION_V2_SEEDS),
        "seed_derivation_source_development_artifact_sha256": (
            EXPECTED_SOURCE_DEVELOPMENT_SHA256
        ),
        "complete_registered_method_family_required": True,
        "complete_workload_family_required": True,
        "artifact_overwrite_permitted": False,
    }
    for field, expected in split_checks.items():
        if split_protocol.get(field) != expected:
            raise CombinedValidationError(
                f"{context}.split_protocol.{field} differs from the frozen amendment"
            )


def _validate_formal_run_budget(
    *,
    context: str,
    method: str,
    budget: Mapping[str, Any],
    mandatory_bootstrap: int,
    registered_budget: int,
    post_publications: int,
    post_generations: int,
    post_reactivations: int,
    generator_calls: int,
) -> None:
    """Reject quota-compatible-looking artifacts with changed method semantics."""

    if method == "uniform":
        expected = (0, 0, 0, 0, 0)
        exact_required = True
    elif method == "bootstrap_only":
        expected = (1, 0, 0, 0, 1)
        exact_required = True
    elif method == "always":
        expected = (1, 99, 99, 99, 100)
        exact_required = True
    elif method == "period_80":
        expected = (1, 24, 24, 24, 25)
        exact_required = False
    elif method in FORMAL_EXACT_B25_METHODS:
        expected = (1, 25, 25, 25, 26)
        exact_required = True
    elif method == "js_cap_B25":
        expected = None
        exact_required = False
        if not (
            mandatory_bootstrap == 1
            and registered_budget == 25
            and 0 <= post_publications <= 25
            and post_generations == post_publications
            and post_reactivations == 0
            and generator_calls == 1 + post_generations
        ):
            raise CombinedValidationError(f"{context} violates frozen js_cap_B25 budget semantics")
    elif method == CONTEXT:
        expected = None
        exact_required = False
        if not (
            mandatory_bootstrap == 1
            and registered_budget == 25
            and 0 <= post_publications <= 25
            and 0 <= post_generations <= post_publications
            and post_reactivations == post_publications - post_generations
            and generator_calls == 1 + post_generations
        ):
            raise CombinedValidationError(
                f"{context} violates frozen context_memory_B25 budget semantics"
            )
    else:  # Protected by the exact formal method-family lock.
        raise CombinedValidationError(f"{context} has unknown formal method {method!r}")

    if expected is not None:
        actual = (
            mandatory_bootstrap,
            registered_budget,
            post_publications,
            post_generations,
            generator_calls,
        )
        if actual != expected or post_reactivations != 0:
            raise CombinedValidationError(
                f"{context} violates frozen {method} budget semantics: "
                f"expected={expected}, actual={actual}, reactivations={post_reactivations}"
            )
    if budget.get("exact_quota_required") is not exact_required:
        raise CombinedValidationError(f"{context}.budget.exact_quota_required is inconsistent")
    if exact_required and budget.get("exact_quota_satisfied") is not True:
        raise CombinedValidationError(f"{context}.budget.exact_quota_satisfied must be true")
    if budget.get("cap_satisfied") is not True:
        raise CombinedValidationError(f"{context}.budget.cap_satisfied must be true")
    if budget.get("generation_cap_satisfied") is not True:
        raise CombinedValidationError(
            f"{context}.budget.generation_cap_satisfied must be true"
        )


def _normalize_artifacts(
    artifacts: Sequence[Mapping[str, Any]], source_labels: Sequence[str]
) -> dict[str, Any]:
    if len(artifacts) != 4 or len(source_labels) != 4:
        raise CombinedValidationError("exactly four artifacts are required")

    normalized_runs: list[dict[str, Any]] = []
    scenario_metadata: dict[str, dict[str, Any]] = {}
    reference_methods: set[str] | None = None
    reference_seeds: set[int] | None = None
    reference_workloads: set[str] | None = None
    reference_protocol: str | None = None
    reference_checkpoint: tuple[str, str] | None = None
    reference_simulator: str | None = None
    evidence_classes: set[str] = set()
    seen_scenarios: set[tuple[str, int]] = set()
    map_hashes: dict[str, str] = {}

    for artifact_index, (artifact, label) in enumerate(zip(artifacts, source_labels)):
        context = f"artifact[{artifact_index}] ({label})"
        if artifact.get("schema") != SOURCE_SCHEMA:
            raise CombinedValidationError(f"{context}.schema must be {SOURCE_SCHEMA!r}")
        if artifact.get("status") != "complete":
            raise CombinedValidationError(f"{context}.status must be 'complete'")
        evidence_class = _canonical_evidence_class(artifact, context)
        evidence_classes.add(evidence_class)

        methods_raw = artifact.get("methods")
        seeds_raw = artifact.get("seeds")
        workloads_raw = artifact.get("workloads")
        runs_raw = artifact.get("runs")
        protocol = artifact.get("protocol")
        generator = artifact.get("generator")
        if not isinstance(methods_raw, list) or not methods_raw:
            raise CombinedValidationError(f"{context}.methods must be non-empty")
        if not all(isinstance(value, str) and value for value in methods_raw):
            raise CombinedValidationError(f"{context}.methods must contain strings")
        methods = set(methods_raw)
        if len(methods) != len(methods_raw):
            raise CombinedValidationError(f"{context}.methods contains duplicates")
        if not REQUIRED_METHODS.issubset(methods):
            raise CombinedValidationError(
                f"{context}.methods lacks {sorted(REQUIRED_METHODS - methods)}"
            )
        if (
            not isinstance(seeds_raw, list)
            or len(seeds_raw) != EXPECTED_ROOT_SEEDS
            or not all(isinstance(value, int) and not isinstance(value, bool) for value in seeds_raw)
            or len(set(seeds_raw)) != len(seeds_raw)
        ):
            raise CombinedValidationError(
                f"{context}.seeds must contain {EXPECTED_ROOT_SEEDS} unique integers"
            )
        seeds = set(seeds_raw)
        if (
            evidence_class == "contaminated_pilot_validation"
            and seeds != set(EXPECTED_CONTAMINATED_SEEDS)
        ):
            raise CombinedValidationError(
                f"{context}.seeds is not the known contaminated 101--110 pilot set"
            )
        if (
            not isinstance(workloads_raw, list)
            or set(workloads_raw) != set(EXPECTED_WORKLOADS)
            or len(workloads_raw) != len(set(workloads_raw))
        ):
            raise CombinedValidationError(
                f"{context}.workloads must be {list(EXPECTED_WORKLOADS)!r}"
            )
        workloads = set(workloads_raw)
        if not isinstance(runs_raw, list) or not runs_raw:
            raise CombinedValidationError(f"{context}.runs must be non-empty")
        if not isinstance(protocol, dict):
            raise CombinedValidationError(f"{context}.protocol must be an object")
        if not isinstance(generator, dict):
            raise CombinedValidationError(f"{context}.generator must be an object")

        map_id = _string(artifact.get("map_id"), f"{context}.map_id")
        map_sha = _string(artifact.get("map_sha256"), f"{context}.map_sha256")
        agents = _integer(protocol.get("agents"), f"{context}.protocol.agents", minimum=1)
        scenario_key = (map_id, agents)
        if scenario_key in seen_scenarios:
            raise CombinedValidationError(f"duplicate map/density artifact {scenario_key!r}")
        seen_scenarios.add(scenario_key)
        scenario_id = f"{map_id}__agents_{agents}"
        scenario_metadata[scenario_id] = {
            "scenario_id": scenario_id,
            "map_id": map_id,
            "map_sha256": map_sha,
            "agents": agents,
            "density_label": f"agents={agents}",
            "source_label": label,
        }
        if map_id in map_hashes and map_hashes[map_id] != map_sha:
            raise CombinedValidationError(f"map hash changed across density cells for {map_id}")
        map_hashes[map_id] = map_sha

        protocol_signature = _protocol_signature(protocol)
        checkpoint_signature = _checkpoint_signature(generator, context)
        simulator_signature = _string(
            artifact.get("period_on_sim_sha256"), f"{context}.period_on_sim_sha256"
        )
        if evidence_class == "validation_v2":
            _validate_validation_v2_lock(
                artifact,
                context=context,
                methods=methods,
                seeds_in_artifact_order=seeds_raw,
                workloads=workloads,
                map_id=map_id,
                map_sha256=map_sha,
                agents=agents,
                protocol=protocol,
                checkpoint=checkpoint_signature,
                simulator_sha256=simulator_signature,
            )
        if reference_methods is None:
            reference_methods = methods
            reference_seeds = seeds
            reference_workloads = workloads
            reference_protocol = protocol_signature
            reference_checkpoint = checkpoint_signature
            reference_simulator = simulator_signature
        else:
            if methods != reference_methods:
                raise CombinedValidationError("all four artifacts must use the same method family")
            if seeds != reference_seeds:
                raise CombinedValidationError("all four artifacts must use the same root seeds")
            if workloads != reference_workloads:
                raise CombinedValidationError("all four artifacts must use the same workloads")
            if protocol_signature != reference_protocol:
                raise CombinedValidationError("controller/evaluation protocol differs across artifacts")
            if checkpoint_signature != reference_checkpoint:
                raise CombinedValidationError("frozen checkpoint hashes differ across artifacts")
            if simulator_signature != reference_simulator:
                raise CombinedValidationError("simulator binary hash differs across artifacts")

        expected_run_keys = set(itertools.product(methods, seeds, workloads))
        seen_run_keys: set[tuple[str, int, str]] = set()
        for run_index, raw in enumerate(runs_raw):
            run_context = f"{context}.runs[{run_index}]"
            if not isinstance(raw, dict):
                raise CombinedValidationError(f"{run_context} must be an object")
            method = raw.get("method")
            seed = raw.get("root_seed", raw.get("seed"))
            workload = raw.get("workload")
            if method not in methods or seed not in seeds or workload not in workloads:
                raise CombinedValidationError(f"{run_context} has an undeclared cell key")
            if raw.get("seed", seed) != seed:
                raise CombinedValidationError(f"{run_context} seed/root_seed mismatch")
            if raw.get("map_id") != map_id:
                raise CombinedValidationError(f"{run_context}.map_id differs from artifact map")
            if raw.get("split") not in {artifact.get("split"), None}:
                raise CombinedValidationError(f"{run_context}.split differs from artifact split")
            if raw.get("evidence_class") not in {artifact.get("evidence_class"), None}:
                raise CombinedValidationError(
                    f"{run_context}.evidence_class differs from artifact evidence"
                )
            timing_evidence_valid = raw.get("timing_evidence_valid")
            if not isinstance(timing_evidence_valid, bool):
                raise CombinedValidationError(
                    f"{run_context}.timing_evidence_valid must be boolean"
                )
            if timing_evidence_valid is not protocol.get("timing_evidence_valid"):
                raise CombinedValidationError(
                    f"{run_context} timing evidence disagrees with artifact protocol"
                )
            if timing_evidence_valid and not (
                protocol.get("jobs") == 1
                and protocol.get("exclusive_timing_declared") is True
            ):
                raise CombinedValidationError(
                    f"{run_context} falsely claims exclusive timing evidence"
                )
            run_key = (str(method), int(seed), str(workload))
            if run_key in seen_run_keys:
                raise CombinedValidationError(f"duplicate run cell {scenario_id}:{run_key!r}")
            seen_run_keys.add(run_key)

            tasks = _integer(raw.get("num_task_finished"), f"{run_context}.num_task_finished")
            horizon = _integer(raw.get("scored_horizon"), f"{run_context}.scored_horizon", minimum=1)
            decision_window = _integer(
                raw.get("decision_window"), f"{run_context}.decision_window", minimum=1
            )
            throughput = _number(
                raw.get("throughput_per_timestep"),
                f"{run_context}.throughput_per_timestep",
                minimum=0.0,
            )
            if not math.isclose(throughput, tasks / horizon, rel_tol=1e-12, abs_tol=1e-12):
                raise CombinedValidationError(f"{run_context} has inconsistent throughput")
            if horizon != EXPECTED_HORIZON or decision_window != EXPECTED_DECISION_WINDOW:
                raise CombinedValidationError(
                    f"{run_context} must use H={EXPECTED_HORIZON}, D={EXPECTED_DECISION_WINDOW}"
                )
            budget = raw.get("budget")
            safety = raw.get("safety")
            invariants = raw.get("invariants")
            if not isinstance(budget, dict) or not isinstance(safety, dict) or not isinstance(invariants, dict):
                raise CombinedValidationError(f"{run_context} lacks budget/safety/invariants objects")
            for field in (
                "manifest_id",
                "reset_causal_fingerprint",
                "release_projection_fingerprint",
                "distribution_update_fingerprint",
            ):
                _string(raw.get(field), f"{run_context}.{field}")
            task_tape_identity = raw.get("task_tape_identity")
            final_prefixes = raw.get("final_task_tape_prefixes")
            if not isinstance(task_tape_identity, dict) or not task_tape_identity:
                raise CombinedValidationError(f"{run_context}.task_tape_identity is required")
            if not isinstance(final_prefixes, dict):
                raise CombinedValidationError(f"{run_context}.final_task_tape_prefixes is required")
            released_prefixes = final_prefixes.get("released_prefix_lengths")
            if (
                not isinstance(released_prefixes, list)
                or not released_prefixes
                or not all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in released_prefixes
                )
            ):
                raise CombinedValidationError(
                    f"{run_context}.final_task_tape_prefixes.released_prefix_lengths is invalid"
                )
            if not isinstance(safety.get("passed"), bool):
                raise CombinedValidationError(f"{run_context}.safety.passed must be boolean")
            for field in (
                "collision_count",
                "edge_swap_count",
                "endpoint_mismatch_count",
                "invalid_move_count",
                "planner_timeout_count",
                "route_trace_invalid_count",
            ):
                _integer(safety.get(field, 0), f"{run_context}.safety.{field}")
            if not isinstance(invariants.get("passed"), bool):
                raise CombinedValidationError(f"{run_context}.invariants.passed must be boolean")
            _integer(
                invariants.get("online_workload_rng_draws", 0),
                f"{run_context}.invariants.online_workload_rng_draws",
            )
            post_publications = _integer(
                raw.get("post_bootstrap_publication_count"),
                f"{run_context}.post_bootstrap_publication_count",
            )
            generator_calls = _integer(raw.get("generator_calls"), f"{run_context}.generator_calls")
            if budget.get("post_bootstrap_publication_count") != post_publications:
                raise CombinedValidationError(f"{run_context} publication count disagrees with budget")
            if budget.get("total_generator_calls") != generator_calls:
                raise CombinedValidationError(f"{run_context} generator calls disagree with budget")
            post_generations = _integer(
                budget.get("post_bootstrap_generation_count", post_publications),
                f"{run_context}.budget.post_bootstrap_generation_count",
            )
            post_reactivations = _integer(
                budget.get("post_bootstrap_reactivation_count", 0),
                f"{run_context}.budget.post_bootstrap_reactivation_count",
            )
            if post_generations + post_reactivations != post_publications:
                raise CombinedValidationError(f"{run_context} operations do not partition publications")
            mandatory_bootstrap = _integer(
                budget.get("mandatory_bootstrap_calls", raw.get("mandatory_bootstrap_calls", 0)),
                f"{run_context}.budget.mandatory_bootstrap_calls",
            )
            if generator_calls != mandatory_bootstrap + post_generations:
                raise CombinedValidationError(f"{run_context} generator-call accounting mismatch")
            registered_budget = _integer(
                budget.get("post_bootstrap_budget", raw.get("publication_budget", 0)),
                f"{run_context}.budget.post_bootstrap_budget",
            )
            if raw.get("publication_budget", registered_budget) != registered_budget:
                raise CombinedValidationError(f"{run_context} publication budget disagrees")
            if raw.get("post_bootstrap_generation_count", post_generations) != post_generations:
                raise CombinedValidationError(f"{run_context} generation count disagrees")
            if raw.get("post_bootstrap_reactivation_count", post_reactivations) != post_reactivations:
                raise CombinedValidationError(f"{run_context} reactivation count disagrees")
            if evidence_class == "validation_v2":
                _validate_formal_run_budget(
                    context=run_context,
                    method=str(method),
                    budget=budget,
                    mandatory_bootstrap=mandatory_bootstrap,
                    registered_budget=registered_budget,
                    post_publications=post_publications,
                    post_generations=post_generations,
                    post_reactivations=post_reactivations,
                    generator_calls=generator_calls,
                )

            normalized = dict(raw)
            normalized.update(
                {
                    "source_label": label,
                    "scenario_id": scenario_id,
                    "map_id": map_id,
                    "agents": agents,
                    "density_label": f"agents={agents}",
                    "method": str(method),
                    "seed": int(seed),
                    "root_seed": int(seed),
                    "workload": str(workload),
                    "tasks": tasks,
                    "throughput": throughput,
                    "post_publications": post_publications,
                    "post_generations": post_generations,
                    "post_reactivations": post_reactivations,
                    "generator_calls_normalized": generator_calls,
                    "registered_budget": registered_budget,
                    "generator_seconds_normalized": _number(
                        raw.get("generator_seconds", 0.0),
                        f"{run_context}.generator_seconds",
                        minimum=0.0,
                    ),
                }
            )
            normalized_runs.append(normalized)

        if seen_run_keys != expected_run_keys:
            raise CombinedValidationError(
                f"{context} is not a complete method×seed×workload grid; "
                f"missing={sorted(expected_run_keys - seen_run_keys)[:8]}"
            )

    if len(evidence_classes) != 1:
        raise CombinedValidationError("fresh validation-v2 and contaminated legacy evidence cannot be pooled")
    evidence_class_final = next(iter(evidence_classes))
    maps = sorted({key[0] for key in seen_scenarios})
    agents_by_map = {
        map_id: sorted(agents for candidate_map, agents in seen_scenarios if candidate_map == map_id)
        for map_id in maps
    }
    if (
        len(maps) != EXPECTED_MAPS
        or len(seen_scenarios) != EXPECTED_MAPS * EXPECTED_DENSITIES
        or any(len(values) != EXPECTED_DENSITIES for values in agents_by_map.values())
    ):
        raise CombinedValidationError(
            "artifacts must contain exactly two agent-density levels on each of two maps"
        )
    # Equal density ratios imply different integer agent counts on maps with
    # different free-space capacity.  Normalize the lower/higher count within
    # each map rather than incorrectly treating the four counts as four levels.
    for scenario_id, metadata in scenario_metadata.items():
        ordered_agents = agents_by_map[metadata["map_id"]]
        density_index = ordered_agents.index(metadata["agents"])
        metadata["density_label"] = ("rho=0.20", "rho=0.35")[density_index]
        for run in normalized_runs:
            if run["scenario_id"] == scenario_id:
                run["density_label"] = metadata["density_label"]
    density_labels = ["rho=0.20", "rho=0.35"]
    if evidence_class_final == "validation_v2":
        observed_locked_scenarios = {
            (item["map_id"], item["map_sha256"], item["agents"])
            for item in scenario_metadata.values()
        }
        if observed_locked_scenarios != EXPECTED_SCENARIOS:
            raise CombinedValidationError(
                "artifacts do not equal the frozen validation-v2 scenario set"
            )

    assert reference_methods is not None
    assert reference_seeds is not None
    methods_sorted = sorted(reference_methods)
    seeds_sorted = (
        list(EXPECTED_VALIDATION_V2_SEEDS)
        if evidence_class_final == "validation_v2"
        else sorted(reference_seeds)
    )
    workloads_sorted = [value for value in EXPECTED_WORKLOADS if value in reference_workloads]

    # Within each exogenous scenario cell, every method must see exactly the
    # same tape, reset, release projection, and workload process.
    paired_fields = (
        "manifest_id",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    )
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for run in normalized_runs:
        grouped[(run["scenario_id"], run["seed"], run["workload"])].append(run)
    for cell, arms in grouped.items():
        if {run["method"] for run in arms} != set(methods_sorted):
            raise CombinedValidationError(f"paired cell {cell!r} lacks method arms")
        reference = arms[0]
        for run in arms[1:]:
            for field in paired_fields:
                if run.get(field) != reference.get(field):
                    raise CombinedValidationError(f"unpaired {field} in cell {cell!r}")
            if _canonical(run.get("task_tape_identity")) != _canonical(reference.get("task_tape_identity")):
                raise CombinedValidationError(f"unpaired task_tape_identity in cell {cell!r}")
            run_released = run.get("final_task_tape_prefixes", {}).get("released_prefix_lengths")
            ref_released = reference.get("final_task_tape_prefixes", {}).get("released_prefix_lengths")
            if run_released != ref_released:
                raise CombinedValidationError(f"unpaired released task prefix in cell {cell!r}")

    return {
        "methods": methods_sorted,
        "seeds": seeds_sorted,
        "maps": maps,
        "densities": density_labels,
        "agent_counts": sorted({key[1] for key in seen_scenarios}),
        "workloads": workloads_sorted,
        "scenarios": [scenario_metadata[key] for key in sorted(scenario_metadata)],
        "runs": normalized_runs,
        "evidence_class": evidence_class_final,
        "checkpoint": {
            "file_sha256": reference_checkpoint[0],
            "params_sha256": reference_checkpoint[1],
        },
        "simulator_sha256": reference_simulator,
    }


def _safety_audit(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    planner_timeouts = 0
    budget_violation_attempts = 0
    safety_error_count = 0
    route_attribution_error_count = 0
    timing_valid_count = 0
    for run in runs:
        identity = {
            "scenario_id": run["scenario_id"],
            "seed": run["seed"],
            "workload": run["workload"],
            "method": run["method"],
        }
        safety = run["safety"]
        invariants = run["invariants"]
        budget = run["budget"]

        collision_count = int(safety.get("collision_count", run.get("collisions", 0)))
        edge_swap_count = int(safety.get("edge_swap_count", run.get("edge_swaps", 0)))
        endpoint_mismatch_count = int(safety.get("endpoint_mismatch_count", 0))
        invalid_move_count = int(safety.get("invalid_move_count", run.get("invalid_moves", 0)))
        route_trace_invalid_count = int(safety.get("route_trace_invalid_count", 0))
        safety_error_count += (
            collision_count
            + edge_swap_count
            + invalid_move_count
            + route_trace_invalid_count
        )
        cohort_audit = run.get("cohort_attribution_audit")
        route_reasons = run.get("route_build_reason_counts")
        nested_route_reasons = (
            cohort_audit.get("route_build_reason_counts")
            if isinstance(cohort_audit, dict)
            else None
        )
        valid_route_reasons = (
            isinstance(route_reasons, dict)
            and bool(route_reasons)
            and route_reasons == nested_route_reasons
            and all(
                reason in ALLOWED_ROUTE_BUILD_REASONS
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 0
                for reason, count in route_reasons.items()
            )
        )
        route_attribution_ok = (
            isinstance(cohort_audit, dict)
            and cohort_audit.get("unexposed_zero_route_completions_excluded") is True
            and isinstance(cohort_audit.get("route_exposed_completion_count"), int)
            and cohort_audit.get("route_exposed_completion_count") >= 0
            and isinstance(cohort_audit.get("unexposed_zero_route_completion_count"), int)
            and cohort_audit.get("unexposed_zero_route_completion_count") >= 0
            and invariants.get("unexposed_completions_excluded_from_cohorts") is True
            and route_trace_invalid_count == 0
            and valid_route_reasons
        )
        if not route_attribution_ok:
            route_attribution_error_count += 1
        if run.get("timing_evidence_valid") is True:
            timing_valid_count += 1

        checks = {
            "runner_safety_passed": safety.get("passed") is True,
            "zero_collisions": collision_count == 0,
            "zero_edge_swaps": edge_swap_count == 0,
            "zero_endpoint_mismatches": endpoint_mismatch_count == 0,
            "zero_invalid_moves": invalid_move_count == 0,
            "zero_route_trace_invalid": route_trace_invalid_count == 0,
            "route_attribution_invariants_passed": route_attribution_ok,
            "runner_invariants_passed": invariants.get("passed") is True,
            "zero_online_workload_rng_draws": int(invariants.get("online_workload_rng_draws", 0)) == 0,
            "tape_not_exhausted": invariants.get("tape_not_exhausted", True) is True,
            "reward_sum_matches_completed": invariants.get("reward_sum_matches_completed", True) is True,
            "publication_cap_satisfied": run["post_publications"] <= run["registered_budget"],
            "generator_cap_satisfied": run["post_generations"] <= run["registered_budget"],
            "runner_budget_cap_flag": budget.get("cap_satisfied", True) is True,
            "runner_generator_cap_flag": budget.get("generation_cap_satisfied", True) is True,
        }
        for check, passed in checks.items():
            if not passed:
                failures.append({"check": check, **identity})
        attempts = int(budget.get("budget_violation_attempts", run.get("budget_violation_count", 0)))
        if attempts < 0:
            failures.append({"check": "nonnegative_budget_violation_attempts", **identity})
        budget_violation_attempts += max(0, attempts)
        planner_timeouts += int(safety.get("planner_timeout_count", run.get("planner_timeouts", 0)))

    integrity_gate_passed = (
        not failures
        and safety_error_count == 0
        and planner_timeouts == 0
        and budget_violation_attempts == 0
        and route_attribution_error_count == 0
    )
    return {
        "complete_four_artifact_grid": True,
        "paired_exogenous_inputs_match": True,
        "passed": integrity_gate_passed,
        "integrity_gate_passed": integrity_gate_passed,
        "failure_count": len(failures),
        "failures": failures,
        "safety_error_count": safety_error_count,
        "planner_timeout_count_method_outcome_not_excluded": planner_timeouts,
        "budget_violation_attempt_count": budget_violation_attempts,
        "route_attribution_error_count": route_attribution_error_count,
        "timing_evidence_valid_run_count": timing_valid_count,
        "all_runs_have_exclusive_timing_evidence": timing_valid_count == len(runs),
        "note": (
            "Planner timeouts remain recorded method outcomes, but the frozen "
            "validation-v2 integrity gate requires zero. Structural, pairing, and "
            "accounting violations hard-fail before inference."
        ),
    }


def _cluster_bootstrap(
    relative_root_effects: Sequence[float],
    absolute_root_effects: Sequence[float],
    *,
    samples: int,
) -> dict[str, Any]:
    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    if not relative_root_effects or len(relative_root_effects) != len(absolute_root_effects):
        raise ValueError("bootstrap root-effect vectors must be non-empty and aligned")
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(relative_root_effects)
    relative_draws: list[float] = []
    absolute_draws: list[float] = []
    for _ in range(samples):
        selected = [rng.randrange(n) for _ in range(n)]
        relative_draws.append(_mean(relative_root_effects[index] for index in selected))
        absolute_draws.append(_mean(absolute_root_effects[index] for index in selected))
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
    if not nonzero:
        return {
            "method": "exact",
            "alternative_greater": "candidate > comparator",
            "nonzero_root_seeds": 0,
            "assignments": 1,
            "p_greater": 1.0,
            "p_two_sided": 1.0,
        }
    if len(nonzero) > 24:
        raise CombinedValidationError("exact sign-flip is capped at 24 nonzero root seeds")
    observed = math.fsum(nonzero)
    assignments = 1 << len(nonzero)
    greater = 0
    two_sided = 0
    tolerance = 1e-15
    for bits in range(assignments):
        statistic = math.fsum(
            value if bits & (1 << index) else -value
            for index, value in enumerate(nonzero)
        )
        if statistic >= observed - tolerance:
            greater += 1
        if abs(statistic) >= abs(observed) - tolerance:
            two_sided += 1
    return {
        "method": "exact",
        "alternative_greater": "candidate > comparator",
        "nonzero_root_seeds": len(nonzero),
        "assignments": assignments,
        "p_greater": greater / assignments,
        "p_two_sided": two_sided / assignments,
    }


def _holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    running = 0.0
    result: dict[str, float] = {}
    for rank, (name, p_value) in enumerate(ordered):
        running = max(running, (count - rank) * float(p_value))
        result[name] = min(1.0, running)
    return result


def _direction(value: float, tolerance: float = 1e-15) -> str:
    if value > tolerance:
        return "positive"
    if value < -tolerance:
        return "negative"
    return "zero"


def _group_effects(cells: Sequence[Mapping[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for cell in cells:
        grouped[str(cell[field])].append(cell)
    result: dict[str, dict[str, Any]] = {}
    for value, rows in sorted(grouped.items()):
        relative = _mean(float(row["relative_effect"]) for row in rows)
        absolute = _mean(float(row["absolute_task_delta"]) for row in rows)
        result[value] = {
            "n_paired_cells": len(rows),
            "mean_relative_effect": relative,
            "mean_relative_effect_percent": 100.0 * relative,
            "mean_absolute_task_delta": absolute,
            "direction": _direction(relative),
        }
    return result


def _comparison(
    name: str,
    candidate: str,
    comparator: str,
    family: str,
    indexed: Mapping[tuple[str, int, str, str], Mapping[str, Any]],
    scenarios: Sequence[str],
    seeds: Sequence[int],
    workloads: Sequence[str],
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    relative_by_seed: dict[int, list[float]] = defaultdict(list)
    absolute_by_seed: dict[int, list[float]] = defaultdict(list)
    for scenario_id, seed, workload in itertools.product(scenarios, seeds, workloads):
        candidate_run = indexed[(scenario_id, seed, workload, candidate)]
        comparator_run = indexed[(scenario_id, seed, workload, comparator)]
        baseline = float(comparator_run["throughput"])
        if baseline <= 0.0:
            raise CombinedValidationError(
                f"zero comparator throughput in {name}:{scenario_id}:{seed}:{workload}"
            )
        relative = float(candidate_run["throughput"]) / baseline - 1.0
        absolute = float(candidate_run["tasks"]) - float(comparator_run["tasks"])
        cell = {
            "scenario_id": scenario_id,
            "map_id": candidate_run["map_id"],
            "agents": candidate_run["agents"],
            "density_label": candidate_run["density_label"],
            "seed": seed,
            "workload": workload,
            "relative_effect": relative,
            "absolute_task_delta": absolute,
        }
        cells.append(cell)
        relative_by_seed[seed].append(relative)
        absolute_by_seed[seed].append(absolute)
    root_relative = [_mean(relative_by_seed[seed]) for seed in seeds]
    root_absolute = [_mean(absolute_by_seed[seed]) for seed in seeds]
    sign_flip = _exact_sign_flip(root_relative)
    return {
        "name": name,
        "family": family,
        "candidate": candidate,
        "comparator": comparator,
        "independent_unit": "root_seed",
        "n_root_seed_clusters": len(seeds),
        "cells_per_root_seed_cluster": len(scenarios) * len(workloads),
        "n_paired_scenario_cells": len(cells),
        "mean_relative_effect": _mean(root_relative),
        "mean_relative_effect_percent": 100.0 * _mean(root_relative),
        "median_root_seed_relative_effect": statistics.median(root_relative),
        "mean_absolute_task_delta": _mean(root_absolute),
        "minimum_cell_relative_effect": min(float(cell["relative_effect"]) for cell in cells),
        "minimum_cell_relative_effect_percent": 100.0 * min(
            float(cell["relative_effect"]) for cell in cells
        ),
        "root_seed_relative_effects": {
            str(seed): effect for seed, effect in zip(seeds, root_relative)
        },
        "root_seed_absolute_task_deltas": {
            str(seed): effect for seed, effect in zip(seeds, root_absolute)
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
        "cluster_bootstrap": _cluster_bootstrap(
            root_relative, root_absolute, samples=bootstrap_samples
        ),
        "exact_sign_flip": sign_flip,
        "direction_by_map": _group_effects(cells, "map_id"),
        "direction_by_density": _group_effects(cells, "density_label"),
        "direction_by_workload": _group_effects(cells, "workload"),
    }


def _method_summaries(methods: Sequence[str], runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method in methods:
        selected = [run for run in runs if run["method"] == method]
        rows.append(
            {
                "method": method,
                "n_scenario_cells": len(selected),
                "mean_tasks": _mean(float(run["tasks"]) for run in selected),
                "mean_throughput": _mean(float(run["throughput"]) for run in selected),
                "mean_post_bootstrap_publications": _mean(
                    float(run["post_publications"]) for run in selected
                ),
                "mean_post_bootstrap_generations": _mean(
                    float(run["post_generations"]) for run in selected
                ),
                "mean_generator_calls": _mean(
                    float(run["generator_calls_normalized"]) for run in selected
                ),
                "mean_generator_seconds": _mean(
                    float(run["generator_seconds_normalized"]) for run in selected
                ),
            }
        )
    rows.sort(key=lambda row: (-row["mean_throughput"], row["method"]))
    for rank, row in enumerate(rows, 1):
        row["throughput_rank"] = rank
    return rows


def _rankings_by(
    methods: Sequence[str], runs: Sequence[Mapping[str, Any]], field: str
) -> dict[str, list[dict[str, Any]]]:
    values = sorted({str(run[field]) for run in runs})
    result: dict[str, list[dict[str, Any]]] = {}
    for value in values:
        rows = []
        for method in methods:
            selected = [
                run for run in runs
                if run["method"] == method and str(run[field]) == value
            ]
            rows.append(
                {
                    "method": method,
                    "mean_throughput": _mean(float(run["throughput"]) for run in selected),
                    "mean_tasks": _mean(float(run["tasks"]) for run in selected),
                }
            )
        rows.sort(key=lambda row: (-row["mean_throughput"], row["method"]))
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        result[value] = rows
    return result


def _pareto_frontier(
    summaries: Sequence[Mapping[str, Any]], cost_field: str
) -> dict[str, Any]:
    frontier: list[str] = []
    dominated_by: dict[str, list[str]] = {}
    for row in summaries:
        dominators: list[str] = []
        for other in summaries:
            if other["method"] == row["method"]:
                continue
            weak = (
                float(other["mean_throughput"]) >= float(row["mean_throughput"])
                and float(other[cost_field]) <= float(row[cost_field])
            )
            strict = (
                float(other["mean_throughput"]) > float(row["mean_throughput"])
                or float(other[cost_field]) < float(row[cost_field])
            )
            if weak and strict:
                dominators.append(str(other["method"]))
        if dominators:
            dominated_by[str(row["method"])] = sorted(dominators)
        else:
            frontier.append(str(row["method"]))
    frontier.sort(
        key=lambda method: next(
            float(row[cost_field]) for row in summaries if row["method"] == method
        )
    )
    return {
        "objectives": {"mean_throughput": "maximize", cost_field: "minimize"},
        "frontier_methods": frontier,
        "dominated_by": dominated_by,
        "context_memory": {
            "on_frontier": CONTEXT in frontier,
            "dominated_by": dominated_by.get(CONTEXT, []),
        },
    }


def _reduction(candidate: Mapping[str, Any], comparator: Mapping[str, Any], field: str) -> float:
    denominator = float(comparator[field])
    numerator = float(candidate[field])
    if denominator <= 0.0:
        return 0.0 if numerator <= 0.0 else -math.inf
    return 1.0 - numerator / denominator


def _pure_throughput_separation(
    indexed: Mapping[tuple[str, int, str, str], Mapping[str, Any]],
    scenarios: Sequence[str],
    seeds: Sequence[int],
    workloads: Sequence[str],
    methods: Sequence[str],
    summaries: Sequence[Mapping[str, Any]],
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    """Conservatively adjust the selected top method against all competitors."""

    if len(summaries) < 2:
        raise CombinedValidationError("pure-throughput gate requires at least two methods")
    top = str(summaries[0]["method"])
    runner_up = str(summaries[1]["method"])
    comparators = [method for method in methods if method != top]
    root_effects: dict[str, list[float]] = {}
    for comparator in comparators:
        effects: list[float] = []
        for seed in seeds:
            cell_effects = []
            for scenario_id, workload in itertools.product(scenarios, workloads):
                candidate = indexed[(scenario_id, seed, workload, top)]
                baseline = indexed[(scenario_id, seed, workload, comparator)]
                denominator = float(baseline["throughput"])
                if denominator <= 0.0:
                    raise CombinedValidationError(
                        f"zero comparator throughput in pure-throughput gate: {comparator}"
                    )
                cell_effects.append(float(candidate["throughput"]) / denominator - 1.0)
            effects.append(_mean(cell_effects))
        root_effects[comparator] = effects

    rng = random.Random(BOOTSTRAP_SEED)
    draws: dict[str, list[float]] = {comparator: [] for comparator in comparators}
    for _ in range(bootstrap_samples):
        selected = [rng.randrange(len(seeds)) for _ in seeds]
        for comparator in comparators:
            draws[comparator].append(
                _mean(root_effects[comparator][index] for index in selected)
            )
    # A Bonferroni simultaneous interval is conservative but valid after the
    # top method is selected from the same frozen method family.
    family_size = len(comparators)
    lower_probability = 0.025 / family_size
    upper_probability = 1.0 - lower_probability
    raw_p = {
        comparator: _exact_sign_flip(root_effects[comparator])["p_greater"]
        for comparator in comparators
    }
    holm_p = _holm_adjust(raw_p)
    rows: dict[str, dict[str, Any]] = {}
    for comparator in comparators:
        sorted_draws = sorted(draws[comparator])
        sign_flip = _exact_sign_flip(root_effects[comparator])
        rows[comparator] = {
            "mean_relative_effect": _mean(root_effects[comparator]),
            "root_seed_relative_effects": {
                str(seed): effect for seed, effect in zip(seeds, root_effects[comparator])
            },
            "bonferroni_familywise_95ci": [
                _percentile(sorted_draws, lower_probability),
                _percentile(sorted_draws, upper_probability),
            ],
            "exact_sign_flip_p_greater": sign_flip["p_greater"],
            "holm_adjusted_p_greater_family_all_competitors": holm_p[comparator],
        }
    runner_lower = float(rows[runner_up]["bonferroni_familywise_95ci"][0])
    return {
        "selected_top_method": top,
        "runner_up_method": runner_up,
        "method_family_size": len(methods),
        "multiplicity_family_size": family_size,
        "adjustment": "two-sided Bonferroni simultaneous cluster-bootstrap intervals",
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "top_ranks_first_by_mean": int(summaries[0]["throughput_rank"]) == 1,
        "runner_up_multiplicity_adjusted_ci_lower": runner_lower,
        "runner_up_adjusted_ci_lower_strictly_positive": runner_lower > 0.0,
        "comparisons": rows,
    }


def _validation_gate(
    evidence_class: str,
    audit: Mapping[str, Any],
    comparisons: Mapping[str, Mapping[str, Any]],
    summaries: Sequence[Mapping[str, Any]],
    design: Mapping[str, Any],
    pareto: Mapping[str, Mapping[str, Any]],
    pure_throughput: Mapping[str, Any],
) -> dict[str, Any]:
    summary_by_method = {row["method"]: row for row in summaries}
    causal_exact = comparisons["causal_vs_exact"]
    causal_random = comparisons["causal_vs_random"]
    context_exact = comparisons["context_vs_exact"]
    context_bootstrap = comparisons["context_vs_bootstrap"]
    calls_reduction = _reduction(
        summary_by_method[CONTEXT], summary_by_method[EXACT],
        "mean_generator_calls",
    )
    publication_reduction = _reduction(
        summary_by_method[CONTEXT], summary_by_method[EXACT],
        "mean_post_bootstrap_publications",
    )
    generator_time_reduction = _reduction(
        summary_by_method[CONTEXT], summary_by_method[EXACT],
        "mean_generator_seconds",
    )
    common = {
        "fresh_validation_v2_evidence": evidence_class == "validation_v2",
        "ten_root_seed_clusters": design["n_root_seed_clusters"] == EXPECTED_ROOT_SEEDS,
        "complete_2_map_x_2_density_x_3_workload_design": (
            design["maps"] == EXPECTED_MAPS
            and design["densities"] == EXPECTED_DENSITIES
            and design["workloads"] == len(EXPECTED_WORKLOADS)
        ),
        "integrity_gate_all_zero": audit["integrity_gate_passed"],
        "zero_safety_errors": audit["safety_error_count"] == 0,
        "zero_planner_timeouts": (
            audit["planner_timeout_count_method_outcome_not_excluded"] == 0
        ),
        "zero_budget_errors": audit["budget_violation_attempt_count"] == 0,
        "zero_route_attribution_errors": audit["route_attribution_error_count"] == 0,
    }
    causal_exact_ci_lower = float(
        causal_exact["cluster_bootstrap"]["mean_relative_effect_ci"][0]
    )
    causal_random_ci_lower = float(
        causal_random["cluster_bootstrap"]["mean_relative_effect_ci"][0]
    )
    causal_root_wins = int(causal_exact["root_seed_win_tie_loss"]["wins"])
    causal_root_win_rate = causal_root_wins / int(causal_exact["n_root_seed_clusters"])
    causal_positive_maps = sum(
        row["direction"] == "positive"
        for row in causal_exact["direction_by_map"].values()
    )
    causal_positive_workloads = sum(
        row["direction"] == "positive"
        for row in causal_exact["direction_by_workload"].values()
    )
    causal_stationary = float(
        causal_exact["direction_by_workload"]["stationary"]["mean_relative_effect"]
    )
    causal_checks = {
        **common,
        "mean_relative_vs_exact_at_least_plus_2pct": (
            float(causal_exact["mean_relative_effect"]) >= 0.02
        ),
        "cluster_bootstrap_95ci_lower_vs_exact_strictly_positive": (
            causal_exact_ci_lower > 0.0
        ),
        "one_sided_exact_sign_flip_vs_exact_below_0_05": (
            float(causal_exact["exact_sign_flip"]["p_greater"]) < 0.05
        ),
        "root_seed_win_rate_at_least_0_60": causal_root_win_rate >= 0.60,
        "positive_on_both_maps": causal_positive_maps == EXPECTED_MAPS,
        "at_least_two_of_three_workloads_positive": causal_positive_workloads >= 2,
        "stationary_relative_effect_at_least_minus_1pct": causal_stationary >= -0.01,
        "vs_random_cluster_bootstrap_95ci_lower_strictly_above_minus_1pct": (
            causal_random_ci_lower > -0.01
        ),
    }
    causal_passed = all(causal_checks.values())

    context_bootstrap_ci_lower = float(
        context_bootstrap["cluster_bootstrap"]["mean_relative_effect_ci"][0]
    )
    context_positive_maps = sum(
        row["direction"] == "positive"
        for row in context_bootstrap["direction_by_map"].values()
    )
    context_calls_pareto = bool(
        pareto["throughput_vs_generator_calls"]["context_memory"]["on_frontier"]
    )
    context_validation_checks = {
        **common,
        "mean_relative_vs_bootstrap_at_least_plus_2pct": (
            float(context_bootstrap["mean_relative_effect"]) >= 0.02
        ),
        "cluster_bootstrap_95ci_lower_vs_bootstrap_strictly_positive": (
            context_bootstrap_ci_lower > 0.0
        ),
        "one_sided_exact_sign_flip_vs_bootstrap_below_0_05": (
            float(context_bootstrap["exact_sign_flip"]["p_greater"]) < 0.05
        ),
        "mean_post_bootstrap_switches_at_most_5": (
            float(summary_by_method[CONTEXT]["mean_post_bootstrap_publications"]) <= 5.0
        ),
        "b25_generator_call_reduction_at_least_80pct": calls_reduction >= 0.80,
        "undominated_on_throughput_vs_generator_calls": context_calls_pareto,
        "positive_on_both_maps": context_positive_maps == EXPECTED_MAPS,
    }
    context_validation_passed = all(context_validation_checks.values())

    exclusive_timing_available = bool(audit["all_runs_have_exclusive_timing_evidence"])
    timing_reduction_passed = generator_time_reduction >= 0.80
    context_full_ready = (
        context_validation_passed
        and exclusive_timing_available
        and timing_reduction_passed
    )
    if not context_validation_passed:
        context_full_status = "validation_candidate_gate_failed"
    elif not exclusive_timing_available:
        context_full_status = "pending_external_exclusive_timing"
    elif not timing_reduction_passed:
        context_full_status = "exclusive_timing_reduction_gate_failed"
    else:
        context_full_status = "full_efficiency_claim_ready"

    context_exact_ci_lower = float(
        context_exact["cluster_bootstrap"]["mean_relative_effect_ci"][0]
    )
    near_exact_checks = {
        **common,
        "mean_relative_vs_exact_at_least_minus_0_5pct": (
            float(context_exact["mean_relative_effect"]) >= -0.005
        ),
        "cluster_bootstrap_95ci_lower_vs_exact_strictly_above_minus_1pct": (
            context_exact_ci_lower > -0.01
        ),
    }
    near_exact_permitted = all(near_exact_checks.values())

    pure_throughput_checks = {
        **common,
        "selected_controller_ranks_first_by_mean": pure_throughput[
            "top_ranks_first_by_mean"
        ],
        "multiplicity_adjusted_95ci_lower_vs_runner_up_strictly_positive": (
            pure_throughput["runner_up_adjusted_ci_lower_strictly_positive"]
        ),
    }
    pure_throughput_passed = all(pure_throughput_checks.values())

    if causal_passed and context_validation_passed:
        recommendation = (
            "GO_CAUSAL_QUALITY_AND_CONTEXT_VALIDATION_CANDIDATE_"
            "PENDING_EXCLUSIVE_TIMING"
            if not context_full_ready
            else "GO_CAUSAL_QUALITY_AND_FULL_CONTEXT_EFFICIENCY"
        )
    elif causal_passed:
        recommendation = "GO_CAUSAL_QUALITY_ONLY"
    elif context_validation_passed:
        recommendation = (
            "GO_CONTEXT_VALIDATION_CANDIDATE_PENDING_EXCLUSIVE_TIMING"
            if not context_full_ready
            else "GO_FULL_CONTEXT_EFFICIENCY"
        )
    else:
        recommendation = "NO_GO_RETURN_TO_DEVELOPMENT"
    return {
        "name": "frozen_combined_validation_v2_decision_gates",
        "scope": (
            "Validation method-freeze decision only; never authorizes a locked-test, "
            "confirmatory, global-SOTA, or paper-final claim."
        ),
        "thresholds": {
            "causal_mean_relative_vs_exact_min": 0.02,
            "causal_root_seed_win_rate_min": 0.60,
            "causal_stationary_relative_min": -0.01,
            "causal_vs_random_ci_lower_strictly_above": -0.01,
            "context_mean_relative_vs_bootstrap_min": 0.02,
            "context_mean_post_bootstrap_switches_max": 5.0,
            "context_b25_generator_call_reduction_min": 0.80,
            "context_b25_generator_time_reduction_min": 0.80,
            "context_near_exact_mean_min": -0.005,
            "context_near_exact_ci_lower_strictly_above": -0.01,
            "pure_throughput_adjusted_ci_lower_vs_runner_up_strictly_above": 0.0,
        },
        "causal_quality_go": {
            "passed": causal_passed,
            "checks": causal_checks,
            "root_seed_win_rate": causal_root_win_rate,
            "positive_map_count": causal_positive_maps,
            "positive_workload_count": causal_positive_workloads,
        },
        "context_validation_candidate_passed": context_validation_passed,
        "context_validation_candidate": {
            "passed": context_validation_passed,
            "checks": context_validation_checks,
            "generator_call_reduction_vs_exact_B25": calls_reduction,
            "publication_reduction_vs_exact": publication_reduction,
            "mean_post_bootstrap_switches": summary_by_method[CONTEXT][
                "mean_post_bootstrap_publications"
            ],
        },
        "context_full_efficiency_claim_ready": context_full_ready,
        "context_full_efficiency_claim": {
            "ready": context_full_ready,
            "status": context_full_status,
            "exclusive_timing_evidence_available": exclusive_timing_available,
            "generator_time_reduction_vs_exact_B25": generator_time_reduction,
            "generator_time_reduction_at_least_80pct": (
                timing_reduction_passed if exclusive_timing_available else None
            ),
            "parallel_generator_seconds_classification": (
                "confirmatory_exclusive_timing"
                if exclusive_timing_available
                else "diagnostic_only_not_eligible_for_time_gate"
            ),
        },
        "context_near_exact_language": {
            "permitted": near_exact_permitted,
            "checks": near_exact_checks,
        },
        "pure_throughput_best_evaluated_controller": {
            **pure_throughput,
            "passed": pure_throughput_passed,
            "checks": pure_throughput_checks,
            "scope": (
                "Frozen OnlineGGO backbone and evaluated publication controllers only."
            ),
        },
        "passed_any_candidate_path": causal_passed or context_validation_passed,
        "recommendation": recommendation,
    }


def analyze_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    source_labels: Sequence[str] | None = None,
    source_sha256: Sequence[str] | None = None,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    labels = list(source_labels or [f"artifact_{index}" for index in range(len(artifacts))])
    if len(labels) != len(artifacts):
        raise ValueError("source_labels length must match artifacts")
    hashes = list(source_sha256 or ["synthetic_or_in_memory"] * len(artifacts))
    if len(hashes) != len(artifacts):
        raise ValueError("source_sha256 length must match artifacts")
    normalized = _normalize_artifacts(artifacts, labels)
    runs = normalized["runs"]
    methods = normalized["methods"]
    seeds = normalized["seeds"]
    workloads = normalized["workloads"]
    scenarios = [item["scenario_id"] for item in normalized["scenarios"]]
    indexed = {
        (run["scenario_id"], run["seed"], run["workload"], run["method"]): run
        for run in runs
    }
    comparison_rows = [
        _comparison(
            name,
            candidate,
            comparator,
            family,
            indexed,
            scenarios,
            seeds,
            workloads,
            bootstrap_samples=bootstrap_samples,
        )
        for name, candidate, comparator, family in COMPARISONS
    ]
    for family in sorted({row["family"] for row in comparison_rows}):
        family_rows = [row for row in comparison_rows if row["family"] == family]
        greater = _holm_adjust(
            {row["name"]: row["exact_sign_flip"]["p_greater"] for row in family_rows}
        )
        two_sided = _holm_adjust(
            {row["name"]: row["exact_sign_flip"]["p_two_sided"] for row in family_rows}
        )
        for row in family_rows:
            row["exact_sign_flip"]["holm_family"] = family
            row["exact_sign_flip"]["holm_adjusted_p_greater"] = greater[row["name"]]
            row["exact_sign_flip"]["holm_adjusted_p_two_sided"] = two_sided[row["name"]]
    comparisons = {row["name"]: row for row in comparison_rows}
    summaries = _method_summaries(methods, runs)
    pure_throughput = _pure_throughput_separation(
        indexed,
        scenarios,
        seeds,
        workloads,
        methods,
        summaries,
        bootstrap_samples=bootstrap_samples,
    )
    audit = _safety_audit(runs)
    design = {
        "n_input_artifacts": len(artifacts),
        "n_root_seed_clusters": len(seeds),
        "root_seeds": seeds,
        "maps": len(normalized["maps"]),
        "map_ids": normalized["maps"],
        "densities": len(normalized["densities"]),
        "density_labels": normalized["densities"],
        "agent_counts": normalized["agent_counts"],
        "workloads": len(workloads),
        "workload_names": workloads,
        "methods": methods,
        "scenario_cells_per_method": len(scenarios) * len(seeds) * len(workloads),
        "cells_per_root_seed_cluster_per_method": len(scenarios) * len(workloads),
        "total_runs": len(runs),
        "independent_unit": "root_seed",
        "pseudoreplication_guard": (
            "All 12 map/density/workload cells sharing a root seed remain in one cluster."
        ),
    }
    pareto = {
        "throughput_vs_publications": _pareto_frontier(
            summaries, "mean_post_bootstrap_publications"
        ),
        "throughput_vs_generator_calls": _pareto_frontier(
            summaries, "mean_generator_calls"
        ),
        "throughput_vs_generator_seconds": _pareto_frontier(
            summaries, "mean_generator_seconds"
        ),
    }
    gate = _validation_gate(
        normalized["evidence_class"],
        audit,
        comparisons,
        summaries,
        design,
        pareto,
        pure_throughput,
    )
    return {
        "schema": ANALYSIS_SCHEMA,
        "sources": [
            {"label": label, "sha256": digest}
            for label, digest in zip(labels, hashes)
        ],
        "evidence": {
            "source_evidence_class": normalized["evidence_class"],
            "fresh_validation_v2": normalized["evidence_class"] == "validation_v2",
            "claim_warning": (
                "This is a ten-root-seed validation freeze analysis. It is not "
                "locked-test, confirmatory, or global-SOTA evidence."
                if normalized["evidence_class"] == "validation_v2"
                else "Legacy validation seeds were exposed and are marked contaminated; no gate can pass."
            ),
        },
        "reproducibility": {
            "checkpoint": normalized["checkpoint"],
            "simulator_sha256": normalized["simulator_sha256"],
            "scenarios": normalized["scenarios"],
            "frozen_validation_v2_lock": {
                "root_seeds": list(EXPECTED_VALIDATION_V2_SEEDS),
                "formal_methods": list(EXPECTED_FORMAL_METHODS),
                "source_development_artifact_sha256": (
                    EXPECTED_SOURCE_DEVELOPMENT_SHA256
                ),
                "scored_horizon": EXPECTED_HORIZON,
                "decision_window": EXPECTED_DECISION_WINDOW,
                "warmup_time": 200,
                "release_interval_per_agent": 110,
                "guard_suffix_tasks_per_agent": 4,
                "sigma": 0.75,
                "context_memory": {
                    "recall_threshold": 0.05,
                    "recall_margin": 0.02,
                    "absolute_score_gate": 0.10,
                    "min_gap_windows": 6,
                    "maintenance_age_windows": 25,
                    "maintenance_stability_gate": 0.20,
                },
            },
        },
        "design": design,
        "audit": audit,
        "method_macro_ranking": summaries,
        "rankings_by_map": _rankings_by(methods, runs, "map_id"),
        "rankings_by_density": _rankings_by(methods, runs, "density_label"),
        "rankings_by_workload": _rankings_by(methods, runs, "workload"),
        "registered_comparisons": comparisons,
        "multiplicity": {
            "procedure": "Holm step-down",
            "families": {
                "causal_primary": ["causal_vs_exact", "causal_vs_random"],
                "context_secondary": ["context_vs_bootstrap", "context_vs_exact"],
            },
            "note": "Holm adjusts exact root-seed sign-flip p-values within each declared family.",
        },
        "pareto": pareto,
        "preregistered_go_no_go": gate,
    }


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def render_markdown(report: Mapping[str, Any]) -> str:
    design = report["design"]
    audit = report["audit"]
    gate = report["preregistered_go_no_go"]
    lines = [
        "# Combined validation-v2 analysis",
        "",
        f"> **Scope:** {report['evidence']['claim_warning']}",
        "",
        (
            f"Design: {design['n_root_seed_clusters']} root-seed clusters, "
            f"{design['maps']} maps × {design['densities']} densities × "
            f"{design['workloads']} workloads = "
            f"{design['scenario_cells_per_method']} paired cells per method. "
            f"Inference uses **{design['n_root_seed_clusters']}**, not "
            f"**{design['scenario_cells_per_method']}**, independent observations."
        ),
        "",
        f"Audit: **{'PASS' if audit['passed'] else 'FAIL'}**; "
        f"planner timeouts retained as outcomes: "
        f"{audit['planner_timeout_count_method_outcome_not_excluded']}.",
        "",
        "## Macro ranking",
        "",
        "| Rank | Method | Mean tasks | Mean throughput | Post pubs | Generator calls |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in report["method_macro_ranking"]:
        lines.append(
            f"| {row['throughput_rank']} | `{row['method']}` | "
            f"{_fmt(row['mean_tasks'])} | {_fmt(row['mean_throughput'], 5)} | "
            f"{_fmt(row['mean_post_bootstrap_publications'])} | "
            f"{_fmt(row['mean_generator_calls'])} |"
        )
    lines.extend(
        [
            "",
            "## Root-cluster paired comparisons",
            "",
            "| Comparison | Mean Δ% | 95% cluster CI | Min cell Δ% | W/T/L roots | p> Holm | p2 Holm |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, row in report["registered_comparisons"].items():
        ci = row["cluster_bootstrap"]["mean_relative_effect_ci"]
        wtl = row["root_seed_win_tie_loss"]
        sign = row["exact_sign_flip"]
        lines.append(
            f"| `{name}` | {_fmt(row['mean_relative_effect_percent'])}% | "
            f"[{_fmt(100 * ci[0])}%, {_fmt(100 * ci[1])}%] | "
            f"{_fmt(row['minimum_cell_relative_effect_percent'])}% | "
            f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} | "
            f"{sign['holm_adjusted_p_greater']:.4g} | "
            f"{sign['holm_adjusted_p_two_sided']:.4g} |"
        )
    lines.extend(["", "## Map and workload directions", ""])
    for name, row in report["registered_comparisons"].items():
        maps = ", ".join(
            f"{key}: {value['direction']} ({_fmt(value['mean_relative_effect_percent'])}%)"
            for key, value in row["direction_by_map"].items()
        )
        workloads = ", ".join(
            f"{key}: {value['direction']} ({_fmt(value['mean_relative_effect_percent'])}%)"
            for key, value in row["direction_by_workload"].items()
        )
        lines.extend([f"- `{name}` maps — {maps}", f"- `{name}` workloads — {workloads}"])
    lines.extend(
        [
            "",
            "## Preregistered validation freeze gate",
            "",
            f"Recommendation: **`{gate['recommendation']}`**.",
            "",
            f"- Causal quality path: **{'PASS' if gate['causal_quality_go']['passed'] else 'FAIL'}**",
            f"- Context validation candidate: **{'PASS' if gate['context_validation_candidate_passed'] else 'FAIL'}**",
            f"- Context full efficiency claim: **{'READY' if gate['context_full_efficiency_claim_ready'] else 'NOT READY'}** "
            f"(`{gate['context_full_efficiency_claim']['status']}`)",
            f"- Context near-exact language gate: **{'PASS' if gate['context_near_exact_language']['permitted'] else 'FAIL'}**",
            f"- Pure-throughput separation: **{'PASS' if gate['pure_throughput_best_evaluated_controller']['passed'] else 'FAIL'}** "
            f"(top `{gate['pure_throughput_best_evaluated_controller']['selected_top_method']}` vs "
            f"runner-up `{gate['pure_throughput_best_evaluated_controller']['runner_up_method']}`)",
            "",
            "## Pareto frontiers",
            "",
        ]
    )
    for name, item in report["pareto"].items():
        lines.append(
            f"- {name}: " + ", ".join(f"`{method}`" for method in item["frontier_methods"])
        )
    lines.extend(
        [
            "",
            "The gate only decides whether to freeze a candidate before untouched "
            "locked testing. It does not license a paper-final or SOTA statement.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    paths = [path.resolve() for path in args.artifacts]
    artifacts = []
    for path in paths:
        with path.open("r", encoding="utf-8") as stream:
            artifacts.append(json.load(stream))
    report = analyze_artifacts(
        artifacts,
        source_labels=[str(path) for path in paths],
        source_sha256=[_sha256(path) for path in paths],
        bootstrap_samples=args.bootstrap_samples,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "output_json": str(args.output_json.resolve()),
                "output_md": str(args.output_md.resolve()),
                "recommendation": report["preregistered_go_no_go"]["recommendation"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
