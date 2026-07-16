#!/usr/bin/env python3
"""Strictly audit the four-scenario event-reserve development matrix.

The input is four development-only artifacts, one for each scenario declared
by a required frozen config.  Each artifact must contain the same complete
five-arm, 10-root, three-workload grid.  Inference is clustered by root seed;
the 12 map-density/workload cells sharing a root are never treated as
independent observations.

This is a development screen only.  A pass can nominate the unchanged
``context_eventreserve_G5S6`` treatment for a new untouched validation run; it
cannot support paper, locked-test, or SOTA claims.
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
SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
CONFIG_SCHEMA = "dai.context-eventreserve-development-matrix/v1"
ANALYSIS_SCHEMA = "dai.context-eventreserve-development-matrix-analysis/v1"
CONFIG_SHA_FIELD = "development_matrix_config_sha256"
EXPECTED_CONFIG_SHA256 = "adda8cf0175ccac6a469e71ead1b3ec66ab96a4cfcd3d6dd98a80e41a4338e86"

EXACT = "exact_even_B25"
BOOTSTRAP = "bootstrap_only"
CONTEXT = "context_memory_B25"
DUALCAP = "context_dualcap_G4S5"
EVENTRESERVE = "context_eventreserve_G5S6"
TARGET_METHODS = (EXACT, BOOTSTRAP, CONTEXT, DUALCAP, EVENTRESERVE)
COMPARATORS = (BOOTSTRAP, EXACT, CONTEXT, DUALCAP)
EXPECTED_WORKLOADS = ("stationary", "abrupt", "recurrent")
EXPECTED_ROOT_SEEDS = 10
EXPECTED_SCENARIOS = 4
RUNS_PER_SCENARIO = 150
TOTAL_RUNS = 600

DUALCAP_GENERATION_CAP = 4
DUALCAP_SWITCH_CAP = 5
DUALCAP_TOTAL_CALL_CAP = 5
EVENTRESERVE_GENERATION_CAP = 5
EVENTRESERVE_SWITCH_CAP = 6
EVENTRESERVE_TOTAL_CALL_CAP = 6


def _load_base_analyzer() -> ModuleType:
    path = Path(__file__).with_name("analyze_context_dualcap_dev10.py")
    spec = importlib.util.spec_from_file_location("_eventreserve_base", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load baseline audit helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_analyzer()


class EventReserveDevelopmentError(ValueError):
    """The inputs do not equal the frozen event-reserve development design."""


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
        raise EventReserveDevelopmentError(
            f"{field} must be an integer >= {minimum}"
        )
    return int(value)


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventReserveDevelopmentError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise EventReserveDevelopmentError(
            f"{field} must be finite and >= {minimum}"
        )
    return result


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventReserveDevelopmentError(f"{field} must be a non-empty string")
    return value


def _sha_string(value: Any, field: str) -> str:
    result = _string(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise EventReserveDevelopmentError(f"{field} must be a lowercase SHA-256")
    return result


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


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
            "scenario_id": run.get("scenario_id"),
            "method": run.get("method"),
            "seed": run.get("seed"),
            "workload": run.get("workload"),
        }
    if detail is not None:
        item["detail"] = detail
    failures.append(item)


def _validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema") != CONFIG_SCHEMA:
        raise EventReserveDevelopmentError(
            f"config.schema must equal {CONFIG_SCHEMA!r}"
        )
    if config.get("evidence_class") != "development_only":
        raise EventReserveDevelopmentError("config must remain development_only")
    if config.get("candidate") != EVENTRESERVE:
        raise EventReserveDevelopmentError("config candidate differs from event-reserve")
    if config.get("methods") != list(TARGET_METHODS):
        raise EventReserveDevelopmentError("config methods differ from the five-arm order")

    seeds = config.get("root_seeds")
    if (
        not isinstance(seeds, list)
        or len(seeds) != EXPECTED_ROOT_SEEDS
        or len(seeds) != len(set(seeds))
        or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)
    ):
        raise EventReserveDevelopmentError(
            "config must declare ten unique integer root seeds"
        )
    if config.get("workloads") != list(EXPECTED_WORKLOADS):
        raise EventReserveDevelopmentError("config workloads differ from frozen order")

    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != EXPECTED_SCENARIOS:
        raise EventReserveDevelopmentError("config must declare exactly four scenarios")
    scenario_ids: set[str] = set()
    scenario_cells: set[tuple[str, str, int]] = set()
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            raise EventReserveDevelopmentError(
                f"config.scenarios[{index}] must be an object"
            )
        scenario_id = _string(scenario.get("id"), f"config.scenarios[{index}].id")
        map_name = _string(scenario.get("map"), f"config.scenarios[{index}].map")
        map_sha = _sha_string(
            scenario.get("map_sha256"), f"config.scenarios[{index}].map_sha256"
        )
        agents = _integer(
            scenario.get("agents"), f"config.scenarios[{index}].agents", minimum=1
        )
        cell = (map_name, map_sha, agents)
        if scenario_id in scenario_ids or cell in scenario_cells:
            raise EventReserveDevelopmentError(
                "config scenario ids and map/hash/agent cells must be unique"
            )
        scenario_ids.add(scenario_id)
        scenario_cells.add(cell)

    protocol = config.get("protocol")
    if not isinstance(protocol, dict):
        raise EventReserveDevelopmentError("config.protocol must be an object")
    required_protocol = {
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
        "context_match_threshold": 0.05,
        "dualcap_post_bootstrap_generation_cap": DUALCAP_GENERATION_CAP,
        "dualcap_effective_switch_cap": DUALCAP_SWITCH_CAP,
        "dualcap_total_generator_call_cap": DUALCAP_TOTAL_CALL_CAP,
        "eventreserve_post_bootstrap_generation_cap": EVENTRESERVE_GENERATION_CAP,
        "eventreserve_effective_switch_cap": EVENTRESERVE_SWITCH_CAP,
        "eventreserve_total_generator_call_cap": EVENTRESERVE_TOTAL_CALL_CAP,
        "independent_inference_unit": "root_seed",
        "cells_per_root_seed_per_method": 12,
        "runs_per_scenario": RUNS_PER_SCENARIO,
        "total_runs": TOTAL_RUNS,
    }
    for field, expected in required_protocol.items():
        if protocol.get(field) != expected:
            raise EventReserveDevelopmentError(
                f"config.protocol.{field} differs from the required design"
            )

    frozen = config.get("frozen_artifacts")
    expected_frozen_fields = {
        "claim_runner_sha256",
        "runner_sha256",
        "checkpoint_file_sha256",
        "checkpoint_params_sha256",
        "period_on_sim_sha256",
    }
    if not isinstance(frozen, dict) or set(frozen) != expected_frozen_fields:
        raise EventReserveDevelopmentError(
            "config.frozen_artifacts has an unexpected shape"
        )
    for field, value in frozen.items():
        _sha_string(value, f"config.frozen_artifacts.{field}")

    expected_gates = {
        "audit_all_passed": True,
        "eventreserve_vs_bootstrap_mean_relative_effect_at_least": 0.02,
        "eventreserve_vs_bootstrap_cluster_ci_lower_strictly_above": 0.0,
        "eventreserve_vs_bootstrap_exact_sign_flip_p_greater_strictly_below": 0.05,
        "eventreserve_vs_bootstrap_all_root_directions_positive": True,
        "eventreserve_vs_exact_mean_relative_effect_at_least": -0.005,
        "eventreserve_vs_exact_cluster_ci_lower_strictly_above": -0.01,
        "eventreserve_vs_context_mean_relative_effect_at_least": -0.01,
        "eventreserve_vs_context_cluster_ci_lower_strictly_above": -0.01,
        "generator_call_reduction_vs_exact_at_least": 0.8,
        "mean_post_bootstrap_switches_at_most": 5.0,
    }
    if config.get("screen_gates") != expected_gates:
        raise EventReserveDevelopmentError(
            "config.screen_gates differs from the non-relaxable screen"
        )


def load_config(config_path: Path) -> tuple[dict[str, Any], str, Path]:
    path = config_path.resolve()
    try:
        digest = _sha256(path)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EventReserveDevelopmentError(f"cannot read config: {error}") from error
    if not isinstance(value, dict):
        raise EventReserveDevelopmentError("config top-level value must be an object")
    if digest != EXPECTED_CONFIG_SHA256:
        raise EventReserveDevelopmentError(
            "event-reserve config SHA-256 differs from the frozen config"
        )
    _validate_config(value)
    return value, digest, path


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
            raise EventReserveDevelopmentError(
                f"local frozen treatment source {path.name} differs from config"
            )
        result[field] = {
            "path": str(path),
            "sha256": observed,
            "matches_freeze": True,
        }
    return result


def _scenario_for_artifact(
    artifact: Mapping[str, Any],
    scenarios: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> Mapping[str, Any]:
    map_name = Path(_string(artifact.get("map_path"), f"{label}.map_path")).name
    map_sha = _sha_string(artifact.get("map_sha256"), f"{label}.map_sha256")
    protocol = artifact.get("protocol")
    if not isinstance(protocol, dict):
        raise EventReserveDevelopmentError(f"{label}.protocol must be an object")
    agents = _integer(protocol.get("agents"), f"{label}.protocol.agents", minimum=1)
    matches = [
        scenario
        for scenario in scenarios
        if scenario["map"] == map_name
        and scenario["map_sha256"] == map_sha
        and scenario["agents"] == agents
    ]
    if len(matches) != 1:
        raise EventReserveDevelopmentError(
            f"{label} map/hash/agents does not identify one frozen scenario"
        )
    scenario = matches[0]
    if artifact.get("map_id") != Path(str(scenario["map"])).stem:
        raise EventReserveDevelopmentError(f"{label}.map_id differs from scenario")
    return scenario


def _protocol_signature(protocol: Mapping[str, Any]) -> str:
    return _canonical({key: value for key, value in protocol.items() if key != "agents"})


def _validate_artifact_protocol(
    artifact: Mapping[str, Any],
    config: Mapping[str, Any],
    config_sha: str,
    scenario: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, str, str, str]:
    if artifact.get(CONFIG_SHA_FIELD) != config_sha:
        raise EventReserveDevelopmentError(
            f"{label}.{CONFIG_SHA_FIELD} differs from the supplied config SHA-256"
        )
    protocol = artifact["protocol"]
    frozen_protocol = config["protocol"]
    for artifact_field in (
        "warmup_time",
        "scored_horizon",
        "decision_window",
        "release_interval_per_agent",
        "guard_suffix_tasks_per_agent",
        "sigma",
    ):
        if protocol.get(artifact_field) != frozen_protocol[artifact_field]:
            raise EventReserveDevelopmentError(
                f"{label}.protocol.{artifact_field} differs from config"
            )
    if protocol.get("agents") != scenario["agents"]:
        raise EventReserveDevelopmentError(f"{label}.protocol.agents differs")
    if protocol.get("num_scored_windows") != 100:
        raise EventReserveDevelopmentError(
            f"{label}.protocol.num_scored_windows must equal 100"
        )
    if protocol.get("eligible_post_bootstrap_decisions") != 99:
        raise EventReserveDevelopmentError(
            f"{label}.protocol.eligible_post_bootstrap_decisions must equal 99"
        )
    if protocol.get("b25_budget") != 25:
        raise EventReserveDevelopmentError(f"{label}.protocol.b25_budget must equal 25")

    context = protocol.get(CONTEXT)
    dualcap = protocol.get(DUALCAP)
    eventreserve = protocol.get(EVENTRESERVE)
    if not all(isinstance(item, dict) for item in (context, dualcap, eventreserve)):
        raise EventReserveDevelopmentError(
            f"{label} lacks context, dual-cap, or event-reserve protocol metadata"
        )
    if context.get("recall_threshold") != frozen_protocol["context_match_threshold"]:
        raise EventReserveDevelopmentError(f"{label} context threshold differs")
    dualcap_checks = {
        "development_only": True,
        "base_controller": CONTEXT,
        "recall_threshold": frozen_protocol["context_match_threshold"],
        "post_bootstrap_generation_cap": DUALCAP_GENERATION_CAP,
        "effective_guidance_switch_cap": DUALCAP_SWITCH_CAP,
        "total_generator_call_cap": DUALCAP_TOTAL_CALL_CAP,
        "mandatory_bootstrap_counts_toward_post_caps": False,
    }
    for field, expected in dualcap_checks.items():
        if dualcap.get(field) != expected:
            raise EventReserveDevelopmentError(
                f"{label}.protocol.{DUALCAP}.{field} differs from freeze"
            )
    eventreserve_checks = {
        "development_only": True,
        "base_controller": CONTEXT,
        "recall_threshold": frozen_protocol["context_match_threshold"],
        "post_bootstrap_generation_cap": EVENTRESERVE_GENERATION_CAP,
        "effective_guidance_switch_cap": EVENTRESERVE_SWITCH_CAP,
        "total_generator_call_cap": EVENTRESERVE_TOTAL_CALL_CAP,
        "mandatory_bootstrap_counts_toward_post_caps": False,
        "generation_cap_state": "past_executed_post_bootstrap_generations_only",
        "sixth_switch_reserve": (
            "fresh_generation_only_with_accepted_triggered_"
            "unconstrained_preview_and_not_maintenance_only"
        ),
        "reactivation_generation_charge": 0,
        "quota_rule": (
            "at_most_G5_fresh_generations_and_S6_switches_with_"
            "event_reserved_sixth_switch"
        ),
    }
    for field, expected in eventreserve_checks.items():
        if eventreserve.get(field) != expected:
            raise EventReserveDevelopmentError(
                f"{label}.protocol.{EVENTRESERVE}.{field} differs from freeze"
            )

    split = artifact.get("split_protocol")
    if not isinstance(split, dict) or split.get("classification") != "development":
        raise EventReserveDevelopmentError(f"{label}.split_protocol is not development")
    generator = artifact.get("generator")
    if not isinstance(generator, dict):
        raise EventReserveDevelopmentError(f"{label}.generator must be an object")
    frozen = config["frozen_artifacts"]
    if generator.get("file_sha256") != frozen["checkpoint_file_sha256"]:
        raise EventReserveDevelopmentError(f"{label} checkpoint file SHA differs")
    if generator.get("params_sha256") != frozen["checkpoint_params_sha256"]:
        raise EventReserveDevelopmentError(f"{label} checkpoint params SHA differs")
    simulator_sha = _sha_string(
        artifact.get("period_on_sim_sha256"), f"{label}.period_on_sim_sha256"
    )
    if simulator_sha != frozen["period_on_sim_sha256"]:
        raise EventReserveDevelopmentError(f"{label} simulator SHA differs")
    return (
        _protocol_signature(protocol),
        _canonical(split),
        _canonical(generator),
        simulator_sha,
    )


def _normalize_eventreserve_run(
    raw: Mapping[str, Any],
    *,
    index: int,
    seeds: Sequence[int],
    map_id: str,
) -> dict[str, Any]:
    context = f"runs[{index}]"
    method = raw.get("method")
    seed = raw.get("root_seed", raw.get("seed"))
    workload = raw.get("workload")
    if method != EVENTRESERVE or seed not in seeds or workload not in EXPECTED_WORKLOADS:
        raise EventReserveDevelopmentError(
            f"{context} is not a declared event-reserve cell"
        )
    if raw.get("seed") != seed:
        raise EventReserveDevelopmentError(f"{context}.seed must equal root_seed")
    if raw.get("split") != "development" or raw.get("evidence_class") != "development":
        raise EventReserveDevelopmentError(f"{context} must be development evidence")
    if raw.get("map_id") != map_id:
        raise EventReserveDevelopmentError(f"{context}.map_id differs from artifact")
    tasks = _integer(raw.get("num_task_finished"), f"{context}.num_task_finished")
    horizon = _integer(raw.get("scored_horizon"), f"{context}.scored_horizon", minimum=1)
    decision_window = _integer(
        raw.get("decision_window"), f"{context}.decision_window", minimum=1
    )
    window_count = _integer(raw.get("window_count"), f"{context}.window_count", minimum=2)
    if horizon % decision_window or window_count != horizon // decision_window:
        raise EventReserveDevelopmentError(f"{context} has inconsistent windows")
    throughput = _number(
        raw.get("throughput_per_timestep"),
        f"{context}.throughput_per_timestep",
        minimum=0.0,
    )
    if not math.isclose(throughput, tasks / horizon, rel_tol=1e-12, abs_tol=1e-12):
        raise EventReserveDevelopmentError(f"{context}.throughput != tasks/H")
    for field in (
        "manifest_id",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    ):
        _string(raw.get(field), f"{context}.{field}")
    if not isinstance(raw.get("task_tape_identity"), dict) or not raw["task_tape_identity"]:
        raise EventReserveDevelopmentError(f"{context}.task_tape_identity is required")
    prefixes = raw.get("final_task_tape_prefixes")
    if not isinstance(prefixes, dict):
        raise EventReserveDevelopmentError(f"{context}.final_task_tape_prefixes required")
    released = prefixes.get("released_prefix_lengths")
    if (
        not isinstance(released, list)
        or not released
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in released)
    ):
        raise EventReserveDevelopmentError(f"{context}.released_prefix_lengths invalid")
    for field in ("budget", "safety", "invariants", "cohort_attribution_audit"):
        if not isinstance(raw.get(field), dict):
            raise EventReserveDevelopmentError(f"{context}.{field} must be an object")
    if not isinstance(raw.get("publication_timeline"), list):
        raise EventReserveDevelopmentError(f"{context}.publication_timeline must be a list")
    item = dict(raw)
    item.update(
        {
            "method": EVENTRESERVE,
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
    return item


EVENT_TIMELINE_FIELDS = (
    "constraint_candidate",
    "constraint_binding",
    "generation_cap_candidate",
    "generation_cap_binding",
    "eventreserve_reserve_active",
    "eventreserve_reserve_candidate",
    "eventreserve_preview_accepted",
    "eventreserve_preview_triggered",
    "eventreserve_event_preview_accepted",
    "eventreserve_event_preview_triggered",
    "eventreserve_reserve_qualified",
    "eventreserve_reserve_binding",
)


def _event_timeline_audit(run: Mapping[str, Any]) -> dict[str, int]:
    timeline = run["publication_timeline"]
    if len(timeline) != int(run["window_count"]):
        raise EventReserveDevelopmentError("event-reserve timeline length mismatch")
    result: dict[str, int] = defaultdict(int)
    executed_switches = 0
    executed_generations = 0
    decision_indices: list[int] = []
    for index, row in enumerate(timeline):
        if not isinstance(row, dict):
            raise EventReserveDevelopmentError("timeline entries must be objects")
        decision_index = _integer(
            row.get("decision_index"), f"timeline[{index}].decision_index"
        )
        decision_indices.append(decision_index)
        if decision_index == 0:
            continue
        for field in EVENT_TIMELINE_FIELDS:
            if not isinstance(row.get(field), bool):
                raise EventReserveDevelopmentError(
                    f"timeline[{index}].{field} must be boolean"
                )
        accepted = row.get("accepted") is True
        operation = row.get("executed_operation")
        uncapped = row.get("uncapped_proposed_operation")
        constraint_candidate = row["constraint_candidate"]
        constraint_binding = row["constraint_binding"]
        generation_candidate = row["generation_cap_candidate"]
        generation_binding = row["generation_cap_binding"]
        reserve_active = row["eventreserve_reserve_active"]
        reserve_candidate = row["eventreserve_reserve_candidate"]
        preview_accepted = row["eventreserve_preview_accepted"]
        preview_triggered = row["eventreserve_preview_triggered"]
        event_preview_accepted = row["eventreserve_event_preview_accepted"]
        event_preview_triggered = row["eventreserve_event_preview_triggered"]
        reserve_qualified = row["eventreserve_reserve_qualified"]
        reserve_binding = row["eventreserve_reserve_binding"]

        switches_before = executed_switches
        generations_before = executed_generations
        result["switches"] += int(accepted)
        result["charged_switches"] += int(
            row.get("charged_to_post_bootstrap_budget") is True
        )
        result["generations"] += int(operation == "generate")
        result["charged_generations"] += int(
            row.get("charged_to_generator_budget") is True
        )
        result["reactivations"] += int(operation == "reactivate")
        result["generation_candidates"] += int(generation_candidate)
        result["generation_bindings"] += int(generation_binding)
        result["reserve_candidates"] += int(reserve_candidate)
        result["reserve_preview_accepts"] += int(preview_accepted)
        result["reserve_qualified"] += int(reserve_qualified)
        result["reserve_bindings"] += int(reserve_binding)
        result["reserve_generation_bindings"] += int(
            reserve_qualified and generation_binding
        )
        result["reserve_executions"] += int(
            reserve_active and accepted and operation == "generate"
        )

        valid = True
        valid &= constraint_candidate == (generation_candidate or reserve_candidate)
        valid &= constraint_binding == (generation_binding or reserve_binding)
        valid &= not generation_binding or generation_candidate
        valid &= not reserve_candidate or (
            reserve_active and uncapped in {"generate", "reactivate"}
        )
        valid &= not preview_accepted or reserve_candidate
        valid &= not preview_triggered or reserve_candidate
        valid &= not event_preview_accepted or reserve_candidate
        valid &= not event_preview_triggered or reserve_candidate
        valid &= not reserve_qualified or (
            preview_accepted
            and preview_triggered
            and event_preview_accepted
            and event_preview_triggered
            and uncapped == "generate"
        )
        valid &= not reserve_binding or (preview_accepted and not reserve_qualified)
        valid &= not constraint_binding or (not accepted and operation == "hold")
        valid &= not (reserve_active and accepted) or (
            operation == "generate"
            and reserve_qualified
            and not generation_binding
        )
        valid &= not accepted or operation in {"generate", "reactivate"}
        valid &= accepted or operation == "hold"
        result["invalid_implications"] += int(not valid)

        if accepted:
            executed_switches += 1
        if operation == "generate":
            executed_generations += 1
        if reserve_active:
            result["reserve_active_rows"] += 1
            result["invalid_reserve_position"] += int(switches_before != 5)
        result["invalid_generation_candidate_state"] += int(
            generation_candidate
            and generations_before < EVENTRESERVE_GENERATION_CAP
        )
    if decision_indices != list(range(int(run["window_count"]))):
        raise EventReserveDevelopmentError("timeline decision indices must be 0..N-1")
    return dict(result)


def _audit_eventreserve_budget(
    runs: Sequence[Mapping[str, Any]], failures: list[dict[str, Any]]
) -> None:
    for run in runs:
        budget = run["budget"]
        timeline = _event_timeline_audit(run)
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
        calls = _integer(
            budget.get("total_generator_calls"), "budget.total_generator_calls"
        )
        violations = _integer(
            budget.get("budget_violation_attempts"),
            "budget.budget_violation_attempts",
        )
        generation_candidates = _integer(
            budget.get("generation_cap_candidate_count"),
            "budget.generation_cap_candidate_count",
        )
        generation_bindings = _integer(
            budget.get("generation_cap_binding_count"),
            "budget.generation_cap_binding_count",
        )
        reserve_candidates = _integer(
            budget.get("eventreserve_candidate_count"),
            "budget.eventreserve_candidate_count",
        )
        reserve_preview_accepts = _integer(
            budget.get("eventreserve_preview_accept_count"),
            "budget.eventreserve_preview_accept_count",
        )
        reserve_qualified = _integer(
            budget.get("eventreserve_qualified_count"),
            "budget.eventreserve_qualified_count",
        )
        reserve_bindings = _integer(
            budget.get("eventreserve_binding_count"),
            "budget.eventreserve_binding_count",
        )
        reserve_generation_bindings = _integer(
            budget.get("eventreserve_generation_cap_binding_count"),
            "budget.eventreserve_generation_cap_binding_count",
        )
        reserve_executions = _integer(
            budget.get("eventreserve_execution_count"),
            "budget.eventreserve_execution_count",
        )
        checks = {
            "eventreserve_one_mandatory_bootstrap": mandatory == 1,
            "eventreserve_bootstrap_outside_caps": budget.get(
                "mandatory_bootstrap_counts_toward_post_caps"
            ) is False,
            "eventreserve_registered_switch_cap_6": registered == 6,
            "eventreserve_declared_switch_cap_6": budget.get(
                "effective_guidance_switch_cap"
            ) == 6,
            "eventreserve_declared_generation_cap_5": budget.get(
                "post_bootstrap_generation_cap"
            ) == 5,
            "eventreserve_declared_total_call_cap_6": budget.get(
                "total_generator_call_cap"
            ) == 6,
            "eventreserve_switches_at_most_6": publications <= 6,
            "eventreserve_generations_at_most_5": generations <= 5,
            "eventreserve_total_calls_at_most_6": calls <= 6,
            "eventreserve_operation_partition": generations + reactivations == publications,
            "eventreserve_generator_call_conservation": calls == mandatory + generations,
            "eventreserve_flat_calls_match": run.get("generator_calls") == calls,
            "eventreserve_flat_publications_match": run.get(
                "post_bootstrap_publication_count"
            ) == publications,
            "eventreserve_flat_generations_match": run.get(
                "post_bootstrap_generation_count"
            ) == generations,
            "eventreserve_flat_reactivations_match": run.get(
                "post_bootstrap_reactivation_count"
            ) == reactivations,
            "eventreserve_flat_budget_match": run.get("publication_budget") == registered,
            "eventreserve_flat_switches_match": run.get(
                "effective_guidance_switch_count"
            ) == publications,
            "eventreserve_timeline_switches_match": timeline.get("switches", 0) == publications,
            "eventreserve_timeline_charged_switches_match": timeline.get(
                "charged_switches", 0
            ) == publications,
            "eventreserve_timeline_generations_match": timeline.get(
                "generations", 0
            ) == generations,
            "eventreserve_timeline_charged_generations_match": timeline.get(
                "charged_generations", 0
            ) == generations,
            "eventreserve_timeline_reactivations_match": timeline.get(
                "reactivations", 0
            ) == reactivations,
            "eventreserve_generation_candidates_match_timeline": timeline.get(
                "generation_candidates", 0
            ) == generation_candidates,
            "eventreserve_generation_bindings_match_timeline": timeline.get(
                "generation_bindings", 0
            ) == generation_bindings,
            "eventreserve_candidates_match_timeline": timeline.get(
                "reserve_candidates", 0
            ) == reserve_candidates,
            "eventreserve_preview_accepts_match_timeline": timeline.get(
                "reserve_preview_accepts", 0
            ) == reserve_preview_accepts,
            "eventreserve_qualified_match_timeline": timeline.get(
                "reserve_qualified", 0
            ) == reserve_qualified,
            "eventreserve_bindings_match_timeline": timeline.get(
                "reserve_bindings", 0
            ) == reserve_bindings,
            "eventreserve_generation_bindings_match_timeline": timeline.get(
                "reserve_generation_bindings", 0
            ) == reserve_generation_bindings,
            "eventreserve_executions_match_timeline": timeline.get(
                "reserve_executions", 0
            ) == reserve_executions,
            "eventreserve_generation_binding_order": (
                0 <= generation_bindings <= generation_candidates
            ),
            "eventreserve_preview_order": (
                0 <= reserve_preview_accepts <= reserve_candidates
            ),
            "eventreserve_preview_partition": (
                reserve_preview_accepts == reserve_qualified + reserve_bindings
            ),
            "eventreserve_qualified_partition": (
                reserve_qualified
                == reserve_executions + reserve_generation_bindings
            ),
            "eventreserve_at_most_one_reserved_execution": 0 <= reserve_executions <= 1,
            "eventreserve_timeline_implications_valid": timeline.get(
                "invalid_implications", 0
            ) == 0,
            "eventreserve_reserve_position_valid": timeline.get(
                "invalid_reserve_position", 0
            ) == 0,
            "eventreserve_generation_state_valid": timeline.get(
                "invalid_generation_candidate_state", 0
            ) == 0,
            "eventreserve_runner_generation_audit_passed": budget.get(
                "generation_cap_binding_audit_satisfied"
            ) is True,
            "eventreserve_runner_conservation_passed": budget.get(
                "eventreserve_audit_conservation_satisfied"
            ) is True,
            "eventreserve_budget_semantics": budget.get("budget_semantics")
            == "generation_cap_5_switch_cap_6_event_reserved_sixth",
            "eventreserve_quota_not_exact": budget.get("exact_quota_required") is False,
            "eventreserve_runner_cap_satisfied": budget.get("cap_satisfied") is True,
            "eventreserve_runner_switch_cap_satisfied": budget.get(
                "switch_cap_satisfied"
            ) is True,
            "eventreserve_runner_generation_cap_satisfied": budget.get(
                "generation_cap_satisfied"
            ) is True,
            "eventreserve_runner_total_call_cap_satisfied": budget.get(
                "total_generator_call_cap_satisfied"
            ) is True,
            "eventreserve_zero_budget_violations": violations == 0,
            "eventreserve_zero_flat_budget_violations": run.get(
                "budget_violation_count"
            ) == 0,
        }
        for check, passed in checks.items():
            if not passed:
                _failure(failures, "eventreserve_budget", check, run)


def _merge_totals(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = defaultdict(int)
    route_reasons: dict[str, int] = defaultdict(int)
    for source in (left, right):
        for field, value in source.items():
            if field == "route_build_reason_counts":
                for reason, count in value.items():
                    route_reasons[str(reason)] += int(count)
            else:
                result[field] += int(value)
    result["route_build_reason_counts"] = dict(sorted(route_reasons.items()))
    return dict(result)


def _normalize_and_audit(
    artifacts: Sequence[Mapping[str, Any]],
    labels: Sequence[str],
    config: Mapping[str, Any],
    config_sha: str,
) -> dict[str, Any]:
    if len(artifacts) != EXPECTED_SCENARIOS:
        raise EventReserveDevelopmentError("exactly four artifacts are required")
    expected_seeds = list(config["root_seeds"])
    expected_keys = set(
        itertools.product(TARGET_METHODS, expected_seeds, EXPECTED_WORKLOADS)
    )
    seen_scenarios: set[str] = set()
    signatures: tuple[str, str, str, str] | None = None
    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    totals: dict[str, Any] = {}

    for artifact, label in zip(artifacts, labels):
        if not isinstance(artifact, dict):
            raise EventReserveDevelopmentError(f"{label} must be a JSON object")
        if artifact.get("schema") != SOURCE_SCHEMA or artifact.get("status") != "complete":
            raise EventReserveDevelopmentError(f"{label} is not a complete source artifact")
        if artifact.get("split") != "development" or artifact.get("evidence_class") != "development":
            raise EventReserveDevelopmentError(f"{label} is not development evidence")
        if artifact.get("seeds") != expected_seeds:
            raise EventReserveDevelopmentError(f"{label}.seeds differs from config")
        if artifact.get("methods") != list(TARGET_METHODS):
            raise EventReserveDevelopmentError(f"{label}.methods differs from config")
        if artifact.get("workloads") != list(EXPECTED_WORKLOADS):
            raise EventReserveDevelopmentError(f"{label}.workloads differs from config")
        raw_runs = artifact.get("runs")
        if not isinstance(raw_runs, list) or len(raw_runs) != RUNS_PER_SCENARIO:
            raise EventReserveDevelopmentError(
                f"{label} must contain exactly {RUNS_PER_SCENARIO} runs"
            )
        raw_keys: list[tuple[Any, Any, Any]] = [
            (
                run.get("method") if isinstance(run, dict) else None,
                run.get("root_seed", run.get("seed")) if isinstance(run, dict) else None,
                run.get("workload") if isinstance(run, dict) else None,
            )
            for run in raw_runs
        ]
        if len(raw_keys) != len(set(raw_keys)):
            raise EventReserveDevelopmentError(f"{label} has duplicate run cells")
        if set(raw_keys) != expected_keys:
            raise EventReserveDevelopmentError(
                f"{label} has missing or extra run cells"
            )

        scenario = _scenario_for_artifact(artifact, config["scenarios"], label=label)
        scenario_id = str(scenario["id"])
        if scenario_id in seen_scenarios:
            raise EventReserveDevelopmentError(f"duplicate scenario {scenario_id}")
        seen_scenarios.add(scenario_id)
        current_signature = _validate_artifact_protocol(
            artifact, config, config_sha, scenario, label=label
        )
        if signatures is None:
            signatures = current_signature
        elif current_signature != signatures:
            raise EventReserveDevelopmentError(
                "protocol/checkpoint/simulator metadata differs across artifacts"
            )

        baseline_raw = [run for run in raw_runs if run["method"] != EVENTRESERVE]
        baseline_artifact = {
            **artifact,
            "methods": list(BASE.TARGET_METHODS),
            "runs": baseline_raw,
        }
        try:
            seeds, map_id = BASE._validate_top_level(baseline_artifact)
            baseline_runs = BASE._normalize_runs(baseline_artifact, seeds, map_id)
            baseline_failures: list[dict[str, Any]] = []
            BASE._audit_pairing(baseline_runs, baseline_failures)
            BASE._audit_budget(baseline_runs, baseline_failures)
            baseline_totals = BASE._audit_safety_and_attribution(
                baseline_runs, baseline_failures
            )
        except BASE.DualCapArtifactError as error:
            raise EventReserveDevelopmentError(f"{label}: {error}") from error
        for item in baseline_failures:
            failures.append(
                {"scenario_id": scenario_id, "source_label": label, **item}
            )

        event_runs = [
            _normalize_eventreserve_run(
                run, index=index, seeds=expected_seeds, map_id=map_id
            )
            for index, run in enumerate(raw_runs)
            if run["method"] == EVENTRESERVE
        ]
        event_failures: list[dict[str, Any]] = []
        _audit_eventreserve_budget(event_runs, event_failures)
        try:
            event_totals = BASE._audit_safety_and_attribution(
                event_runs, event_failures
            )
        except BASE.DualCapArtifactError as error:
            raise EventReserveDevelopmentError(f"{label}: {error}") from error
        for item in event_failures:
            failures.append(
                {"scenario_id": scenario_id, "source_label": label, **item}
            )

        all_runs = [*baseline_runs, *event_runs]
        indexed = {
            (str(run["method"]), int(run["seed"]), str(run["workload"])): run
            for run in all_runs
        }
        paired_fields = (
            "manifest_id",
            "reset_causal_fingerprint",
            "release_projection_fingerprint",
            "distribution_update_fingerprint",
        )
        for seed, workload in itertools.product(expected_seeds, EXPECTED_WORKLOADS):
            reference = indexed[(EXACT, seed, workload)]
            candidate = indexed[(EVENTRESERVE, seed, workload)]
            for field in paired_fields:
                if candidate.get(field) != reference.get(field):
                    _failure(
                        failures,
                        "pairing",
                        f"paired_{field}",
                        candidate,
                    )
            if _canonical(candidate.get("task_tape_identity")) != _canonical(
                reference.get("task_tape_identity")
            ):
                _failure(failures, "pairing", "paired_task_tape_identity", candidate)
            if candidate.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            ) != reference.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            ):
                _failure(failures, "pairing", "paired_released_prefixes", candidate)
            if (
                candidate["scored_horizon"],
                candidate["decision_window"],
                candidate["window_count"],
            ) != (
                reference["scored_horizon"],
                reference["decision_window"],
                reference["window_count"],
            ):
                _failure(failures, "pairing", "paired_evaluation_horizon", candidate)

        totals = _merge_totals(totals, _merge_totals(baseline_totals, event_totals))
        normalized.extend(
            {
                **run,
                "scenario_id": scenario_id,
                "agents": int(scenario["agents"]),
                "map_name": str(scenario["map"]),
                "map_sha256": str(scenario["map_sha256"]),
            }
            for run in all_runs
        )

    expected_scenario_ids = {str(item["id"]) for item in config["scenarios"]}
    if seen_scenarios != expected_scenario_ids:
        raise EventReserveDevelopmentError("artifact scenario set differs from config")
    if len(normalized) != TOTAL_RUNS:
        raise EventReserveDevelopmentError("combined grid must contain 600 runs")
    return {"runs": normalized, "failures": failures, "totals": totals}


def _group_summary(
    cells: Sequence[Mapping[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    return {
        value: BASE._direction_summary(
            [cell for cell in cells if str(cell[field]) == value]
        )
        for value in sorted({str(cell[field]) for cell in cells})
    }


def _comparison(
    comparator: str,
    indexed: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    seeds = list(config["root_seeds"])
    scenarios = [str(item["id"]) for item in config["scenarios"]]
    cells: list[dict[str, Any]] = []
    relative_by_root: dict[int, list[float]] = defaultdict(list)
    absolute_by_root: dict[int, list[float]] = defaultdict(list)
    for scenario_id, seed, workload in itertools.product(
        scenarios, seeds, EXPECTED_WORKLOADS
    ):
        candidate = indexed[(scenario_id, EVENTRESERVE, seed, workload)]
        baseline = indexed[(scenario_id, comparator, seed, workload)]
        denominator = float(baseline["tasks"])
        if denominator <= 0:
            raise EventReserveDevelopmentError(
                f"zero comparator tasks in {scenario_id}:{seed}:{workload}:{comparator}"
            )
        absolute = float(candidate["tasks"]) - denominator
        relative = float(candidate["tasks"]) / denominator - 1.0
        cell = {
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
        cells.append(cell)
        relative_by_root[seed].append(relative)
        absolute_by_root[seed].append(absolute)
    root_relative = [_mean(relative_by_root[seed]) for seed in seeds]
    root_absolute = [_mean(absolute_by_root[seed]) for seed in seeds]
    return {
        "name": f"eventreserve_vs_{comparator}",
        "candidate": EVENTRESERVE,
        "comparator": comparator,
        "independent_unit": "root_seed",
        "n_paired_cells": len(cells),
        "n_root_seed_clusters": len(seeds),
        "cells_per_root_seed_cluster": 12,
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
        "cluster_bootstrap": BASE._cluster_bootstrap(
            root_relative, root_absolute, samples=bootstrap_samples
        ),
        "exact_sign_flip": BASE._exact_sign_flip(root_relative),
    }


def _holm_adjust(comparisons: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    raw = {
        comparator: float(row["exact_sign_flip"]["p_greater"])
        for comparator, row in comparisons.items()
    }
    ordered = sorted(raw, key=lambda comparator: (raw[comparator], comparator))
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, comparator in enumerate(ordered):
        candidate = min(1.0, (count - rank) * raw[comparator])
        running = max(running, candidate)
        adjusted[comparator] = running
    for comparator, value in adjusted.items():
        comparisons[comparator]["exact_sign_flip"]["p_greater_holm"] = value
    return {
        "method": "holm_step_down",
        "family": [f"eventreserve_vs_{item}" for item in COMPARATORS],
        "family_size": len(COMPARATORS),
        "raw_p_greater": raw,
        "adjusted_p_greater": adjusted,
        "ordered_comparators": ordered,
    }


def _method_summaries(
    runs: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for method in TARGET_METHODS:
        selected = [run for run in runs if run["method"] == method]
        result[method] = {
            "n_cells": len(selected),
            "mean_tasks": _mean(float(run["tasks"]) for run in selected),
            "mean_throughput": _mean(float(run["throughput"]) for run in selected),
            "mean_generator_calls": _mean(
                float(run["generator_calls"]) for run in selected
            ),
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
        raise EventReserveDevelopmentError("resource comparator must be positive")
    return 1.0 - candidate / comparator


def _screen(
    config: Mapping[str, Any],
    audit: Mapping[str, Any],
    comparisons: Mapping[str, Mapping[str, Any]],
    summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    gates = config["screen_gates"]
    bootstrap = comparisons[BOOTSTRAP]
    exact = comparisons[EXACT]
    context = comparisons[CONTEXT]
    dualcap = comparisons[DUALCAP]
    call_reduction = _reduction(
        float(summaries[EVENTRESERVE]["mean_generator_calls"]),
        float(summaries[EXACT]["mean_generator_calls"]),
    )
    checks = {
        "audit_all_passed": audit["passed"] is gates["audit_all_passed"],
        "eventreserve_vs_bootstrap_mean_at_least_2pct": (
            float(bootstrap["mean_relative_effect"])
            >= gates["eventreserve_vs_bootstrap_mean_relative_effect_at_least"]
        ),
        "eventreserve_vs_bootstrap_ci_lower_strictly_positive": (
            float(bootstrap["cluster_bootstrap"]["mean_relative_effect_ci"][0])
            > gates["eventreserve_vs_bootstrap_cluster_ci_lower_strictly_above"]
        ),
        "eventreserve_vs_bootstrap_exact_sign_flip_p_greater_below_0_05": (
            float(bootstrap["exact_sign_flip"]["p_greater"])
            < gates[
                "eventreserve_vs_bootstrap_exact_sign_flip_p_greater_strictly_below"
            ]
        ),
        "eventreserve_vs_bootstrap_all_10_roots_positive": (
            bootstrap["root_seed_win_tie_loss"]
            == {"wins": 10, "ties": 0, "losses": 0}
        ) is gates["eventreserve_vs_bootstrap_all_root_directions_positive"],
        "eventreserve_vs_exact_mean_at_least_minus_0_5pct": (
            float(exact["mean_relative_effect"])
            >= gates["eventreserve_vs_exact_mean_relative_effect_at_least"]
        ),
        "eventreserve_vs_exact_ci_lower_strictly_above_minus_1pct": (
            float(exact["cluster_bootstrap"]["mean_relative_effect_ci"][0])
            > gates["eventreserve_vs_exact_cluster_ci_lower_strictly_above"]
        ),
        "eventreserve_vs_context_mean_at_least_minus_1pct": (
            float(context["mean_relative_effect"])
            >= gates["eventreserve_vs_context_mean_relative_effect_at_least"]
        ),
        "eventreserve_vs_context_ci_lower_strictly_above_minus_1pct": (
            float(context["cluster_bootstrap"]["mean_relative_effect_ci"][0])
            > gates["eventreserve_vs_context_cluster_ci_lower_strictly_above"]
        ),
        "generator_call_reduction_vs_exact_at_least_80pct": (
            call_reduction >= gates["generator_call_reduction_vs_exact_at_least"]
        ),
        "mean_post_bootstrap_switches_at_most_5": (
            float(summaries[EVENTRESERVE]["mean_post_bootstrap_switches"])
            <= gates["mean_post_bootstrap_switches_at_most"]
        ),
    }
    if not checks["audit_all_passed"]:
        recommendation = "NO_GO_FIX_EVENTRESERVE_DEVELOPMENT_AUDIT"
    elif all(checks.values()):
        recommendation = "GO_FREEZE_UNCHANGED_EVENTRESERVE_FOR_FRESH_VALIDATION_V3_ONLY"
    else:
        recommendation = "NO_GO_EVENTRESERVE_DEVELOPMENT_SCREEN_FAILED"
    return {
        "passed": all(checks.values()),
        "recommendation": recommendation,
        "checks": checks,
        "frozen_thresholds": dict(gates),
        "resource_effects": {
            "generator_call_reduction_vs_exact": call_reduction,
            "generator_call_reduction_vs_context": _reduction(
                float(summaries[EVENTRESERVE]["mean_generator_calls"]),
                float(summaries[CONTEXT]["mean_generator_calls"]),
            ),
        },
        "dualcap_point_estimate": {
            "mean_relative_effect": dualcap["mean_relative_effect"],
            "mean_relative_effect_percent": dualcap["mean_relative_effect_percent"],
            "mean_absolute_task_delta": dualcap["mean_absolute_task_delta"],
            "eventreserve_strictly_better": dualcap["mean_relative_effect"] > 0.0,
            "is_screen_gate": False,
        },
        "development_only_no_paper_locked_test_or_sota_claim": True,
        "only_permitted_next_step_if_passed": (
            "Freeze the unchanged candidate and run a new untouched validation-v3."
        ),
    }


def analyze_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    config_path: Path,
    source_labels: Sequence[str] | None = None,
    source_sha256: Sequence[str] | None = None,
    bootstrap_samples: int = BASE.DEFAULT_BOOTSTRAP_SAMPLES,
    verify_local_sources: bool = True,
) -> dict[str, Any]:
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    labels = list(source_labels or [f"artifact_{index}" for index in range(len(artifacts))])
    hashes = list(source_sha256 or ["synthetic_or_in_memory"] * len(artifacts))
    if len(labels) != len(artifacts) or len(hashes) != len(artifacts):
        raise ValueError("source labels/hashes must align with artifacts")
    config, config_sha, resolved_config = load_config(config_path)
    treatment_sources = (
        _verify_local_treatment_sources(config)
        if verify_local_sources
        else {"verification_skipped_for_in_memory_test": True}
    )
    normalized = _normalize_and_audit(
        artifacts, labels, config, config_sha
    )
    runs = normalized["runs"]
    failures = normalized["failures"]
    audit = {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "totals": normalized["totals"],
        "complete_four_scenario_five_method_grid": len(runs) == TOTAL_RUNS,
        "paired_exogenous_inputs_match": not any(
            item["category"] == "pairing" for item in failures
        ),
        "baseline_budget_and_dualcap_contracts_passed": not any(
            item["category"] == "budget" for item in failures
        ),
        "eventreserve_budget_and_conservation_passed": not any(
            item["category"] == "eventreserve_budget" for item in failures
        ),
        "safety_timeout_route_and_invariants_passed": not any(
            item["category"] == "integrity" for item in failures
        ),
        "config_checkpoint_simulator_and_source_protocol_match_freeze": True,
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
    comparisons: dict[str, dict[str, Any]] = {
        comparator: _comparison(
            comparator, indexed, config, bootstrap_samples=bootstrap_samples
        )
        for comparator in COMPARATORS
    }
    multiplicity = _holm_adjust(comparisons)
    summaries = _method_summaries(runs)
    screening = _screen(config, audit, comparisons, summaries)
    return {
        "schema": ANALYSIS_SCHEMA,
        "sources": [
            {"label": label, "sha256": digest}
            for label, digest in zip(labels, hashes)
        ],
        "frozen_config": {
            "path": str(resolved_config),
            "sha256": config_sha,
            "schema": config["schema"],
            "artifact_declaration_field": CONFIG_SHA_FIELD,
        },
        "frozen_treatment_sources": treatment_sources,
        "evidence_warning": (
            "Four-scenario development-only evidence; no paper, locked-test, "
            "or SOTA claim is permitted."
        ),
        "design": {
            "scenario_ids": [str(item["id"]) for item in config["scenarios"]],
            "n_scenarios": 4,
            "root_seeds": list(config["root_seeds"]),
            "n_root_seed_clusters": 10,
            "workloads": list(EXPECTED_WORKLOADS),
            "methods": list(TARGET_METHODS),
            "paired_cells_per_method": 120,
            "cells_per_root_seed_cluster_per_method": 12,
            "total_runs": len(runs),
            "independent_unit": "root_seed",
            "pseudoreplication_guard": (
                "All four scenario and three workload cells sharing one root "
                "remain a single 12-cell inference cluster."
            ),
        },
        "audit": audit,
        "method_summaries": summaries,
        "comparisons": comparisons,
        "multiplicity": multiplicity,
        "screening": screening,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    audit = report["audit"]
    screen = report["screening"]
    lines = [
        "# Context event-reserve combined development screen",
        "",
        f"> **Scope:** {report['evidence_warning']}",
        "",
        f"- Config SHA-256: `{report['frozen_config']['sha256']}`",
        "- Design: 4 scenarios × 10 roots × 3 workloads = 120 paired cells per method",
        "- Independent observations: 10 root clusters (12 cells per cluster)",
        f"- Audit: **{'PASS' if audit['passed'] else 'FAIL'}**",
        f"- Recommendation: **`{screen['recommendation']}`**",
        "",
        "## Root-cluster paired effects",
        "",
        "| Comparator | Mean Δ tasks | Mean Δ% | 95% cluster CI | Root W/T/L | raw p> | Holm p> |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for comparator in COMPARATORS:
        row = report["comparisons"][comparator]
        ci = row["cluster_bootstrap"]["mean_relative_effect_ci"]
        wtl = row["root_seed_win_tie_loss"]
        test = row["exact_sign_flip"]
        lines.append(
            f"| `{comparator}` | {row['mean_absolute_task_delta']:+.2f} | "
            f"{row['mean_relative_effect_percent']:+.2f}% | "
            f"[{100 * ci[0]:+.2f}%, {100 * ci[1]:+.2f}%] | "
            f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} | "
            f"{test['p_greater']:.4g} | {test['p_greater_holm']:.4g} |"
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
    lines.extend(["", "## Frozen screen gates", ""])
    for name, passed in screen["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    dualcap = screen["dualcap_point_estimate"]
    lines.extend(
        [
            "",
            f"Event-reserve vs dual-cap point estimate: "
            f"{dualcap['mean_relative_effect_percent']:+.2f}% "
            f"(better={dualcap['eventreserve_strictly_better']}; not a gate).",
            "",
            "A full pass only licenses fresh validation-v3 of the unchanged candidate.",
            "",
        ]
    )
    if audit["failures"]:
        lines.extend(["## Audit failures", ""])
        for item in audit["failures"]:
            lines.append(
                f"- `{item.get('scenario_id', '?')}:{item['category']}/{item['check']}` "
                f"`{item.get('cell', item.get('detail', {}))}`"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--bootstrap-samples", type=int, default=BASE.DEFAULT_BOOTSTRAP_SAMPLES
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    paths = [path.resolve() for path in args.artifacts]
    try:
        artifacts = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        if any(not isinstance(item, dict) for item in artifacts):
            raise EventReserveDevelopmentError("artifact top levels must be objects")
        report = analyze_artifacts(
            artifacts,
            config_path=args.config,
            source_labels=[str(path) for path in paths],
            source_sha256=[_sha256(path) for path in paths],
            bootstrap_samples=args.bootstrap_samples,
        )
    except (OSError, json.JSONDecodeError, EventReserveDevelopmentError) as error:
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
