#!/usr/bin/env python3
"""Structurally audit the same-call engineering preflight.

This program deliberately performs no treatment-effect calculation.  It checks
the four root-17 engineering artifacts, their append-only attempt ledgers, an
archived root-17 deterministic replay, two exact repeats, and a future-suffix
metamorphic pair.  The sole output is one machine-readable JSON object.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import tarfile
from typing import Any, Iterable, Mapping, Sequence
import uuid


SCHEMA = "dai.same-call-preflight-audit/v1"
ARTIFACT_SCHEMA = "dai.claim-aware-absolute-budget/v1"
ATTEMPT_SCHEMA = "dai.same-call-attempt-ledger/v1"
EVENTRESERVE_EVIDENCE_SHA256 = (
    "dedf2a8d840c27ff9482d626476c2bd14b3001e23196663225e579b484020c22"
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
ROOT_SEED = 17
WORKLOADS = ("stationary", "abrupt", "recurrent")
METHODS = (
    "bootstrap_only",
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
    "context_no_reactivation_B25",
    "context_memory_B25",
    "exact_even_B25",
)
COMMON_ARMS = (
    "bootstrap_only",
    "context_memory_B25",
    "exact_even_B25",
)
REPLAY_ARMS = ("context_memory_B25", "exact_even_B25")
EXPECTED_SCENARIOS = {
    ("warehouse_small_narrow_kiva", 218): (
        "narrow_r020",
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
    ),
    ("warehouse_small_narrow_kiva", 382): (
        "narrow_r035",
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
    ),
    ("warehouse_small_kiva", 255): (
        "regular_r020",
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
    ),
    ("warehouse_small_kiva", 447): (
        "regular_r035",
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
    ),
}
EXACT_SCHEDULES = {
    "bootstrap_only": [],
    "exact_even_G4": [25, 50, 75, 99],
    "exact_even_G5": [20, 40, 60, 80, 99],
    "exact_even_B25": [
        4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52,
        56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 96, 99,
    ],
}
TIMING_KEYS = {
    "elapsed_seconds",
    "generator_seconds",
    "simulator_seconds",
    "planner_seconds",
    "timing_evidence_valid",
}
EXECUTION_KEYS = {
    "execution_process_id",
    "execution_parent_process_id",
    "execution_host",
    "execution_process_start_ns",
    "run_uuid",
}


class PreflightAuditError(ValueError):
    """Raised when a structural or deterministic preflight condition fails."""


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


def _strict_sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightAuditError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"expected JSON object: {path}")
    return value


def _looks_like_artifact(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value.get("schema") == ARTIFACT_SCHEMA


def resolve_smoke_artifacts(paths: Sequence[Path]) -> list[Path]:
    """Resolve either four artifact files or directories containing them."""

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
        else:
            _fail(f"smoke artifact path does not exist: {path}")
    unique = list(dict.fromkeys(found))
    _equal(len(unique), 4, "number of smoke artifacts")
    return unique


def resolve_named_artifact(path: Path, label: str) -> Path:
    path = path.resolve()
    if path.is_file():
        return path
    if path.is_dir():
        named = path / f"{label}.json"
        if named.is_file():
            return named
    _fail(f"cannot resolve {label} artifact from {path}")
    raise AssertionError("unreachable")


def _cell_key(run: Mapping[str, Any], agents: int) -> tuple[str, int, str]:
    return (str(run.get("map_id")), int(agents), str(run.get("workload")))


def _run_key(run: Mapping[str, Any], agents: int) -> tuple[str, int, str, str]:
    return (*_cell_key(run, agents), str(run.get("method")))


def _actual_switch_indices(run: Mapping[str, Any]) -> list[int]:
    timeline = run.get("publication_timeline")
    _require(isinstance(timeline, list), "publication_timeline must be a list")
    return [
        int(entry["decision_index"])
        for entry in timeline[1:]
        if entry.get("executed_operation") in {"generate", "reactivate"}
    ]


def _actual_generation_indices(run: Mapping[str, Any]) -> list[int]:
    return [
        int(entry["decision_index"])
        for entry in run["publication_timeline"][1:]
        if entry.get("executed_operation") == "generate"
    ]


def _audit_integrity_and_budget(run: Mapping[str, Any], context: str) -> None:
    _equal(run.get("seed"), ROOT_SEED, f"{context}.seed")
    _equal(run.get("root_seed"), ROOT_SEED, f"{context}.root_seed")
    _equal(run.get("scored_horizon"), 2000, f"{context}.scored_horizon")
    _equal(run.get("decision_window"), 20, f"{context}.decision_window")
    _equal(run.get("window_count"), 100, f"{context}.window_count")
    safety = run.get("safety")
    _require(isinstance(safety, dict), f"{context}.safety must be an object")
    _equal(safety.get("passed"), True, f"{context}.safety.passed")
    for field in (
        "collision_count", "edge_swap_count", "endpoint_mismatch_count",
        "invalid_move_count", "planner_timeout_count", "route_trace_invalid_count",
    ):
        _equal(safety.get(field), 0, f"{context}.safety.{field}")
    for field in ("collisions", "edge_swaps", "invalid_moves", "planner_timeouts"):
        _equal(run.get(field), 0, f"{context}.{field}")
    invariants = run.get("invariants")
    _require(isinstance(invariants, dict), f"{context}.invariants must be an object")
    _equal(invariants.get("passed"), True, f"{context}.invariants.passed")
    _equal(invariants.get("online_workload_rng_draws"), 0, f"{context}.online RNG")
    _equal(invariants.get("tape_not_exhausted"), True, f"{context}.tape sentinel")
    _equal(
        invariants.get("reward_sum_matches_completed"),
        True,
        f"{context}.reward conservation",
    )

    timeline = run.get("publication_timeline")
    windows = run.get("windows")
    _require(isinstance(timeline, list), f"{context}.timeline must be a list")
    _require(isinstance(windows, list), f"{context}.windows must be a list")
    _equal(len(timeline), 100, f"{context}.timeline length")
    _equal(len(windows), 100, f"{context}.window length")
    _equal([entry.get("decision_index") for entry in timeline], list(range(100)), f"{context}.timeline indices")
    _equal([window.get("decision_index") for window in windows], list(range(100)), f"{context}.window indices")
    bootstrap = timeline[0]
    _equal(bootstrap.get("executed_operation"), "bootstrap_generate", f"{context}.bootstrap operation")
    _equal(bootstrap.get("accepted"), True, f"{context}.bootstrap accepted")

    method = str(run.get("method"))
    switches = _actual_switch_indices(run)
    generations = _actual_generation_indices(run)
    reactivations = [
        int(entry["decision_index"])
        for entry in timeline[1:]
        if entry.get("executed_operation") == "reactivate"
    ]
    _equal(len(switches), run.get("post_bootstrap_publication_count"), f"{context}.switch count")
    _equal(len(generations), run.get("post_bootstrap_generation_count"), f"{context}.generation count")
    _equal(len(reactivations), run.get("post_bootstrap_reactivation_count"), f"{context}.reactivation count")
    _equal(len(switches), run.get("effective_guidance_switch_count"), f"{context}.effective switches")
    _equal(run.get("generator_calls"), 1 + len(generations), f"{context}.generator conservation")
    for index in range(1, 100):
        operation = timeline[index].get("executed_operation")
        _require(operation in {"hold", "generate", "reactivate"}, f"{context}.unknown operation at {index}")
        _equal(
            bool(windows[index].get("guidance_switched_post_bootstrap")),
            operation in {"generate", "reactivate"},
            f"{context}.window/timeline switch at {index}",
        )
        _equal(windows[index].get("guidance_operation"), operation, f"{context}.window operation at {index}")

    budget = run.get("budget")
    _require(isinstance(budget, dict), f"{context}.budget must be an object")
    for field in (
        "cap_satisfied", "switch_cap_satisfied", "generation_cap_satisfied",
        "total_generator_call_cap_satisfied", "generator_call_conservation_satisfied",
        "switch_operation_partition_satisfied", "generation_cap_binding_audit_satisfied",
        "eventreserve_audit_conservation_satisfied",
    ):
        _equal(budget.get(field), True, f"{context}.budget.{field}")
    _equal(budget.get("budget_violation_attempts"), 0, f"{context}.budget violations")
    _equal(run.get("budget_violation_count"), 0, f"{context}.run budget violations")
    _equal(budget.get("total_generator_calls"), run.get("generator_calls"), f"{context}.budget calls")
    _equal(budget.get("post_bootstrap_publication_count"), len(switches), f"{context}.budget switches")
    _equal(budget.get("post_bootstrap_generation_count"), len(generations), f"{context}.budget generations")
    _equal(budget.get("post_bootstrap_reactivation_count"), len(reactivations), f"{context}.budget reactivations")

    if method in EXACT_SCHEDULES:
        _equal(switches, EXACT_SCHEDULES[method], f"{context}.exact schedule")
        _equal(budget.get("exact_quota_required"), True, f"{context}.exact required")
        _equal(budget.get("exact_quota_satisfied"), True, f"{context}.exact satisfied")
    elif method == "random_G5":
        _equal(len(switches), 5, f"{context}.random quota")
        _equal(generations, switches, f"{context}.random generations")
        _equal(budget.get("exact_quota_required"), True, f"{context}.random exact required")
        _equal(budget.get("exact_quota_satisfied"), True, f"{context}.random exact satisfied")
    elif method == "js_cap_G5":
        _require(len(switches) <= 5, f"{context}.js_cap_G5 exceeded five switches")
        _equal(generations, switches, f"{context}.js generations")
    elif method == "context_no_reactivation_B25":
        _require(len(switches) <= 25, f"{context}.no-reactivation exceeded B25")
        _equal(reactivations, [], f"{context}.forbidden reactivations")
        _equal(generations, switches, f"{context}.no-reactivation generations")
    elif method == "context_memory_B25":
        _require(len(switches) <= 25, f"{context}.context exceeded B25")
    else:
        _fail(f"{context}.unexpected method {method}")
    precommitted = run.get("precommitted_post_bootstrap_schedule")
    if method in EXACT_SCHEDULES or method == "random_G5":
        _equal(precommitted, switches, f"{context}.precommitted schedule")
    else:
        _equal(precommitted, None, f"{context}.non-precommitted schedule")


def _audit_execution_metadata(
    artifact: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    context: str,
) -> tuple[set[tuple[str, int, int]], set[str]]:
    _equal(artifact.get("fresh_process_per_arm"), True, f"{context}.fresh process flag")
    _equal(
        artifact.get("protocol", {}).get("fresh_os_process_per_arm"),
        True,
        f"{context}.protocol fresh process flag",
    )
    declared_host = artifact.get("runtime_manifest", {}).get("environment", {}).get("host")
    triples: set[tuple[str, int, int]] = set()
    uuids: set[str] = set()
    pids: set[int] = set()
    for index, run in enumerate(runs):
        prefix = f"{context}.runs[{index}]"
        host = run.get("execution_host")
        pid = run.get("execution_process_id")
        started = run.get("execution_process_start_ns")
        token = run.get("run_uuid")
        _require(isinstance(host, str) and bool(host), f"{prefix}.execution_host missing")
        if declared_host is not None:
            _equal(host, declared_host, f"{prefix}.execution_host")
        _require(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0, f"{prefix}.pid invalid")
        _require(isinstance(started, int) and not isinstance(started, bool) and started > 0, f"{prefix}.start invalid")
        try:
            parsed = uuid.UUID(str(token))
        except (ValueError, TypeError, AttributeError) as exc:
            raise PreflightAuditError(f"{prefix}.run_uuid invalid") from exc
        _equal(parsed.version, 4, f"{prefix}.run_uuid version")
        triple = (host, pid, started)
        _require(triple not in triples, f"{context}.fresh process tuple reused: {triple}")
        _require(str(token) not in uuids, f"{context}.run_uuid reused: {token}")
        _require(pid not in pids, f"{context}.execution pid reused: {pid}")
        triples.add(triple)
        uuids.add(str(token))
        pids.add(pid)
    return triples, uuids


def _ledger_path(artifact_path: Path, artifact: Mapping[str, Any]) -> Path:
    record = artifact.get("attempt_ledger")
    _require(isinstance(record, dict), f"{artifact_path}.attempt_ledger missing")
    declared = Path(str(record.get("path", "")))
    candidates = [declared, artifact_path.with_suffix(".attempts.jsonl")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    _fail(f"cannot locate attempt ledger for {artifact_path}")
    raise AssertionError("unreachable")


def _attempt_identity(run: Mapping[str, Any], agents: int) -> dict[str, Any]:
    return {
        "split": str(run["split"]),
        "map_id": str(run["map_id"]),
        "agents": int(agents),
        "seed": int(run["seed"]),
        "workload": str(run["workload"]),
        "method": str(run["method"]),
    }


def audit_attempt_ledger(
    artifact_path: Path,
    artifact: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ledger_path = _ledger_path(artifact_path, artifact)
    record = artifact["attempt_ledger"]
    _equal(record.get("schema"), ATTEMPT_SCHEMA, f"{artifact_path}.ledger schema")
    _equal(record.get("started_events"), len(runs), f"{artifact_path}.ledger starts")
    _equal(record.get("completed_events"), len(runs), f"{artifact_path}.ledger completions")
    _equal(record.get("sha256"), _file_sha(ledger_path), f"{artifact_path}.ledger sha256")
    try:
        events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightAuditError(f"invalid attempt ledger {ledger_path}: {exc}") from exc
    _equal(len(events), 2 * len(runs), f"{artifact_path}.ledger event count")
    agents = int(artifact.get("protocol", {}).get("agents"))
    expected = {_strict_sha(_attempt_identity(run, agents)): run for run in runs}
    grouped: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    for line_number, event in enumerate(events, 1):
        _require(isinstance(event, dict), f"{ledger_path}:{line_number} must be an object")
        _equal(event.get("schema"), ATTEMPT_SCHEMA, f"{ledger_path}:{line_number}.schema")
        attempt_id = event.get("attempt_id")
        _require(attempt_id in expected, f"{ledger_path}:{line_number}.unknown attempt")
        _equal(event.get("identity"), _attempt_identity(expected[attempt_id], agents), f"{ledger_path}:{line_number}.identity")
        _require(event.get("event") in {"started", "completed"}, f"{ledger_path}:{line_number}.event invalid")
        grouped[str(attempt_id)].append((line_number, event))
    _equal(set(grouped), set(expected), f"{ledger_path}.attempt set")
    for attempt_id, run in expected.items():
        pair = grouped[attempt_id]
        _equal(len(pair), 2, f"{ledger_path}.{attempt_id}.event multiplicity")
        _equal([event["event"] for _, event in pair], ["started", "completed"], f"{ledger_path}.{attempt_id}.event order")
        completed = pair[1][1]
        _equal(completed.get("run_sha256"), _strict_sha(run), f"{ledger_path}.{attempt_id}.run sha")
        for field in ("execution_process_id", "execution_host", "execution_process_start_ns", "run_uuid"):
            _equal(completed.get(field), run.get(field), f"{ledger_path}.{attempt_id}.{field}")
        _equal(completed.get("planner_timeouts"), 0, f"{ledger_path}.{attempt_id}.timeouts")
        _equal(completed.get("safety_passed"), True, f"{ledger_path}.{attempt_id}.safety")
        _equal(completed.get("invariants_passed"), True, f"{ledger_path}.{attempt_id}.invariants")
    return {"events": len(events), "attempts": len(runs), "sha256": record["sha256"]}


def _audit_pairing(runs: Sequence[Mapping[str, Any]], methods: Iterable[str], context: str) -> None:
    expected_methods = set(methods)
    _equal({str(run.get("method")) for run in runs}, expected_methods, f"{context}.method set")
    string_fields = (
        "manifest_id", "reset_causal_fingerprint",
        "release_projection_fingerprint", "distribution_update_fingerprint",
    )
    for run_index, run in enumerate(runs):
        for field in string_fields:
            value = run.get(field)
            _require(
                isinstance(value, str) and bool(value),
                f"{context}.runs[{run_index}].{field} must be a non-empty string",
            )
        identity = run.get("task_tape_identity")
        _require(
            isinstance(identity, dict) and bool(identity),
            f"{context}.runs[{run_index}].task_tape_identity must be a non-empty object",
        )
        for field in ("mode", "schema_version", "manifest_sha256", "content_fnv1a64"):
            value = identity.get(field)
            _require(
                isinstance(value, str) and bool(value),
                f"{context}.runs[{run_index}].task_tape_identity.{field} must be a non-empty string",
            )
        starts = identity.get("start_locations")
        lengths = identity.get("per_agent_lengths")
        total = identity.get("total_tasks")
        _require(
            isinstance(starts, list) and bool(starts),
            f"{context}.runs[{run_index}].task_tape_identity.start_locations must be a non-empty list",
        )
        _require(
            isinstance(lengths, list) and bool(lengths),
            f"{context}.runs[{run_index}].task_tape_identity.per_agent_lengths must be a non-empty list",
        )
        _equal(
            len(starts),
            len(lengths),
            f"{context}.runs[{run_index}].task tape agent dimensions",
        )
        _require(
            all(isinstance(value, int) and not isinstance(value, bool) for value in starts),
            f"{context}.runs[{run_index}].task tape starts must be integers",
        )
        _require(
            all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in lengths
            ),
            f"{context}.runs[{run_index}].task tape lengths must be positive integers",
        )
        _require(
            isinstance(total, int) and not isinstance(total, bool) and total > 0,
            f"{context}.runs[{run_index}].task tape total must be a positive integer",
        )
        _equal(sum(lengths), total, f"{context}.runs[{run_index}].task tape total")
    for field in (*string_fields, "task_tape_identity"):
        values = {_canonical(run.get(field)) for run in runs}
        _equal(len(values), 1, f"{context}.paired {field}")


def _audit_artifact_header(
    path: Path,
    artifact: Mapping[str, Any],
    *,
    methods: Sequence[str],
    workloads: Sequence[str],
    expected_runs: int,
) -> list[dict[str, Any]]:
    _equal(artifact.get("schema"), ARTIFACT_SCHEMA, f"{path}.schema")
    _equal(artifact.get("status"), "complete", f"{path}.status")
    _equal(artifact.get("split"), "development", f"{path}.split")
    _equal(artifact.get("evidence_class"), "development", f"{path}.evidence_class")
    _equal(tuple(artifact.get("seeds", ())), (ROOT_SEED,), f"{path}.seeds")
    _equal(tuple(artifact.get("methods", ())), tuple(methods), f"{path}.methods")
    _equal(tuple(artifact.get("workloads", ())), tuple(workloads), f"{path}.workloads")
    _equal(artifact.get("period_on_sim_sha256"), SIMULATOR_SHA256, f"{path}.simulator")
    generator = artifact.get("generator", {})
    _equal(generator.get("file_sha256"), CHECKPOINT_SHA256, f"{path}.checkpoint")
    _equal(generator.get("params_sha256"), CHECKPOINT_PARAMS_SHA256, f"{path}.checkpoint params")
    protocol = artifact.get("protocol", {})
    expected_protocol = {
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "num_scored_windows": 100,
        "eligible_post_bootstrap_decisions": 99,
        "b25_budget": 25,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "sigma": 0.75,
        "exclusive_timing_declared": False,
        "timing_evidence_valid": False,
    }
    for field, expected in expected_protocol.items():
        _equal(protocol.get(field), expected, f"{path}.protocol.{field}")
    runs = artifact.get("runs")
    _require(isinstance(runs, list), f"{path}.runs must be a list")
    _equal(len(runs), expected_runs, f"{path}.run count")
    _equal(
        len({_run_key(run, int(protocol["agents"])) for run in runs}),
        expected_runs,
        f"{path}.unique run identities",
    )
    for index, run in enumerate(runs):
        _equal(run.get("split"), "development", f"{path}.runs[{index}].split")
        _equal(run.get("evidence_class"), "development", f"{path}.runs[{index}].evidence")
        _audit_integrity_and_budget(run, f"{path.name}.runs[{index}]")
    return runs


def _without_nondeterminism(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_nondeterminism(item)
            for key, item in value.items()
            if key not in TIMING_KEYS and key not in EXECUTION_KEYS
        }
    if isinstance(value, list):
        return [_without_nondeterminism(item) for item in value]
    return value


def _legacy_projection(run: Mapping[str, Any]) -> dict[str, Any]:
    """Project exactly the deterministic fields promised by the replay audit."""

    fields = (
        "method", "seed", "root_seed", "split", "evidence_class", "map_id",
        "workload", "manifest_id", "num_task_finished", "throughput_per_timestep",
        "scored_horizon", "decision_window", "window_count",
        "mandatory_bootstrap_calls", "post_bootstrap_publication_count",
        "post_bootstrap_generation_count", "post_bootstrap_reactivation_count",
        "effective_guidance_switch_count", "publication_budget",
        "budget_violation_count", "budget", "safety", "collisions", "edge_swaps",
        "invalid_moves", "planner_timeouts", "task_tape_identity",
        "final_task_tape_prefixes", "reset_causal_fingerprint",
        "release_projection_fingerprint", "distribution_update_fingerprint",
        "publication_timeline", "guidance_catalog", "windows", "workload_arrival",
        "generator_calls", "invariants",
    )
    return _without_nondeterminism({field: run.get(field) for field in fields})


def _repeat_projection(run: Mapping[str, Any]) -> dict[str, Any]:
    return _without_nondeterminism(dict(run))


def _load_eventreserve_artifacts(
    archive_path: Path,
    *,
    expected_sha256: str | None = EVENTRESERVE_EVIDENCE_SHA256,
) -> tuple[list[dict[str, Any]], str]:
    archive_path = archive_path.resolve()
    actual_sha = _file_sha(archive_path)
    if expected_sha256 is not None:
        _equal(actual_sha, expected_sha256, "eventreserve evidence SHA256")
    artifacts: list[dict[str, Any]] = []
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
            _equal(len(members), 4, "eventreserve scenario artifact count")
            for member in sorted(members, key=lambda item: item.name):
                stream = archive.extractfile(member)
                _require(stream is not None, f"cannot read archive member {member.name}")
                value = json.loads(stream.read().decode("utf-8"))
                _require(isinstance(value, dict), f"archive member is not an object: {member.name}")
                artifacts.append(value)
    except (OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise PreflightAuditError(f"cannot read eventreserve evidence {archive_path}: {exc}") from exc
    return artifacts, actual_sha


def audit_smoke(
    artifact_paths: Sequence[Path],
    eventreserve_evidence: Path,
    *,
    expected_evidence_sha256: str | None = EVENTRESERVE_EVIDENCE_SHA256,
) -> tuple[dict[str, Any], dict[tuple[str, int, str, str], Mapping[str, Any]]]:
    smoke_index: dict[tuple[str, int, str, str], Mapping[str, Any]] = {}
    scenario_labels: set[str] = set()
    all_triples: set[tuple[str, int, int]] = set()
    all_uuids: set[str] = set()
    ledger_events = 0
    random_schedules: list[list[int]] = []
    for path in artifact_paths:
        artifact = _load_json(path)
        runs = _audit_artifact_header(
            path,
            artifact,
            methods=METHODS,
            workloads=WORKLOADS,
            expected_runs=24,
        )
        agents = int(artifact["protocol"]["agents"])
        scenario_key = (str(artifact.get("map_id")), agents)
        _require(scenario_key in EXPECTED_SCENARIOS, f"{path}.unexpected smoke scenario {scenario_key}")
        label, map_sha = EXPECTED_SCENARIOS[scenario_key]
        _require(label not in scenario_labels, f"duplicate smoke scenario {label}")
        scenario_labels.add(label)
        _equal(artifact.get("map_sha256"), map_sha, f"{path}.map SHA256")
        triples, uuids = _audit_execution_metadata(artifact, runs, str(path))
        _require(all_triples.isdisjoint(triples), "fresh process tuple reused across smoke artifacts")
        _require(all_uuids.isdisjoint(uuids), "run UUID reused across smoke artifacts")
        all_triples.update(triples)
        all_uuids.update(uuids)
        ledger_events += audit_attempt_ledger(path, artifact, runs)["events"]
        for workload in WORKLOADS:
            cell_runs = [run for run in runs if run.get("workload") == workload]
            _equal(len(cell_runs), 8, f"{path}.{workload}.arm count")
            _audit_pairing(cell_runs, METHODS, f"{path}.{workload}")
        for run in runs:
            key = _run_key(run, agents)
            _require(key not in smoke_index, f"duplicate smoke run {key}")
            smoke_index[key] = run
            if run.get("method") == "random_G5":
                random_schedules.append(_actual_switch_indices(run))
    _equal(scenario_labels, {value[0] for value in EXPECTED_SCENARIOS.values()}, "smoke scenario set")
    _equal(len(smoke_index), 96, "smoke matrix size")
    _equal(len(random_schedules), 12, "random_G5 cell count")
    _equal(len({_canonical(schedule) for schedule in random_schedules}), 1, "random_G5 schedule across 12 cells")

    old_artifacts, evidence_sha = _load_eventreserve_artifacts(
        eventreserve_evidence,
        expected_sha256=expected_evidence_sha256,
    )
    old_index: dict[tuple[str, int, str, str], Mapping[str, Any]] = {}
    for artifact in old_artifacts:
        _equal(artifact.get("schema"), ARTIFACT_SCHEMA, "eventreserve artifact schema")
        _equal(artifact.get("status"), "complete", "eventreserve artifact status")
        agents = int(artifact.get("protocol", {}).get("agents"))
        scenario_key = (str(artifact.get("map_id")), agents)
        _require(scenario_key in EXPECTED_SCENARIOS, f"unexpected eventreserve scenario {scenario_key}")
        for run in artifact.get("runs", ()):
            if run.get("seed") == ROOT_SEED and run.get("method") in COMMON_ARMS:
                key = _run_key(run, agents)
                _require(key not in old_index, f"duplicate archived root-17 run {key}")
                old_index[key] = run
    expected_common_keys = {
        (map_id, agents, workload, method)
        for map_id, agents in EXPECTED_SCENARIOS
        for workload in WORKLOADS
        for method in COMMON_ARMS
    }
    _equal(set(old_index), expected_common_keys, "archived root-17 common-arm matrix")
    comparisons = 0
    for key in sorted(expected_common_keys):
        _require(key in smoke_index, f"smoke common arm missing: {key}")
        _equal(
            _legacy_projection(smoke_index[key]),
            _legacy_projection(old_index[key]),
            f"archived deterministic replay {key}",
        )
        comparisons += 1
    return {
        "artifacts": 4,
        "runs": 96,
        "cells": 12,
        "methods": 8,
        "root_seed": ROOT_SEED,
        "fresh_process_arms": 96,
        "attempt_ledger_events": ledger_events,
        "paired_fingerprints": "pass",
        "budget_schedule_safety": "pass",
        "random_G5_schedule": random_schedules[0],
        "random_G5_schedule_equal_across_cells": True,
        "archived_common_arm_comparisons": comparisons,
        "archived_eventreserve_sha256": evidence_sha,
        "archived_deterministic_replay": "bitwise_equal_on_registered_semantics",
    }, smoke_index


def _audit_replay_artifact(path: Path, label: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    artifact = _load_json(path)
    runs = _audit_artifact_header(
        path,
        artifact,
        methods=REPLAY_ARMS,
        workloads=("stationary",),
        expected_runs=2,
    )
    _equal(artifact.get("map_id"), "warehouse_small_narrow_kiva", f"{label}.map")
    _equal(artifact.get("protocol", {}).get("agents"), 218, f"{label}.agents")
    _audit_pairing(runs, REPLAY_ARMS, label)
    _audit_execution_metadata(artifact, runs, label)
    audit_attempt_ledger(path, artifact, runs)
    return artifact, runs


def audit_repeats(repeat_a_path: Path, repeat_b_path: Path) -> dict[str, Any]:
    _, runs_a = _audit_replay_artifact(repeat_a_path, "repeat_a")
    _, runs_b = _audit_replay_artifact(repeat_b_path, "repeat_b")
    index_a = {run["method"]: run for run in runs_a}
    index_b = {run["method"]: run for run in runs_b}
    for method in REPLAY_ARMS:
        execution_a = tuple(index_a[method].get(field) for field in EXECUTION_KEYS)
        execution_b = tuple(index_b[method].get(field) for field in EXECUTION_KEYS)
        _require(
            execution_a != execution_b,
            f"repeatability.{method} reused execution identity",
        )
        _equal(
            _repeat_projection(index_a[method]),
            _repeat_projection(index_b[method]),
            f"repeatability.{method}",
        )
    return {
        "artifacts": 2,
        "arms_compared": 2,
        "comparison": "bitwise_equal_excluding_execution_and_timing",
    }


def _timeline_before(run: Mapping[str, Any], cutoff: int) -> list[Any]:
    return [
        _without_nondeterminism(entry)
        for entry in run["publication_timeline"]
        if int(entry.get("absolute_timestep", cutoff)) < cutoff
    ]


def _windows_before(run: Mapping[str, Any], cutoff: int) -> list[Any]:
    return [
        _without_nondeterminism(window)
        for window in run["windows"]
        if int(window.get("window_end_timestep", cutoff + 1)) <= cutoff
    ]


def audit_future_suffix(base_path: Path, variant_path: Path, *, cutoff: int = 1400) -> dict[str, Any]:
    base_artifact, base_runs = _audit_replay_artifact(base_path, "future_suffix_base")
    variant_artifact, variant_runs = _audit_replay_artifact(variant_path, "future_suffix_variant")
    _equal(base_artifact["protocol"].get("future_suffix_variant"), 0, "base suffix variant")
    _equal(variant_artifact["protocol"].get("future_suffix_variant"), 1, "variant suffix variant")
    _equal(base_artifact["protocol"].get("future_suffix_cutoff_absolute"), cutoff, "base suffix cutoff")
    _equal(variant_artifact["protocol"].get("future_suffix_cutoff_absolute"), cutoff, "variant suffix cutoff")
    base_index = {run["method"]: run for run in base_runs}
    variant_index = {run["method"]: run for run in variant_runs}
    decision_count = None
    window_count = None
    for method in REPLAY_ARMS:
        base = base_index[method]
        variant = variant_index[method]
        base_identity = base["task_tape_identity"]
        variant_identity = variant["task_tape_identity"]
        for field in ("mode", "schema_version", "start_locations", "per_agent_lengths", "total_tasks"):
            _equal(base_identity.get(field), variant_identity.get(field), f"suffix.{method}.tape shape {field}")
        for hash_field in ("manifest_sha256", "content_fnv1a64"):
            _require(
                base_identity.get(hash_field) != variant_identity.get(hash_field),
                f"suffix.{method}.complete tape {hash_field} did not change",
            )
        base_decisions = _timeline_before(base, cutoff)
        variant_decisions = _timeline_before(variant, cutoff)
        base_windows = _windows_before(base, cutoff)
        variant_windows = _windows_before(variant, cutoff)
        _equal(base_decisions, variant_decisions, f"suffix.{method}.pre-cutoff controller decisions")
        _equal(base_windows, variant_windows, f"suffix.{method}.pre-cutoff windows")
        _equal(base.get("distribution_update_fingerprint"), variant.get("distribution_update_fingerprint"), f"suffix.{method}.distribution updates")
        decision_count = len(base_decisions) if decision_count is None else decision_count
        window_count = len(base_windows) if window_count is None else window_count
        _equal(len(base_decisions), decision_count, f"suffix.{method}.decision count")
        _equal(len(base_windows), window_count, f"suffix.{method}.window count")
    return {
        "artifacts": 2,
        "arms_compared": 2,
        "cutoff_absolute": cutoff,
        "strictly_pre_cutoff_decisions_per_arm": decision_count,
        "strictly_pre_cutoff_windows_per_arm": window_count,
        "controller_policy_reward_guidance_release_trace": "bitwise_equal",
        "complete_tape_hashes_differ": True,
    }


def run_audit(
    *,
    smoke_artifacts: Sequence[Path],
    eventreserve_evidence: Path,
    repeat_a: Path,
    repeat_b: Path,
    future_suffix_base: Path,
    future_suffix_variant: Path,
    expected_evidence_sha256: str | None = EVENTRESERVE_EVIDENCE_SHA256,
) -> dict[str, Any]:
    smoke_result, _ = audit_smoke(
        smoke_artifacts,
        eventreserve_evidence,
        expected_evidence_sha256=expected_evidence_sha256,
    )
    repeat_result = audit_repeats(repeat_a, repeat_b)
    suffix_result = audit_future_suffix(future_suffix_base, future_suffix_variant)
    return {
        "schema": SCHEMA,
        "passed": True,
        "status": "complete",
        "audit": {
            "smoke_matrix": smoke_result,
            "repeatability": repeat_result,
            "future_suffix_nonanticipation": suffix_result,
            "effect_inference_performed": False,
            "claim_boundary": "engineering preflight only; no performance estimate or ranking",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke-artifacts",
        nargs="+",
        type=Path,
        required=True,
        help="four artifact JSON files, or a directory containing exactly four",
    )
    parser.add_argument("--eventreserve-evidence", "--eventreserve-tgz", dest="eventreserve_evidence", type=Path, required=True)
    parser.add_argument("--repeat-a", type=Path, required=True)
    parser.add_argument("--repeat-b", type=Path, required=True)
    parser.add_argument("--future-suffix-base", type=Path, required=True)
    parser.add_argument("--future-suffix-variant", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        smoke = resolve_smoke_artifacts(args.smoke_artifacts)
        result = run_audit(
            smoke_artifacts=smoke,
            eventreserve_evidence=args.eventreserve_evidence,
            repeat_a=resolve_named_artifact(args.repeat_a, "repeat_a"),
            repeat_b=resolve_named_artifact(args.repeat_b, "repeat_b"),
            future_suffix_base=resolve_named_artifact(args.future_suffix_base, "future_suffix_base"),
            future_suffix_variant=resolve_named_artifact(args.future_suffix_variant, "future_suffix_variant"),
        )
        exit_code = 0
    except (PreflightAuditError, OSError, KeyError, TypeError, ValueError) as exc:
        result = {
            "schema": SCHEMA,
            "passed": False,
            "status": "failed",
            "audit": {
                "error": str(exc),
                "effect_inference_performed": False,
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
