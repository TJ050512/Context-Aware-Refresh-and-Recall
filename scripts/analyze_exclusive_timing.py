#!/usr/bin/env python3
"""Audit and summarize the frozen context-memory exclusive timing matrix.

This analyzer is deliberately narrow.  It consumes exactly four sequential,
``jobs=1`` development artifacts and can support only the registered
``generator_seconds`` efficiency claim.  Task throughput is neither analyzed
nor reported here.
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
from typing import Any, Mapping, Sequence


SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
CONFIG_SCHEMA = "dai.context-exclusive-timing-protocol/v1"
ANALYSIS_SCHEMA = "dai.context-exclusive-timing-analysis/v1"
EXACT = "exact_even_B25"
CONTEXT = "context_memory_B25"
EXPECTED_METHODS = (EXACT, CONTEXT)
EXPECTED_SEEDS = (17, 18, 19, 20, 21)
EXPECTED_WORKLOADS = ("stationary", "abrupt", "recurrent")
EXPECTED_SCENARIOS = (
    (
        "narrow_r020",
        "warehouse_small_narrow_kiva",
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        218,
    ),
    (
        "narrow_r035",
        "warehouse_small_narrow_kiva",
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        382,
    ),
    (
        "regular_r020",
        "warehouse_small_kiva",
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        255,
    ),
    (
        "regular_r035",
        "warehouse_small_kiva",
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        447,
    ),
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
TIME_REDUCTION_THRESHOLD = 0.80
BOOTSTRAP_SEED = 20260714
BOOTSTRAP_SAMPLES = 10_000


class ExclusiveTimingAuditError(ValueError):
    """An input cannot support the preregistered timing analysis."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExclusiveTimingAuditError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = "positive finite" if positive else "finite"
        raise ExclusiveTimingAuditError(f"{field} must be {qualifier}")
    return result


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ExclusiveTimingAuditError(
            f"{field} must be an integer greater than or equal to {minimum}"
        )
    return int(value)


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires values")
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


def _assert_equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise ExclusiveTimingAuditError(
            f"{field} differs from frozen protocol: expected={expected!r}, actual={actual!r}"
        )


def _validate_config(config: Mapping[str, Any]) -> None:
    _assert_equal(config.get("schema"), CONFIG_SCHEMA, "config.schema")
    _assert_equal(
        config.get("status"),
        "frozen_before_first_exclusive_timing_run",
        "config.status",
    )
    scope = config.get("scope_restrictions", {})
    _assert_equal(
        scope.get("fresh_validation_results_used_to_design_protocol"),
        False,
        "config.scope fresh-result access",
    )
    _assert_equal(
        scope.get("throughput_inference_permitted"),
        False,
        "config.scope throughput inference",
    )
    matrix = config.get("matrix", {})
    _assert_equal(matrix.get("split"), "development", "config.matrix.split")
    _assert_equal(tuple(matrix.get("seeds", ())), EXPECTED_SEEDS, "config.matrix.seeds")
    _assert_equal(
        tuple(matrix.get("methods", ())), EXPECTED_METHODS, "config.matrix.methods"
    )
    _assert_equal(
        tuple(matrix.get("workloads", ())),
        EXPECTED_WORKLOADS,
        "config.matrix.workloads",
    )
    config_scenarios = tuple(
        (
            item.get("label"),
            item.get("map_id"),
            item.get("map_sha256"),
            item.get("agents"),
        )
        for item in matrix.get("scenarios", ())
    )
    _assert_equal(config_scenarios, EXPECTED_SCENARIOS, "config.matrix.scenarios")
    _assert_equal(matrix.get("total_runs"), 120, "config.matrix.total_runs")
    execution = config.get("execution", {})
    for field, expected in (
        ("jobs", 1),
        ("exclusive_timing_flag_required", True),
        ("artifacts_run_strictly_serially", True),
        ("refuse_artifact_log_or_analysis_overwrite", True),
    ):
        _assert_equal(execution.get(field), expected, f"config.execution.{field}")
    analysis = config.get("analysis", {})
    _assert_equal(
        analysis.get("generator_seconds_reduction_min"),
        TIME_REDUCTION_THRESHOLD,
        "config.analysis.generator_seconds_reduction_min",
    )
    _assert_equal(
        analysis.get("gate_requires_total_and_mean"),
        True,
        "config.analysis.gate_requires_total_and_mean",
    )
    _assert_equal(
        analysis.get("cluster_bootstrap_samples"),
        BOOTSTRAP_SAMPLES,
        "config.analysis.cluster_bootstrap_samples",
    )
    _assert_equal(
        analysis.get("cluster_bootstrap_seed"),
        BOOTSTRAP_SEED,
        "config.analysis.cluster_bootstrap_seed",
    )


