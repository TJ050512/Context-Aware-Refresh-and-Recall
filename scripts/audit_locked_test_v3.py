#!/usr/bin/env python3
"""Preflight and structurally audit the one-shot locked-test v3 matrix.

This module never runs a simulator and never summarizes performance.  Before a
launch it verifies the frozen protocol and map bytes.  After all four protected
artifacts finish, it verifies their exact design, integrity flags, and pairing.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


PROTOCOL_SCHEMA = "dai.locked-test-protocol-amendment/v3"
ARTIFACT_SCHEMA = "dai.claim-aware-absolute-budget/v1"
LOCKED_SEEDS = tuple(range(1001, 1031))
WORKLOADS = ("stationary", "abrupt", "recurrent")
METHODS = (
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
CHECKPOINT_SHA256 = (
    "e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d"
)
CHECKPOINT_PARAMS_SHA256 = (
    "6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac"
)
SIMULATOR_SHA256 = (
    "9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5"
)
VALIDATION_ANALYSIS_SCHEMA = "dai.combined-validation-v2-analysis/v1"
EXPECTED_SCENARIOS = {
    "warehouse_r020": {
        "map_id": "warehouse_60x100_kiva",
        "map_file": "warehouse_60x100_kiva.map",
        "map_sha256": (
            "29bde647469ea50e0ec6f605396f0893a24b0a43696014734b095bda89ce60f1"
        ),
        "height": 60,
        "width": 100,
        "free_cells": 3686,
        "agents": 737,
        "nominal_density": 0.20,
    },
    "warehouse_r035": {
        "map_id": "warehouse_60x100_kiva",
        "map_file": "warehouse_60x100_kiva.map",
        "map_sha256": (
            "29bde647469ea50e0ec6f605396f0893a24b0a43696014734b095bda89ce60f1"
        ),
        "height": 60,
        "width": 100,
        "free_cells": 3686,
        "agents": 1290,
        "nominal_density": 0.35,
    },
    "sortation_r020": {
        "map_id": "sortation_small_kiva",
        "map_file": "sortation_small_kiva.map",
        "map_sha256": (
            "7a2ec55f0afc2e5969f15cdb19fefea47d2dbab2aafb51632d54e5e7f9c4e2e1"
        ),
        "height": 33,
        "width": 57,
        "free_cells": 1564,
        "agents": 313,
        "nominal_density": 0.20,
    },
    "sortation_r035": {
        "map_id": "sortation_small_kiva",
        "map_file": "sortation_small_kiva.map",
        "map_sha256": (
            "7a2ec55f0afc2e5969f15cdb19fefea47d2dbab2aafb51632d54e5e7f9c4e2e1"
        ),
        "height": 33,
        "width": 57,
        "free_cells": 1564,
        "agents": 547,
        "nominal_density": 0.35,
    },
}


class LockedAuditError(ValueError):
    """Raised when a frozen locked-test structural condition is violated."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockedAuditError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LockedAuditError(f"expected JSON object: {path}")
    return value


