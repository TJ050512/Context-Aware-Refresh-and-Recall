#!/usr/bin/env python3
"""Audit the amended same-call engineering preflight without estimating effects.

Version 2 separates two questions that version 1 inadvertently conflated:

* the archived, cross-instance evidence is a hard gate only for registered
  sources and causal inputs; its outputs are reported as a non-gating
  diagnostic and are never used for effect inference; and
* a frozen legacy runner replayed on the *current* host must be bitwise equal
  to the new runner on the complete registered legacy projection.

The remaining gates are unchanged: a 96-arm engineering smoke matrix with
append-only ledgers, exact budgets/safety/fresh-process checks, a deterministic
random schedule, same-host repeats, and the future-suffix non-anticipation
metamorphic test.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
from typing import Any, Iterable, Mapping, Sequence


def _load_v1_module() -> Any:
    path = Path(__file__).with_name("audit_same_call_preflight_v1.py")
    spec = importlib.util.spec_from_file_location("audit_same_call_preflight_v1_dependency", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import v1 auditor dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1_module()

SCHEMA = "dai.same-call-preflight-audit/v2"
ATTESTATION_SCHEMA = "dai.same-call-legacy-current-replay-attestation/v1"
ENVIRONMENT_ATTESTATION_SCHEMA = "dai.same-call-environment-attestation/a1"
ARTIFACT_SCHEMA = V1.ARTIFACT_SCHEMA
LEGACY_CURRENT_ARTIFACT_SCHEMA = "dai.same-call-legacy-current-replay-artifact/a1"
ATTEMPT_SCHEMA = V1.ATTEMPT_SCHEMA
EVENTRESERVE_EVIDENCE_SHA256 = V1.EVENTRESERVE_EVIDENCE_SHA256
CHECKPOINT_SHA256 = V1.CHECKPOINT_SHA256
CHECKPOINT_PARAMS_SHA256 = V1.CHECKPOINT_PARAMS_SHA256
SIMULATOR_SHA256 = V1.SIMULATOR_SHA256
ROOT_SEED = V1.ROOT_SEED
WORKLOADS = V1.WORKLOADS
METHODS = V1.METHODS
COMMON_ARMS = V1.COMMON_ARMS
REPLAY_ARMS = V1.REPLAY_ARMS
EXPECTED_SCENARIOS = V1.EXPECTED_SCENARIOS
EXACT_SCHEDULES = V1.EXACT_SCHEDULES
PREDECESSOR_PROTOCOL_SHA256 = "9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41"
AMENDMENT_A1_PROTOCOL_SHA256 = "10f17682a9dc32f33fad2c77289e8c9dff659325de655b584f1d138066f05fdf"
AMENDMENT_A1_PROTOCOL_BASENAME = "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A1.md"
LEGACY_LEDGER_EVENT_SCHEMA = "dai.same-call-legacy-current-replay-ledger-event/a1"

ARCHIVE_MEMBER_PATHS = {
    "claim_runner": "src/dai_lmapf/claim_runner.py",
    "validation_runner": "scripts/run_claim_aware_budgeted_validation.py",
    "config": "configs/context_eventreserve_development_matrix_v1.json",
}
REGISTERED_LEGACY_SOURCE_SHA256 = {
    "claim_runner": "d9bf61bfa2f86881084b2b1abc19aa0f7483206fa58dcdc88c0b086099d03c2e",
    "validation_runner": "694c6af03421e653b7d273d6e5f9da3dd6d1ec349f9120b8efe06bf466b33d50",
    "config": "adda8cf0175ccac6a469e71ead1b3ec66ab96a4cfcd3d6dd98a80e41a4338e86",
    "checkpoint_file": CHECKPOINT_SHA256,
    "period_on_sim": SIMULATOR_SHA256,
}
ARCHIVE_INPUT_FIELDS = (
    "manifest_id",
    "task_tape_identity",
    "reset_causal_fingerprint",
    "release_projection_fingerprint",
    "distribution_update_fingerprint",
)
ARCHIVE_PROTOCOL_FIELDS = (
    "agents",
    "warmup_time",
    "scored_horizon",
    "decision_window",
    "num_scored_windows",
    "eligible_post_bootstrap_decisions",
    "b25_budget",
    "release_interval_per_agent",
    "guard_suffix_tasks_per_agent",
    "sigma",
    "deterministic_agent_stagger",
    "minimum_history",
    "pacing_slack",
    "causal_feature_allowlist",
    "causal_feature_forbidden_fields",
    "distribution_update_fingerprint_semantics",
    "planner_timeout_semantics",
    "context_memory_B25",
    "context_dualcap_G4S5",
    "context_eventreserve_G5S6",
    "causal_block_B25",
    "js_cap_B25",
    "random_memory_B25",
)


class PreflightAuditError(ValueError):
    """Raised when an amended preflight gate fails."""


def _fail(message: str) -> None:
    raise PreflightAuditError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        _fail(f"{context} mismatch: expected={expected!r} actual={actual!r}")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bytes_sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightAuditError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"expected JSON object: {path}")
    return value


def _evidence_record(path: Path, *, label: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    record: dict[str, Any] = {
        "path": str(path),
        "sha256": _file_sha(path),
        "size_bytes": path.stat().st_size,
    }
    if label is not None:
        record["label"] = label
    return record


def _first_difference(actual: Any, expected: Any, path: str = "") -> str | None:
    if type(actual) is not type(expected):
        return path or "$"
    if isinstance(actual, Mapping):
        keys = list(dict.fromkeys([*actual.keys(), *expected.keys()]))
        for key in keys:
            child = f"{path}.{key}" if path else str(key)
            if key not in actual or key not in expected:
                return child
            difference = _first_difference(actual[key], expected[key], child)
            if difference is not None:
                return difference
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}.length"
        for index, (left, right) in enumerate(zip(actual, expected)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    return None if actual == expected else (path or "$")


def _artifact_label(artifact: Mapping[str, Any], context: str) -> str:
    key = (str(artifact.get("map_id")), int(artifact.get("protocol", {}).get("agents")))
    _require(key in EXPECTED_SCENARIOS, f"{context}.unexpected scenario {key}")
    return str(EXPECTED_SCENARIOS[key][0])


def _looks_like_artifact(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value.get("schema") in {
        ARTIFACT_SCHEMA,
        LEGACY_CURRENT_ARTIFACT_SCHEMA,
    }


def resolve_four_artifacts(paths: Sequence[Path], label: str) -> list[Path]:
    found: list[Path] = []
    for supplied in paths:
        path = supplied.resolve()
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(
                candidate
                for candidate in sorted(path.glob("*.json"))
                if _looks_like_artifact(candidate)
            )
            artifacts_dir = path / "artifacts"
            if artifacts_dir.is_dir():
                found.extend(
                    candidate
                    for candidate in sorted(artifacts_dir.glob("*.json"))
                    if _looks_like_artifact(candidate)
                )
        else:
            _fail(f"{label} path does not exist: {path}")
    unique = list(dict.fromkeys(found))
    _equal(len(unique), 4, f"number of {label} artifacts")
    return unique


def resolve_named_artifact(path: Path, label: str) -> Path:
    return V1.resolve_named_artifact(path, label)


def _run_key(run: Mapping[str, Any], agents: int) -> tuple[str, int, str, str]:
    return (str(run.get("map_id")), agents, str(run.get("workload")), str(run.get("method")))


def _source_header(artifact: Mapping[str, Any]) -> dict[str, Any]:
    generator = artifact.get("generator", {})
    return {
        "map_sha256": artifact.get("map_sha256"),
        "period_on_sim_sha256": artifact.get("period_on_sim_sha256"),
        "checkpoint_file_sha256": generator.get("file_sha256"),
        "checkpoint_params_sha256": generator.get("params_sha256"),
    }


def _expected_source_header(map_sha256: str) -> dict[str, Any]:
    return {
        "map_sha256": map_sha256,
        "period_on_sim_sha256": SIMULATOR_SHA256,
        "checkpoint_file_sha256": CHECKPOINT_SHA256,
        "checkpoint_params_sha256": CHECKPOINT_PARAMS_SHA256,
    }


def audit_smoke_structure(
    artifact_paths: Sequence[Path],
) -> tuple[
    dict[str, Any],
    dict[tuple[str, int, str, str], Mapping[str, Any]],
    dict[tuple[str, int], dict[str, Any]],
    dict[str, Any],
]:
    """Audit all non-archive smoke gates and return an indexed matrix."""

    smoke_index: dict[tuple[str, int, str, str], Mapping[str, Any]] = {}
    labels: set[str] = set()
    all_triples: set[tuple[str, int, int]] = set()
    all_uuids: set[str] = set()
    ledger_events = 0
    random_schedules: list[list[int]] = []
    hosts: set[str] = set()
    protocol_hashes: set[str] = set()
    records: list[dict[str, Any]] = []
    scenario_protocols: dict[tuple[str, int], dict[str, Any]] = {}

    for path in artifact_paths:
        artifact = _load_json(path)
        runs = V1._audit_artifact_header(
            path,
            artifact,
            methods=METHODS,
            workloads=WORKLOADS,
            expected_runs=24,
        )
        agents = int(artifact["protocol"]["agents"])
        scenario_key = (str(artifact.get("map_id")), agents)
        _require(scenario_key in EXPECTED_SCENARIOS, f"{path}.unexpected smoke scenario {scenario_key}")
        scenario_label, map_sha = EXPECTED_SCENARIOS[scenario_key]
        _require(scenario_label not in labels, f"duplicate smoke scenario {scenario_label}")
        labels.add(scenario_label)
        _equal(artifact.get("map_sha256"), map_sha, f"{path}.map SHA256")
        _equal(_source_header(artifact), _expected_source_header(map_sha), f"{path}.source header")
        scenario_protocols[scenario_key] = {
            field: artifact.get("protocol", {}).get(field)
            for field in ARCHIVE_PROTOCOL_FIELDS
        }

        runtime = artifact.get("runtime_manifest")
        _require(isinstance(runtime, dict), f"{path}.runtime_manifest missing")
        environment = runtime.get("environment")
        sources = runtime.get("sources")
        _require(isinstance(environment, dict), f"{path}.runtime environment missing")
        _require(isinstance(sources, dict), f"{path}.runtime sources missing")
        host = environment.get("host")
        _require(isinstance(host, str) and bool(host), f"{path}.runtime host missing")
        hosts.add(host)
        protocol_source = sources.get("protocol")
        _require(isinstance(protocol_source, dict), f"{path}.runtime protocol source missing")
        protocol_sha = protocol_source.get("sha256")
        _require(isinstance(protocol_sha, str) and len(protocol_sha) == 64, f"{path}.protocol SHA256 invalid")
        _equal(protocol_sha, PREDECESSOR_PROTOCOL_SHA256, f"{path}.predecessor protocol SHA256")
        protocol_hashes.add(protocol_sha)

        triples, uuids = V1._audit_execution_metadata(artifact, runs, str(path))
        _require(all_triples.isdisjoint(triples), "fresh process tuple reused across smoke artifacts")
        _require(all_uuids.isdisjoint(uuids), "run UUID reused across smoke artifacts")
        all_triples.update(triples)
        all_uuids.update(uuids)
        ledger_events += V1.audit_attempt_ledger(path, artifact, runs)["events"]

        for workload in WORKLOADS:
            cell_runs = [run for run in runs if run.get("workload") == workload]
            _equal(len(cell_runs), 8, f"{path}.{workload}.arm count")
            V1._audit_pairing(cell_runs, METHODS, f"{path}.{workload}")
        for run in runs:
            key = _run_key(run, agents)
            _require(key not in smoke_index, f"duplicate smoke run {key}")
            smoke_index[key] = run
            if run.get("method") == "random_G5":
                random_schedules.append(V1._actual_switch_indices(run))
        records.append(_evidence_record(path, label=scenario_label))

    _equal(labels, {value[0] for value in EXPECTED_SCENARIOS.values()}, "smoke scenario set")
    _equal(len(smoke_index), 96, "smoke matrix size")
    _equal(len(hosts), 1, "smoke runtime host count")
    _equal(len(protocol_hashes), 1, "smoke protocol hash count")
    _equal(len(random_schedules), 12, "random_G5 cell count")
    _equal(len({_canonical(schedule) for schedule in random_schedules}), 1, "random_G5 schedule across 12 cells")

    return (
        {
            "artifacts": 4,
            "runs": 96,
            "cells": 12,
            "methods": 8,
            "root_seed": ROOT_SEED,
            "current_host": next(iter(hosts)),
            "protocol_sha256": next(iter(protocol_hashes)),
            "fresh_process_arms": 96,
            "attempt_ledger_events": ledger_events,
            "paired_fingerprints": "pass",
            "budget_schedule_safety": "pass",
            "random_G5_schedule": random_schedules[0],
            "random_G5_schedule_equal_across_cells": True,
        },
        smoke_index,
        scenario_protocols,
        {"artifacts": records},
    )


def _load_archive(
    archive_path: Path,
    *,
    expected_archive_sha256: str | None,
    expected_source_sha256: Mapping[str, str] | None,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    archive_path = archive_path.resolve()
    archive_sha = _file_sha(archive_path)
    if expected_archive_sha256 is not None:
        _equal(archive_sha, expected_archive_sha256, "archived evidence SHA256")
    artifacts: list[dict[str, Any]] = []
    member_hashes: dict[str, str] = {}
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile()
                and member.name.startswith("results/development_eventreserve/matrix_v1_")
                and member.name.endswith(".json")
                and "/analysis/" not in member.name
            ]
            _equal(len(members), 4, "archived scenario artifact count")
            for member in sorted(members, key=lambda item: item.name):
                stream = archive.extractfile(member)
                _require(stream is not None, f"cannot read archive member {member.name}")
                value = json.loads(stream.read().decode("utf-8"))
                _require(isinstance(value, dict), f"archive member is not an object: {member.name}")
                artifacts.append(value)
            names = {member.name: member for member in archive.getmembers() if member.isfile()}
            for label, member_path in ARCHIVE_MEMBER_PATHS.items():
                _require(member_path in names, f"archive source member missing: {member_path}")
                stream = archive.extractfile(names[member_path])
                _require(stream is not None, f"cannot read archive source member {member_path}")
                member_hashes[label] = _bytes_sha(stream.read())
    except (OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise PreflightAuditError(f"cannot read archived evidence {archive_path}: {exc}") from exc
    if expected_source_sha256 is not None:
        for label in ARCHIVE_MEMBER_PATHS:
            _equal(member_hashes[label], expected_source_sha256[label], f"archive embedded {label} SHA256")
    return artifacts, member_hashes, archive_sha


def audit_archive_inputs_and_diagnostic(
    archive_path: Path,
    smoke_index: Mapping[tuple[str, int, str, str], Mapping[str, Any]],
    smoke_scenario_protocols: Mapping[tuple[str, int], Mapping[str, Any]],
    *,
    expected_archive_sha256: str | None = EVENTRESERVE_EVIDENCE_SHA256,
    expected_source_sha256: Mapping[str, str] | None = REGISTERED_LEGACY_SOURCE_SHA256,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """Gate archived inputs and report, but never gate on, archived outputs."""

    artifacts, embedded_sources, archive_sha = _load_archive(
        archive_path,
        expected_archive_sha256=expected_archive_sha256,
        expected_source_sha256=expected_source_sha256,
    )
    archive_index: dict[tuple[str, int, str, str], Mapping[str, Any]] = {}
    source_headers: dict[tuple[str, int], dict[str, Any]] = {}
    protocol_field_comparisons = {field: 0 for field in ARCHIVE_PROTOCOL_FIELDS}
    config_hash = embedded_sources["config"]
    for artifact in artifacts:
        _equal(artifact.get("schema"), ARTIFACT_SCHEMA, "archive artifact schema")
        _equal(artifact.get("status"), "complete", "archive artifact status")
        agents = int(artifact.get("protocol", {}).get("agents"))
        scenario_key = (str(artifact.get("map_id")), agents)
        _require(scenario_key in EXPECTED_SCENARIOS, f"unexpected archive scenario {scenario_key}")
        _, map_sha = EXPECTED_SCENARIOS[scenario_key]
        _equal(_source_header(artifact), _expected_source_header(map_sha), f"archive {scenario_key}.source header")
        _equal(
            artifact.get("development_matrix_config_sha256"),
            config_hash,
            f"archive {scenario_key}.config SHA256",
        )
        archived_protocol = artifact.get("protocol", {})
        for field in ARCHIVE_PROTOCOL_FIELDS:
            _equal(
                archived_protocol.get(field),
                smoke_scenario_protocols[scenario_key].get(field),
                f"archive registered protocol {scenario_key}.{field}",
            )
            protocol_field_comparisons[field] += 1
        source_headers[scenario_key] = _source_header(artifact)
        runs = artifact.get("runs")
        _require(isinstance(runs, list), f"archive {scenario_key}.runs missing")
        for run in runs:
            if run.get("seed") == ROOT_SEED and run.get("method") in COMMON_ARMS:
                key = _run_key(run, agents)
                _require(key not in archive_index, f"duplicate archived root-17 run {key}")
                archive_index[key] = run

    expected_keys = {
        (map_id, agents, workload, method)
        for map_id, agents in EXPECTED_SCENARIOS
        for workload in WORKLOADS
        for method in COMMON_ARMS
    }
    _equal(set(archive_index), expected_keys, "archived root-17 common-arm matrix")
    _equal(set(smoke_index).intersection(expected_keys), expected_keys, "smoke common-arm matrix")

    input_matches = 0
    output_matches = 0
    output_differences = 0
    first_output_divergence: dict[str, Any] | None = None
    input_field_comparisons = {field: 0 for field in ARCHIVE_INPUT_FIELDS}
    for key in sorted(expected_keys):
        archived = archive_index[key]
        current = smoke_index[key]
        for field in ARCHIVE_INPUT_FIELDS:
            _equal(current.get(field), archived.get(field), f"archive registered input {key}.{field}")
            input_field_comparisons[field] += 1
        input_matches += 1
        if V1._legacy_projection(current) == V1._legacy_projection(archived):
            output_matches += 1
        else:
            output_differences += 1
            if first_output_divergence is None:
                first_output_divergence = {
                    "arm": list(key),
                    "field": _first_difference(
                        V1._legacy_projection(current),
                        V1._legacy_projection(archived),
                    ),
                }

    _equal(input_matches, 36, "archived input comparisons")
    return (
        {
            "archive_sha256": archive_sha,
            "source_identity": {
                "gate": True,
                "embedded_member_sha256": embedded_sources,
                "scenario_source_headers": len(source_headers),
                "status": "pass",
            },
            "registered_input_identity": {
                "gate": True,
                "comparisons": input_matches,
                "fields": list(ARCHIVE_INPUT_FIELDS),
                "field_comparisons": input_field_comparisons,
                "protocol_field_comparisons": protocol_field_comparisons,
                "mismatches": [],
                "status": "pass",
            },
            "cross_instance_output_diagnostic": {
                "comparisons": 36,
                "bitwise_equal_on_legacy_projection": output_matches,
                "bitwise_different_on_legacy_projection": output_differences,
                "first_divergence": first_output_divergence,
                "used_as_gate": False,
                "used_for_effect": False,
                "used_for_ranking": False,
                "interpretation": "diagnostic only; backend/hardware may change floating-point CNN outputs",
            },
        },
        embedded_sources,
        {"archive": _evidence_record(archive_path)},
    )


def _audit_current_legacy_run(run: Mapping[str, Any], context: str) -> None:
    _equal(run.get("seed"), ROOT_SEED, f"{context}.seed")
    _equal(run.get("root_seed"), ROOT_SEED, f"{context}.root_seed")
    _equal(run.get("split"), "development", f"{context}.split")
    _equal(run.get("evidence_class"), "development", f"{context}.evidence_class")
    _equal(run.get("scored_horizon"), 2000, f"{context}.scored_horizon")
    _equal(run.get("decision_window"), 20, f"{context}.decision_window")
    _equal(run.get("window_count"), 100, f"{context}.window_count")
    _equal(len(run.get("windows", ())), 100, f"{context}.windows")
    _equal(len(run.get("publication_timeline", ())), 100, f"{context}.timeline")
    safety = run.get("safety")
    invariants = run.get("invariants")
    budget = run.get("budget")
    _require(isinstance(safety, dict) and safety.get("passed") is True, f"{context}.safety failed")
    _require(isinstance(invariants, dict) and invariants.get("passed") is True, f"{context}.invariants failed")
    _require(isinstance(budget, dict), f"{context}.budget missing")
    for field in ("collisions", "edge_swaps", "invalid_moves", "planner_timeouts", "budget_violation_count"):
        _equal(run.get(field), 0, f"{context}.{field}")
    _equal(invariants.get("online_workload_rng_draws"), 0, f"{context}.online RNG")
    for field in (
        "cap_satisfied",
        "switch_cap_satisfied",
        "generation_cap_satisfied",
        "total_generator_call_cap_satisfied",
        "generator_call_conservation_satisfied",
        "switch_operation_partition_satisfied",
    ):
        _equal(budget.get(field), True, f"{context}.budget.{field}")


def _attestation_sources(
    attestation: Mapping[str, Any],
    embedded_sources: Mapping[str, str],
    *,
    expected_source_sha256: Mapping[str, str] | None,
) -> None:
    sources = attestation.get("sources")
    _require(isinstance(sources, dict), "legacy attestation.sources missing")
    required = ("claim_runner", "validation_runner", "config", "checkpoint_file", "period_on_sim")
    for label in required:
        record = sources.get(label)
        _require(isinstance(record, dict), f"legacy attestation source missing: {label}")
        sha = record.get("sha256")
        _require(isinstance(sha, str) and len(sha) == 64, f"legacy attestation {label}.sha256 invalid")
        expected_declared = record.get("expected_sha256")
        if expected_declared is not None:
            _equal(expected_declared, sha, f"legacy attestation {label}.expected_sha256")
        if expected_source_sha256 is not None:
            _equal(sha, expected_source_sha256[label], f"legacy attestation {label}.sha256")
    for label in ARCHIVE_MEMBER_PATHS:
        _equal(sources[label]["sha256"], embedded_sources[label], f"archive/current legacy source identity {label}")


def _attestation_artifact_records(attestation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = attestation.get("artifacts")
    if isinstance(records, dict):
        normalized = []
        for label, record in records.items():
            _require(isinstance(record, dict), f"legacy attestation artifact {label} invalid")
            normalized.append({"label": label, **record})
        records = normalized
    _require(isinstance(records, list), "legacy attestation.artifacts missing")
    _equal(len(records), 4, "legacy attestation artifact count")
    _require(all(isinstance(record, dict) for record in records), "legacy attestation artifact record invalid")
    return records


def _audit_map_records(attestation: Mapping[str, Any], context: str) -> None:
    maps = attestation.get("maps")
    _require(isinstance(maps, dict), f"{context}.maps missing")
    _equal(len(maps), 2, f"{context}.map record count")
    actual_hashes: set[str] = set()
    for label, record in maps.items():
        _require(isinstance(record, dict), f"{context}.maps.{label} invalid")
        sha = record.get("sha256")
        _require(isinstance(sha, str) and len(sha) == 64, f"{context}.maps.{label}.sha256 invalid")
        if record.get("expected_sha256") is not None:
            _equal(record.get("expected_sha256"), sha, f"{context}.maps.{label}.expected_sha256")
        actual_hashes.add(sha)
    _equal(
        actual_hashes,
        {value[1] for value in EXPECTED_SCENARIOS.values()},
        f"{context}.registered map SHA256 set",
    )


def _resolve_declared_file(declared_path: str, anchor: Path) -> Path:
    declared = Path(declared_path)
    candidates = [declared]
    if not declared.is_absolute():
        candidates.extend((Path.cwd() / declared, anchor.parent / declared, anchor.parent.parent / declared))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    _fail(f"cannot resolve declared evidence file: {declared_path}")
    raise AssertionError("unreachable")


def _audit_legacy_ledger(path: Path) -> dict[str, Any]:
    try:
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightAuditError(f"invalid legacy ledger {path}: {exc}") from exc
    _equal(len(events), 72, "legacy ledger event count")
    previous = None
    cell_events: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    started_pids: set[int] = set()
    completed_instances: set[tuple[str, int, int]] = set()
    for sequence, event in enumerate(events, 1):
        _require(isinstance(event, dict), f"legacy ledger event {sequence} invalid")
        _equal(event.get("schema"), LEGACY_LEDGER_EVENT_SCHEMA, f"legacy ledger event {sequence}.schema")
        _equal(event.get("sequence"), sequence, f"legacy ledger event {sequence}.sequence")
        _equal(event.get("previous_event_sha256"), previous, f"legacy ledger event {sequence}.previous hash")
        supplied = event.get("event_sha256")
        unhashed = dict(event)
        unhashed.pop("event_sha256", None)
        _equal(supplied, V1._strict_sha(unhashed), f"legacy ledger event {sequence}.hash")
        previous = str(supplied)
        kind = event.get("event")
        _require(kind in {"started", "completed"}, f"legacy ledger event {sequence}.kind")
        cell = (str(event.get("label")), str(event.get("workload")), str(event.get("method")))
        cell_events[cell].append(str(kind))
        pid = event.get("pid")
        _require(isinstance(pid, int) and pid > 0, f"legacy ledger event {sequence}.pid")
        if kind == "started":
            _require(pid not in started_pids, f"legacy ledger PID reused: {pid}")
            started_pids.add(pid)
        else:
            _equal(event.get("returncode"), 0, f"legacy ledger event {sequence}.returncode")
            boot_id = event.get("boot_id")
            ticks = event.get("process_start_ticks")
            _require(isinstance(boot_id, str) and bool(boot_id), f"legacy ledger event {sequence}.boot_id")
            _require(isinstance(ticks, int) and ticks > 0, f"legacy ledger event {sequence}.process_start_ticks")
            completed_instances.add((boot_id, pid, ticks))
    _equal(len(cell_events), 36, "legacy ledger unique arm cells")
    for cell, kinds in cell_events.items():
        _equal(kinds, ["started", "completed"], f"legacy ledger cell events {cell}")
    _equal(len(started_pids), 36, "legacy ledger unique PIDs")
    _equal(len(completed_instances), 36, "legacy ledger unique process instances")
    return {
        "schema": LEGACY_LEDGER_EVENT_SCHEMA,
        "event_count": 72,
        "started_events": 36,
        "completed_events": 36,
        "failed_events": 0,
        "unique_process_count": 36,
        "unique_process_instance_count": 36,
        "unique_arm_count": 36,
        "matched_start_complete_arms": 36,
        "final_event_hash": previous,
    }


def _audit_environment_attestation(
    environment_attestation_path: Path,
    replay_attestation: Mapping[str, Any],
    smoke_result: Mapping[str, Any],
    *,
    expected_source_sha256: Mapping[str, str] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = environment_attestation_path.resolve()
    attestation = _load_json(path)
    _equal(attestation.get("schema"), ENVIRONMENT_ATTESTATION_SCHEMA, "environment attestation schema")
    _equal(attestation.get("status"), "complete", "environment attestation status")
    _equal(attestation.get("created_before_legacy_replay"), True, "environment attestation pre-run ordering")
    _equal(attestation.get("fresh_root_runs_observed"), 0, "environment attestation fresh runs")
    _equal(attestation.get("fresh_effect_estimates_computed"), 0, "environment attestation fresh effects")
    environment = attestation.get("environment")
    _require(isinstance(environment, dict), "environment attestation.environment missing")
    _equal(environment.get("host"), smoke_result["current_host"], "environment/smoke host")
    fingerprint = environment.get("host_instance_fingerprint_sha256")
    _require(isinstance(fingerprint, str) and len(fingerprint) == 64, "host instance fingerprint invalid")
    protocol = attestation.get("protocol")
    _require(isinstance(protocol, dict), "environment attestation.protocol missing")
    _equal(protocol.get("sha256"), AMENDMENT_A1_PROTOCOL_SHA256, "environment A1 protocol SHA256")
    _equal(protocol.get("expected_sha256"), AMENDMENT_A1_PROTOCOL_SHA256, "environment expected A1 protocol SHA256")
    _equal(Path(str(protocol.get("path", ""))).name, AMENDMENT_A1_PROTOCOL_BASENAME, "environment A1 protocol basename")
    thread_contract = attestation.get("thread_contract")
    _require(isinstance(thread_contract, dict), "environment thread_contract missing")
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        _equal(str(thread_contract.get(name)), "1", f"environment thread contract {name}")
    launchers = attestation.get("launchers")
    _require(isinstance(launchers, dict), "environment launchers missing")
    for name in ("legacy_replay", "legacy_arm_wrapper"):
        record = launchers.get(name)
        _require(isinstance(record, dict), f"environment launcher missing: {name}")
        sha = record.get("sha256")
        _require(isinstance(sha, str) and len(sha) == 64, f"environment launcher {name}.sha256 invalid")
    sources = attestation.get("sources")
    _require(isinstance(sources, dict), "environment sources missing")
    for name in ("claim_runner", "validation_runner", "config", "checkpoint_file", "period_on_sim"):
        record = sources.get(name)
        _require(isinstance(record, dict), f"environment source missing: {name}")
        sha = record.get("sha256")
        _require(isinstance(sha, str) and len(sha) == 64, f"environment source {name}.sha256 invalid")
        if expected_source_sha256 is not None:
            _equal(sha, expected_source_sha256[name], f"environment source {name}.sha256")
    _audit_map_records(attestation, "environment attestation")
    digest = _file_sha(path)
    _equal(replay_attestation.get("environment_attestation_sha256"), digest, "replay/environment attestation digest")
    reference = replay_attestation.get("environment_attestation")
    _require(isinstance(reference, dict), "replay environment_attestation reference missing")
    _equal(reference.get("sha256"), digest, "replay environment attestation reference SHA256")
    declared_path = reference.get("path")
    _require(isinstance(declared_path, str) and bool(declared_path), "replay environment attestation reference path missing")
    _equal(Path(declared_path).name, path.name, "replay environment attestation basename")
    return attestation, _evidence_record(path)


def audit_current_host_legacy_equivalence(
    artifact_paths: Sequence[Path],
    attestation_path: Path,
    environment_attestation_path: Path,
    smoke_index: Mapping[tuple[str, int, str, str], Mapping[str, Any]],
    smoke_result: Mapping[str, Any],
    embedded_archive_sources: Mapping[str, str],
    *,
    expected_source_sha256: Mapping[str, str] | None = REGISTERED_LEGACY_SOURCE_SHA256,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require the current-host frozen legacy replay to match the new runner."""

    attestation_path = attestation_path.resolve()
    attestation = _load_json(attestation_path)
    _equal(attestation.get("schema"), ATTESTATION_SCHEMA, "legacy attestation schema")
    _equal(attestation.get("status"), "complete", "legacy attestation status")
    _equal(attestation.get("root_seed"), ROOT_SEED, "legacy attestation root_seed")
    environment_attestation, environment_record = _audit_environment_attestation(
        environment_attestation_path,
        attestation,
        smoke_result,
        expected_source_sha256=expected_source_sha256,
    )
    environment = attestation.get("environment")
    _require(isinstance(environment, dict), "legacy attestation.environment missing")
    _equal(environment.get("host"), smoke_result["current_host"], "legacy/smoke current host")
    _equal(
        environment.get("host_instance_fingerprint_sha256"),
        environment_attestation.get("environment", {}).get("host_instance_fingerprint_sha256"),
        "legacy/environment host instance fingerprint",
    )
    protocol = attestation.get("protocol")
    _require(isinstance(protocol, dict), "legacy attestation.protocol missing")
    _equal(protocol.get("sha256"), AMENDMENT_A1_PROTOCOL_SHA256, "legacy A1 protocol SHA256")
    _equal(Path(str(protocol.get("path", ""))).name, AMENDMENT_A1_PROTOCOL_BASENAME, "legacy A1 protocol basename")
    if protocol.get("expected_sha256") is not None:
        _equal(protocol.get("expected_sha256"), protocol.get("sha256"), "legacy protocol expected SHA256")
    _equal(protocol, environment_attestation.get("protocol"), "legacy/environment A1 protocol identity")
    methods = attestation.get("common_methods")
    _equal(set(methods or ()), set(COMMON_ARMS), "legacy attestation common methods")
    count = attestation.get("common_arm_run_count", attestation.get("common_run_count"))
    _equal(count, 36, "legacy attestation common-arm run count")
    _equal(attestation.get("raw_legacy_run_count"), 36, "legacy attestation raw run count")
    _equal(attestation.get("fresh_process_per_arm"), True, "legacy attestation fresh process flag")
    _attestation_sources(
        attestation,
        embedded_archive_sources,
        expected_source_sha256=expected_source_sha256,
    )
    _audit_map_records(attestation, "legacy replay attestation")
    for name in ("claim_runner", "validation_runner", "config", "checkpoint_file", "period_on_sim"):
        _equal(
            attestation["sources"][name],
            environment_attestation["sources"][name],
            f"legacy/environment source identity {name}",
        )

    ledger = attestation.get("ledger")
    _require(isinstance(ledger, dict), "legacy attestation.ledger missing")
    for field, expected in (
        ("started_events", 36),
        ("completed_events", 36),
        ("failed_events", 0),
        ("unique_process_count", 36),
        ("unique_process_instance_count", 36),
        ("unique_arm_count", 36),
        ("matched_start_complete_arms", 36),
    ):
        _equal(ledger.get(field), expected, f"legacy ledger {field}")
    ledger_sha = ledger.get("sha256")
    _require(isinstance(ledger_sha, str) and len(ledger_sha) == 64, "legacy ledger SHA256 invalid")
    ledger_path_declared = ledger.get("path")
    _require(isinstance(ledger_path_declared, str) and bool(ledger_path_declared), "legacy ledger path missing")
    ledger_path = _resolve_declared_file(ledger_path_declared, attestation_path)
    _equal(_file_sha(ledger_path), ledger_sha, "legacy ledger file SHA256")
    independently_audited_ledger = _audit_legacy_ledger(ledger_path)
    for field, actual in independently_audited_ledger.items():
        _equal(ledger.get(field), actual, f"legacy ledger attested {field}")

    artifacts_by_label: dict[str, tuple[Path, dict[str, Any]]] = {}
    records: list[dict[str, Any]] = []
    legacy_process_instances: set[tuple[str, int, int]] = set()
    scenario_by_label = {
        label: (map_id, agents, map_sha)
        for (map_id, agents), (label, map_sha) in EXPECTED_SCENARIOS.items()
    }
    for path in artifact_paths:
        artifact = _load_json(path)
        _equal(artifact.get("status"), "complete", f"{path}.status")
        _equal(artifact.get("fresh_process_per_arm"), True, f"{path}.fresh process flag")
        schema = artifact.get("schema")
        if schema == LEGACY_CURRENT_ARTIFACT_SCHEMA:
            _equal(
                artifact.get("evidence_class"),
                "engineering_compatibility_only_no_effect_inference",
                f"{path}.evidence class",
            )
            _equal(artifact.get("root_seed"), ROOT_SEED, f"{path}.root_seed")
            label = str(artifact.get("scenario"))
            _require(label in scenario_by_label, f"{path}.unexpected legacy scenario {label}")
            map_id, expected_agents, map_sha = scenario_by_label[label]
            agents = int(artifact.get("agents"))
            _equal(agents, expected_agents, f"{path}.agents")
            _equal(set(artifact.get("common_methods", ())), set(COMMON_ARMS), f"{path}.common methods")
            _equal(tuple(artifact.get("workloads", ())), tuple(WORKLOADS), f"{path}.workloads")
            _equal(artifact.get("common_arm_run_count"), 9, f"{path}.common-arm run count")
            _equal(artifact.get("environment_attestation_sha256"), environment_record["sha256"], f"{path}.environment digest")
            _equal(artifact.get("protocol_identity"), protocol, f"{path}.A1 protocol identity")
            run_protocol = artifact.get("run_protocol")
            _require(isinstance(run_protocol, dict), f"{path}.run_protocol missing")
            expected_run_protocol = {
                "warmup_time": 200,
                "scored_horizon": 2000,
                "decision_window": 20,
                "release_interval_per_agent": 110,
                "guard_suffix_tasks_per_agent": 4,
                "sigma": 0.75,
                "context_match_threshold": 0.05,
                "context_recall_margin": 0.02,
                "context_min_score": 0.10,
                "context_min_gap": 6,
                "context_maintenance_age": 25,
                "context_maintenance_stability": 0.20,
                "timing_evidence_valid": False,
            }
            _equal(run_protocol, expected_run_protocol, f"{path}.run protocol")
            _equal(artifact.get("map_sha256"), map_sha, f"{path}.map SHA256")
            runs = artifact.get("runs")
            _require(isinstance(runs, list), f"{path}.runs missing")
            _equal(len(runs), 9, f"{path}.run count")
            executions = artifact.get("arm_executions")
            _require(isinstance(executions, list), f"{path}.arm_executions missing")
            _equal(len(executions), 9, f"{path}.arm execution count")
            execution_cells: set[tuple[str, str]] = set()
            for index, execution in enumerate(executions):
                _require(isinstance(execution, dict), f"{path}.arm_executions[{index}] invalid")
                cell = (str(execution.get("workload")), str(execution.get("method")))
                _require(cell not in execution_cells, f"{path}.duplicate arm execution {cell}")
                execution_cells.add(cell)
                process = execution.get("execution")
                _require(isinstance(process, dict), f"{path}.arm_executions[{index}].execution missing")
                _equal(process.get("host"), smoke_result["current_host"], f"{path}.arm_executions[{index}].host")
                _require(isinstance(process.get("pid"), int) and process.get("pid") > 0, f"{path}.arm_executions[{index}].pid invalid")
                _require(isinstance(process.get("boot_id"), str) and bool(process.get("boot_id")), f"{path}.arm_executions[{index}].boot_id invalid")
                _require(
                    isinstance(process.get("process_start_ticks"), int)
                    and process.get("process_start_ticks") > 0,
                    f"{path}.arm_executions[{index}].process_start_ticks invalid",
                )
                process_instance = (
                    str(process["boot_id"]),
                    int(process["pid"]),
                    int(process["process_start_ticks"]),
                )
                _require(
                    process_instance not in legacy_process_instances,
                    f"legacy fresh process instance reused: {process_instance}",
                )
                legacy_process_instances.add(process_instance)
                command = execution.get("command_argv")
                _require(isinstance(command, list) and bool(command), f"{path}.arm_executions[{index}].command_argv missing")
                for role in ("raw_arm", "log", "spec"):
                    declared = execution.get(f"{role}_path")
                    sha = execution.get(f"{role}_sha256")
                    _require(isinstance(declared, str) and bool(declared), f"{path}.arm_executions[{index}].{role}_path missing")
                    _require(isinstance(sha, str) and len(sha) == 64, f"{path}.arm_executions[{index}].{role}_sha256 invalid")
                    bound_path = _resolve_declared_file(declared, path)
                    _equal(_file_sha(bound_path), sha, f"{path}.arm_executions[{index}].{role} SHA256")
            _equal(
                execution_cells,
                {(workload, method) for workload in WORKLOADS for method in COMMON_ARMS},
                f"{path}.arm execution cells",
            )
        elif schema == ARTIFACT_SCHEMA:
            _equal(tuple(artifact.get("seeds", ())), (ROOT_SEED,), f"{path}.seeds")
            agents = int(artifact.get("protocol", {}).get("agents"))
            scenario_key = (str(artifact.get("map_id")), agents)
            _require(scenario_key in EXPECTED_SCENARIOS, f"{path}.unexpected legacy scenario {scenario_key}")
            label, map_sha = EXPECTED_SCENARIOS[scenario_key]
            map_id = scenario_key[0]
            _equal(_source_header(artifact), _expected_source_header(map_sha), f"{path}.source header")
            _equal(
                artifact.get("development_matrix_config_sha256"),
                embedded_archive_sources["config"],
                f"{path}.config SHA256",
            )
            runs = artifact.get("runs")
            _require(isinstance(runs, list), f"{path}.runs missing")
        else:
            _fail(f"{path}.unsupported legacy artifact schema: {schema!r}")
        _require(label not in artifacts_by_label, f"duplicate current legacy scenario {label}")
        _equal(
            len({_run_key(run, agents) for run in runs}),
            len(runs),
            f"{path}.unique run identities",
        )
        selected = [
            run
            for run in runs
            if run.get("seed") == ROOT_SEED
            and run.get("map_id") == map_id
            and run.get("workload") in WORKLOADS
            and run.get("method") in COMMON_ARMS
        ]
        _equal(len(selected), 9, f"{path}.common-arm run count")
        for index, run in enumerate(selected):
            _audit_current_legacy_run(run, f"{path}.common_runs[{index}]")
        artifacts_by_label[label] = (path, artifact)
        records.append(_evidence_record(path, label=label))
    _equal(set(artifacts_by_label), {item[0] for item in EXPECTED_SCENARIOS.values()}, "legacy scenario set")
    _equal(len(legacy_process_instances), 36, "legacy independently verified process instances")

    attested_records = _attestation_artifact_records(attestation)
    attested_by_label: dict[str, Mapping[str, Any]] = {}
    for record in attested_records:
        label = str(record.get("label"))
        _require(label not in attested_by_label, f"duplicate attested artifact label {label}")
        attested_by_label[label] = record
    _equal(set(attested_by_label), set(artifacts_by_label), "legacy attestation artifact labels")
    for record in records:
        attested = attested_by_label[record["label"]]
        _equal(attested.get("sha256"), record["sha256"], f"legacy attested artifact {record['label']}.sha256")
        if attested.get("size_bytes") is not None:
            _equal(attested.get("size_bytes"), record["size_bytes"], f"legacy attested artifact {record['label']}.size")
        declared_path = attested.get("path")
        _require(isinstance(declared_path, str) and bool(declared_path), f"legacy attested artifact {record['label']}.path")
        _equal(Path(declared_path).name, Path(record["path"]).name, f"legacy attested artifact {record['label']}.basename")

    legacy_index: dict[tuple[str, int, str, str], Mapping[str, Any]] = {}
    for _, artifact in artifacts_by_label.values():
        agents = int(
            artifact.get("agents")
            if artifact.get("schema") == LEGACY_CURRENT_ARTIFACT_SCHEMA
            else artifact["protocol"]["agents"]
        )
        for run in artifact["runs"]:
            if run.get("seed") == ROOT_SEED and run.get("method") in COMMON_ARMS:
                key = _run_key(run, agents)
                _require(key not in legacy_index, f"duplicate current legacy run {key}")
                legacy_index[key] = run
    expected_keys = {
        (map_id, agents, workload, method)
        for map_id, agents in EXPECTED_SCENARIOS
        for workload in WORKLOADS
        for method in COMMON_ARMS
    }
    _equal(set(legacy_index), expected_keys, "current legacy common-arm matrix")
    comparisons = 0
    for key in sorted(expected_keys):
        _require(key in smoke_index, f"new smoke common arm missing: {key}")
        _equal(
            V1._legacy_projection(legacy_index[key]),
            V1._legacy_projection(smoke_index[key]),
            f"current-host legacy/new bitwise projection {key}",
        )
        comparisons += 1
    _equal(comparisons, 36, "current-host legacy/new comparisons")

    return (
        {
            "gate": True,
            "current_host": smoke_result["current_host"],
            "predecessor_protocol_sha256": smoke_result["protocol_sha256"],
            "amendment_a1_protocol_sha256": AMENDMENT_A1_PROTOCOL_SHA256,
            "artifacts": 4,
            "comparisons": comparisons,
            "projection": "complete_registered_legacy_projection",
            "comparison": "bitwise_equal",
            "excluded_nondeterministic_fields": sorted(V1.TIMING_KEYS | V1.EXECUTION_KEYS),
            "legacy_fresh_process_arms": 36,
            "legacy_attempt_ledger": {
                "path": str(ledger_path),
                "sha256": ledger_sha,
                "started_events": 36,
                "completed_events": 36,
                "unique_process_count": 36,
                "unique_process_instance_count": 36,
                "unique_arm_count": 36,
                "matched_start_complete_arms": 36,
            },
            "status": "pass",
        },
        {
            "artifacts": records,
            "attestation": _evidence_record(attestation_path),
            "environment_attestation": environment_record,
            "ledger": _evidence_record(ledger_path),
        },
    )