def _validate_artifact(
    artifact: Mapping[str, Any], expected_scenario: tuple[str, str, str, int]
) -> dict[tuple[int, str, str], Mapping[str, Any]]:
    label, map_id, map_sha256, agents = expected_scenario
    prefix = f"artifact[{label}]"
    _assert_equal(artifact.get("schema"), SOURCE_SCHEMA, f"{prefix}.schema")
    _assert_equal(artifact.get("status"), "complete", f"{prefix}.status")
    _assert_equal(artifact.get("split"), "development", f"{prefix}.split")
    _assert_equal(
        artifact.get("evidence_class"), "development", f"{prefix}.evidence_class"
    )
    _assert_equal(tuple(artifact.get("seeds", ())), EXPECTED_SEEDS, f"{prefix}.seeds")
    _assert_equal(
        tuple(artifact.get("methods", ())), EXPECTED_METHODS, f"{prefix}.methods"
    )
    _assert_equal(
        tuple(artifact.get("workloads", ())), EXPECTED_WORKLOADS, f"{prefix}.workloads"
    )
    _assert_equal(artifact.get("map_id"), map_id, f"{prefix}.map_id")
    _assert_equal(artifact.get("map_sha256"), map_sha256, f"{prefix}.map_sha256")
    _assert_equal(
        artifact.get("period_on_sim_sha256"),
        EXPECTED_SIMULATOR_SHA256,
        f"{prefix}.period_on_sim_sha256",
    )
    generator = artifact.get("generator", {})
    _assert_equal(
        generator.get("file_sha256"),
        EXPECTED_CHECKPOINT_FILE_SHA256,
        f"{prefix}.generator.file_sha256",
    )
    _assert_equal(
        generator.get("params_sha256"),
        EXPECTED_CHECKPOINT_PARAMS_SHA256,
        f"{prefix}.generator.params_sha256",
    )

    protocol = artifact.get("protocol", {})
    expected_protocol = {
        "agents": agents,
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "num_scored_windows": 100,
        "b25_budget": 25,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
        "jobs": 1,
        "exclusive_timing_declared": True,
        "timing_evidence_valid": True,
    }
    for field, expected in expected_protocol.items():
        _assert_equal(protocol.get(field), expected, f"{prefix}.protocol.{field}")
    context_protocol = protocol.get("context_memory_B25", {})
    for field, expected in (
        ("recall_threshold", 0.05),
        ("recall_margin", 0.02),
        ("absolute_score_gate", 0.10),
        ("min_gap_windows", 6),
        ("maintenance_age_windows", 25),
        ("maintenance_stability_gate", 0.20),
    ):
        _assert_equal(
            context_protocol.get(field), expected, f"{prefix}.context.{field}"
        )

    runs = artifact.get("runs")
    if not isinstance(runs, list) or len(runs) != 30:
        raise ExclusiveTimingAuditError(f"{prefix}.runs must contain exactly 30 runs")
    indexed: dict[tuple[int, str, str], Mapping[str, Any]] = {}
    for index, run in enumerate(runs):
        if not isinstance(run, Mapping):
            raise ExclusiveTimingAuditError(f"{prefix}.runs[{index}] must be an object")
        seed = _integer(run.get("seed"), f"{prefix}.runs[{index}].seed")
        root_seed = _integer(
            run.get("root_seed"), f"{prefix}.runs[{index}].root_seed"
        )
        workload = run.get("workload")
        method = run.get("method")
        if seed not in EXPECTED_SEEDS or root_seed != seed:
            raise ExclusiveTimingAuditError(f"{prefix}.runs[{index}] has invalid seed")
        if workload not in EXPECTED_WORKLOADS or method not in EXPECTED_METHODS:
            raise ExclusiveTimingAuditError(f"{prefix}.runs[{index}] has invalid arm")
        _assert_equal(run.get("map_id"), map_id, f"{prefix}.runs[{index}].map_id")
        _assert_equal(
            run.get("timing_evidence_valid"),
            True,
            f"{prefix}.runs[{index}].timing_evidence_valid",
        )
        _assert_equal(run.get("scored_horizon"), 2000, f"{prefix}.run horizon")
        _assert_equal(run.get("decision_window"), 20, f"{prefix}.run window")
        _assert_equal(run.get("window_count"), 100, f"{prefix}.run count")
        _number(run.get("generator_seconds"), f"{prefix}.generator_seconds", positive=True)
        calls = _integer(run.get("generator_calls"), f"{prefix}.generator_calls", minimum=1)
        mandatory = _integer(
            run.get("mandatory_bootstrap_calls"),
            f"{prefix}.mandatory_bootstrap_calls",
        )
        generations = _integer(
            run.get("post_bootstrap_generation_count"),
            f"{prefix}.post_bootstrap_generation_count",
        )
        publications = _integer(
            run.get("post_bootstrap_publication_count"),
            f"{prefix}.post_bootstrap_publication_count",
        )
        reactivations = _integer(
            run.get("post_bootstrap_reactivation_count"),
            f"{prefix}.post_bootstrap_reactivation_count",
        )
        _assert_equal(mandatory, 1, f"{prefix}.mandatory_bootstrap_calls")
        _assert_equal(calls, mandatory + generations, f"{prefix}.generator-call audit")
        _assert_equal(
            publications,
            generations + reactivations,
            f"{prefix}.publication-operation audit",
        )
        _assert_equal(run.get("publication_budget"), 25, f"{prefix}.publication_budget")
        _assert_equal(
            run.get("budget_violation_count"), 0, f"{prefix}.budget_violation_count"
        )
        budget = run.get("budget", {})
        _assert_equal(budget.get("cap_satisfied"), True, f"{prefix}.budget.cap_satisfied")
        if method == EXACT:
            _assert_equal(calls, 26, f"{prefix}.exact generator_calls")
            _assert_equal(generations, 25, f"{prefix}.exact generations")
            _assert_equal(publications, 25, f"{prefix}.exact publications")
            _assert_equal(reactivations, 0, f"{prefix}.exact reactivations")
        elif publications > 25:
            raise ExclusiveTimingAuditError(f"{prefix}.context exceeds B25")
        safety = run.get("safety", {})
        _assert_equal(safety.get("passed"), True, f"{prefix}.safety.passed")
        _assert_equal(run.get("planner_timeouts"), 0, f"{prefix}.planner_timeouts")
        _assert_equal(
            run.get("invariants", {}).get("passed"), True, f"{prefix}.invariants.passed"
        )
        key = (seed, str(workload), str(method))
        if key in indexed:
            raise ExclusiveTimingAuditError(f"{prefix} contains duplicate arm {key}")
        indexed[key] = run

    expected_keys = {
        (seed, workload, method)
        for seed in EXPECTED_SEEDS
        for workload in EXPECTED_WORKLOADS
        for method in EXPECTED_METHODS
    }
    if set(indexed) != expected_keys:
        raise ExclusiveTimingAuditError(f"{prefix} does not contain the exact 30-arm grid")
    for seed in EXPECTED_SEEDS:
        for workload in EXPECTED_WORKLOADS:
            exact = indexed[(seed, workload, EXACT)]
            context = indexed[(seed, workload, CONTEXT)]
            for field in (
                "manifest_id",
                "reset_causal_fingerprint",
                "release_projection_fingerprint",
                "distribution_update_fingerprint",
            ):
                _assert_equal(
                    context.get(field), exact.get(field), f"{prefix}.paired.{field}"
                )
            _assert_equal(
                _canonical(context.get("task_tape_identity")),
                _canonical(exact.get("task_tape_identity")),
                f"{prefix}.paired.task_tape_identity",
            )
    return indexed