def _require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise LockedAuditError(
            f"{context} mismatch: expected={expected!r} actual={actual!r}"
        )


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    """Verify that the supplied machine protocol is exactly the v3 design."""

    _require_equal(protocol.get("schema"), PROTOCOL_SCHEMA, "protocol.schema")
    _require_equal(
        protocol.get("status"),
        "frozen_before_any_locked_test_seed_is_opened",
        "protocol.status",
    )
    locked = protocol.get("locked_split", {})
    _require_equal(locked.get("name"), "locked_test", "locked_split.name")
    _require_equal(tuple(locked.get("seeds", ())), LOCKED_SEEDS, "locked seeds")
    for flag in (
        "seed_vector_is_authoritative",
        "complete_seed_set_required_per_artifact",
        "one_shot_confirmatory_use",
    ):
        _require_equal(locked.get(flag), True, f"locked_split.{flag}")
    _require_equal(
        locked.get("artifact_overwrite_permitted"),
        False,
        "locked_split.artifact_overwrite_permitted",
    )

    _require_equal(
        tuple(protocol.get("formal_registered_methods", ())),
        METHODS,
        "formal method registry",
    )
    amendment = protocol.get("workload_amendment", {})
    _require_equal(
        tuple(amendment.get("locked_workloads", ())), WORKLOADS, "locked workloads"
    )
    _require_equal(amendment.get("removed_workload"), "gradual", "removed workload")
    if "gradual" not in str(amendment.get("claim_boundary", "")).lower():
        raise LockedAuditError("workload amendment must explicitly bound gradual claims")

    common = protocol.get("common_protocol", {})
    expected_common = {
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
        "workloads": list(WORKLOADS),
        "jobs_per_artifact": 3,
        "artifacts_run_concurrently": 4,
        "timing_evidence_valid": False,
        "statistical_unit": (
            "root_seed_cluster_across_all_12_map_density_workload_cells"
        ),
    }
    _require_equal(common, expected_common, "common protocol")
    expected_context = {
        "recall_threshold": 0.05,
        "recall_margin": 0.02,
        "minimum_score": 0.10,
        "minimum_gap_windows": 6,
        "maintenance_age_windows": 25,
        "maintenance_stability_gate": 0.20,
    }
    _require_equal(
        protocol.get("context_memory_B25"), expected_context, "context parameters"
    )

    scenarios = protocol.get("locked_test_matrix", {}).get("scenarios", ())
    observed = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict) or "label" not in scenario:
            raise LockedAuditError("every scenario must be an object with a label")
        label = scenario["label"]
        if label in observed:
            raise LockedAuditError(f"duplicate scenario label: {label}")
        observed[label] = {key: value for key, value in scenario.items() if key != "label"}
    _require_equal(observed, EXPECTED_SCENARIOS, "locked scenarios")
    matrix = protocol["locked_test_matrix"]
    expected_counts = {
        "map_count": 2,
        "density_count_per_map": 2,
        "workload_count": 3,
        "root_seed_count": 30,
        "method_count": 13,
        "runs_per_artifact": 1170,
        "artifact_count": 4,
        "total_runs": 4680,
        "complete_matrix_once_opened": True,
    }
    for key, expected in expected_counts.items():
        _require_equal(matrix.get(key), expected, f"locked_test_matrix.{key}")

    dependencies = protocol.get("frozen_dependencies", {})
    _require_equal(
        dependencies.get("checkpoint_file_sha256"),
        CHECKPOINT_SHA256,
        "checkpoint hash",
    )
    _require_equal(
        dependencies.get("checkpoint_params_sha256"),
        CHECKPOINT_PARAMS_SHA256,
        "checkpoint parameter hash",
    )
    _require_equal(
        dependencies.get("period_on_sim_sha256"), SIMULATOR_SHA256, "simulator hash"
    )