def run_audit(
    *,
    smoke_artifacts: Sequence[Path],
    archived_evidence: Path,
    legacy_current_artifacts: Sequence[Path],
    legacy_current_attestation: Path,
    environment_attestation: Path,
    repeat_a: Path,
    repeat_b: Path,
    future_suffix_base: Path,
    future_suffix_variant: Path,
    expected_archive_sha256: str | None = EVENTRESERVE_EVIDENCE_SHA256,
    expected_legacy_source_sha256: Mapping[str, str] | None = REGISTERED_LEGACY_SOURCE_SHA256,
) -> dict[str, Any]:
    smoke_result, smoke_index, smoke_protocols, smoke_evidence = audit_smoke_structure(smoke_artifacts)
    archive_result, embedded_sources, archive_evidence = audit_archive_inputs_and_diagnostic(
        archived_evidence,
        smoke_index,
        smoke_protocols,
        expected_archive_sha256=expected_archive_sha256,
        expected_source_sha256=expected_legacy_source_sha256,
    )
    legacy_result, legacy_evidence = audit_current_host_legacy_equivalence(
        legacy_current_artifacts,
        legacy_current_attestation,
        environment_attestation,
        smoke_index,
        smoke_result,
        embedded_sources,
        expected_source_sha256=expected_legacy_source_sha256,
    )
    repeat_result = V1.audit_repeats(repeat_a, repeat_b)
    suffix_result = V1.audit_future_suffix(future_suffix_base, future_suffix_variant)
    evidence_manifest = {
        "smoke": smoke_evidence,
        "archived": archive_evidence,
        "legacy_current": legacy_evidence,
        "repeat_a": _evidence_record(repeat_a),
        "repeat_b": _evidence_record(repeat_b),
        "future_suffix_base": _evidence_record(future_suffix_base),
        "future_suffix_variant": _evidence_record(future_suffix_variant),
    }
    return {
        "schema": SCHEMA,
        "passed": True,
        "status": "complete",
        "audit": {
            "smoke_matrix": smoke_result,
            "archived_cross_instance": archive_result,
            "current_host_legacy_new_equivalence": legacy_result,
            "repeatability": repeat_result,
            "future_suffix_nonanticipation": suffix_result,
            "effect_inference_performed": False,
            "archive_outputs_used_for_effect": False,
            "archive_outputs_used_for_gate": False,
            "claim_boundary": "engineering preflight only; no performance estimate or ranking",
        },
        "evidence_manifest": evidence_manifest,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-artifacts", nargs="+", type=Path, required=True)
    parser.add_argument("--archived-evidence", "--eventreserve-evidence", dest="archived_evidence", type=Path, required=True)
    parser.add_argument("--legacy-current-artifacts", nargs="+", type=Path, required=True)
    parser.add_argument("--legacy-current-attestation", type=Path, required=True)
    parser.add_argument("--environment-attestation", type=Path, required=True)
    parser.add_argument("--repeat-a", type=Path, required=True)
    parser.add_argument("--repeat-b", type=Path, required=True)
    parser.add_argument("--future-suffix-base", type=Path, required=True)
    parser.add_argument("--future-suffix-variant", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        smoke = resolve_four_artifacts(args.smoke_artifacts, "smoke")
        legacy = resolve_four_artifacts(args.legacy_current_artifacts, "legacy current")
        repeat_a = resolve_named_artifact(args.repeat_a, "repeat_a")
        repeat_b = resolve_named_artifact(args.repeat_b, "repeat_b")
        suffix_base = resolve_named_artifact(args.future_suffix_base, "future_suffix_base")
        suffix_variant = resolve_named_artifact(args.future_suffix_variant, "future_suffix_variant")
        result = run_audit(
            smoke_artifacts=smoke,
            archived_evidence=args.archived_evidence,
            legacy_current_artifacts=legacy,
            legacy_current_attestation=args.legacy_current_attestation,
            environment_attestation=args.environment_attestation,
            repeat_a=repeat_a,
            repeat_b=repeat_b,
            future_suffix_base=suffix_base,
            future_suffix_variant=suffix_variant,
        )
        exit_code = 0
    except (PreflightAuditError, V1.PreflightAuditError, OSError, KeyError, TypeError, ValueError) as exc:
        result = {
            "schema": SCHEMA,
            "passed": False,
            "status": "failed",
            "audit": {
                "error": str(exc),
                "effect_inference_performed": False,
                "archive_outputs_used_for_effect": False,
                "archive_outputs_used_for_gate": False,
                "claim_boundary": "engineering preflight only; no performance estimate or ranking",
            },
        }
        exit_code = 1
    payload = json.dumps(result, sort_keys=True, allow_nan=False)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
