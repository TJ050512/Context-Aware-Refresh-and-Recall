#!/usr/bin/env python3
"""Execute exactly one frozen legacy common arm in a fresh OS process.

This is a recorded A1 compatibility wrapper, not a second implementation of
the experiment.  It verifies the immutable wrapper/legacy source hashes,
loads the historical validation runner from its exact file, and calls that
runner's ``_run_one`` once.  The wrapper deliberately does not aggregate,
retry, or alter a run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA = "dai.same-call-legacy-current-arm/a1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
COMMON_METHODS = frozenset(
    {"bootstrap_only", "context_memory_B25", "exact_even_B25"}
)
WORKLOADS = frozenset({"stationary", "abrupt", "recurrent"})
SPEC_FIELDS = frozenset(
    {
        "workspace",
        "checkpoint",
        "checkpoint_sha256",
        "checkpoint_params_sha256",
        "split",
        "map_path",
        "agents",
        "warmup_time",
        "horizon",
        "decision_window",
        "release_interval",
        "guard_suffix",
        "sigma",
        "pacing_slack",
        "minimum_history",
        "context_match_threshold",
        "context_recall_margin",
        "context_min_score",
        "context_min_gap",
        "context_maintenance_age",
        "context_maintenance_stability",
        "timing_evidence_valid",
        "seed",
        "workload",
        "method",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _check_sha(path: Path, expected: str, name: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    expected = _validated_digest(expected, name)
    actual = _sha256_file(path)
    if actual != expected:
        raise RuntimeError(
            f"SHA mismatch for {name}: path={path} expected={expected} actual={actual}"
        )
    return actual


def _read_process_start_ticks() -> int | None:
    """Return Linux /proc process start ticks when available."""

    try:
        # Field 22 follows a parenthesized command that may contain spaces.
        tail = Path("/proc/self/stat").read_text(encoding="utf-8").rsplit(") ", 1)[1]
        return int(tail.split()[19])
    except (FileNotFoundError, IndexError, OSError):
        return None


def _read_boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return None


def _pin_torch_threads() -> dict[str, Any]:
    """Apply and attest the A1 one-thread PyTorch contract before inference."""

    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    actual = {
        "version": torch.__version__,
        "num_threads": torch.get_num_threads(),
        "num_interop_threads": torch.get_num_interop_threads(),
    }
    if actual["num_threads"] != 1 or actual["num_interop_threads"] != 1:
        raise RuntimeError(f"PyTorch thread pin failed: {actual}")
    return actual


def _validate_spec(spec: Mapping[str, Any], workspace: Path) -> None:
    if set(spec) != SPEC_FIELDS:
        missing = sorted(SPEC_FIELDS - set(spec))
        extra = sorted(set(spec) - SPEC_FIELDS)
        raise ValueError(f"legacy arm spec field mismatch missing={missing} extra={extra}")
    if Path(str(spec["workspace"])).resolve() != workspace:
        raise ValueError("spec workspace does not match --workspace")
    if spec["split"] != "development" or spec["seed"] != 17:
        raise ValueError("A1 legacy replay is restricted to development root 17")
    if spec["method"] not in COMMON_METHODS:
        raise ValueError(f"unexpected common method {spec['method']!r}")
    if spec["workload"] not in WORKLOADS:
        raise ValueError(f"unexpected workload {spec['workload']!r}")
    if spec["timing_evidence_valid"] is not False:
        raise ValueError("A1 compatibility replay is not timing evidence")
    expected_scalars = {
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
    }
    for field, expected in expected_scalars.items():
        if spec[field] != expected:
            raise ValueError(
                f"unexpected A1 legacy arm value {field}={spec[field]!r}; "
                f"expected {expected!r}"
            )


def _load_legacy_runner(path: Path) -> Any:
    module_name = "dai_frozen_legacy_validation_runner_a1"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load frozen validation runner {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "_run_one", None)):
        raise RuntimeError("frozen validation runner has no callable _run_one")
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--spec-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-wrapper-sha256", required=True)
    parser.add_argument("--expected-validation-runner-sha256", required=True)
    parser.add_argument("--expected-claim-runner-sha256", required=True)
    args = parser.parse_args()

    started_utc = _utc_now()
    workspace = args.workspace.resolve()
    wrapper = Path(__file__).resolve()
    validation_runner = workspace / "scripts/run_claim_aware_budgeted_validation.py"
    claim_runner = workspace / "src/dai_lmapf/claim_runner.py"
    wrapper_sha = _check_sha(
        wrapper, args.expected_wrapper_sha256, "legacy arm wrapper"
    )
    validation_sha = _check_sha(
        validation_runner,
        args.expected_validation_runner_sha256,
        "frozen validation runner",
    )
    claim_sha = _check_sha(
        claim_runner, args.expected_claim_runner_sha256, "frozen claim runner"
    )
    bad_threads = {name: os.environ.get(name) for name in THREAD_ENV if os.environ.get(name) != "1"}
    if bad_threads:
        raise RuntimeError(f"thread contract is not pinned to one: {bad_threads}")
    torch_threads = _pin_torch_threads()

    spec_path = args.spec_file.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite legacy arm output: {output}")
    raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(raw_spec, dict):
        raise TypeError("legacy arm spec must be a JSON object")
    _validate_spec(raw_spec, workspace)
    spec_sha = _sha256_file(spec_path)

    runner = _load_legacy_runner(validation_runner)
    run = runner._run_one(raw_spec)
    if run.get("method") != raw_spec["method"]:
        raise RuntimeError("legacy runner returned the wrong method")
    if run.get("workload") != raw_spec["workload"] or run.get("seed") != 17:
        raise RuntimeError("legacy runner returned the wrong causal cell")

    execution = {
        "host": socket.gethostname(),
        "boot_id": _read_boot_id(),
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "process_start_ticks": _read_process_start_ticks(),
        "started_utc": started_utc,
        "completed_utc": _utc_now(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
        "torch_threads": torch_threads,
    }
    result = {
        "schema": SCHEMA,
        "status": "complete",
        "evidence_class": "engineering_compatibility_only_no_effect_inference",
        "root_seed": 17,
        "spec_path": str(spec_path),
        "spec_sha256": spec_sha,
        "source_lineage": {
            "wrapper_sha256": wrapper_sha,
            "validation_runner_sha256": validation_sha,
            "claim_runner_sha256": claim_sha,
        },
        "execution": execution,
        "run": run,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(
        f"LEGACY_ARM_A1_COMPLETE method={run['method']} "
        f"workload={run['workload']} tasks={run['num_task_finished']} "
        f"output={output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