def parse_map(path: Path) -> dict[str, Any]:
    """Parse the MovingAI-style header and validate every grid row."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise LockedAuditError(f"cannot read map {path}: {exc}") from exc
    if len(lines) < 4:
        raise LockedAuditError(f"map header is truncated: {path}")
    _require_equal(lines[0], "type octile", f"{path.name} type header")
    try:
        height_key, height_text = lines[1].split()
        width_key, width_text = lines[2].split()
        height, width = int(height_text), int(width_text)
    except (ValueError, TypeError) as exc:
        raise LockedAuditError(f"invalid dimensions in {path}") from exc
    _require_equal(height_key, "height", f"{path.name} height key")
    _require_equal(width_key, "width", f"{path.name} width key")
    _require_equal(lines[3], "map", f"{path.name} map marker")
    grid = lines[4:]
    _require_equal(len(grid), height, f"{path.name} row count")
    wrong_widths = sorted({len(row) for row in grid if len(row) != width})
    if wrong_widths:
        raise LockedAuditError(
            f"{path.name} row width mismatch: expected {width}, saw {wrong_widths}"
        )
    characters = set("".join(grid))
    if not characters.issubset(set(".@WET")):
        raise LockedAuditError(f"{path.name} has unexpected cells {sorted(characters)}")
    return {
        "height": height,
        "width": width,
        "free_cells": sum(cell != "@" for row in grid for cell in row),
        "sha256": sha256_file(path),
    }


def audit_maps(protocol: Mapping[str, Any], map_dir: Path) -> dict[str, Any]:
    validate_protocol(protocol)
    audited: dict[str, Any] = {}
    for scenario in EXPECTED_SCENARIOS.values():
        map_file = scenario["map_file"]
        if map_file in audited:
            continue
        actual = parse_map(map_dir / map_file)
        for key in ("height", "width", "free_cells"):
            _require_equal(actual[key], scenario[key], f"{map_file}.{key}")
        _require_equal(actual["sha256"], scenario["map_sha256"], f"{map_file}.sha256")
        audited[map_file] = actual
    return audited


def audit_validation_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the minimum validation decision that may precede locked opening."""

    _require_equal(
        report.get("schema"), VALIDATION_ANALYSIS_SCHEMA, "validation analysis schema"
    )
    evidence = report.get("evidence", {})
    _require_equal(
        evidence.get("source_evidence_class"),
        "validation_v2",
        "validation evidence class",
    )
    _require_equal(
        evidence.get("fresh_validation_v2"), True, "fresh validation-v2 evidence"
    )
    audit = report.get("audit", {})
    _require_equal(audit.get("passed"), True, "validation structural audit")
    _require_equal(
        audit.get("integrity_gate_passed"), True, "validation integrity gate"
    )
    design = report.get("design", {})
    expected_design = {
        "n_root_seed_clusters": 10,
        "maps": 2,
        "densities": 2,
        "workloads": 3,
        "total_runs": 1560,
    }
    for key, expected in expected_design.items():
        _require_equal(design.get(key), expected, f"validation design.{key}")
    gate = report.get("preregistered_go_no_go", {})
    causal = gate.get("causal_quality_go", {}).get("passed") is True
    context = gate.get("context_validation_candidate", {}).get("passed") is True
    _require_equal(
        gate.get("passed_any_candidate_path"),
        causal or context,
        "validation candidate roll-up",
    )
    if not (causal or context):
        raise LockedAuditError(
            "locked opening blocked: neither predeclared validation candidate path passed"
        )
    return {
        "fresh_validation_v2": True,
        "integrity": "pass",
        "causal_quality_candidate": causal,
        "context_validation_candidate": context,
    }


def _audit_integrity(run: Mapping[str, Any], context: str) -> None:
    safety = run.get("safety", {})
    _require_equal(safety.get("passed"), True, f"{context}.safety.passed")
    for field in (
        "collision_count",
        "edge_swap_count",
        "endpoint_mismatch_count",
        "invalid_move_count",
        "planner_timeout_count",
        "route_trace_invalid_count",
    ):
        _require_equal(safety.get(field), 0, f"{context}.safety.{field}")
    _require_equal(run.get("planner_timeouts"), 0, f"{context}.planner_timeouts")
    _require_equal(run.get("collisions"), 0, f"{context}.collisions")
    _require_equal(run.get("edge_swaps"), 0, f"{context}.edge_swaps")
    _require_equal(run.get("invalid_moves"), 0, f"{context}.invalid_moves")
    _require_equal(
        run.get("invariants", {}).get("passed"), True, f"{context}.invariants.passed"
    )
    budget = run.get("budget", {})
    _require_equal(budget.get("cap_satisfied"), True, f"{context}.budget.cap_satisfied")
    _require_equal(
        budget.get("generation_cap_satisfied"),
        True,
        f"{context}.budget.generation_cap_satisfied",
    )
    _require_equal(
        budget.get("budget_violation_attempts"),
        0,
        f"{context}.budget.budget_violation_attempts",
    )
    _require_equal(
        run.get("budget_violation_count"), 0, f"{context}.budget_violation_count"
    )


