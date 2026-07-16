#!/usr/bin/env python3
"""Run and attest the A1 same-host legacy compatibility replay.

The orchestrator first writes an immutable host/environment attestation, then
executes the 36 registered common arms with one hash-gated wrapper process per
arm.  It never retries or overwrites.  On success it emits four nine-run
scenario artifacts and a separate replay attestation that binds the pre-run
environment digest, every command, raw arm, log, ledger, and merged artifact.

All outputs are engineering compatibility evidence only.  Root 17 is
contaminated development data and must never be used for treatment effects.
"""

from __future__ import annotations

import argparse
from collections import deque
import contextlib
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shlex
import socket
import subprocess
import sys
import sysconfig
import time
from typing import Any, Iterable, Mapping, Sequence


ENVIRONMENT_SCHEMA = "dai.same-call-environment-attestation/a1"
REPLAY_SCHEMA = "dai.same-call-legacy-current-replay-attestation/v1"
ARTIFACT_SCHEMA = "dai.same-call-legacy-current-replay-artifact/a1"
LEDGER_EVENT_SCHEMA = "dai.same-call-legacy-current-replay-ledger-event/a1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
COMMON_METHODS = (
    "bootstrap_only",
    "context_memory_B25",
    "exact_even_B25",
)
WORKLOADS = ("stationary", "abrupt", "recurrent")
SCENARIOS = (
    ("narrow_r020", "warehouse_small_narrow_kiva.map", 218),
    ("narrow_r035", "warehouse_small_narrow_kiva.map", 382),
    ("regular_r020", "warehouse_small_kiva.map", 255),
    ("regular_r035", "warehouse_small_kiva.map", 447),
)
CHECKPOINT_FILE_SHA256 = (
    "e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d"
)
CHECKPOINT_PARAMS_SHA256 = (
    "6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac"
)
MAP_SHA256 = {
    "warehouse_small_narrow_kiva.map": (
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6"
    ),
    "warehouse_small_kiva.map": (
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"
    ),
}
SOURCE_SPECS = {
    "config": (
        "configs/context_eventreserve_development_matrix_v1.json",
        "adda8cf0175ccac6a469e71ead1b3ec66ab96a4cfcd3d6dd98a80e41a4338e86",
    ),
    "claim_runner": (
        "src/dai_lmapf/claim_runner.py",
        "d9bf61bfa2f86881084b2b1abc19aa0f7483206fa58dcdc88c0b086099d03c2e",
    ),
    "validation_runner": (
        "scripts/run_claim_aware_budgeted_validation.py",
        "694c6af03421e653b7d273d6e5f9da3dd6d1ec349f9120b8efe06bf466b33d50",
    ),
    "publication_policy": (
        "src/dai_lmapf/publication_policy.py",
        "d860af7cc664ff30eaed6bad099313c27f74e99e933f95503d668d57b0ec6d88",
    ),
    "frozen_cnn_generator": (
        "src/dai_lmapf/frozen_cnn_generator.py",
        "023126dd8ce34e8a65ae011f8a7dbb0cca754220b62920db812237de0285b7f2",
    ),
    "online_ggo_adapter": (
        "src/dai_lmapf/online_ggo_adapter.py",
        "013cae2734aa67782ae560e55eeb9b51c9be7343ab27e6ef2e3836ffcc1e913b",
    ),
    "absolute_workload": (
        "src/dai_lmapf/absolute_workload.py",
        "2f2244bac3cad67a057457b4daec79d56486f1dbe7d073b1d2b456c649a3f38e",
    ),
    "trafficflow_online_env": (
        "external/OnlineGGO/CMAES/env_search/iterative_update/envs/trafficflow_online_env.py",
        "178d954b17f1bf33a1772fd481adb66709de221957dc41ae9c592e591ecfa5a4",
    ),
    "task_generator": (
        "external/OnlineGGO/CMAES/env_search/utils/task_generator.py",
        "ae37b0c02bca7815af3d8e491507281ed92d85fa7ed91ec7ebe3ca44c889dbf5",
    ),
    "traffic_mapf_config": (
        "external/OnlineGGO/CMAES/env_search/traffic_mapf/config.py",
        "7346056cc9c135f4a81ed1bd1a9703b80d1bd5501338d484b9c6919eac807974",
    ),
    "same_call_claim_runner": (
        "src/dai_lmapf/same_call_claim_runner.py",
        "53fe48d7fda7638dbd79423d01f4f07de5e13a04938d9a1516855347413ef495",
    ),
    "same_call_validation_runner": (
        "scripts/run_same_call_confirmation_v1.py",
        "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538",
    ),
    "predecessor_protocol": (
        "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md",
        "9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41",
    ),
}
PERIOD_ON_SIM = (
    "external/OnlineGGO/CMAES/simulators/trafficMAPF_on/"
    "period_on_sim.cpython-39-x86_64-linux-gnu.so"
)
PERIOD_ON_SIM_SHA256 = (
    "9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5"
)
CHECKPOINT = (
    "external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/"
    "optimal_update_model_10000.json"
)
MAP_DIRECTORY = (
    "external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_digest(value: str, name: str) -> str:
    value = value.lower()
    if not SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be 64 lowercase hexadecimal digits")
    return value


def _identity(workspace: Path, relative_path: str, expected: str) -> dict[str, Any]:
    expected = _validated_digest(expected, relative_path)
    path = workspace / relative_path
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = _sha256_file(path)
    if actual != expected:
        raise RuntimeError(
            f"SHA mismatch path={path} expected={expected} actual={actual}"
        )
    return {
        "path": relative_path,
        "sha256": actual,
        "expected_sha256": expected,
        "size_bytes": path.stat().st_size,
    }


def _write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _workspace_relative(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError as exc:
        raise ValueError(f"path must lie within workspace: {path}") from exc


def _safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _run_capture(argv: Sequence[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        return {
            "argv": list(argv),
            "returncode": completed.returncode,
            "output": completed.stdout.strip(),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"argv": list(argv), "error": type(exc).__name__, "detail": str(exc)}


def _capture_libstdcpp() -> dict[str, Any]:
    discovery = _run_capture(("g++", "-print-file-name=libstdc++.so.6"))
    if discovery.get("returncode") != 0:
        return {"discovery": discovery}
    reported = str(discovery.get("output", "")).strip()
    path = Path(reported)
    if not path.is_file():
        return {"discovery": discovery, "reported_path": reported, "error": "not_file"}
    resolved = path.resolve()
    strings = _run_capture(("strings", str(resolved)))
    symbols = sorted(
        set(
            re.findall(
                r"(?:GLIBCXX|CXXABI)_\d+(?:\.\d+)+",
                str(strings.get("output", "")),
            )
        ),
        key=lambda value: tuple(
            int(part) for part in value.split("_", 1)[1].split(".")
        ),
    )
    return {
        "reported_path": reported,
        "resolved_path": str(resolved),
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
        "highest_versioned_symbols": symbols[-12:],
    }


def _parse_cpu_info() -> dict[str, Any]:
    text = _safe_read(Path("/proc/cpuinfo")) or ""
    records = [record for record in text.split("\n\n") if record.strip()]
    parsed = []
    for record in records:
        fields = {}
        for line in record.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        parsed.append(fields)
    first = parsed[0] if parsed else {}
    flags = first.get("flags", first.get("Features", "")).split()
    models = []
    for item in parsed:
        model = item.get("model name", item.get("Processor"))
        if model and model not in models:
            models.append(model)
    try:
        affinity = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    return {
        "logical_count_os": os.cpu_count(),
        "processor_record_count": len(parsed),
        "models": models,
        "vendor_id": first.get("vendor_id"),
        "microcode": first.get("microcode"),
        "flags": flags,
        "affinity": affinity,
        "cpuinfo_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _capture_python_libraries() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "compiler": platform.python_compiler(),
            "build": list(platform.python_build()),
            "sysconfig_platform": sysconfig.get_platform(),
            "soabi": sysconfig.get_config_var("SOABI"),
            "cc": sysconfig.get_config_var("CC"),
            "cxx": sysconfig.get_config_var("CXX"),
        }
    }
    try:
        import numpy as np

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            np.show_config()
        result["numpy"] = {
            "version": np.__version__,
            "show_config": buffer.getvalue().strip(),
        }
    except Exception as exc:  # pragma: no cover - remote dependency hard gate
        raise RuntimeError(f"NumPy environment attestation failed: {exc}") from exc
    try:
        import torch

        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        cudnn = getattr(torch.backends, "cudnn", None)
        cuda_version = getattr(getattr(torch, "version", None), "cuda", None)
        hip_version = getattr(getattr(torch, "version", None), "hip", None)
        result["torch"] = {
            "version": torch.__version__,
            "git_version": getattr(getattr(torch, "version", None), "git_version", None),
            "cuda_build": cuda_version,
            "hip_build": hip_version,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
            "cudnn_version": cudnn.version() if cudnn is not None else None,
            "cudnn_enabled": getattr(cudnn, "enabled", None),
            "cudnn_deterministic": getattr(cudnn, "deterministic", None),
            "cudnn_benchmark": getattr(cudnn, "benchmark", None),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "num_threads": torch.get_num_threads(),
            "num_interop_threads": torch.get_num_interop_threads(),
            "default_dtype": str(torch.get_default_dtype()),
            "config": torch.__config__.show(),
        }
    except Exception as exc:  # pragma: no cover - remote dependency hard gate
        raise RuntimeError(f"PyTorch environment attestation failed: {exc}") from exc
    if (
        result["torch"]["num_threads"] != 1
        or result["torch"]["num_interop_threads"] != 1
    ):
        raise RuntimeError(f"PyTorch one-thread attestation failed: {result['torch']}")
    return result


def _capture_environment() -> dict[str, Any]:
    gpu_query = _run_capture(
        (
            "nvidia-smi",
            "--query-gpu=index,name,uuid,driver_version,vbios_version",
            "--format=csv,noheader,nounits",
        )
    )
    gpu_inventory = [
        line.strip()
        for line in str(gpu_query.get("output", "")).splitlines()
        if line.strip()
    ]
    if gpu_query.get("returncode") != 0 or not gpu_inventory:
        raise RuntimeError(
            "A1 host attestation requires a successful nonempty ordered "
            f"NVIDIA GPU inventory: {gpu_query}"
        )
    machine_id = _safe_read(Path("/etc/machine-id"))
    product_uuid = _safe_read(Path("/sys/class/dmi/id/product_uuid"))
    cpu = _parse_cpu_info()
    host_payload = {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "machine_id_sha256": (
            hashlib.sha256(machine_id.encode("utf-8")).hexdigest()
            if machine_id
            else None
        ),
        "dmi_product_uuid_sha256": (
            hashlib.sha256(product_uuid.encode("utf-8")).hexdigest()
            if product_uuid
            else None
        ),
        "cpu_models": cpu["models"],
        "logical_cpu_count": cpu["logical_count_os"],
        "gpu_inventory_ordered": gpu_inventory,
    }
    uname = platform.uname()
    native_runtime = {
        "gcc": _run_capture(("gcc", "--version")),
        "gxx": _run_capture(("g++", "--version")),
        "ldd": _run_capture(("ldd", "--version")),
        "libstdcpp": _capture_libstdcpp(),
    }
    if not native_runtime["libstdcpp"].get("sha256"):
        raise RuntimeError(
            f"A1 host attestation could not identify libstdc++: {native_runtime['libstdcpp']}"
        )
    environment = {
        "host": socket.gethostname(),
        "host_instance_fingerprint_payload": host_payload,
        "host_instance_fingerprint_sha256": _canonical_sha256(host_payload),
        "uname": {
            "system": uname.system,
            "node": uname.node,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
            "processor": uname.processor,
        },
        "platform": platform.platform(),
        "architecture": list(platform.architecture()),
        "os_release": _safe_read(Path("/etc/os-release")),
        "glibc": list(platform.libc_ver()),
        "cpu": cpu,
        "gpu_inventory": gpu_query,
        "nvidia_smi": _run_capture(("nvidia-smi",)),
        "compilers_and_native_runtime": native_runtime,
        "libraries": _capture_python_libraries(),
        "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
        "device_policy": {
            "cnn_inference_device": "cpu (FrozenCNNGuidanceGenerator does not move tensors to CUDA)",
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        },
        "rng_and_determinism_environment": {
            name: os.environ.get(name)
            for name in (
                "PYTHONHASHSEED",
                "CUBLAS_WORKSPACE_CONFIG",
                "CUDA_LAUNCH_BLOCKING",
                "NVIDIA_TF32_OVERRIDE",
            )
        },
    }
    return environment


def _environment_compatibility_projection(environment: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable host/runtime fields that must match at replay time.

    The full ``nvidia-smi`` snapshot is retained as provenance but contains
    volatile utilization/temperature fields.  Only the ordered inventory query
    and stable software/hardware configuration participate in the hard gate.
    Likewise, raw ``/proc/cpuinfo`` contains a changing MHz field, so its raw
    digest is recorded but not compared.
    """

    cpu = dict(environment.get("cpu", {}))
    cpu.pop("cpuinfo_sha256", None)
    gpu_inventory = environment.get("gpu_inventory", {})
    return {
        "host": environment.get("host"),
        "host_instance_fingerprint_sha256": environment.get(
            "host_instance_fingerprint_sha256"
        ),
        "uname": environment.get("uname"),
        "platform": environment.get("platform"),
        "architecture": environment.get("architecture"),
        "os_release": environment.get("os_release"),
        "glibc": environment.get("glibc"),
        "cpu_stable": cpu,
        "gpu_inventory": gpu_inventory,
        "compilers_and_native_runtime": environment.get(
            "compilers_and_native_runtime"
        ),
        "libraries": environment.get("libraries"),
        "thread_environment": environment.get("thread_environment"),
        "device_policy": environment.get("device_policy"),
        "rng_and_determinism_environment": environment.get(
            "rng_and_determinism_environment"
        ),
    }


def _validate_existing_environment_attestation(
    attestation: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
    sources: Mapping[str, Any],
    maps: Mapping[str, Any],
    launchers: Mapping[str, Any],
    additional_frozen_files: Mapping[str, Any],
    thread_contract: Mapping[str, Any],
    execution_plan: Mapping[str, Any],
    current_environment: Mapping[str, Any],
) -> None:
    expected_scalars = {
        "schema": ENVIRONMENT_SCHEMA,
        "status": "complete",
        "created_before_legacy_replay": True,
        "fresh_root_runs_observed": 0,
        "fresh_effect_estimates_computed": 0,
        "fresh_method_rankings_inspected": 0,
    }
    for field, expected in expected_scalars.items():
        if attestation.get(field) != expected:
            raise RuntimeError(
                f"environment attestation field mismatch {field}: "
                f"expected={expected!r} actual={attestation.get(field)!r}"
            )
    expected_objects = {
        "protocol": protocol,
        "sources": sources,
        "maps": maps,
        "launchers": launchers,
        "additional_frozen_files": additional_frozen_files,
        "thread_contract": thread_contract,
        "execution_plan": execution_plan,
    }
    for field, expected in expected_objects.items():
        if _canonical_sha256(attestation.get(field)) != _canonical_sha256(expected):
            raise RuntimeError(f"environment attestation {field} no longer matches")
    recorded_environment = attestation.get("environment")
    if not isinstance(recorded_environment, dict):
        raise RuntimeError("environment attestation lacks environment mapping")
    recorded_projection = _environment_compatibility_projection(recorded_environment)
    current_projection = _environment_compatibility_projection(current_environment)
    if _canonical_sha256(recorded_projection) != _canonical_sha256(current_projection):
        raise RuntimeError(
            "current host/runtime does not match the sealed environment attestation"
        )


def _parse_additional_files(
    workspace: Path, values: Iterable[str]
) -> dict[str, dict[str, Any]]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--frozen-file must be RELATIVE_PATH=SHA256")
        relative, digest = value.rsplit("=", 1)
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"frozen file path must be safe and relative: {relative}")
        if relative in result:
            raise ValueError(f"duplicate --frozen-file path: {relative}")
        result[relative] = _identity(workspace, relative, digest)
    return result


def _append_ledger_event(
    ledger_path: Path,
    event: Mapping[str, Any],
    sequence: int,
    previous_hash: str | None,
) -> str:
    payload = {
        "schema": LEDGER_EVENT_SCHEMA,
        "sequence": sequence,
        "recorded_utc": _utc_now(),
        "previous_event_sha256": previous_hash,
        **event,
    }
    payload["event_sha256"] = _canonical_sha256(payload)
    with ledger_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return payload["event_sha256"]


def _validate_ledger(path: Path) -> dict[str, Any]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    previous = None
    for expected_sequence, event in enumerate(events, 1):
        if event.get("schema") != LEDGER_EVENT_SCHEMA:
            raise RuntimeError("ledger schema mismatch")
        if event.get("sequence") != expected_sequence:
            raise RuntimeError("ledger sequence is not contiguous")
        if event.get("previous_event_sha256") != previous:
            raise RuntimeError("ledger hash chain is broken")
        supplied = event.get("event_sha256")
        unhashed = dict(event)
        unhashed.pop("event_sha256", None)
        if supplied != _canonical_sha256(unhashed):
            raise RuntimeError("ledger event hash mismatch")
        previous = supplied
    started = [event for event in events if event.get("event") == "started"]
    completed = [event for event in events if event.get("event") == "completed"]
    failed = [event for event in events if event.get("event") == "failed"]
    arm_key = lambda event: (
        event.get("label"),
        event.get("workload"),
        event.get("method"),
    )
    started_by_arm = {arm_key(event): event for event in started}
    completed_by_arm = {arm_key(event): event for event in completed}
    if len(started_by_arm) != len(started):
        raise RuntimeError("ledger contains a duplicate arm start")
    if len(completed_by_arm) != len(completed):
        raise RuntimeError("ledger contains a duplicate arm completion")
    if set(started_by_arm) != set(completed_by_arm) and not failed:
        raise RuntimeError("ledger start/completion arm sets differ")
    for key in set(started_by_arm) & set(completed_by_arm):
        if started_by_arm[key].get("pid") != completed_by_arm[key].get("pid"):
            raise RuntimeError(f"ledger PID changed within arm {key}")
    process_ids = [event.get("pid") for event in started]
    instances = [
        (event.get("boot_id"), event.get("pid"), event.get("process_start_ticks"))
        for event in completed
    ]
    return {
        "path": None,
        "sha256": _sha256_file(path),
        "schema": LEDGER_EVENT_SCHEMA,
        "event_count": len(events),
        "started_events": len(started),
        "completed_events": len(completed),
        "failed_events": len(failed),
        "unique_arm_count": len(started_by_arm),
        "matched_start_complete_arms": len(
            set(started_by_arm) & set(completed_by_arm)
        ),
        "unique_process_count": len(set(process_ids)),
        "unique_process_instance_count": len(set(instances)),
        "final_event_hash": previous,
    }


def _make_spec(
    workspace: Path, checkpoint: Path, map_path: Path, agents: int, workload: str, method: str
) -> dict[str, Any]:
    return {
        "workspace": str(workspace),
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": CHECKPOINT_FILE_SHA256,
        "checkpoint_params_sha256": CHECKPOINT_PARAMS_SHA256,
        "split": "development",
        "map_path": str(map_path),
        "agents": agents,
        "warmup_time": 200,
        "horizon": 2000,
        "decision_window": 20,
        "release_interval": 110,
        "guard_suffix": 4,
        "sigma": 0.75,
        "pacing_slack": 2,
        "minimum_history": 4,
        "context_match_threshold": 0.05,
        "context_recall_margin": 0.02,
        "context_min_score": 0.10,
        "context_min_gap": 6,
        "context_maintenance_age": 25,
        "context_maintenance_stability": 0.20,
        "timing_evidence_valid": False,
        "seed": 17,
        "workload": workload,
        "method": method,
    }


def _validate_raw_arm(
    raw: Mapping[str, Any], expected_spec: Mapping[str, Any], expected_host: str
) -> None:
    if raw.get("schema") != "dai.same-call-legacy-current-arm/a1":
        raise RuntimeError("raw legacy arm schema mismatch")
    if raw.get("status") != "complete" or raw.get("root_seed") != 17:
        raise RuntimeError("raw legacy arm is not complete root 17 evidence")
    execution = raw.get("execution")
    run = raw.get("run")
    if not isinstance(execution, dict) or not isinstance(run, dict):
        raise RuntimeError("raw legacy arm lacks execution or run payload")
    if execution.get("host") != expected_host:
        raise RuntimeError("raw legacy arm ran on an unattested host")
    if run.get("method") != expected_spec["method"]:
        raise RuntimeError("raw legacy arm method mismatch")
    if run.get("workload") != expected_spec["workload"] or run.get("seed") != 17:
        raise RuntimeError("raw legacy arm cell mismatch")
    if run.get("safety", {}).get("passed") is not True:
        raise RuntimeError("raw legacy arm safety audit failed")
    if run.get("invariants", {}).get("passed") is not True:
        raise RuntimeError("raw legacy arm invariant audit failed")


def _pairing_gate(runs: Sequence[Mapping[str, Any]]) -> None:
    paired_fields = (
        "manifest_id",
        "reset_causal_fingerprint",
        "task_tape_identity",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    )
    for workload in WORKLOADS:
        arms = [run for run in runs if run.get("workload") == workload]
        if len(arms) != 3 or {run.get("method") for run in arms} != set(COMMON_METHODS):
            raise RuntimeError(f"incomplete common-arm cell workload={workload}")
        for field in paired_fields:
            if len({_canonical_sha256(run.get(field)) for run in arms}) != 1:
                raise RuntimeError(f"legacy replay pairing mismatch {workload=} {field=}")


def _write_scenario_artifact(
    workspace: Path,
    output_root: Path,
    label: str,
    map_name: str,
    agents: int,
    arms: Sequence[Mapping[str, Any]],
    environment_sha: str,
    protocol_identity: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    runs = [dict(arm["raw"]["run"]) for arm in arms]
    runs.sort(key=lambda run: (run["workload"], run["method"]))
    _pairing_gate(runs)
    process_instances = [
        {
            "boot_id": arm["raw"]["execution"].get("boot_id"),
            "pid": arm["raw"]["execution"].get("pid"),
            "process_start_ticks": arm["raw"]["execution"].get("process_start_ticks"),
        }
        for arm in arms
    ]
    if len({_canonical_sha256(value) for value in process_instances}) != 9:
        raise RuntimeError(f"scenario {label} does not have nine fresh processes")
    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "status": "complete",
        "evidence_class": "engineering_compatibility_only_no_effect_inference",
        "root_seed": 17,
        "scenario": label,
        "agents": agents,
        "map_path": f"{MAP_DIRECTORY}/{map_name}",
        "map_sha256": MAP_SHA256[map_name],
        "common_methods": list(COMMON_METHODS),
        "workloads": list(WORKLOADS),
        "common_arm_run_count": 9,
        "fresh_process_per_arm": True,
        "environment_attestation_sha256": environment_sha,
        "protocol_identity": dict(protocol_identity),
        "run_protocol": {
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
        },
        "arm_executions": [
            {
                "method": arm["spec"]["method"],
                "workload": arm["spec"]["workload"],
                "raw_arm_path": _workspace_relative(arm["raw_path"], workspace),
                "raw_arm_sha256": _sha256_file(arm["raw_path"]),
                "log_path": _workspace_relative(arm["log_path"], workspace),
                "log_sha256": _sha256_file(arm["log_path"]),
                "spec_path": _workspace_relative(arm["spec_path"], workspace),
                "spec_sha256": _sha256_file(arm["spec_path"]),
                "command_argv": arm["command"],
                "command_display": shlex.join(arm["command"]),
                "execution": arm["raw"]["execution"],
            }
            for arm in arms
        ],
        "runs": runs,
    }
    artifact_path = output_root / "artifacts" / f"{label}.json"
    _write_json_exclusive(artifact_path, artifact)
    csv_path = output_root / "artifacts" / f"{label}.csv"
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        fields = (
            "method",
            "seed",
            "map_id",
            "workload",
            "num_task_finished",
            "throughput_per_timestep",
            "mandatory_bootstrap_calls",
            "post_bootstrap_publication_count",
            "publication_budget",
            "budget_violation_count",
            "generator_seconds",
            "simulator_seconds",
            "elapsed_seconds",
        )
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            writer.writerow({field: run[field] for field in fields})
        stream.flush()
        os.fsync(stream.fileno())
    identity = {
        "label": label,
        "path": _workspace_relative(artifact_path, workspace),
        "sha256": _sha256_file(artifact_path),
        "size_bytes": artifact_path.stat().st_size,
    }
    csv_identity = {
        "role": "scenario_csv",
        "label": label,
        "path": _workspace_relative(csv_path, workspace),
        "sha256": _sha256_file(csv_path),
        "size_bytes": csv_path.stat().st_size,
    }
    return identity, csv_identity


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--protocol-path",
        default="EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A1.md",
    )
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--expected-launcher-sha256", required=True)
    parser.add_argument("--expected-arm-wrapper-sha256", required=True)
    parser.add_argument(
        "--output-root", default="results/same_call_legacy_replay_a1"
    )
    parser.add_argument(
        "--environment-attestation",
        default="reports/same_call_environment_attestation_a1.json",
    )
    parser.add_argument("--max-parallel-arms", type=int, default=12)
    parser.add_argument(
        "--frozen-file",
        action="append",
        default=[],
        metavar="RELATIVE_PATH=SHA256",
        help="additional versioned analyzer/launcher/config identity",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify every frozen input and print the plan without writing or running",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--capture-environment-only",
        action="store_true",
        help="seal the pre-arm environment report, then exit without starting replay",
    )
    mode.add_argument(
        "--use-existing-environment-attestation",
        action="store_true",
        help="hard-verify the already sealed report, then execute the 36-arm replay",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    for name in THREAD_ENV:
        os.environ[name] = "1"
    if args.max_parallel_arms < 1 or args.max_parallel_arms > 36:
        raise ValueError("--max-parallel-arms must lie in [1, 36]")
    workspace = args.workspace.resolve()
    output_root = (workspace / args.output_root).resolve()
    environment_path = (workspace / args.environment_attestation).resolve()
    protocol_path = (workspace / args.protocol_path).resolve()
    _workspace_relative(output_root, workspace)
    _workspace_relative(environment_path, workspace)
    protocol_relative = _workspace_relative(protocol_path, workspace)

    launcher_relative = _workspace_relative(Path(__file__).resolve(), workspace)
    launcher_identity = _identity(
        workspace, launcher_relative, args.expected_launcher_sha256
    )
    wrapper_relative = "scripts/run_same_host_legacy_arm_a1.py"
    wrapper_identity = _identity(
        workspace, wrapper_relative, args.expected_arm_wrapper_sha256
    )
    source_identities = {
        name: _identity(workspace, relative, digest)
        for name, (relative, digest) in SOURCE_SPECS.items()
    }
    source_identities["checkpoint_file"] = _identity(
        workspace, CHECKPOINT, CHECKPOINT_FILE_SHA256
    )
    source_identities["period_on_sim"] = _identity(
        workspace, PERIOD_ON_SIM, PERIOD_ON_SIM_SHA256
    )
    protocol_identity = _identity(
        workspace, protocol_relative, args.expected_protocol_sha256
    )
    maps = {
        "narrow": _identity(
            workspace,
            f"{MAP_DIRECTORY}/warehouse_small_narrow_kiva.map",
            MAP_SHA256["warehouse_small_narrow_kiva.map"],
        ),
        "regular": _identity(
            workspace,
            f"{MAP_DIRECTORY}/warehouse_small_kiva.map",
            MAP_SHA256["warehouse_small_kiva.map"],
        ),
    }
    additional = _parse_additional_files(workspace, args.frozen_file)

    # Validate the effective checkpoint vector, not only the JSON bytes.
    sys.path.insert(0, str(workspace / "src"))
    from dai_lmapf.frozen_cnn_generator import load_frozen_cnn_checkpoint

    checkpoint = load_frozen_cnn_checkpoint(
        workspace / CHECKPOINT,
        expected_file_sha256=CHECKPOINT_FILE_SHA256,
        expected_params_sha256=CHECKPOINT_PARAMS_SHA256,
    )
    if checkpoint.params_sha256 != CHECKPOINT_PARAMS_SHA256:
        raise RuntimeError("checkpoint parameter payload identity mismatch")
    source_identities["checkpoint_file"]["params_sha256"] = checkpoint.params_sha256
    source_identities["checkpoint_file"][
        "expected_params_sha256"
    ] = CHECKPOINT_PARAMS_SHA256

    plan_summary = {
        "root_seed": 17,
        "common_methods": list(COMMON_METHODS),
        "workloads": list(WORKLOADS),
        "scenarios": [label for label, _, _ in SCENARIOS],
        "common_arm_run_count": 36,
        "fresh_process_per_arm": True,
        "max_parallel_arms": args.max_parallel_arms,
        "output_root": _workspace_relative(output_root, workspace),
        "environment_attestation": _workspace_relative(environment_path, workspace),
    }
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run_passed",
                    "protocol": protocol_identity,
                    "launcher": launcher_identity,
                    "arm_wrapper": wrapper_identity,
                    "sources": source_identities,
                    "maps": maps,
                    "additional_frozen_files": additional,
                    "plan": plan_summary,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if not (
        args.capture_environment_only
        or args.use_existing_environment_attestation
    ):
        raise ValueError(
            "real execution requires either --capture-environment-only or "
            "--use-existing-environment-attestation"
        )
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite output root: {output_root}")
    if args.capture_environment_only and environment_path.exists():
        raise FileExistsError(
            f"refusing to overwrite environment attestation: {environment_path}"
        )
    if args.use_existing_environment_attestation and not environment_path.is_file():
        raise FileNotFoundError(
            f"sealed environment attestation is absent: {environment_path}"
        )

    environment = _capture_environment()
    if any(environment["thread_environment"].get(name) != "1" for name in THREAD_ENV):
        raise RuntimeError("captured environment violates the one-thread contract")
    launchers = {
        "legacy_replay": launcher_identity,
        "legacy_arm_wrapper": wrapper_identity,
    }
    thread_contract = {name: "1" for name in THREAD_ENV}
    environment_attestation = {
        "schema": ENVIRONMENT_SCHEMA,
        "status": "complete",
        "created_utc": _utc_now(),
        "created_before_legacy_replay": True,
        "fresh_root_runs_observed": 0,
        "fresh_effect_estimates_computed": 0,
        "fresh_method_rankings_inspected": 0,
        "evidence_class": "frozen_host_environment_no_effect_inference",
        "protocol": protocol_identity,
        "sources": source_identities,
        "maps": maps,
        "launchers": launchers,
        "additional_frozen_files": additional,
        "thread_contract": thread_contract,
        "execution_plan": plan_summary,
        "environment": environment,
    }
    if args.capture_environment_only:
        _write_json_exclusive(environment_path, environment_attestation)
        environment_sha = _sha256_file(environment_path)
        print(
            "SAME_CALL_ENVIRONMENT_ATTESTATION_A1_CAPTURED "
            f"path={environment_path} sha256={environment_sha} "
            "fresh_root_runs_observed=0 replay_arms_started=0",
            flush=True,
        )
        return

    sealed_environment = json.loads(environment_path.read_text(encoding="utf-8"))
    if not isinstance(sealed_environment, dict):
        raise TypeError("sealed environment attestation must be a JSON object")
    _validate_existing_environment_attestation(
        sealed_environment,
        protocol=protocol_identity,
        sources=source_identities,
        maps=maps,
        launchers=launchers,
        additional_frozen_files=additional,
        thread_contract=thread_contract,
        execution_plan=plan_summary,
        current_environment=environment,
    )
    environment_sha = _sha256_file(environment_path)

    output_root.mkdir(parents=True, exist_ok=False)
    for relative in ("specs", "raw_arms", "logs", "artifacts"):
        (output_root / relative).mkdir()

    spec_records = []
    checkpoint_path = workspace / CHECKPOINT
    map_dir = workspace / MAP_DIRECTORY
    wrapper_path = workspace / wrapper_relative
    for label, map_name, agents in SCENARIOS:
        for workload in WORKLOADS:
            for method in COMMON_METHODS:
                stem = f"{label}__{workload}__{method}"
                spec = _make_spec(
                    workspace,
                    checkpoint_path,
                    map_dir / map_name,
                    agents,
                    workload,
                    method,
                )
                spec_path = output_root / "specs" / f"{stem}.json"
                raw_path = output_root / "raw_arms" / f"{stem}.json"
                log_path = output_root / "logs" / f"{stem}.log"
                _write_json_exclusive(spec_path, spec)
                command = [
                    sys.executable,
                    str(wrapper_path),
                    "--workspace",
                    str(workspace),
                    "--spec-file",
                    str(spec_path),
                    "--output",
                    str(raw_path),
                    "--expected-wrapper-sha256",
                    wrapper_identity["sha256"],
                    "--expected-validation-runner-sha256",
                    source_identities["validation_runner"]["sha256"],
                    "--expected-claim-runner-sha256",
                    source_identities["claim_runner"]["sha256"],
                ]
                spec_records.append(
                    {
                        "label": label,
                        "map_name": map_name,
                        "agents": agents,
                        "workload": workload,
                        "method": method,
                        "spec": spec,
                        "spec_path": spec_path,
                        "raw_path": raw_path,
                        "log_path": log_path,
                        "command": command,
                    }
                )
    run_context = {
        "schema": "dai.same-call-legacy-current-replay-context/a1",
        "status": "sealed_before_first_arm",
        "sealed_utc": _utc_now(),
        "environment_attestation": {
            "path": _workspace_relative(environment_path, workspace),
            "sha256": environment_sha,
        },
        "plan": plan_summary,
        "commands": [
            {
                "label": record["label"],
                "workload": record["workload"],
                "method": record["method"],
                "spec_path": _workspace_relative(record["spec_path"], workspace),
                "spec_sha256": _sha256_file(record["spec_path"]),
                "argv": record["command"],
                "display": shlex.join(record["command"]),
            }
            for record in spec_records
        ],
    }
    context_path = output_root / "run_context.json"
    _write_json_exclusive(context_path, run_context)

    ledger_path = output_root / "attempts.jsonl"
    ledger_path.touch(exist_ok=False)
    pending = deque(spec_records)
    active: dict[int, dict[str, Any]] = {}
    finished: list[dict[str, Any]] = []
    sequence = 0
    previous_event_hash: str | None = None
    while pending or active:
        while pending and len(active) < args.max_parallel_arms:
            record = pending.popleft()
            log_stream = record["log_path"].open("x", encoding="utf-8")
            process = subprocess.Popen(
                record["command"],
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                cwd=str(workspace),
                env=os.environ.copy(),
                text=True,
            )
            record["process"] = process
            record["log_stream"] = log_stream
            sequence += 1
            previous_event_hash = _append_ledger_event(
                ledger_path,
                {
                    "event": "started",
                    "label": record["label"],
                    "workload": record["workload"],
                    "method": record["method"],
                    "pid": process.pid,
                    "command_argv_sha256": _canonical_sha256(record["command"]),
                    "spec_sha256": _sha256_file(record["spec_path"]),
                },
                sequence,
                previous_event_hash,
            )
            active[process.pid] = record
            print(
                f"started legacy A1 arm pid={process.pid} scenario={record['label']} "
                f"workload={record['workload']} method={record['method']}",
                flush=True,
            )
        made_progress = False
        for pid, record in list(active.items()):
            process = record["process"]
            returncode = process.poll()
            if returncode is None:
                continue
            made_progress = True
            record["log_stream"].close()
            event_name = "completed" if returncode == 0 else "failed"
            raw = None
            execution = {}
            if returncode == 0:
                raw = json.loads(record["raw_path"].read_text(encoding="utf-8"))
                _validate_raw_arm(raw, record["spec"], environment["host"])
                execution = raw["execution"]
                if execution.get("pid") != pid:
                    raise RuntimeError("wrapper PID does not match spawned PID")
                record["raw"] = raw
            record["returncode"] = returncode
            sequence += 1
            previous_event_hash = _append_ledger_event(
                ledger_path,
                {
                    "event": event_name,
                    "label": record["label"],
                    "workload": record["workload"],
                    "method": record["method"],
                    "pid": pid,
                    "boot_id": execution.get("boot_id"),
                    "process_start_ticks": execution.get("process_start_ticks"),
                    "returncode": returncode,
                    "raw_arm_sha256": (
                        _sha256_file(record["raw_path"])
                        if record["raw_path"].is_file()
                        else None
                    ),
                    "log_sha256": _sha256_file(record["log_path"]),
                },
                sequence,
                previous_event_hash,
            )
            finished.append(record)
            del active[pid]
            print(
                f"{event_name} legacy A1 arm pid={pid} scenario={record['label']} "
                f"workload={record['workload']} method={record['method']}",
                flush=True,
            )
        if active and not made_progress:
            time.sleep(0.2)

    failures = [record for record in finished if record["returncode"] != 0]
    if failures:
        failure_path = output_root / "failure.json"
        _write_json_exclusive(
            failure_path,
            {
                "schema": "dai.same-call-legacy-current-replay-failure/a1",
                "status": "failed",
                "environment_attestation_sha256": environment_sha,
                "failed_arms": [
                    {
                        "scenario": record["label"],
                        "workload": record["workload"],
                        "method": record["method"],
                        "returncode": record["returncode"],
                        "log_path": _workspace_relative(record["log_path"], workspace),
                    }
                    for record in failures
                ],
            },
        )
        raise RuntimeError(
            f"legacy A1 replay failed in {len(failures)} arms; preserved {failure_path}"
        )

    ledger = _validate_ledger(ledger_path)
    ledger["path"] = _workspace_relative(ledger_path, workspace)
    if (
        ledger["started_events"] != 36
        or ledger["completed_events"] != 36
        or ledger["failed_events"] != 0
        or ledger["unique_process_count"] != 36
        or ledger["unique_process_instance_count"] != 36
        or ledger["unique_arm_count"] != 36
        or ledger["matched_start_complete_arms"] != 36
    ):
        raise RuntimeError(f"fresh-process ledger gate failed: {ledger}")

    artifact_identities = []
    supplemental = []
    for label, map_name, agents in SCENARIOS:
        selected = [record for record in finished if record["label"] == label]
        identity, csv_identity = _write_scenario_artifact(
            workspace,
            output_root,
            label,
            map_name,
            agents,
            selected,
            environment_sha,
            protocol_identity,
        )
        artifact_identities.append(identity)
        supplemental.append(csv_identity)
    for record in finished:
        for role, path in (
            ("raw_arm", record["raw_path"]),
            ("arm_log", record["log_path"]),
            ("arm_spec", record["spec_path"]),
        ):
            supplemental.append(
                {
                    "role": role,
                    "label": record["label"],
                    "workload": record["workload"],
                    "method": record["method"],
                    "path": _workspace_relative(path, workspace),
                    "sha256": _sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    supplemental.extend(
        [
            {
                "role": "sealed_run_context",
                "path": _workspace_relative(context_path, workspace),
                "sha256": _sha256_file(context_path),
                "size_bytes": context_path.stat().st_size,
            },
            {
                "role": "append_only_attempt_ledger",
                "path": _workspace_relative(ledger_path, workspace),
                "sha256": _sha256_file(ledger_path),
                "size_bytes": ledger_path.stat().st_size,
            },
        ]
    )
    process_instances = [
        (
            record["raw"]["execution"].get("boot_id"),
            record["raw"]["execution"].get("pid"),
            record["raw"]["execution"].get("process_start_ticks"),
        )
        for record in finished
    ]
    replay_attestation = {
        "schema": REPLAY_SCHEMA,
        "status": "complete",
        "completed_utc": _utc_now(),
        "evidence_class": "engineering_compatibility_only_no_effect_inference",
        "root_seed": 17,
        "common_methods": list(COMMON_METHODS),
        "workloads": list(WORKLOADS),
        "scenarios": [label for label, _, _ in SCENARIOS],
        "common_arm_run_count": 36,
        "raw_legacy_run_count": 36,
        "fresh_process_per_arm": True,
        "environment_attestation_sha256": environment_sha,
        "environment_attestation": {
            "path": _workspace_relative(environment_path, workspace),
            "sha256": environment_sha,
        },
        "environment": {
            "host": environment["host"],
            "host_instance_fingerprint_sha256": environment[
                "host_instance_fingerprint_sha256"
            ],
        },
        "protocol": protocol_identity,
        "sources": source_identities,
        "maps": maps,
        "launchers": {
            "legacy_replay": launcher_identity,
            "legacy_arm_wrapper": wrapper_identity,
        },
        "additional_frozen_files": additional,
        "thread_contract": {name: "1" for name in THREAD_ENV},
        "process_attestation": {
            "declared_policy": "one recorded wrapper subprocess invoking frozen legacy _run_one exactly once per arm",
            "unique_pid_count": len({value[1] for value in process_instances}),
            "unique_process_instance_count": len(set(process_instances)),
            "all_hosts_equal_attested_host": all(
                record["raw"]["execution"].get("host") == environment["host"]
                for record in finished
            ),
        },
        "ledger": ledger,
        "artifacts": artifact_identities,
        "supplemental_artifacts": supplemental,
        "commands": run_context["commands"],
    }
    replay_path = output_root / "replay_attestation.json"
    _write_json_exclusive(replay_path, replay_attestation)
    print(
        "SAME_HOST_LEGACY_REPLAY_A1_COMPLETE "
        f"common_arms=36 environment_attestation_sha256={environment_sha} "
        f"replay_attestation={replay_path} replay_sha256={_sha256_file(replay_path)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
