#!/usr/bin/env python3
"""Run the A1 frozen source/unit gate and emit append-only JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any


SCHEMA = "dai.same-call-unit-suite/a1"
MANIFEST_SCHEMA = "dai.same-call-implementation-freeze/a1"
EXCLUDED_TESTS = {
    "test_analyze_context_dualcap_development_matrix.py": (
        "historical v3 drift sentinel is pinned to its own earlier source "
        "snapshot; the A1 manifest separately verifies every active and "
        "legacy same-call source"
    ),
}
REQUIRED_ACTIVE_TESTS = frozenset(
    {
        "test_claim_runner.py",
        "test_same_call_claim_runner.py",
        "test_analyze_same_call_confirmation_v1.py",
        "test_audit_same_call_preflight_v1.py",
        "test_audit_same_call_preflight_v2.py",
        "test_same_host_legacy_replay_a1.py",
        "test_publication_policy.py",
        "test_frozen_cnn_generator.py",
        "test_online_ggo_adapter.py",
        "test_absolute_workload.py",
        "test_tasks.py",
    }
)
MINIMUM_TEST_COUNT = 210


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _resolve(workspace: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError("manifest artifact path must be a non-empty string")
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/same_call_unit_suite_a1.json")
    )
    parser.add_argument(
        "--log", type=Path, default=Path("logs/same_call_unit_suite_a1.log")
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    workspace = args.workspace.expanduser().resolve()
    manifest_path = (
        args.freeze_manifest.expanduser().resolve()
        if args.freeze_manifest.is_absolute()
        else (workspace / args.freeze_manifest).resolve()
    )
    output = args.output if args.output.is_absolute() else workspace / args.output
    log = args.log if args.log.is_absolute() else workspace / args.log
    if output.exists() or log.exists():
        raise FileExistsError("refusing to overwrite A1 unit evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    expected_manifest_sha = args.expected_freeze_sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha):
        raise ValueError("--expected-freeze-sha256 must be a lowercase SHA-256")
    observed_manifest_sha = _sha256(manifest_path)
    if observed_manifest_sha != expected_manifest_sha:
        raise RuntimeError(
            "A1 freeze manifest mismatch: "
            f"expected={expected_manifest_sha} actual={observed_manifest_sha}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unexpected A1 freeze manifest schema")
    if manifest.get("fresh_root_runs_observed") != 0:
        raise ValueError("A1 freeze must precede every fresh-root run")
    records = manifest.get("file_artifacts")
    if not isinstance(records, dict) or not records:
        raise ValueError("A1 freeze file_artifacts must be a non-empty object")

    source_checks: dict[str, dict[str, Any]] = {}
    sources_passed = True
    for name, record in sorted(records.items()):
        if not isinstance(record, dict):
            raise ValueError(f"invalid A1 freeze artifact record: {name}")
        path = _resolve(workspace, record.get("path"))
        expected = record.get("sha256")
        actual = _sha256(path) if path.is_file() else None
        passed = isinstance(expected, str) and actual == expected
        sources_passed &= passed
        source_checks[name] = {
            "path": str(path),
            "expected_sha256": expected,
            "observed_sha256": actual,
            "passed": passed,
        }

    tests_dir = workspace / "tests"
    all_tests = sorted(tests_dir.glob("test_*.py"))
    discovered_names = {path.name for path in all_tests}
    missing_active_tests = sorted(REQUIRED_ACTIVE_TESTS - discovered_names)
    selected = [path for path in all_tests if path.name not in EXCLUDED_TESTS]
    command = [sys.executable, "-m", "unittest", *map(str, selected)]
    environment = os.environ.copy()
    pythonpath = [str(workspace / "src"), str(workspace)]
    if environment.get("PYTHONPATH"):
        pythonpath.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)

    started_ns = time.time_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=args.timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        transcript = completed.stdout
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = 124
        transcript = (error.stdout or "") + "\nA1_UNIT_GATE_TIMEOUT\n"
    ended_ns = time.time_ns()
    log.write_text(transcript, encoding="utf-8")

    matches = re.findall(r"Ran (\d+) tests? in", transcript)
    tests_run = int(matches[-1]) if matches else 0
    unittest_passed = bool(
        returncode == 0
        and not timed_out
        and tests_run >= MINIMUM_TEST_COUNT
        and re.search(r"^OK(?: \(|$)", transcript, flags=re.MULTILINE)
    )
    passed = bool(sources_passed and not missing_active_tests and unittest_passed)
    payload = {
        "schema": SCHEMA,
        "status": "complete" if passed else "failed",
        "passed": passed,
        "audit": {
            "passed": passed,
            "sources_passed": sources_passed,
            "unittest_passed": unittest_passed,
            "required_active_tests_present": not missing_active_tests,
            "effect_inference_performed": False,
        },
        "freeze_manifest": {
            "path": str(manifest_path),
            "sha256": observed_manifest_sha,
        },
        "environment": {
            "host_platform": platform.platform(),
            "python": platform.python_version(),
            "executable": sys.executable,
        },
        "source_checks": source_checks,
        "test_selection": {
            "discovered_count": len(all_tests),
            "selected_count": len(selected),
            "selected": [path.name for path in selected],
            "excluded": EXCLUDED_TESTS,
            "required_active_tests": sorted(REQUIRED_ACTIVE_TESTS),
            "missing_active_tests": missing_active_tests,
            "minimum_test_count": MINIMUM_TEST_COUNT,
        },
        "execution": {
            "command": command,
            "cwd": str(workspace),
            "started_ns": started_ns,
            "ended_ns": ended_ns,
            "elapsed_seconds": (ended_ns - started_ns) / 1_000_000_000,
            "timeout_seconds": args.timeout_seconds,
            "timed_out": timed_out,
            "returncode": returncode,
            "tests_run": tests_run,
            "log_path": str(log),
            "log_sha256": _sha256(log),
        },
    }
    _write_json_exclusive(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
