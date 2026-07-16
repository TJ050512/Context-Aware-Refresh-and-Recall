#!/usr/bin/env python3
"""Audit and screen the frozen four-scenario dual-cap development matrix.

The analyzer consumes exactly the four artifacts declared by
``configs/context_dualcap_development_matrix_v1.json``.  It reuses the strict
single-artifact runtime, pairing, route, and budget audits, then performs all
inference at the root-seed level.  Each root cluster contains all 12
map/density/workload cells.

A pass only nominates the unchanged candidate for fresh validation-v3.
Development artifacts cannot support paper, locked-test, or SOTA claims.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import statistics
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
FROZEN_CONFIG_PATH = ROOT / "configs" / "context_dualcap_development_matrix_v1.json"
EXPECTED_CONFIG_SHA256 = "a8e98493c96fa6c1d521e817b5dd4549f95e8b294588f4b01b50ebe9a995f1a4"
ANALYSIS_SCHEMA = "dai.context-dualcap-development-matrix-analysis/v1"
CONFIG_SCHEMA = "dai.context-dualcap-development-matrix/v1"


def _load_single_analyzer() -> ModuleType:
    path = Path(__file__).with_name("analyze_context_dualcap_dev10.py")
    spec = importlib.util.spec_from_file_location("_context_dualcap_dev10", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery
        raise RuntimeError(f"cannot load single-map analyzer from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SINGLE = _load_single_analyzer()


class CombinedDevelopmentError(ValueError):
    """Inputs do not equal the frozen four-scenario development matrix."""


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
        raise CombinedDevelopmentError(f"{field} must be an integer >= {minimum}")
    return int(value)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CombinedDevelopmentError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CombinedDevelopmentError(f"{field} must be a finite number")
    return result


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CombinedDevelopmentError(f"{field} must be a non-empty string")
    return value


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


def _validate_frozen_config(config: Mapping[str, Any]) -> None:
    if config.get("schema") != CONFIG_SCHEMA:
        raise CombinedDevelopmentError(f"config.schema must equal {CONFIG_SCHEMA!r}")
    if config.get("evidence_class") != "development_only":
        raise CombinedDevelopmentError("config must remain development_only")
    if config.get("candidate") != SINGLE.DUALCAP:
        raise CombinedDevelopmentError("config candidate differs from context_dualcap_G4S5")
    if config.get("method_change_after_one_map_screen") is not False:
        raise CombinedDevelopmentError("candidate must be unchanged after the one-map screen")
    if config.get("methods") != list(SINGLE.TARGET_METHODS):
        raise CombinedDevelopmentError("config methods differ from the frozen four-arm order")
    seeds = config.get("root_seeds")
    if (
        not isinstance(seeds, list)
        or len(seeds) != SINGLE.EXPECTED_ROOT_SEEDS
        or len(seeds) != len(set(seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)
    ):
        raise CombinedDevelopmentError("config must declare ten unique integer root seeds")
    if config.get("workloads") != list(SINGLE.EXPECTED_WORKLOADS):
        raise CombinedDevelopmentError("config workloads differ from the frozen order")

    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 4:
        raise CombinedDevelopmentError("config must declare exactly four scenarios")
    ids: set[str] = set()
    tuples: set[tuple[str, str, int]] = set()
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            raise CombinedDevelopmentError(f"config.scenarios[{index}] must be an object")
        scenario_id = _string(scenario.get("id"), f"config.scenarios[{index}].id")
        map_name = _string(scenario.get("map"), f"config.scenarios[{index}].map")
        map_sha = _string(
            scenario.get("map_sha256"), f"config.scenarios[{index}].map_sha256"
        )
        agents = _integer(scenario.get("agents"), f"config.scenarios[{index}].agents", minimum=1)
        if len(map_sha) != 64:
            raise CombinedDevelopmentError("config map SHA-256 values must have 64 hex digits")
        if scenario_id in ids or (map_name, map_sha, agents) in tuples:
            raise CombinedDevelopmentError("config scenario ids and map/hash/agent cells must be unique")
        ids.add(scenario_id)
        tuples.add((map_name, map_sha, agents))

    protocol = config.get("protocol")
    if not isinstance(protocol, dict):
        raise CombinedDevelopmentError("config.protocol must be an object")
    expected_protocol = {
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
        "context_match_threshold": 0.05,
        "dualcap_post_bootstrap_generation_cap": 4,
        "dualcap_effective_switch_cap": 5,
        "dualcap_total_generator_call_cap": 5,
        "independent_inference_unit": "root_seed",
        "cells_per_root_seed_per_method": 12,
        "runs_per_scenario": 120,
        "total_runs": 480,
    }
    if protocol != expected_protocol:
        raise CombinedDevelopmentError("config.protocol differs from the frozen matrix protocol")

    frozen = config.get("frozen_artifacts")
    expected_frozen_fields = {
        "claim_runner_sha256",
        "runner_sha256",
        "checkpoint_file_sha256",
        "checkpoint_params_sha256",
        "period_on_sim_sha256",
    }
    if not isinstance(frozen, dict) or set(frozen) != expected_frozen_fields:
        raise CombinedDevelopmentError("config.frozen_artifacts has an unexpected shape")
    for field, value in frozen.items():
        if not isinstance(value, str) or len(value) != 64:
            raise CombinedDevelopmentError(f"config.frozen_artifacts.{field} is not SHA-256")

    gates = config.get("screen_gates")
    expected_gates = {
        "audit_all_passed": True,
        "dualcap_vs_bootstrap_mean_relative_effect_at_least": 0.02,
        "dualcap_vs_bootstrap_cluster_ci_lower_strictly_above": 0.0,
        "dualcap_vs_bootstrap_exact_sign_flip_p_greater_strictly_below": 0.05,
        "dualcap_vs_bootstrap_all_root_directions_positive": True,
        "dualcap_vs_exact_mean_relative_effect_at_least": -0.005,
        "dualcap_vs_exact_cluster_ci_lower_strictly_above": -0.01,
        "dualcap_vs_context_mean_relative_effect_at_least": -0.01,
        "dualcap_vs_context_cluster_ci_lower_strictly_above": -0.01,
        "generator_call_reduction_vs_exact_at_least": 0.8,
        "mean_post_bootstrap_switches_at_most": 5.0,
    }
    if gates != expected_gates:
        raise CombinedDevelopmentError("config.screen_gates differs from the frozen gates")


def load_frozen_config() -> tuple[dict[str, Any], str]:
    path = FROZEN_CONFIG_PATH.resolve()
    digest = _sha256(path)
    if digest != EXPECTED_CONFIG_SHA256:
        raise CombinedDevelopmentError(
            "frozen development-matrix config SHA-256 mismatch; do not relax or rewrite gates"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CombinedDevelopmentError(f"cannot read frozen config: {error}") from error
    if not isinstance(value, dict):
        raise CombinedDevelopmentError("frozen config top-level value must be an object")
    _validate_frozen_config(value)
    return value, digest


def _scenario_by_artifact(
    artifact: Mapping[str, Any],
    scenarios: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> Mapping[str, Any]:
    map_path = _string(artifact.get("map_path"), f"{label}.map_path")
    map_name = Path(map_path).name
    map_sha = _string(artifact.get("map_sha256"), f"{label}.map_sha256")
    protocol = artifact.get("protocol")
    if not isinstance(protocol, dict):
        raise CombinedDevelopmentError(f"{label}.protocol must be an object")
    agents = _integer(protocol.get("agents"), f"{label}.protocol.agents", minimum=1)
    matches = [
        scenario
        for scenario in scenarios
        if scenario["map"] == map_name
        and scenario["map_sha256"] == map_sha
        and scenario["agents"] == agents
    ]
    if len(matches) != 1:
        raise CombinedDevelopmentError(
            f"{label} map/hash/agents does not identify exactly one frozen scenario"
        )
    scenario = matches[0]
    if artifact.get("map_id") != Path(str(scenario["map"])).stem:
        raise CombinedDevelopmentError(f"{label}.map_id differs from frozen scenario")
    return scenario


def _protocol_signature(protocol: Mapping[str, Any]) -> str:
    # Agent count is the declared density treatment.  Every other evaluation,
    # controller, and execution-provenance field must be identical.
    return _canonical({key: value for key, value in protocol.items() if key != "agents"})


def _validate_source_protocol(
    artifact: Mapping[str, Any],
    config: Mapping[str, Any],
    scenario: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, str, str, str]:
    protocol = artifact["protocol"]
    frozen_protocol = config["protocol"]
    scalar_mapping = {
        "warmup_time": "warmup_time",
        "scored_horizon": "scored_horizon",
        "decision_window": "decision_window",
        "release_interval_per_agent": "release_interval_per_agent",
        "guard_suffix_tasks_per_agent": "guard_suffix_tasks_per_agent",
        "sigma": "sigma",
    }
    for artifact_field, config_field in scalar_mapping.items():
        if protocol.get(artifact_field) != frozen_protocol[config_field]:
            raise CombinedDevelopmentError(
                f"{label}.protocol.{artifact_field} differs from frozen config"
            )
    if protocol.get("agents") != scenario["agents"]:
        raise CombinedDevelopmentError(f"{label}.protocol.agents differs from scenario")
    if protocol.get("num_scored_windows") != (
        frozen_protocol["scored_horizon"] // frozen_protocol["decision_window"]
    ):
        raise CombinedDevelopmentError(f"{label}.protocol.num_scored_windows is inconsistent")
    context = protocol.get("context_memory_B25")
    dualcap = protocol.get("context_dualcap_G4S5")
    if not isinstance(context, dict) or not isinstance(dualcap, dict):
        raise CombinedDevelopmentError(f"{label} lacks frozen context protocol objects")
    if context.get("recall_threshold") != frozen_protocol["context_match_threshold"]:
        raise CombinedDevelopmentError(f"{label} context recall threshold differs")
    dualcap_checks = {
        "development_only": True,
        "base_controller": "context_memory_B25",
        "recall_threshold": frozen_protocol["context_match_threshold"],
        "post_bootstrap_generation_cap": frozen_protocol[
            "dualcap_post_bootstrap_generation_cap"
        ],
        "effective_guidance_switch_cap": frozen_protocol[
            "dualcap_effective_switch_cap"
        ],
        "total_generator_call_cap": frozen_protocol[
            "dualcap_total_generator_call_cap"
        ],
        "mandatory_bootstrap_counts_toward_post_caps": False,
    }
    for field, expected in dualcap_checks.items():
        if dualcap.get(field) != expected:
            raise CombinedDevelopmentError(
                f"{label}.protocol.context_dualcap_G4S5.{field} differs from freeze"
            )

    split_protocol = artifact.get("split_protocol")
    if not isinstance(split_protocol, dict) or split_protocol.get("classification") != "development":
        raise CombinedDevelopmentError(f"{label}.split_protocol is not development")
    generator = artifact.get("generator")
    if not isinstance(generator, dict):
        raise CombinedDevelopmentError(f"{label}.generator must be an object")
    checkpoint_file = _string(generator.get("file_sha256"), f"{label}.generator.file_sha256")
    checkpoint_params = _string(
        generator.get("params_sha256"), f"{label}.generator.params_sha256"
    )
    frozen = config["frozen_artifacts"]
    if checkpoint_file != frozen["checkpoint_file_sha256"]:
        raise CombinedDevelopmentError(f"{label} checkpoint file SHA differs from freeze")
    if checkpoint_params != frozen["checkpoint_params_sha256"]:
        raise CombinedDevelopmentError(f"{label} checkpoint params SHA differs from freeze")
    simulator = _string(
        artifact.get("period_on_sim_sha256"), f"{label}.period_on_sim_sha256"
    )
    if simulator != frozen["period_on_sim_sha256"]:
        raise CombinedDevelopmentError(f"{label} simulator SHA differs from freeze")
    return (
        _protocol_signature(protocol),
        _canonical(split_protocol),
        _canonical(generator),
        simulator,
    )


def _verify_local_treatment_sources(config: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "claim_runner_sha256": ROOT / "src" / "dai_lmapf" / "claim_runner.py",
        "runner_sha256": ROOT / "scripts" / "run_claim_aware_budgeted_validation.py",
    }
    result: dict[str, Any] = {}
    for field, path in paths.items():
        observed = _sha256(path)
        expected = config["frozen_artifacts"][field]
        if observed != expected:
            raise CombinedDevelopmentError(
                f"local frozen treatment source {path.name} differs from config"
            )
        result[field] = {"path": str(path), "sha256": observed, "matches_freeze": True}
    return result


def _normalize_and_audit(
    artifacts: Sequence[Mapping[str, Any]],
    labels: Sequence[str],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if len(artifacts) != 4:
        raise CombinedDevelopmentError("exactly four scenario artifacts are required")
    expected_seeds = list(config["root_seeds"])
    expected_methods = list(config["methods"])
    expected_workloads = list(config["workloads"])
    seen_scenarios: set[str] = set()
    reference_signatures: tuple[str, str, str, str] | None = None
    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    totals: dict[str, int] = defaultdict(int)
    route_totals: dict[str, int] = defaultdict(int)

    for artifact, label in zip(artifacts, labels):
        if not isinstance(artifact, dict):
            raise CombinedDevelopmentError(f"{label} must be a JSON object")
        if artifact.get("seeds") != expected_seeds:
            raise CombinedDevelopmentError(f"{label}.seeds differs from frozen order")
        if artifact.get("methods") != expected_methods:
            raise CombinedDevelopmentError(f"{label}.methods differs from frozen order")
        if artifact.get("workloads") != expected_workloads:
            raise CombinedDevelopmentError(f"{label}.workloads differs from frozen order")
        raw_runs = artifact.get("runs")
        if not isinstance(raw_runs, list) or len(raw_runs) != config["protocol"]["runs_per_scenario"]:
            raise CombinedDevelopmentError(f"{label} must contain exactly 120 runs")
        scenario = _scenario_by_artifact(
            artifact, config["scenarios"], label=label
        )
        scenario_id = str(scenario["id"])
        if scenario_id in seen_scenarios:
            raise CombinedDevelopmentError(f"duplicate frozen scenario {scenario_id}")
        seen_scenarios.add(scenario_id)
        signatures = _validate_source_protocol(
            artifact, config, scenario, label=label
        )
        if reference_signatures is None:
            reference_signatures = signatures
        elif signatures != reference_signatures:
            raise CombinedDevelopmentError(
                "checkpoint/simulator/split/source protocol differs across artifacts"
            )
        try:
            seeds, map_id = SINGLE._validate_top_level(artifact)
            runs = SINGLE._normalize_runs(artifact, seeds, map_id)
            artifact_failures: list[dict[str, Any]] = []
            SINGLE._audit_pairing(runs, artifact_failures)
            SINGLE._audit_budget(runs, artifact_failures)
            artifact_totals = SINGLE._audit_safety_and_attribution(
                runs, artifact_failures
            )
        except SINGLE.DualCapArtifactError as error:
            raise CombinedDevelopmentError(f"{label}: {error}") from error
        for failure in artifact_failures:
            failures.append({"scenario_id": scenario_id, "source_label": label, **failure})
        for field, value in artifact_totals.items():
            if field == "route_build_reason_counts":
                for reason, count in value.items():
                    route_totals[reason] += int(count)
            else:
                totals[field] += int(value)
        for run in runs:
            normalized.append(
                {
                    **run,
                    "scenario_id": scenario_id,
                    "agents": int(scenario["agents"]),
                    "map_name": str(scenario["map"]),
                    "map_sha256": str(scenario["map_sha256"]),
                }
            )
    expected_scenarios = {str(scenario["id"]) for scenario in config["scenarios"]}
    if seen_scenarios != expected_scenarios:
        raise CombinedDevelopmentError(
            f"scenario set differs from config; missing={sorted(expected_scenarios - seen_scenarios)}"
        )
    if len(normalized) != config["protocol"]["total_runs"]:
        raise CombinedDevelopmentError("combined normalized matrix must contain 480 runs")
    totals["route_build_reason_counts"] = dict(sorted(route_totals.items()))  # type: ignore[assignment]
    return {"runs": normalized, "failures": failures, "totals": dict(totals)}


def _group_summary(
    cells: Sequence[Mapping[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    values = sorted({str(cell[field]) for cell in cells})
    for value in values:
        result[value] = SINGLE._direction_summary(
            [cell for cell in cells if str(cell[field]) == value]
        )
    return result


def _comparison(
    comparator: str,
    indexed: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    seeds = list(config["root_seeds"])
    scenarios = [str(item["id"]) for item in config["scenarios"]]
    workloads = list(config["workloads"])
    cells: list[dict[str, Any]] = []
    relative_by_root: dict[int, list[float]] = defaultdict(list)
    absolute_by_root: dict[int, list[float]] = defaultdict(list)
    for scenario_id, seed, workload in itertools.product(scenarios, seeds, workloads):
        candidate = indexed[(scenario_id, SINGLE.DUALCAP, seed, workload)]
        baseline = indexed[(scenario_id, comparator, seed, workload)]
        denominator = float(baseline["tasks"])
        if denominator <= 0:
            raise CombinedDevelopmentError(
                f"zero comparator tasks in {scenario_id}:{seed}:{workload}:{comparator}"
            )
        absolute = float(candidate["tasks"]) - denominator
        relative = float(candidate["tasks"]) / denominator - 1.0
        item = {
            "scenario_id": scenario_id,
            "map_name": candidate["map_name"],
            "agents": candidate["agents"],
            "seed": seed,
            "workload": workload,
            "candidate_tasks": int(candidate["tasks"]),
            "comparator_tasks": int(baseline["tasks"]),
            "absolute_task_delta": absolute,
            "relative_effect": relative,
            "relative_effect_percent": 100.0 * relative,
        }
        cells.append(item)
        relative_by_root[seed].append(relative)
        absolute_by_root[seed].append(absolute)
    root_relative = [_mean(relative_by_root[seed]) for seed in seeds]
    root_absolute = [_mean(absolute_by_root[seed]) for seed in seeds]
    return {
        "name": f"dualcap_vs_{comparator}",
        "candidate": SINGLE.DUALCAP,
        "comparator": comparator,
        "independent_unit": "root_seed",
        "n_paired_cells": len(cells),
        "n_root_seed_clusters": len(seeds),
        "cells_per_root_seed_cluster": len(scenarios) * len(workloads),
        "mean_relative_effect": _mean(root_relative),
        "mean_relative_effect_percent": 100.0 * _mean(root_relative),
        "mean_absolute_task_delta": _mean(root_absolute),
        "median_root_relative_effect": statistics.median(root_relative),
        "paired_cells": cells,
        "root_seed_relative_effects": {
            str(seed): effect for seed, effect in zip(seeds, root_relative)
        },
        "root_seed_absolute_task_deltas": {
            str(seed): effect for seed, effect in zip(seeds, root_absolute)
        },
        "root_seed_win_tie_loss": {
            "wins": sum(effect > 0 for effect in root_relative),
            "ties": sum(effect == 0 for effect in root_relative),
            "losses": sum(effect < 0 for effect in root_relative),
        },
        "cell_win_tie_loss": {
            "wins": sum(float(cell["relative_effect"]) > 0 for cell in cells),
            "ties": sum(float(cell["relative_effect"]) == 0 for cell in cells),
            "losses": sum(float(cell["relative_effect"]) < 0 for cell in cells),
        },
        "workload_strata": _group_summary(cells, "workload"),
        "scenario_strata": _group_summary(cells, "scenario_id"),
        "cluster_bootstrap": SINGLE._cluster_bootstrap(
            root_relative, root_absolute, samples=bootstrap_samples
        ),
        "exact_sign_flip": SINGLE._exact_sign_flip(root_relative),
    }


def _method_summaries(
    runs: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for method in SINGLE.TARGET_METHODS:
        selected = [run for run in runs if run["method"] == method]
        summaries[method] = {
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
    return summaries


def _reduction(candidate: float, comparator: float) -> float:
    if comparator <= 0:
        raise CombinedDevelopmentError("resource comparator must be positive")
    return 1.0 - candidate / comparator


def _screen(
    config: Mapping[str, Any],
    audit: Mapping[str, Any],
    comparisons: Mapping[str, Mapping[str, Any]],
    summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    gates = config["screen_gates"]
    bootstrap = comparisons[SINGLE.BOOTSTRAP]
    exact = comparisons[SINGLE.EXACT]
    context = comparisons[SINGLE.CONTEXT]
    call_reduction = _reduction(
        float(summaries[SINGLE.DUALCAP]["mean_generator_calls"]),
        float(summaries[SINGLE.EXACT]["mean_generator_calls"]),
    )
    checks = {
        "audit_all_passed": audit["passed"] is gates["audit_all_passed"],
        "dualcap_vs_bootstrap_mean_relative_effect_at_least_2pct": (
            float(bootstrap["mean_relative_effect"])
            >= float(gates["dualcap_vs_bootstrap_mean_relative_effect_at_least"])
        ),
        "dualcap_vs_bootstrap_cluster_ci_lower_strictly_positive": (
            float(bootstrap["cluster_bootstrap"]["mean_relative_effect_ci"][0])
            > float(gates["dualcap_vs_bootstrap_cluster_ci_lower_strictly_above"])
        ),
        "dualcap_vs_bootstrap_exact_sign_flip_p_greater_below_0_05": (
            float(bootstrap["exact_sign_flip"]["p_greater"])
            < float(
                gates[
                    "dualcap_vs_bootstrap_exact_sign_flip_p_greater_strictly_below"
                ]
            )
        ),
        "dualcap_vs_bootstrap_all_10_root_directions_positive": (
            bootstrap["root_seed_win_tie_loss"] == {"wins": 10, "ties": 0, "losses": 0}
        )
        is gates["dualcap_vs_bootstrap_all_root_directions_positive"],
        "dualcap_vs_exact_mean_at_least_minus_0_5pct": (
            float(exact["mean_relative_effect"])
            >= float(gates["dualcap_vs_exact_mean_relative_effect_at_least"])
        ),
        "dualcap_vs_exact_cluster_ci_lower_strictly_above_minus_1pct": (
            float(exact["cluster_bootstrap"]["mean_relative_effect_ci"][0])
            > float(gates["dualcap_vs_exact_cluster_ci_lower_strictly_above"])
        ),
        "dualcap_vs_context_mean_noninferior_minus_1pct": (
            float(context["mean_relative_effect"])
            >= float(gates["dualcap_vs_context_mean_relative_effect_at_least"])
        ),
        "dualcap_vs_context_cluster_ci_lower_strictly_above_minus_1pct": (
            float(context["cluster_bootstrap"]["mean_relative_effect_ci"][0])
            > float(gates["dualcap_vs_context_cluster_ci_lower_strictly_above"])
        ),
        "generator_call_reduction_vs_exact_at_least_80pct": (
            call_reduction >= float(gates["generator_call_reduction_vs_exact_at_least"])
        ),
        "mean_post_bootstrap_switches_at_most_5": (
            float(summaries[SINGLE.DUALCAP]["mean_post_bootstrap_switches"])
            <= float(gates["mean_post_bootstrap_switches_at_most"])
        ),
    }
    if not checks["audit_all_passed"]:
        recommendation = "NO_GO_FIX_COMBINED_DEVELOPMENT_AUDIT"
    elif all(checks.values()):
        recommendation = "GO_FREEZE_UNCHANGED_CANDIDATE_FOR_FRESH_VALIDATION_V3_ONLY"
    else:
        recommendation = "NO_GO_COMBINED_DEVELOPMENT_SCREEN_FAILED"
    context_calls = float(summaries[SINGLE.CONTEXT]["mean_generator_calls"])
    context_switches = float(summaries[SINGLE.CONTEXT]["mean_post_bootstrap_switches"])
    return {
        "passed": all(checks.values()),
        "recommendation": recommendation,
        "checks": checks,
        "frozen_thresholds": dict(gates),
        "resource_effects": {
            "generator_call_reduction_vs_exact": call_reduction,
            "generator_call_reduction_vs_context": _reduction(
                float(summaries[SINGLE.DUALCAP]["mean_generator_calls"]), context_calls
            ),
            "post_bootstrap_switch_reduction_vs_exact": _reduction(
                float(summaries[SINGLE.DUALCAP]["mean_post_bootstrap_switches"]),
                float(summaries[SINGLE.EXACT]["mean_post_bootstrap_switches"]),
            ),
            "post_bootstrap_switch_reduction_vs_context": (
                _reduction(
                    float(summaries[SINGLE.DUALCAP]["mean_post_bootstrap_switches"]),
                    context_switches,
                )
                if context_switches > 0
                else None
            ),
        },
        "development_only_no_paper_locked_test_or_sota_claim": True,
        "only_permitted_next_step_if_passed": (
            "Freeze the unchanged treatment and derive/run a new untouched "
            "validation-v3; do not run locked-test or use claim language yet."
        ),
    }


def analyze_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    source_labels: Sequence[str] | None = None,
    source_sha256: Sequence[str] | None = None,
    bootstrap_samples: int = SINGLE.DEFAULT_BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    labels = list(source_labels or [f"artifact_{index}" for index in range(len(artifacts))])
    hashes = list(source_sha256 or ["synthetic_or_in_memory"] * len(artifacts))
    if len(labels) != len(artifacts) or len(hashes) != len(artifacts):
        raise ValueError("source labels/hashes must align with artifacts")
    config, config_sha = load_frozen_config()
    treatment_sources = _verify_local_treatment_sources(config)
    normalized = _normalize_and_audit(artifacts, labels, config)
    runs = normalized["runs"]
    failures = normalized["failures"]
    audit = {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "totals": normalized["totals"],
        "complete_four_scenario_grid": len(runs) == 480,
        "paired_exogenous_inputs_match": not any(
            item["category"] == "pairing" for item in failures
        ),
        "budget_and_dualcap_contracts_passed": not any(
            item["category"] == "budget" for item in failures
        ),
        "safety_timeout_route_and_invariants_passed": not any(
            item["category"] == "integrity" for item in failures
        ),
        "checkpoint_simulator_and_source_protocol_match_freeze": True,
    }
    indexed = {
        (
            str(run["scenario_id"]),
            str(run["method"]),
            int(run["seed"]),
            str(run["workload"]),
        ): run
        for run in runs
    }
    comparisons = {
        comparator: _comparison(
            comparator,
            indexed,
            config,
            bootstrap_samples=bootstrap_samples,
        )
        for comparator in SINGLE.COMPARATORS
    }
    summaries = _method_summaries(runs)
    screening = _screen(config, audit, comparisons, summaries)
    return {
        "schema": ANALYSIS_SCHEMA,
        "sources": [
            {"label": label, "sha256": digest}
            for label, digest in zip(labels, hashes)
        ],
        "frozen_config": {
            "path": str(FROZEN_CONFIG_PATH),
            "sha256": config_sha,
            "schema": config["schema"],
        },
        "frozen_treatment_sources": treatment_sources,
        "evidence_warning": (
            "Four-scenario development-only evidence. Even a full pass cannot "
            "support paper results, locked testing, or SOTA claims."
        ),
        "design": {
            "scenario_ids": [str(item["id"]) for item in config["scenarios"]],
            "n_scenarios": 4,
            "root_seeds": list(config["root_seeds"]),
            "n_root_seed_clusters": 10,
            "workloads": list(config["workloads"]),
            "methods": list(config["methods"]),
            "paired_cells_per_method": 120,
            "cells_per_root_seed_cluster_per_method": 12,
            "total_runs": len(runs),
            "independent_unit": "root_seed",
            "pseudoreplication_guard": (
                "All four map-density scenarios and three workloads sharing a "
                "root seed remain in one 12-cell cluster."
            ),
        },
        "audit": audit,
        "method_summaries": summaries,
        "comparisons": comparisons,
        "screening": screening,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    design = report["design"]
    audit = report["audit"]
    screen = report["screening"]
    lines = [
        "# Context dual-cap combined development screen",
        "",
        f"> **Scope:** {report['evidence_warning']}",
        "",
        f"- Frozen config SHA-256: `{report['frozen_config']['sha256']}`",
        f"- Design: 4 scenarios × 10 roots × 3 workloads = "
        f"{design['paired_cells_per_method']} paired cells per method",
        f"- Independent observations: {design['n_root_seed_clusters']} root clusters, "
        f"not {design['paired_cells_per_method']} cells",
        f"- Audit: **{'PASS' if audit['passed'] else 'FAIL'}**",
        f"- Recommendation: **`{screen['recommendation']}`**",
        "",
        "## Root-cluster paired effects",
        "",
        "| Comparator | Mean Δ tasks | Mean Δ% | 95% root-cluster CI | Root W/T/L | p(greater) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for comparator in SINGLE.COMPARATORS:
        row = report["comparisons"][comparator]
        ci = row["cluster_bootstrap"]["mean_relative_effect_ci"]
        wtl = row["root_seed_win_tie_loss"]
        lines.append(
            f"| `{comparator}` | {row['mean_absolute_task_delta']:+.2f} | "
            f"{row['mean_relative_effect_percent']:+.2f}% | "
            f"[{100 * ci[0]:+.2f}%, {100 * ci[1]:+.2f}%] | "
            f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} | "
            f"{row['exact_sign_flip']['p_greater']:.4g} |"
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
    for method in SINGLE.TARGET_METHODS:
        row = report["method_summaries"][method]
        lines.append(
            f"| `{method}` | {row['mean_tasks']:.2f} | "
            f"{row['mean_generator_calls']:.2f} | "
            f"{row['mean_post_bootstrap_generations']:.2f} | "
            f"{row['mean_post_bootstrap_switches']:.2f} |"
        )
    lines.extend(["", "## Frozen screen gates", ""])
    for name, passed in screen["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    lines.extend(
        [
            "",
            "A complete PASS only licenses freezing the unchanged candidate and "
            "starting fresh validation-v3. It is not paper, locked-test, or SOTA evidence.",
            "",
        ]
    )
    if audit["failures"]:
        lines.extend(["## Audit failures", ""])
        for item in audit["failures"]:
            lines.append(
                f"- `{item['scenario_id']}:{item['category']}/{item['check']}` "
                f"`{item.get('cell', item.get('detail', {}))}`"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument(
        "--bootstrap-samples", type=int, default=SINGLE.DEFAULT_BOOTSTRAP_SAMPLES
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    paths = [path.resolve() for path in args.artifacts]
    artifacts: list[Mapping[str, Any]] = []
    try:
        for path in paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise CombinedDevelopmentError(f"{path} top-level JSON must be an object")
            artifacts.append(value)
        report = analyze_artifacts(
            artifacts,
            source_labels=[str(path) for path in paths],
            source_sha256=[_sha256(path) for path in paths],
            bootstrap_samples=args.bootstrap_samples,
        )
    except (OSError, json.JSONDecodeError, CombinedDevelopmentError) as error:
        raise SystemExit(f"ERROR: {error}") from error
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