def audit_artifact(
    artifact: Mapping[str, Any], scenario_label: str
) -> dict[str, Any]:
    """Audit one 1,170-run artifact without reading or ranking outcomes."""

    if scenario_label not in EXPECTED_SCENARIOS:
        raise LockedAuditError(f"unknown scenario label: {scenario_label}")
    scenario = EXPECTED_SCENARIOS[scenario_label]
    _require_equal(artifact.get("schema"), ARTIFACT_SCHEMA, f"{scenario_label}.schema")
    _require_equal(artifact.get("status"), "complete", f"{scenario_label}.status")
    _require_equal(artifact.get("split"), "locked_test", f"{scenario_label}.split")
    _require_equal(
        artifact.get("evidence_class"), "locked_test", f"{scenario_label}.evidence_class"
    )
    _require_equal(tuple(artifact.get("seeds", ())), LOCKED_SEEDS, f"{scenario_label}.seeds")
    _require_equal(tuple(artifact.get("methods", ())), METHODS, f"{scenario_label}.methods")
    _require_equal(
        tuple(artifact.get("workloads", ())), WORKLOADS, f"{scenario_label}.workloads"
    )
    _require_equal(artifact.get("map_id"), scenario["map_id"], f"{scenario_label}.map_id")
    _require_equal(
        Path(str(artifact.get("map_path", ""))).name,
        scenario["map_file"],
        f"{scenario_label}.map_path",
    )
    _require_equal(
        artifact.get("map_sha256"), scenario["map_sha256"], f"{scenario_label}.map_sha256"
    )
    _require_equal(
        artifact.get("period_on_sim_sha256"),
        SIMULATOR_SHA256,
        f"{scenario_label}.period_on_sim_sha256",
    )
    generator = artifact.get("generator", {})
    _require_equal(
        generator.get("file_sha256"), CHECKPOINT_SHA256, f"{scenario_label}.checkpoint"
    )
    _require_equal(
        generator.get("params_sha256"),
        CHECKPOINT_PARAMS_SHA256,
        f"{scenario_label}.checkpoint_params",
    )

    run_protocol = artifact.get("protocol", {})
    expected_scalars = {
        "agents": scenario["agents"],
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "num_scored_windows": 100,
        "eligible_post_bootstrap_decisions": 99,
        "b25_budget": 25,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
        "jobs": 3,
        "exclusive_timing_declared": False,
        "timing_evidence_valid": False,
    }
    for key, expected in expected_scalars.items():
        _require_equal(run_protocol.get(key), expected, f"{scenario_label}.protocol.{key}")
    memory = run_protocol.get("context_memory_B25", {})
    expected_memory = {
        "recall_threshold": 0.05,
        "recall_margin": 0.02,
        "absolute_score_gate": 0.10,
        "min_gap_windows": 6,
        "maintenance_age_windows": 25,
        "maintenance_stability_gate": 0.20,
    }
    for key, expected in expected_memory.items():
        _require_equal(memory.get(key), expected, f"{scenario_label}.context.{key}")

    split_protocol = artifact.get("split_protocol", {})
    _require_equal(
        split_protocol.get("classification"),
        "sealed_locked_test",
        f"{scenario_label}.split_protocol.classification",
    )
    _require_equal(
        tuple(split_protocol.get("preregistered_seeds", ())),
        LOCKED_SEEDS,
        f"{scenario_label}.split_protocol.preregistered_seeds",
    )

    runs = artifact.get("runs")
    if not isinstance(runs, list):
        raise LockedAuditError(f"{scenario_label}.runs must be a list")
    _require_equal(len(runs), 1170, f"{scenario_label}.run count")
    observed_keys: set[tuple[int, str, str]] = set()
    pairing: dict[tuple[int, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    pairing_fields = (
        "manifest_id",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    )
    for index, run in enumerate(runs):
        context = f"{scenario_label}.runs[{index}]"
        seed = run.get("seed")
        workload = run.get("workload")
        method = run.get("method")
        if seed not in LOCKED_SEEDS or workload not in WORKLOADS or method not in METHODS:
            raise LockedAuditError(
                f"{context} is outside the frozen seed/workload/method domains"
            )
        key = (seed, workload, method)
        if key in observed_keys:
            raise LockedAuditError(f"duplicate arm {key!r} in {scenario_label}")
        observed_keys.add(key)
        _require_equal(run.get("root_seed"), seed, f"{context}.root_seed")
        _require_equal(run.get("split"), "locked_test", f"{context}.split")
        _require_equal(run.get("evidence_class"), "locked_test", f"{context}.evidence_class")
        _require_equal(run.get("map_id"), scenario["map_id"], f"{context}.map_id")
        _require_equal(run.get("scored_horizon"), 2000, f"{context}.scored_horizon")
        _require_equal(run.get("decision_window"), 20, f"{context}.decision_window")
        _require_equal(run.get("window_count"), 100, f"{context}.window_count")
        _require_equal(run.get("timing_evidence_valid"), False, f"{context}.timing")
        _audit_integrity(run, context)
        for field in pairing_fields:
            value = run.get(field)
            if not isinstance(value, str) or not value:
                raise LockedAuditError(f"{context}.{field} must be a non-empty string")
            pairing[(seed, workload)][field].add(value)

    expected_keys = set(itertools.product(LOCKED_SEEDS, WORKLOADS, METHODS))
    if observed_keys != expected_keys:
        missing = len(expected_keys - observed_keys)
        extra = len(observed_keys - expected_keys)
        raise LockedAuditError(
            f"{scenario_label} arm matrix mismatch: missing={missing} extra={extra}"
        )
    for cell, field_values in pairing.items():
        for field, values in field_values.items():
            if len(values) != 1:
                raise LockedAuditError(
                    f"{scenario_label} pairing mismatch cell={cell} field={field}"
                )
    _require_equal(len(pairing), 90, f"{scenario_label}.paired cell count")
    return {
        "scenario": scenario_label,
        "runs": len(runs),
        "paired_cells": len(pairing),
        "integrity": "pass",
    }


def audit_matrix(
    protocol: Mapping[str, Any], map_dir: Path, artifact_dir: Path
) -> dict[str, Any]:
    maps = audit_maps(protocol, map_dir)
    artifacts = []
    for label in EXPECTED_SCENARIOS:
        path = artifact_dir / f"{label}.json"
        if not path.is_file():
            raise LockedAuditError(f"missing protected artifact: {path}")
        artifacts.append(audit_artifact(load_json(path), label))
    _require_equal(sum(row["runs"] for row in artifacts), 4680, "matrix run count")
    return {"maps": maps, "artifacts": artifacts, "total_runs": 4680}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--map-dir", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--validation-gate", type=Path)
    parser.add_argument("--require-validation-candidate", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    protocol = load_json(args.protocol)
    validation = None
    if args.require_validation_candidate:
        if args.validation_gate is None:
            parser.error(
                "--validation-gate is required with --require-validation-candidate"
            )
        validation = audit_validation_gate(load_json(args.validation_gate))
    if args.preflight_only:
        result = {
            "preflight": "pass",
            "maps": audit_maps(protocol, args.map_dir),
            "validation": validation,
        }
    else:
        if args.artifact_dir is None:
            parser.error("--artifact-dir is required unless --preflight-only is used")
        result = audit_matrix(protocol, args.map_dir, args.artifact_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
