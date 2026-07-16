#!/usr/bin/env python3
"""Seal the effect-blind A2 freeze, reused preflight, and final config.

The sealer deliberately reads only control-plane/provenance documents.  It
never opens any A1 result, CSV, attempt-ledger, driver-log, or outcome report.
All three outputs are prepared only after every gate passes and are written
with exclusive-create semantics.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


A2_PROTOCOL_SHA256 = "c1caaf9532ac728b19761d0eab60628d8e32e4d3a101512b51fa0a5abeebf9dd"
A1_FAILURE_SHA256 = "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
A1_FREEZE_SHA256 = "fef9b1ebaed8511fc7e97ee8852834ffa42e6d09b3bff5f54f6b1c3113938a87"
A1_CONFIG_SHA256 = "272a98ebf7feefd2cf3300fefc20c789e8893bf23c05ba898741a4ec89eba004"
A1_PROTOCOL_SHA256 = "10f17682a9dc32f33fad2c77289e8c9dff659325de655b584f1d138066f05fdf"

A1_ROOTS = (
    767369, 695428, 323681, 904171, 446020,
    434435, 488565, 514527, 544573, 838809,
)
A2_ROOTS = (
    691817, 376110, 263001, 293231, 296805,
    274330, 997942, 319782, 807287, 326454,
)
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
WORKLOADS = ("stationary", "abrupt", "recurrent")
BEHAVIOR_KEYS = frozenset(
    {
        "claim_runner",
        "validation_runner",
        "publication_policy",
        "frozen_cnn_generator",
        "online_ggo_adapter",
        "trafficflow_online_env",
        "task_generator",
    }
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object: {path}")
    return value


def _resolve(workspace: Path, value: Path | str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def _display_path(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _require_sha(value: str, label: str) -> str:
    if not SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _require_file_sha(path: Path, expected: str, label: str) -> str:
    _require_sha(expected, f"{label} expected digest")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is absent: {path}")
    actual = _sha256(path)
    if actual != expected:
        raise RuntimeError(
            f"{label} SHA-256 mismatch: expected={expected} actual={actual} path={path}"
        )
    return actual


def _passed(payload: Mapping[str, Any]) -> bool:
    audit = payload.get("audit")
    return bool(
        payload.get("passed") is True
        and not (isinstance(audit, Mapping) and audit.get("passed") is False)
    )


def _artifact_record(path: Path, workspace: Path, digest: str) -> dict[str, str]:
    return {
        "path": _display_path(path, workspace),
        "sha256": digest,
        "verification": "file_sha256",
    }


def _verify_a1_file_artifacts(
    workspace: Path,
    a1_freeze: Mapping[str, Any],
    a1_config: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    manifest_records = a1_freeze.get("file_artifacts")
    config_records = a1_config.get("frozen_artifacts")
    required = a1_config.get("required_frozen_artifacts")
    if not isinstance(manifest_records, Mapping) or not manifest_records:
        raise ValueError("A1 implementation freeze lacks file_artifacts")
    if not isinstance(config_records, Mapping) or not isinstance(required, list):
        raise ValueError("A1 final config lacks its frozen artifact manifest")
    if not BEHAVIOR_KEYS.issubset(manifest_records):
        raise ValueError(
            f"A1 freeze lacks behavior sources: {sorted(BEHAVIOR_KEYS - set(manifest_records))}"
        )

    inherited: dict[str, dict[str, str]] = {}
    checks: dict[str, dict[str, Any]] = {}
    for name, raw_record in sorted(manifest_records.items()):
        if not isinstance(raw_record, Mapping):
            raise TypeError(f"invalid A1 frozen file record: {name}")
        raw_path = raw_record.get("path")
        expected = raw_record.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            raise ValueError(f"incomplete A1 frozen file record: {name}")
        path = _resolve(workspace, raw_path)
        actual = _require_file_sha(path, expected, f"A1 frozen artifact {name}")
        config_record = config_records.get(name)
        if (
            name not in required
            or not isinstance(config_record, Mapping)
            or config_record.get("verification") != "file_sha256"
            or config_record.get("sha256") != expected
        ):
            raise RuntimeError(f"A1 config/freeze artifact binding differs for {name}")
        inherited[name] = {"path": raw_path, "sha256": expected}
        checks[name] = {
            "path": _display_path(path, workspace),
            "expected_sha256": expected,
            "observed_sha256": actual,
            "behavior_source": name in BEHAVIOR_KEYS,
            "passed": True,
        }
    return inherited, checks


def _load_environment_helpers(path: Path) -> tuple[Callable[[], Any], Callable[[Any], Any]]:
    spec = importlib.util.spec_from_file_location("a2_frozen_environment_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen environment helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._capture_environment, module._environment_compatibility_projection


def _run_a2_tests(workspace: Path, test_paths: Sequence[Path]) -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "-v", *map(str, test_paths)]
    completed = subprocess.run(
        command,
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        check=False,
    )
    transcript = completed.stdout
    matches = re.findall(r"Ran (\d+) tests? in", transcript)
    tests_run = int(matches[-1]) if matches else 0
    if completed.returncode != 0 or tests_run < 1 or not re.search(
        r"^OK(?: \(|$)", transcript, flags=re.MULTILINE
    ):
        raise RuntimeError(f"A2 unit tests failed:\n{transcript}")
    return {
        "passed": True,
        "returncode": completed.returncode,
        "tests_run": tests_run,
        "command": command,
        "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        "transcript": transcript,
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def seal(
    args: argparse.Namespace,
    *,
    live_environment: Mapping[str, Any] | None = None,
    test_result: Mapping[str, Any] | None = None,
    fixed_protocol_sha256: str = A2_PROTOCOL_SHA256,
    fixed_failure_sha256: str = A1_FAILURE_SHA256,
    fixed_a1_freeze_sha256: str = A1_FREEZE_SHA256,
) -> dict[str, str]:
    workspace = args.workspace.expanduser().resolve()
    paths = {
        "a1_config": _resolve(workspace, args.a1_final_config),
        "a1_freeze": _resolve(workspace, args.a1_implementation_freeze),
        "a1_preflight": _resolve(workspace, args.a1_preflight),
        "protocol_a2": _resolve(workspace, args.a2_protocol),
        "failure_a1": _resolve(workspace, args.a1_failure_report),
        "runner_a2": _resolve(workspace, args.a2_runner),
        "analyzer_a2": _resolve(workspace, args.a2_analyzer),
        "launcher_a2": _resolve(workspace, args.a2_launcher),
        "test_runner_a2": _resolve(workspace, args.a2_runner_test),
        "test_analyzer_a2": _resolve(workspace, args.a2_analyzer_test),
        "test_launcher_a2": _resolve(workspace, args.a2_launcher_test),
        "builder_a2": Path(__file__).resolve(),
        "test_builder_a2": _resolve(workspace, args.a2_builder_test),
    }
    outputs = {
        "freeze": _resolve(workspace, args.freeze_output),
        "preflight": _resolve(workspace, args.preflight_output),
        "config": _resolve(workspace, args.config_output),
    }
    if len(set(outputs.values())) != 3:
        raise ValueError("A2 freeze, preflight, and config outputs must be distinct")
    occupied = [str(path) for path in outputs.values() if path.exists()]
    if occupied:
        raise FileExistsError(f"refusing to overwrite A2 sealed outputs: {occupied}")
    for raw in (args.a2_results_dir, args.a2_logs_dir):
        path = _resolve(workspace, raw)
        if path.exists():
            raise FileExistsError(
                f"A2 fresh-run path already exists; cannot attest zero A2 runs: {path}"
            )

    _require_file_sha(paths["protocol_a2"], fixed_protocol_sha256, "A2 protocol")
    _require_file_sha(paths["failure_a1"], fixed_failure_sha256, "A1 effect-blind failure report")
    _require_file_sha(paths["a1_freeze"], fixed_a1_freeze_sha256, "A1 implementation freeze")

    expected_a2 = {
        "runner_a2": args.expected_a2_runner_sha256,
        "analyzer_a2": args.expected_a2_analyzer_sha256,
        "launcher_a2": args.expected_a2_launcher_sha256,
        "test_runner_a2": args.expected_a2_runner_test_sha256,
        "test_analyzer_a2": args.expected_a2_analyzer_test_sha256,
        "test_launcher_a2": args.expected_a2_launcher_test_sha256,
    }
    for name, expected in expected_a2.items():
        _require_file_sha(paths[name], expected, name)

    failure = _load_object(paths["failure_a1"], "A1 effect-blind failure report")
    if (
        failure.get("schema") != "dai.same-call-a1-effect-blind-execution-failure/v1"
        or failure.get("status") != "a1_matrix_abandoned_before_effect_analysis"
        or failure.get("a1_protocol_sha256") != A1_PROTOCOL_SHA256
    ):
        raise ValueError("unexpected A1 effect-blind incident identity")
    audit = failure.get("audit")
    if not isinstance(audit, Mapping) or {
        "runs": audit.get("runs"),
        "unique_bare_pids": audit.get("unique_bare_pids"),
        "unique_process_instances_host_pid_start_ns": audit.get(
            "unique_process_instances_host_pid_start_ns"
        ),
        "unique_run_uuids": audit.get("unique_run_uuids"),
    } != {
        "runs": 960,
        "unique_bare_pids": 959,
        "unique_process_instances_host_pid_start_ns": 960,
        "unique_run_uuids": 960,
    } or audit.get("append_only_ledger_bindings_passed") is not True:
        raise ValueError("A1 incident metadata does not match the registered effect-blind failure")

    a1_config_sha = _sha256(paths["a1_config"])
    if a1_config_sha != failure.get("a1_config_sha256"):
        raise RuntimeError("A1 final config is not the config sealed by the A1 incident")
    if fixed_failure_sha256 == A1_FAILURE_SHA256 and a1_config_sha != A1_CONFIG_SHA256:
        raise RuntimeError("A1 final config differs from the canonical A1 config")
    a1_config = _load_object(paths["a1_config"], "A1 final config")
    if (
        a1_config.get("schema") != "dai.same-call-confirmation/a1"
        or tuple(a1_config.get("root_seeds", ())) != A1_ROOTS
        or tuple(a1_config.get("methods", ())) != METHODS
        or tuple(a1_config.get("workloads", ())) != WORKLOADS
    ):
        raise ValueError("A1 final config scientific identity is unexpected")
    provenance = a1_config.get("provenance")
    if not isinstance(provenance, Mapping) or (
        provenance.get("fresh_root_runs_observed_at_freeze") != 0
        or provenance.get("effect_inference_performed_before_config") is not False
    ):
        raise ValueError("A1 config was not sealed before fresh roots/effect inference")

    a1_freeze = _load_object(paths["a1_freeze"], "A1 implementation freeze")
    if (
        a1_freeze.get("schema") != "dai.same-call-implementation-freeze/a1"
        or a1_freeze.get("fresh_root_runs_observed") != 0
        or a1_freeze.get("fresh_effect_estimates_computed") != 0
        or a1_freeze.get("fresh_method_rankings_inspected") != 0
    ):
        raise ValueError("A1 implementation manifest is not the pre-fresh freeze")

    expected_preflight_sha = _require_sha(
        args.expected_a1_preflight_sha256, "--expected-a1-preflight-sha256"
    )
    _require_file_sha(paths["a1_preflight"], expected_preflight_sha, "A1 full preflight")
    a1_preflight = _load_object(paths["a1_preflight"], "A1 full preflight")
    if not _passed(a1_preflight):
        raise RuntimeError("A1 full preflight did not pass")
    preflight_audit = a1_preflight.get("audit")
    if not isinstance(preflight_audit, Mapping) or preflight_audit.get(
        "effect_inference_performed"
    ) is not False:
        raise ValueError("A1 preflight does not prove effect-blind execution")
    evidence = a1_config.get("preflight_evidence")
    a1_full = evidence.get("a1_full_preflight") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(a1_full, Mapping)
        or a1_full.get("passed") is not True
        or a1_full.get("sha256") != expected_preflight_sha
    ):
        raise RuntimeError("A1 config does not bind the supplied passing full preflight")

    inherited, source_checks = _verify_a1_file_artifacts(
        workspace, a1_freeze, a1_config
    )

    target = a1_config.get("target_environment")
    if not isinstance(target, Mapping):
        raise ValueError("A1 config lacks target_environment")
    target_path = _resolve(workspace, str(target.get("path", "")))
    target_sha = target.get("sha256")
    target_host = target.get("execution_host")
    if not isinstance(target_sha, str) or not isinstance(target_host, str):
        raise ValueError("A1 target_environment binding is incomplete")
    _require_file_sha(target_path, target_sha, "A1 target environment attestation")
    attestation = _load_object(target_path, "A1 environment attestation")
    sealed_environment = attestation.get("environment")
    if (
        attestation.get("schema") != "dai.same-call-environment-attestation/a1"
        or attestation.get("status") != "complete"
        or attestation.get("fresh_root_runs_observed") != 0
        or attestation.get("fresh_effect_estimates_computed") != 0
        or not isinstance(sealed_environment, Mapping)
        or sealed_environment.get("host") != target_host
        or socket.gethostname() != target_host
    ):
        raise RuntimeError("current host or sealed A1 environment identity differs")
    helper_record = inherited.get("legacy_replay_launcher")
    if not isinstance(helper_record, Mapping):
        raise ValueError("A1 freeze lacks the frozen environment helper")
    helper_path = _resolve(workspace, helper_record["path"])
    capture, projection = _load_environment_helpers(helper_path)
    current_environment = dict(live_environment) if live_environment is not None else capture()
    sealed_projection = projection(sealed_environment)
    current_projection = projection(current_environment)
    if current_projection != sealed_projection:
        raise RuntimeError("live host/environment projection differs from A1 attestation")

    if test_result is None:
        test_result = _run_a2_tests(
            workspace,
            (
                paths["test_runner_a2"],
                paths["test_launcher_a2"],
                paths["test_analyzer_a2"],
            ),
        )
    if test_result.get("passed") is not True:
        raise RuntimeError("A2 unit/source tests did not pass")

    # Close the ordinary test/capture time-of-check window before sealing.
    _require_file_sha(paths["protocol_a2"], fixed_protocol_sha256, "A2 protocol postcheck")
    _require_file_sha(paths["failure_a1"], fixed_failure_sha256, "A1 failure report postcheck")
    _require_file_sha(paths["a1_freeze"], fixed_a1_freeze_sha256, "A1 freeze postcheck")
    _require_file_sha(paths["a1_config"], a1_config_sha, "A1 final config postcheck")
    _require_file_sha(paths["a1_preflight"], expected_preflight_sha, "A1 preflight postcheck")
    _require_file_sha(target_path, target_sha, "A1 environment attestation postcheck")
    for name, expected in expected_a2.items():
        _require_file_sha(paths[name], expected, f"{name} postcheck")
    for name, record in inherited.items():
        _require_file_sha(
            _resolve(workspace, record["path"]),
            record["sha256"],
            f"A1 frozen artifact {name} postcheck",
        )

    a2_records = {
        "protocol_a2": _artifact_record(paths["protocol_a2"], workspace, fixed_protocol_sha256),
        "a1_effect_blind_failure": _artifact_record(paths["failure_a1"], workspace, fixed_failure_sha256),
        "runner_a2": _artifact_record(paths["runner_a2"], workspace, expected_a2["runner_a2"]),
        "analyzer_a2": _artifact_record(paths["analyzer_a2"], workspace, expected_a2["analyzer_a2"]),
        "launcher_a2": _artifact_record(paths["launcher_a2"], workspace, expected_a2["launcher_a2"]),
        "test_runner_a2": _artifact_record(paths["test_runner_a2"], workspace, expected_a2["test_runner_a2"]),
        "test_analyzer_a2": _artifact_record(paths["test_analyzer_a2"], workspace, expected_a2["test_analyzer_a2"]),
        "test_launcher_a2": _artifact_record(paths["test_launcher_a2"], workspace, expected_a2["test_launcher_a2"]),
        "builder_a2": _artifact_record(paths["builder_a2"], workspace, _sha256(paths["builder_a2"])),
        "test_builder_a2": _artifact_record(paths["test_builder_a2"], workspace, _sha256(paths["test_builder_a2"])),
    }
    freeze_files = copy.deepcopy(inherited)
    for record in freeze_files.values():
        record["verification"] = "file_sha256"
    freeze_files.update(a2_records)
    freeze = {
        "schema": "dai.same-call-implementation-freeze/a2",
        "status": "frozen_before_any_a2_fresh_root",
        "created_date": "2026-07-14",
        "a2_fresh_root_runs_observed": 0,
        "a2_effect_estimates_computed": 0,
        "a2_method_rankings_inspected": 0,
        "a1_effect_estimates_computed": 0,
        "a1_method_rankings_inspected": 0,
        "a1_outcome_tier_assigned": False,
        "effect_inference_performed": False,
        "predecessors": {
            "a1_final_config": _artifact_record(paths["a1_config"], workspace, a1_config_sha),
            "a1_implementation_freeze": _artifact_record(paths["a1_freeze"], workspace, fixed_a1_freeze_sha256),
            "a1_full_preflight": _artifact_record(paths["a1_preflight"], workspace, expected_preflight_sha),
            "a1_effect_blind_failure": _artifact_record(paths["failure_a1"], workspace, fixed_failure_sha256),
        },
        "replacement_roots": list(A2_ROOTS),
        "retired_a1_roots": list(A1_ROOTS),
        "root_derivation": {
            "source_sha256": fixed_failure_sha256,
            "domain": "dai-same-call-confirmatory-a2-pid-reuse-correction",
            "formula": "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)",
        },
        "file_artifacts": freeze_files,
        "metadata_artifacts": copy.deepcopy(a1_freeze.get("metadata_artifacts", {})),
        "scientific_contract_unchanged": copy.deepcopy(
            a1_freeze.get("scientific_contract_unchanged", {})
        ),
        "target_environment_reverification": {
            "path": _display_path(target_path, workspace),
            "sha256": target_sha,
            "execution_host": target_host,
            "compatibility_projection_sha256": _canonical_sha256(sealed_projection),
            "live_projection_matched": True,
        },
    }
    freeze_bytes = _json_bytes(freeze)
    freeze_sha = hashlib.sha256(freeze_bytes).hexdigest()

    preflight = {
        "schema": "dai.same-call-preflight-seal/a2",
        "status": "passed_before_any_a2_fresh_root",
        "passed": True,
        "a2_fresh_root_runs_observed": 0,
        "a2_effect_estimates_computed": 0,
        "a2_method_rankings_inspected": 0,
        "effect_inference_performed": False,
        "claim_boundary": "Control-plane, source, unit, and host provenance only; no A1 or A2 outcome was read.",
        "implementation_freeze": {
            "path": _display_path(outputs["freeze"], workspace),
            "sha256": freeze_sha,
        },
        "reused_a1_preflight": {
            "path": _display_path(paths["a1_preflight"], workspace),
            "sha256": expected_preflight_sha,
            "passed": True,
            "effect_inference_performed": False,
        },
        "source_reverification": {
            "passed": True,
            "checks": source_checks,
        },
        "host_environment_reverification": {
            "passed": True,
            "execution_host": target_host,
            "attestation_path": _display_path(target_path, workspace),
            "attestation_sha256": target_sha,
            "sealed_projection_sha256": _canonical_sha256(sealed_projection),
            "live_projection_sha256": _canonical_sha256(current_projection),
        },
        "a2_unit_tests": dict(test_result),
        "a2_artifacts": a2_records,
        "replacement_roots": list(A2_ROOTS),
    }
    preflight_bytes = _json_bytes(preflight)
    preflight_sha = hashlib.sha256(preflight_bytes).hexdigest()

    frozen_artifacts = copy.deepcopy(a1_config.get("frozen_artifacts", {}))
    frozen_artifacts.update(a2_records)
    preflight_evidence = copy.deepcopy(a1_config.get("preflight_evidence", {}))
    preflight_evidence["a2_preflight_seal"] = {
        "path": _display_path(outputs["preflight"], workspace),
        "sha256": preflight_sha,
        "passed": True,
    }
    config = {
        "schema": "dai.same-call-confirmation/a2",
        "status": "frozen_after_passing_a2_preflight_before_a2_fresh_matrix",
        "artifact_config_sha256_field": a1_config["artifact_config_sha256_field"],
        "methods": list(METHODS),
        "root_seeds": list(A2_ROOTS),
        "root_derivation": {
            "source_sha256": fixed_failure_sha256,
            "domain": "dai-same-call-confirmatory-a2-pid-reuse-correction",
            "formula": "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)",
        },
        "workloads": list(WORKLOADS),
        "scenarios": copy.deepcopy(a1_config["scenarios"]),
        "protocol": copy.deepcopy(a1_config["protocol"]),
        "process_identity_gate": {
            "hard_identity": ["execution_host", "execution_process_id", "execution_process_start_ns"],
            "unique_process_instances_required": 960,
            "unique_run_uuids_required": 960,
            "bare_pid_uniqueness_is_gate": False,
        },
        "required_frozen_artifacts": sorted(frozen_artifacts),
        "frozen_artifacts": frozen_artifacts,
        "required_preflight_evidence": sorted(preflight_evidence),
        "preflight_evidence": preflight_evidence,
        "target_environment": copy.deepcopy(target),
        "provenance": {
            "implementation_freeze_path": _display_path(outputs["freeze"], workspace),
            "implementation_freeze_sha256": freeze_sha,
            "a2_preflight_path": _display_path(outputs["preflight"], workspace),
            "a2_preflight_sha256": preflight_sha,
            "a1_effect_blind_failure_sha256": fixed_failure_sha256,
            "a2_fresh_root_runs_observed_at_freeze": 0,
            "a2_effect_estimates_computed_before_config": 0,
            "a2_method_rankings_inspected_before_config": 0,
            "effect_inference_performed_before_config": False,
        },
    }
    config_bytes = _json_bytes(config)

    # The precheck above catches ordinary collisions; O_EXCL closes the race.
    _write_exclusive(outputs["freeze"], freeze_bytes)
    _write_exclusive(outputs["preflight"], preflight_bytes)
    _write_exclusive(outputs["config"], config_bytes)
    return {
        "freeze_path": str(outputs["freeze"]),
        "freeze_sha256": freeze_sha,
        "preflight_path": str(outputs["preflight"]),
        "preflight_sha256": preflight_sha,
        "config_path": str(outputs["config"]),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--a1-final-config", type=Path, required=True)
    parser.add_argument(
        "--a1-implementation-freeze", type=Path,
        default=Path("configs/same_call_implementation_freeze_a1.json"),
    )
    parser.add_argument("--a1-preflight", type=Path, required=True)
    parser.add_argument("--expected-a1-preflight-sha256", required=True)
    parser.add_argument(
        "--a2-protocol", type=Path,
        default=Path("EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md"),
    )
    parser.add_argument(
        "--a1-failure-report", type=Path,
        default=Path("reports/same_call_a1_effect_blind_execution_failure.json"),
    )
    parser.add_argument("--a2-runner", type=Path, default=Path("scripts/run_same_call_confirmation_a2.py"))
    parser.add_argument("--a2-analyzer", type=Path, default=Path("scripts/analyze_same_call_confirmation_a2.py"))
    parser.add_argument("--a2-launcher", type=Path, default=Path("scripts/run_same_call_confirmation_matrix_a2.sh"))
    parser.add_argument("--a2-runner-test", type=Path, default=Path("tests/test_run_same_call_confirmation_a2.py"))
    parser.add_argument("--a2-analyzer-test", type=Path, default=Path("tests/test_analyze_same_call_confirmation_a2.py"))
    parser.add_argument("--a2-launcher-test", type=Path, default=Path("tests/test_run_same_call_confirmation_matrix_a2.py"))
    parser.add_argument("--a2-builder-test", type=Path, default=Path("tests/test_build_same_call_confirmation_config_a2.py"))
    parser.add_argument("--expected-a2-runner-sha256", required=True)
    parser.add_argument("--expected-a2-analyzer-sha256", required=True)
    parser.add_argument("--expected-a2-launcher-sha256", required=True)
    parser.add_argument("--expected-a2-runner-test-sha256", required=True)
    parser.add_argument("--expected-a2-analyzer-test-sha256", required=True)
    parser.add_argument("--expected-a2-launcher-test-sha256", required=True)
    parser.add_argument(
        "--freeze-output", type=Path,
        default=Path("configs/same_call_implementation_freeze_a2.json"),
    )
    parser.add_argument(
        "--preflight-output", type=Path,
        default=Path("reports/same_call_preflight_a2.json"),
    )
    parser.add_argument(
        "--config-output", type=Path,
        default=Path("configs/same_call_confirmation_a2.json"),
    )
    parser.add_argument(
        "--a2-results-dir", type=Path,
        default=Path("results/same_call_confirmation_a2"),
    )
    parser.add_argument(
        "--a2-logs-dir", type=Path,
        default=Path("logs/same_call_confirmation_a2"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = seal(args)
    print("SAME_CALL_CONFIRMATION_A2_SEALED " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
