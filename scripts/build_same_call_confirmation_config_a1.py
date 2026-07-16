#!/usr/bin/env python3
"""Build the final A1 confirmation config from sealed preflight evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


FREEZE_SCHEMA = "dai.same-call-implementation-freeze/a1"
SCHEMA = "dai.same-call-confirmation/a1"
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
ROOTS = (
    767369,
    695428,
    323681,
    904171,
    446020,
    434435,
    488565,
    514527,
    544573,
    838809,
)
WORKLOADS = ("stationary", "abrupt", "recurrent")
SCENARIOS = (
    (
        "narrow_r020",
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        218,
    ),
    (
        "narrow_r035",
        "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        382,
    ),
    (
        "regular_r020",
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        255,
    ),
    (
        "regular_r035",
        "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        447,
    ),
)
METADATA = {
    "checkpoint_file": "e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d",
    "checkpoint_params": "6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac",
    "period_on_sim": "9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5",
    "narrow_map": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
    "regular_map": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
}
STANDARD_PREFLIGHT = (
    "unit_suite",
    "engineering_smoke",
    "common_arm_reproducibility",
    "repeated_arm_replay",
    "future_suffix_metamorphic",
    "rng_isolation",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(workspace: Path, value: Path) -> Path:
    return value.expanduser().resolve() if value.is_absolute() else (workspace / value).resolve()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _passed(payload: dict[str, Any]) -> bool:
    audit = payload.get("audit")
    return bool(
        payload.get("passed") is True
        and not (isinstance(audit, dict) and audit.get("passed") is False)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--unit-report", type=Path, required=True)
    parser.add_argument("--preflight-report", type=Path, required=True)
    parser.add_argument("--environment-attestation", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("configs/same_call_confirmation_a1.json")
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    freeze_path = _resolve(workspace, args.freeze_manifest)
    unit_path = _resolve(workspace, args.unit_report)
    preflight_path = _resolve(workspace, args.preflight_report)
    environment_path = _resolve(workspace, args.environment_attestation)
    output = _resolve(workspace, args.output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite final A1 config: {output}")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_freeze_sha256):
        raise ValueError("--expected-freeze-sha256 must be a lowercase SHA-256")
    freeze_sha = _sha(freeze_path)
    if freeze_sha != args.expected_freeze_sha256:
        raise RuntimeError("A1 implementation freeze digest mismatch")
    freeze = _load_object(freeze_path)
    if freeze.get("schema") != FREEZE_SCHEMA or freeze.get("fresh_root_runs_observed") != 0:
        raise ValueError("implementation freeze is not a pre-fresh A1 manifest")
    file_artifacts = freeze.get("file_artifacts")
    if not isinstance(file_artifacts, dict) or not file_artifacts:
        raise ValueError("implementation freeze lacks file_artifacts")
    required_core = {
        "claim_runner",
        "validation_runner",
        "publication_policy",
        "frozen_cnn_generator",
        "online_ggo_adapter",
        "trafficflow_online_env",
        "task_generator",
        "protocol",
        "protocol_a1",
        "analyzer",
        "launcher",
    }
    if not required_core.issubset(file_artifacts):
        raise ValueError(f"implementation freeze lacks {sorted(required_core - set(file_artifacts))}")
    for name, record in file_artifacts.items():
        if not isinstance(record, dict):
            raise TypeError(f"invalid frozen file record {name}")
        path = _resolve(workspace, Path(str(record.get("path", ""))))
        if not path.is_file() or _sha(path) != record.get("sha256"):
            raise RuntimeError(f"frozen file drift before config build: {name}")

    unit = _load_object(unit_path)
    preflight = _load_object(preflight_path)
    environment = _load_object(environment_path)
    if not _passed(unit) or not _passed(preflight):
        raise RuntimeError("unit or full preflight report does not pass")
    if environment.get("schema") != "dai.same-call-environment-attestation/a1":
        raise ValueError("unexpected environment attestation schema")
    if environment.get("fresh_root_runs_observed") != 0:
        raise ValueError("environment attestation was not sealed pre-fresh")
    host = environment.get("environment", {}).get("host")
    if not isinstance(host, str) or not host:
        raise ValueError("environment attestation lacks execution host")

    frozen_artifacts: dict[str, dict[str, Any]] = {
        name: {
            "path": record["path"],
            "sha256": record["sha256"],
            "verification": "file_sha256",
        }
        for name, record in sorted(file_artifacts.items())
    }
    for name, digest in METADATA.items():
        if name in frozen_artifacts:
            raise ValueError(f"metadata/file artifact name collision: {name}")
        frozen_artifacts[name] = {
            "sha256": digest,
            "verification": "artifact_metadata",
        }

    unit_record = {
        "path": str(unit_path.relative_to(workspace)),
        "sha256": _sha(unit_path),
        "passed": True,
    }
    preflight_record = {
        "path": str(preflight_path.relative_to(workspace)),
        "sha256": _sha(preflight_path),
        "passed": True,
    }
    preflight_evidence = {
        name: (unit_record if name == "unit_suite" else preflight_record)
        for name in STANDARD_PREFLIGHT
    }
    preflight_evidence["a1_full_preflight"] = preflight_record

    config = {
        "schema": SCHEMA,
        "status": "frozen_after_passing_a1_preflight_before_fresh_matrix",
        "artifact_config_sha256_field": "development_matrix_config_sha256",
        "methods": list(METHODS),
        "root_seeds": list(ROOTS),
        "workloads": list(WORKLOADS),
        "scenarios": [
            {"id": name, "map_sha256": map_sha, "agents": agents}
            for name, map_sha, agents in SCENARIOS
        ],
        "protocol": {
            "warmup_time": 200,
            "scored_horizon": 2000,
            "decision_window": 20,
            "release_interval_per_agent": 110,
            "guard_suffix_tasks_per_agent": 4,
            "independent_inference_unit": "root_seed",
            "cells_per_root_seed_per_method": 12,
            "total_runs": 960,
            "bootstrap_samples": 10000,
            "bootstrap_seed": 20260715,
            "noninferiority_margin": 0.01,
        },
        "required_frozen_artifacts": sorted(frozen_artifacts),
        "frozen_artifacts": frozen_artifacts,
        "required_preflight_evidence": sorted(preflight_evidence),
        "preflight_evidence": preflight_evidence,
        "target_environment": {
            "path": str(environment_path.relative_to(workspace)),
            "sha256": _sha(environment_path),
            "execution_host": host,
        },
        "provenance": {
            "implementation_freeze_path": str(freeze_path.relative_to(workspace)),
            "implementation_freeze_sha256": freeze_sha,
            "fresh_root_runs_observed_at_freeze": 0,
            "effect_inference_performed_before_config": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(f"SAME_CALL_CONFIRMATION_A1_CONFIG_FROZEN path={output} sha256={_sha(output)}")


if __name__ == "__main__":
    main()
