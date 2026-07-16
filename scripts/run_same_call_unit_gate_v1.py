#!/usr/bin/env python3
"""Run the frozen same-call unit gate and emit audit-ready JSON evidence."""

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


SCHEMA = "dai.same-call-unit-suite/v1"
EXPECTED_SOURCES = {
    "src/dai_lmapf/claim_runner.py": "d9bf61bfa2f86881084b2b1abc19aa0f7483206fa58dcdc88c0b086099d03c2e",
    "scripts/run_claim_aware_budgeted_validation.py": "694c6af03421e653b7d273d6e5f9da3dd6d1ec349f9120b8efe06bf466b33d50",
    "src/dai_lmapf/same_call_claim_runner.py": "53fe48d7fda7638dbd79423d01f4f07de5e13a04938d9a1516855347413ef495",
    "scripts/run_same_call_confirmation_v1.py": "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538",
    "scripts/analyze_same_call_confirmation_v1.py": "05fbed132204d6f6b6ea8ecaac6d425957413c921f47ef7d16189f47cb019c53",
    "scripts/audit_same_call_preflight_v1.py": "d8e73e7fc0ef23483ef2ee1046dbcfc988f47326a4180e322969d1ee7614880e",
    "scripts/run_same_call_smoke_v1.sh": "595e108f4b9fbda448b8d3f1cc363671e055e32a43c13cb917ac376eae3d46fa",
    "scripts/run_same_call_preflight_replays_v1.sh": "b8456b3cd8202a8617650d4ba618ff909cf3d0d5d89390c57198f06fe6efd12d",
    "configs/same_call_implementation_freeze_v1.json": "b4df56441942d8c3fcea8c67207026934a2de4bcc2921b2d307787dcd2520c26",
    "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md": "9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41",
}
EXCLUDED_TESTS = {
    "test_analyze_context_dualcap_development_matrix.py": (
        "historical v3 drift sentinel is pinned to its earlier treatment-source "
        "snapshot; the later event-reserve snapshot is checked separately and "
        "the historical source files remain byte-identical"
    ),
}
REQUIRED_ACTIVE_TESTS = frozenset(
    {
        "test_claim_runner.py",
        "test_same_call_claim_runner.py",
        "test_analyze_same_call_confirmation_v1.py",
        "test_audit_same_call_preflight_v1.py",
        "test_publication_policy.py",
        "test_frozen_cnn_generator.py",
        "test_online_ggo_adapter.py",
        "test_absolute_workload.py",
        "test_tasks.py",
    }
)
MINIMUM_TEST_COUNT = 200


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/same_call_unit_suite_v1.json")
    )
    parser.add_argument(
        "--log", type=Path, default=Path("logs/same_call_unit_suite_v1.log")
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    workspace = args.workspace.expanduser().resolve()
    output = args.output if args.output.is_absolute() else workspace / args.output
    log = args.log if args.log.is_absolute() else workspace / args.log
    if output.exists() or log.exists():
        raise FileExistsError("refusing to overwrite same-call unit evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    source_checks: dict[str, dict[str, Any]] = {}
    sources_passed = True
    for relative, expected in EXPECTED_SOURCES.items():
        path = workspace / relative
        actual = _sha256(path) if path.is_file() else None
        passed = actual == expected
        sources_passed &= passed
        source_checks[relative] = {
            "expected_sha256": expected,
            "observed_sha256": actual,
            "passed": passed,
        }

    tests_dir = workspace / "tests"
    all_tests = sorted(tests_dir.glob("test_*.py"))
    discovered_names = {path.name for path in all_tests}
    absent_declared_exclusions = sorted(set(EXCLUDED_TESTS) - discovered_names)
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
        transcript = (error.stdout or "") + "\nUNIT_GATE_TIMEOUT\n"
    ended_ns = time.time_ns()
    log.write_text(transcript, encoding="utf-8")

    matches = re.findall(r"Ran (\d+) tests? in", transcript)
    tests_run = int(matches[-1]) if matches else 0
    unittest_passed = (
        returncode == 0
        and not timed_out
        and tests_run >= MINIMUM_TEST_COUNT
        and re.search(r"^OK(?: \(|$)", transcript, flags=re.MULTILINE) is not None
    )
    passed = bool(
        sources_passed
        and not missing_active_tests
        and len(selected) > 0
        and unittest_passed
    )
    payload = {
        "schema": SCHEMA,
        "status": "complete" if passed else "failed",
        "passed": passed,
        "audit": {
            "passed": passed,
            "sources_passed": sources_passed,
            "unittest_passed": unittest_passed,
            "required_active_tests_present": not missing_active_tests,
            "excluded_tests_not_executed": not any(
                path.name in EXCLUDED_TESTS for path in selected
            ),
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
            "absent_declared_exclusions": absent_declared_exclusions,
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
    _write_json(output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
