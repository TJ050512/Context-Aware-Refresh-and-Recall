#!/usr/bin/env python3
"""A2 process-identity correction for the frozen same-call analyzer.

This version delegates every source, integrity, estimand, inference, and tier
calculation to the exact frozen v1 analyzer.  A2 substitutes its preregistered
untouched replacement-root vector and corrects the execution audit to treat an
OS process instance as ``(host, pid, process_start_ns)`` rather than require
the recyclable integer PID to be globally unique across a long-running
matrix.  Canonical run UUID uniqueness remains an independent hard gate.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Any, Mapping, Sequence


V1_PATH = Path(__file__).with_name("analyze_same_call_confirmation_v1.py")
V1_SHA256 = "05fbed132204d6f6b6ea8ecaac6d425957413c921f47ef7d16189f47cb019c53"
A2_PROTOCOL_PATH = V1_PATH.parents[1] / "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md"
A2_PROTOCOL_SHA256 = "c1caaf9532ac728b19761d0eab60628d8e32e4d3a101512b51fa0a5abeebf9dd"
A2_ROOTS = (
    691817,
    376110,
    263001,
    293231,
    296805,
    274330,
    997942,
    319782,
    807287,
    326454,
)
ROOTS = A2_ROOTS
A2_DEFAULT_CONFIG = V1_PATH.parents[1] / "configs" / "same_call_confirmation_a2.json"
ANALYZER_REVISION = "dai.same-call-confirmation-analyzer/a2-process-identity"
BARE_PID_FAILURE = {
    "category": "fresh_process",
    "check": "one_unique_os_process_per_arm",
}
PROCESS_INSTANCE_CHECK = "unique_host_pid_process_start_per_arm"
RUN_UUID_CHECK = "one_unique_run_uuid_per_arm"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_frozen_v1() -> Any:
    actual = _sha256_file(V1_PATH)
    if actual != V1_SHA256:
        raise RuntimeError(
            "frozen v1 analyzer dependency SHA256 mismatch: "
            f"expected={V1_SHA256} actual={actual} path={V1_PATH}"
        )
    spec = importlib.util.spec_from_file_location(
        "same_call_confirmation_frozen_v1_dependency", V1_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen v1 analyzer: {V1_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_frozen_v1()
if _sha256_file(A2_PROTOCOL_PATH) != A2_PROTOCOL_SHA256:
    raise RuntimeError(
        "frozen A2 protocol SHA256 mismatch: "
        f"expected={A2_PROTOCOL_SHA256} actual={_sha256_file(A2_PROTOCOL_PATH)} "
        f"path={A2_PROTOCOL_PATH}"
    )

# A2 invalidates the abandoned A1 vector and changes only this registered
# design constant before any A2 artifact is normalized or any inference runs.
V1.ROOTS = A2_ROOTS
V1.DEFAULT_CONFIG = A2_DEFAULT_CONFIG
SameCallConfirmationError = V1.SameCallConfirmationError
_ORIGINAL_NORMALIZE_AND_AUDIT = V1._normalize_and_audit
_ORIGINAL_ANALYZE_ARTIFACTS = V1.analyze_artifacts


def _has_failure(failures: Sequence[Mapping[str, Any]], check: str) -> bool:
    return any(
        item.get("category") == "fresh_process" and item.get("check") == check
        for item in failures
    )


def _normalize_and_audit(
    artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    config_sha: str,
    expected_hashes: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Apply only the A2 process-instance identity correction."""

    runs, original_failures, original_totals = _ORIGINAL_NORMALIZE_AND_AUDIT(
        artifacts, config, config_sha, expected_hashes
    )
    failures = [
        failure
        for failure in original_failures
        if not (
            failure.get("category") == BARE_PID_FAILURE["category"]
            and failure.get("check") == BARE_PID_FAILURE["check"]
        )
    ]

    bare_pids = [int(run["execution_process_id"]) for run in runs]
    process_instances = [
        (
            str(run["execution_host"]),
            int(run["execution_process_id"]),
            int(run["execution_process_start_ns"]),
        )
        for run in runs
    ]
    run_uuids = [str(run["run_uuid"]) for run in runs]

    # Reinforce the two actual identity gates independently of the v1 result.
    if (
        len(set(process_instances)) != len(runs)
        and not _has_failure(failures, PROCESS_INSTANCE_CHECK)
    ):
        failures.append(
            {"category": "fresh_process", "check": PROCESS_INSTANCE_CHECK}
        )
    if len(set(run_uuids)) != len(runs) and not _has_failure(failures, RUN_UUID_CHECK):
        failures.append({"category": "fresh_process", "check": RUN_UUID_CHECK})

    totals = dict(original_totals)
    totals.pop("unique_execution_processes", None)
    totals.update(
        {
            "unique_bare_pids": len(set(bare_pids)),
            "unique_process_instances": len(set(process_instances)),
            "unique_run_uuids": len(set(run_uuids)),
            "bare_pid_reuse_count": len(runs) - len(set(bare_pids)),
            "bare_pid_uniqueness_is_gate": False,
            "process_instance_uniqueness_is_gate": True,
            "run_uuid_uniqueness_is_gate": True,
        }
    )
    return runs, failures, totals


# The original analyze function resolves this helper through its module global.
V1._normalize_and_audit = _normalize_and_audit


def analyze_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    config_path: Path = A2_DEFAULT_CONFIG,
    source_labels: Sequence[str] | None = None,
    source_sha256: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run the unchanged frozen analysis after the corrected A2 audit."""

    report = _ORIGINAL_ANALYZE_ARTIFACTS(
        artifacts,
        config_path=config_path,
        source_labels=source_labels,
        source_sha256=source_sha256,
    )
    report["analyzer_revision"] = ANALYZER_REVISION
    report["analyzer_lineage"] = {
        "frozen_v1_path": str(V1_PATH),
        "frozen_v1_sha256": V1_SHA256,
        "a2_protocol_path": str(A2_PROTOCOL_PATH),
        "a2_protocol_sha256": A2_PROTOCOL_SHA256,
        "a2_root_seeds": list(A2_ROOTS),
        "correction_scope": "execution identity audit only; estimands, inference, and tier logic unchanged",
    }
    return report


# Let the exact frozen CLI use the versioned analyze entry point above.
V1.analyze_artifacts = analyze_artifacts
render_markdown = V1.render_markdown


def main() -> None:
    V1.main()


if __name__ == "__main__":
    main()