def _reduction(context_value: float, exact_value: float) -> float:
    if exact_value <= 0.0:
        raise ExclusiveTimingAuditError("exact denominator must be positive")
    return 1.0 - context_value / exact_value


def _aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    exact_seconds = math.fsum(float(record["exact_seconds"]) for record in records)
    context_seconds = math.fsum(float(record["context_seconds"]) for record in records)
    exact_calls = math.fsum(float(record["exact_calls"]) for record in records)
    context_calls = math.fsum(float(record["context_calls"]) for record in records)
    return {
        "paired_cells": len(records),
        "exact_generator_seconds": exact_seconds,
        "context_generator_seconds": context_seconds,
        "pooled_generator_seconds_reduction": _reduction(context_seconds, exact_seconds),
        "mean_paired_cell_generator_seconds_reduction": statistics.fmean(
            float(record["seconds_reduction"]) for record in records
        ),
        "exact_generator_calls": int(exact_calls),
        "context_generator_calls": int(context_calls),
        "pooled_generator_call_reduction": _reduction(context_calls, exact_calls),
        "mean_paired_cell_generator_call_reduction": statistics.fmean(
            float(record["call_reduction"]) for record in records
        ),
    }


def analyze(
    artifacts: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    config: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the preregistered timing report after strict integrity checks."""

    _validate_config(config)
    if len(artifacts) != 4:
        raise ExclusiveTimingAuditError("exactly four artifacts are required")
    expected_by_label = {item[0]: item for item in EXPECTED_SCENARIOS}
    if {label for label, _ in artifacts} != set(expected_by_label):
        raise ExclusiveTimingAuditError("artifact labels differ from the four frozen scenarios")

    records: list[dict[str, Any]] = []
    for label, artifact in artifacts:
        indexed = _validate_artifact(artifact, expected_by_label[label])
        for seed in EXPECTED_SEEDS:
            for workload in EXPECTED_WORKLOADS:
                exact = indexed[(seed, workload, EXACT)]
                context = indexed[(seed, workload, CONTEXT)]
                exact_seconds = float(exact["generator_seconds"])
                context_seconds = float(context["generator_seconds"])
                exact_calls = int(exact["generator_calls"])
                context_calls = int(context["generator_calls"])
                records.append(
                    {
                        "scenario": label,
                        "seed": seed,
                        "workload": workload,
                        "exact_seconds": exact_seconds,
                        "context_seconds": context_seconds,
                        "seconds_reduction": _reduction(context_seconds, exact_seconds),
                        "exact_calls": exact_calls,
                        "context_calls": context_calls,
                        "call_reduction": _reduction(context_calls, exact_calls),
                    }
                )
    if len(records) != 60:
        raise ExclusiveTimingAuditError("combined matrix must have exactly 60 pairs")

    overall = _aggregate(records)
    by_scenario = {
        label: _aggregate([record for record in records if record["scenario"] == label])
        for label, *_ in EXPECTED_SCENARIOS
    }
    by_workload = {
        workload: _aggregate(
            [record for record in records if record["workload"] == workload]
        )
        for workload in EXPECTED_WORKLOADS
    }
    by_seed_records: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_seed_records[int(record["seed"])].append(record)
    by_seed = {str(seed): _aggregate(by_seed_records[seed]) for seed in EXPECTED_SEEDS}

    cluster_totals = [
        (
            float(by_seed[str(seed)]["exact_generator_seconds"]),
            float(by_seed[str(seed)]["context_generator_seconds"]),
        )
        for seed in EXPECTED_SEEDS
    ]
    rng = random.Random(BOOTSTRAP_SEED)
    bootstrap: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = [cluster_totals[rng.randrange(len(cluster_totals))] for _ in cluster_totals]
        bootstrap.append(
            _reduction(
                math.fsum(context for _, context in sampled),
                math.fsum(exact for exact, _ in sampled),
            )
        )
    bootstrap.sort()
    bootstrap_ci = [_percentile(bootstrap, 0.025), _percentile(bootstrap, 0.975)]

    saved = [exact - context for exact, context in cluster_totals]
    observed = statistics.fmean(saved)
    signflip_stats = [
        statistics.fmean(sign * value for sign, value in zip(signs, saved))
        for signs in itertools.product((-1.0, 1.0), repeat=len(saved))
    ]
    one_sided_p = sum(value >= observed - 1e-15 for value in signflip_stats) / len(
        signflip_stats
    )

    total_pass = (
        overall["pooled_generator_seconds_reduction"] >= TIME_REDUCTION_THRESHOLD
    )
    mean_pass = (
        overall["mean_paired_cell_generator_seconds_reduction"]
        >= TIME_REDUCTION_THRESHOLD
    )
    timing_gate_passed = total_pass and mean_pass
    return {
        "schema": ANALYSIS_SCHEMA,
        "status": "complete",
        "claim_scope": {
            "supported": "generator_seconds efficiency for context_memory_B25 versus exact_even_B25 on the frozen four-scenario development timing matrix",
            "throughput_inference_permitted": False,
            "global_lmapf_sota_inference_permitted": False,
            "note": "Timing artifacts are not used for task-throughput estimation or controller ranking.",
        },
        "audit": {
            "passed": True,
            "timing_evidence_valid": True,
            "paired_cells": 60,
            "runs": 120,
            "root_seed_clusters": 5,
            "artifacts": list(sources or []),
        },
        "primary_timing_gate": {
            "threshold": TIME_REDUCTION_THRESHOLD,
            "pooled_reduction": overall["pooled_generator_seconds_reduction"],
            "mean_paired_cell_reduction": overall[
                "mean_paired_cell_generator_seconds_reduction"
            ],
            "pooled_reduction_passed": total_pass,
            "mean_reduction_passed": mean_pass,
            "passed": timing_gate_passed,
            "decision": (
                "PASS_GENERATOR_TIME_REDUCTION_GATE"
                if timing_gate_passed
                else "FAIL_GENERATOR_TIME_REDUCTION_GATE"
            ),
        },
        "overall": overall,
        "by_scenario": by_scenario,
        "by_workload": by_workload,
        "by_root_seed": by_seed,
        "cluster_diagnostics": {
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "pooled_reduction_cluster_bootstrap_95ci": bootstrap_ci,
            "exact_one_sided_sign_flip_p_on_mean_saved_seconds": one_sided_p,
            "sign_flip_assignments": len(signflip_stats),
            "diagnostics_are_not_timing_gate_components": True,
        },
        "call_diagnostic": {
            "pooled_call_reduction": overall["pooled_generator_call_reduction"],
            "mean_paired_cell_call_reduction": overall[
                "mean_paired_cell_generator_call_reduction"
            ],
            "at_least_80pct_pooled": (
                overall["pooled_generator_call_reduction"] >= TIME_REDUCTION_THRESHOLD
            ),
            "not_a_timing_gate_component": True,
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    gate = report["primary_timing_gate"]
    overall = report["overall"]
    diagnostics = report["cluster_diagnostics"]
    lines = [
        "# Context-memory exclusive generator timing",
        "",
        f"Decision: **{gate['decision']}**",
        "",
        "This report is valid only for generator-time efficiency. It does not "
        "analyze throughput and cannot establish a global LMAPF SOTA claim.",
        "",
        "## Frozen primary gate",
        "",
        f"- Pooled generator-seconds reduction: {gate['pooled_reduction']:.2%}",
        f"- Mean paired-cell reduction: {gate['mean_paired_cell_reduction']:.2%}",
        f"- Required for both: {gate['threshold']:.0%}",
        f"- Paired cells: {report['audit']['paired_cells']}",
        "",
        "## Compute totals and diagnostics",
        "",
        f"- Exact generator seconds: {overall['exact_generator_seconds']:.6f}",
        f"- Context generator seconds: {overall['context_generator_seconds']:.6f}",
        f"- Pooled generator-call reduction: {overall['pooled_generator_call_reduction']:.2%}",
        "- Root-seed cluster bootstrap 95% CI: "
        f"[{diagnostics['pooled_reduction_cluster_bootstrap_95ci'][0]:.2%}, "
        f"{diagnostics['pooled_reduction_cluster_bootstrap_95ci'][1]:.2%}]",
        "- One-sided exact root-cluster sign-flip p (diagnostic only): "
        f"{diagnostics['exact_one_sided_sign_flip_p_on_mean_saved_seconds']:.6f}",
        "",
        "## Scenario audit",
        "",
        "| Scenario | Pairs | Pooled time reduction | Mean cell reduction | Call reduction |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, values in report["by_scenario"].items():
        lines.append(
            f"| {label} | {values['paired_cells']} | "
            f"{values['pooled_generator_seconds_reduction']:.2%} | "
            f"{values['mean_paired_cell_generator_seconds_reduction']:.2%} | "
            f"{values['pooled_generator_call_reduction']:.2%} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "configs/context_exclusive_timing_protocol_v1.json",
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.output_json, args.output_md):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite timing analysis: {path}")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    scenario_lookup = {
        (map_id, agents): label for label, map_id, _, agents in EXPECTED_SCENARIOS
    }
    loaded: list[tuple[str, Mapping[str, Any]]] = []
    sources: list[dict[str, Any]] = []
    for path in args.artifacts:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        key = (artifact.get("map_id"), artifact.get("protocol", {}).get("agents"))
        label = scenario_lookup.get(key)
        if label is None:
            raise ExclusiveTimingAuditError(f"unregistered scenario in {path}")
        loaded.append((label, artifact))
        sources.append(
            {
                "label": label,
                "path": str(path.resolve()),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    report = analyze(loaded, config=config, sources=sources)
    report["config"] = {
        "path": str(args.config.resolve()),
        "sha256": _sha256(args.config),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["primary_timing_gate"], indent=2, sort_keys=True))
    print(f"analysis_json={args.output_json}")
    print(f"analysis_md={args.output_md}")


if __name__ == "__main__":
    main()
