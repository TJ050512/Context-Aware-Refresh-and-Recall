#!/usr/bin/env python3
"""Build Experiment B's standalone 40-root confirmation config.

The builder reads control-plane evidence only.  It re-verifies the sealed B
host attestation against the live host, re-hashes every inherited source and
backbone, and then atomically creates the config without overwrite.  The
result is an internal content-hashed pre-specification, not a public
preregistration.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
from typing import Any, Callable, Mapping, Sequence


def _load_common() -> Any:
    path = Path(__file__).with_name("capture_same_call_environment_b.py")
    spec = importlib.util.spec_from_file_location("same_call_b_freeze_common", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import B freeze helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = _load_common()
CONFIG_SCHEMA = "dai.same-call-confirmation/b"
FREEZE_SCHEMA = "dai.same-call-implementation-freeze/b"
INHERITED_PREFLIGHT_KINDS = frozenset(
    {
        "unit_suite",
        "engineering_smoke",
        "common_arm_reproducibility",
        "repeated_arm_replay",
        "future_suffix_metamorphic",
        "rng_isolation",
    }
)


def _record_for_config(record: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(record))


def _verify_attested_b_artifacts(
    workspace: Path,
    attested: Mapping[str, Any],
    *,
    self_path: Path,
    expected_self_sha256: str | None,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for label, raw in sorted(attested.items()):
        if not isinstance(raw, Mapping):
            raise TypeError(f"invalid attested B artifact record: {label}")
        relative = raw.get("path")
        expected = raw.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError(f"incomplete attested B artifact: {label}")
        path = C.resolve_inside(workspace, relative, f"attested B artifact {label}")
        current = C.verify_file(path, expected, f"attested B artifact {label}")
        current["path"] = C.display_path(path, workspace)
        records[label] = current
    required = C.CORE_B_ARTIFACTS | {"capture_environment_b"}
    missing = required - set(records)
    if missing:
        raise ValueError(f"sealed attestation lacks B artifacts: {sorted(missing)}")
    sealed_self_sha256 = str(records["builder_b"]["sha256"])
    if (
        expected_self_sha256 is not None
        and C.require_sha(expected_self_sha256, "B config builder")
        != sealed_self_sha256
    ):
        raise RuntimeError(
            "CLI builder digest differs from the builder sealed in the attestation"
        )
    self_path = C.resolve_inside(workspace, self_path, "B config builder")
    current_self = C.verify_file(self_path, sealed_self_sha256, "B config builder")
    current_self["path"] = C.display_path(self_path, workspace)
    if records.get("builder_b") != current_self:
        raise RuntimeError("live B builder differs from the builder sealed in the attestation")
    return records


def _validate_attestation_contract(
    attestation: Mapping[str, Any],
    *,
    protocol_record: Mapping[str, Any],
    workspace: Path,
    a2_config_path: Path,
    fixed_a2_config_sha256: str,
) -> None:
    expected_scalars = {
        "schema": C.ATTESTATION_SCHEMA,
        "status": "complete",
        "passed": True,
        "created_before_experiment_b": True,
        "b_fresh_root_runs_observed": 0,
        "b_effect_estimates_computed": 0,
        "b_method_rankings_inspected": 0,
        "b_effect_inference_performed": False,
        "prior_a2_outcomes_known": True,
        "standalone_primary_analysis": True,
        "pool_with_a2": False,
        "public_preregistration": False,
    }
    for field, expected in expected_scalars.items():
        if attestation.get(field) != expected:
            raise RuntimeError(
                f"B environment attestation field mismatch {field}: "
                f"expected={expected!r} actual={attestation.get(field)!r}"
            )
    if attestation.get("protocol") != protocol_record:
        raise RuntimeError("B protocol record differs from the sealed attestation")
    predecessor = attestation.get("predecessor_config")
    expected_predecessor = {
        "path": C.display_path(a2_config_path, workspace),
        "sha256": fixed_a2_config_sha256,
        "role": "scientific-contract template; prior A2 outcomes were known and informed B power design",
    }
    if predecessor != expected_predecessor:
        raise RuntimeError("B attestation predecessor-config identity differs")
    contract = attestation.get("experiment_b_contract")
    if not isinstance(contract, Mapping):
        raise RuntimeError("B environment attestation lacks its experiment contract")
    if (
        tuple(contract.get("root_seeds", ())) != C.B_ROOTS
        or contract.get("root_count") != 40
        or contract.get("roots_disjoint_from_a1_and_a2") is not True
        or tuple(contract.get("methods", ())) != C.METHODS
        or tuple(contract.get("workloads", ())) != C.WORKLOADS
        or tuple(contract.get("scenario_ids", ())) != tuple(item[0] for item in C.SCENARIOS)
        or contract.get("runs_per_scenario") != 960
        or contract.get("attempt_ledger_events_per_scenario") != 1920
        or contract.get("paired_cells_per_method") != 480
        or contract.get("total_runs") != 3840
    ):
        raise RuntimeError("B environment attestation scientific contract differs")
    derivation = contract.get("root_derivation")
    expected_derivation = {
        "source_sha256": C.ROOT_SOURCE_SHA256,
        "domain": C.ROOT_DOMAIN,
        "formula": "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)",
        "index_start": 0,
        "index_end": 39,
        "count": 40,
    }
    if not isinstance(derivation, Mapping) or dict(derivation) != expected_derivation:
        raise RuntimeError("B environment attestation root derivation differs")


def _report_passed(payload: Mapping[str, Any]) -> bool:
    audit = payload.get("audit")
    if payload.get("passed") is False:
        return False
    if isinstance(audit, Mapping) and audit.get("passed") is False:
        return False
    return bool(
        payload.get("passed") is True
        or (isinstance(audit, Mapping) and audit.get("passed") is True)
    )


def _verify_preflight_record(
    workspace: Path,
    raw: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    relative = raw.get("path")
    expected = raw.get("sha256")
    if raw.get("passed") is not True or not isinstance(relative, str) or not isinstance(expected, str):
        raise RuntimeError(f"preflight record is incomplete or not declared PASS: {label}")
    path = C.resolve_inside(workspace, relative, f"preflight {label}")
    C.verify_file(path, C.require_sha(expected, f"preflight {label}"), f"preflight {label}")
    payload = C.load_object(path, f"preflight {label}")
    if not _report_passed(payload):
        raise RuntimeError(f"preflight report does not report PASS: {label}")
    return {
        "path": C.display_path(path, workspace),
        "sha256": expected,
        "passed": True,
    }


def _verify_inherited_preflights(
    workspace: Path, a2_config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    evidence = a2_config.get("preflight_evidence")
    if not isinstance(evidence, Mapping) or not INHERITED_PREFLIGHT_KINDS.issubset(evidence):
        raise RuntimeError("A2 config lacks the six frozen v1 preflight kinds")
    return {
        label: _verify_preflight_record(workspace, evidence[label], label)
        for label in sorted(INHERITED_PREFLIGHT_KINDS)
    }


def _verify_b_smoke_record(
    workspace: Path,
    smoke_path: Path,
    expected_sha256: str,
    jobs_per_scenario: int,
) -> dict[str, Any]:
    record = _verify_preflight_record(
        workspace,
        {
            "path": C.display_path(smoke_path, workspace),
            "sha256": C.require_sha(expected_sha256, "B smoke digest"),
            "passed": True,
        },
        "b_engineering_smoke",
    )
    payload = C.load_object(smoke_path, "B engineering smoke")
    smoke_jobs = payload.get("jobs_per_scenario")
    if smoke_jobs is None and isinstance(payload.get("execution"), Mapping):
        smoke_jobs = payload["execution"].get("jobs_per_scenario")
    expected = {
        "schema": "dai.same-call-engineering-smoke/b",
        "status": "complete",
        "passed": True,
        "split": "development",
        "b_root_runs_observed": 0,
        "effect_inference_performed": False,
    }
    if any(payload.get(field) != value for field, value in expected.items()):
        raise RuntimeError("B engineering smoke identity/safety fields are invalid")
    roots = payload.get("root_seeds")
    if roots != [17] or set(roots) & set(C.B_ROOTS):
        raise RuntimeError("B engineering smoke must use only historical root 17")
    if smoke_jobs != jobs_per_scenario:
        raise RuntimeError(
            "jobs_per_scenario must equal the setting exercised by B smoke: "
            f"smoke={smoke_jobs!r} requested={jobs_per_scenario!r}"
        )
    record["jobs_per_scenario"] = jobs_per_scenario
    record["b_root_runs_observed"] = 0
    return record


def build_config(
    *,
    workspace: Path,
    output: Path,
    freeze_output: Path,
    attestation_path: Path,
    expected_attestation_sha256: str,
    smoke_path: Path,
    expected_smoke_sha256: str,
    jobs_per_scenario: int,
    a2_config_path: Path,
    protocol_path: Path,
    self_path: Path,
    expected_self_sha256: str | None,
    formal_outcome_paths: Sequence[Path],
    fixed_protocol_sha256: str = C.PROTOCOL_B_SHA256,
    fixed_a2_config_sha256: str = C.A2_CONFIG_SHA256,
    expected_v1_sha256: str = C.V1_RUNNER_SHA256,
    expected_backbone_sha256: Mapping[str, str] = C.CANONICAL_BACKBONE_SHA256,
    backbone_paths: Mapping[str, str] = C.BACKBONE_PATHS,
    checkpoint_params_hasher: Callable[[Path, Path], str] = C._checkpoint_params_sha256,
    environment_capture: Callable[[], Mapping[str, Any]] | None = None,
    environment_projection: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    live_hostname: str | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    output = C.resolve_inside(workspace, output, "B config output")
    freeze_output = C.resolve_inside(workspace, freeze_output, "B freeze output")
    if output == freeze_output:
        raise ValueError("B config and implementation-freeze outputs must differ")
    occupied = [str(path) for path in (output, freeze_output) if path.exists()]
    if occupied:
        raise FileExistsError(f"refusing to overwrite B sealed outputs: {occupied}")
    if not isinstance(jobs_per_scenario, int) or isinstance(jobs_per_scenario, bool) or jobs_per_scenario < 1:
        raise ValueError("jobs_per_scenario must be a positive integer selected by pre-B smoke")
    for path in formal_outcome_paths:
        checked = C.resolve_inside(workspace, path, "formal B outcome path")
        if checked.exists():
            raise FileExistsError(
                f"cannot freeze B config after a formal outcome path exists: {checked}"
            )

    protocol_path = C.resolve_inside(workspace, protocol_path, "B protocol")
    protocol_record = C.verify_file(protocol_path, fixed_protocol_sha256, "B protocol")
    protocol_record["path"] = C.display_path(protocol_path, workspace)
    a2_config_path = C.resolve_inside(workspace, a2_config_path, "A2 config")
    a2_config, sources, backbones = C.verify_frozen_inputs(
        workspace,
        a2_config_path,
        fixed_a2_config_sha256=fixed_a2_config_sha256,
        expected_v1_sha256=expected_v1_sha256,
        expected_backbone_sha256=expected_backbone_sha256,
        backbone_paths=backbone_paths,
        checkpoint_params_hasher=checkpoint_params_hasher,
    )
    inherited_preflights = _verify_inherited_preflights(workspace, a2_config)
    smoke_path = C.resolve_inside(workspace, smoke_path, "B engineering smoke")
    smoke_record = _verify_b_smoke_record(
        workspace,
        smoke_path,
        expected_smoke_sha256,
        jobs_per_scenario,
    )

    attestation_path = C.resolve_inside(workspace, attestation_path, "B attestation")
    attestation_record = C.verify_file(
        attestation_path,
        C.require_sha(expected_attestation_sha256, "B attestation digest"),
        "B environment attestation",
    )
    attestation_record["path"] = C.display_path(attestation_path, workspace)
    attestation = C.load_object(attestation_path, "B environment attestation")
    _validate_attestation_contract(
        attestation,
        protocol_record=protocol_record,
        workspace=workspace,
        a2_config_path=a2_config_path,
        fixed_a2_config_sha256=fixed_a2_config_sha256,
    )
    if attestation.get("inherited_file_sources") != sources:
        raise RuntimeError("inherited source identities differ from the B attestation")
    if attestation.get("backbone_artifacts") != backbones:
        raise RuntimeError("backbone identities differ from the B attestation")
    attested_b = attestation.get("b_control_plane_artifacts")
    if not isinstance(attested_b, Mapping):
        raise RuntimeError("B attestation lacks control-plane artifact identities")
    b_artifacts = _verify_attested_b_artifacts(
        workspace,
        attested_b,
        self_path=self_path,
        expected_self_sha256=expected_self_sha256,
    )

    sealed_environment = attestation.get("environment")
    sealed_projection = attestation.get("environment_compatibility_projection")
    if not isinstance(sealed_environment, Mapping) or not isinstance(sealed_projection, Mapping):
        raise RuntimeError("B attestation lacks full environment/projection")
    if C.canonical_sha256(sealed_projection) != attestation.get(
        "environment_compatibility_projection_sha256"
    ):
        raise RuntimeError("B attestation compatibility-projection digest is invalid")
    if environment_capture is None or environment_projection is None:
        helper = sources.get("legacy_replay_launcher")
        if not isinstance(helper, Mapping):
            raise RuntimeError("A2 source manifest lacks the environment helper")
        capture, projection = C.load_environment_helpers(workspace / str(helper["path"]))
        environment_capture = environment_capture or capture
        environment_projection = environment_projection or projection
    for name in C.THREAD_ENV:
        os.environ[name] = "1"
    current_environment = dict(environment_capture())
    current_projection = dict(environment_projection(current_environment))
    if dict(environment_projection(sealed_environment)) != dict(sealed_projection):
        raise RuntimeError("stored B compatibility projection is not reproducible")
    if current_projection != dict(sealed_projection):
        raise RuntimeError("live host/runtime differs from the sealed B attestation")
    hostname = live_hostname or socket.gethostname()
    if (
        attestation.get("execution_host") != hostname
        or sealed_environment.get("host") != hostname
        or current_environment.get("host") != hostname
    ):
        raise RuntimeError(
            f"live hostname differs from sealed B host: top_level={attestation.get('execution_host')!r} "
            f"sealed={sealed_environment.get('host')!r} "
            f"captured={current_environment.get('host')!r} live={hostname!r}"
        )
    fingerprint = sealed_environment.get("host_instance_fingerprint_sha256")
    if current_environment.get("host_instance_fingerprint_sha256") != fingerprint:
        raise RuntimeError("live host fingerprint differs from the sealed B attestation")

    zero_records = attestation.get("zero_b_outcome_checks")
    if not isinstance(zero_records, list) or not zero_records:
        raise RuntimeError("B attestation lacks zero-outcome path checks")
    for record in zero_records:
        if not isinstance(record, Mapping) or record.get("exists") is not False:
            raise RuntimeError("invalid zero-outcome record in B attestation")
        checked = C.resolve_inside(workspace, str(record.get("path", "")), "attested zero path")
        if checked.exists():
            raise FileExistsError(f"B path appeared after environment sealing: {checked}")

    frozen_artifacts: dict[str, dict[str, Any]] = {
        label: _record_for_config(record) for label, record in sources.items()
    }
    frozen_artifacts.update(
        {label: _record_for_config(record) for label, record in backbones.items()}
    )
    frozen_artifacts.update(
        {label: _record_for_config(record) for label, record in b_artifacts.items()}
    )
    frozen_artifacts["protocol_b"] = _record_for_config(protocol_record)
    frozen_artifacts["predecessor_a2_config"] = {
        "path": C.display_path(a2_config_path, workspace),
        "sha256": fixed_a2_config_sha256,
        "verification": "file_sha256",
        "size_bytes": a2_config_path.stat().st_size,
    }

    scientific_protocol = copy.deepcopy(a2_config["protocol"])
    scientific_protocol.update(
        {
            "total_runs": 3840,
            "runs_per_scenario": 960,
            "attempt_ledger_events_per_scenario": 1920,
            "attempt_starts_per_scenario": 960,
            "attempt_completions_per_scenario": 960,
            "split": "same_call_confirmation_v1",
            "fresh_process_per_arm": True,
            "sigma": 0.75,
            "context_match_threshold": 0.05,
            "context_recall_margin": 0.02,
            "context_min_score": 0.10,
            "context_min_gap": 6,
            "context_maintenance_age": 25,
            "context_maintenance_stability": 0.20,
            "noninferiority_point_estimate_gate": -0.005,
            "noninferiority_comparator": "exact_even_B25",
            "noninferiority_method": "context_memory_B25",
            "noninferiority_alpha": 0.05,
            "superiority_holm_family_size": 6,
        }
    )
    scenarios = copy.deepcopy(a2_config["scenarios"])
    root_derivation = {
        "source_sha256": C.ROOT_SOURCE_SHA256,
        "domain": C.ROOT_DOMAIN,
        "formula": "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)",
        "index_start": 0,
        "index_end": 39,
        "count": 40,
    }
    preflight_evidence = copy.deepcopy(inherited_preflights)
    preflight_evidence["b_engineering_smoke"] = smoke_record
    preflight_evidence["b_environment_attestation"] = {
        "path": C.display_path(attestation_path, workspace),
        "sha256": expected_attestation_sha256,
        "passed": True,
        "b_fresh_root_runs_observed": 0,
    }

    freeze = {
        "schema": FREEZE_SCHEMA,
        "status": "content_hashed_internal_pre_specification_before_any_b_root",
        "created_utc": C.utc_now(),
        "public_preregistration": False,
        "b_fresh_root_runs_observed": 0,
        "b_effect_estimates_computed": 0,
        "b_method_rankings_inspected": 0,
        "effect_inference_performed": False,
        "effect_inference_scope": "Experiment B only; A2 outcomes were known before this design",
        "prior_a2_outcomes_known": True,
        "standalone_primary_analysis": True,
        "pool_with_a2": False,
        "confirmation_roots": list(C.B_ROOTS),
        "root_derivation": root_derivation,
        "methods": list(C.METHODS),
        "workloads": list(C.WORKLOADS),
        "scenarios": scenarios,
        "execution": {
            "jobs_per_scenario": jobs_per_scenario,
            "scenario_processes": 4,
            "thread_environment": {name: "1" for name in C.THREAD_ENV},
            "runs_per_scenario": 960,
            "attempt_ledger_events_per_scenario": 1920,
            "total_runs": 3840,
        },
        "protocol": _record_for_config(protocol_record),
        "target_environment": {
            "path": C.display_path(attestation_path, workspace),
            "sha256": expected_attestation_sha256,
            "execution_host": hostname,
            "host_instance_fingerprint_sha256": fingerprint,
            "compatibility_projection_sha256": attestation[
                "environment_compatibility_projection_sha256"
            ],
        },
        "b_engineering_smoke": copy.deepcopy(smoke_record),
        "file_artifacts": copy.deepcopy(frozen_artifacts),
        "preflight_evidence": copy.deepcopy(preflight_evidence),
        "predecessor_a2_config": {
            "path": C.display_path(a2_config_path, workspace),
            "sha256": fixed_a2_config_sha256,
        },
    }
    freeze_encoded = C.json_bytes(freeze)
    freeze_sha256 = hashlib.sha256(freeze_encoded).hexdigest()
    config = {
        "schema": CONFIG_SCHEMA,
        "status": "content_hashed_internal_pre_specification_frozen_before_b_matrix",
        "execution_host": hostname,
        "public_preregistration": False,
        "standalone_replication": True,
        "primary_analysis_pools_with_a1_or_a2": False,
        "artifact_config_sha256_field": a2_config["artifact_config_sha256_field"],
        "methods": list(C.METHODS),
        "root_seeds": list(C.B_ROOTS),
        "root_derivation": root_derivation,
        "workloads": list(C.WORKLOADS),
        "scenarios": scenarios,
        "protocol": scientific_protocol,
        "execution": {
            "jobs_per_scenario": jobs_per_scenario,
            "scenario_processes": 4,
            "thread_environment": {name: "1" for name in C.THREAD_ENV},
            "runs_per_scenario": 960,
            "attempt_ledger_events_per_scenario": 1920,
            "total_runs": 3840,
        },
        "process_identity_gate": {
            "hard_identity": [
                "execution_host",
                "execution_process_id",
                "execution_process_start_ns",
            ],
            "unique_process_instances_required": 3840,
            "unique_run_uuids_required": 3840,
            "bare_pid_uniqueness_is_gate": False,
        },
        "required_frozen_artifacts": sorted(frozen_artifacts),
        "frozen_artifacts": frozen_artifacts,
        "required_preflight_evidence": sorted(preflight_evidence),
        "preflight_evidence": preflight_evidence,
        "target_environment": {
            "path": C.display_path(attestation_path, workspace),
            "sha256": expected_attestation_sha256,
            "execution_host": hostname,
            "host_instance_fingerprint_sha256": fingerprint,
            "compatibility_projection_sha256": attestation[
                "environment_compatibility_projection_sha256"
            ],
        },
        "analysis_contract": {
            "execute_after_complete_integrity_audit_only": True,
            "execute_content_hashed_analyzer_exactly_once": True,
            "whole_root_bootstrap_samples": 10000,
            "whole_root_bootstrap_seed": 20260715,
            "singleton_noninferiority_separate_from_holm_family": True,
            "report_regardless_of_direction": True,
        },
        "provenance": {
            "pre_specification_class": "internal_content_hashed_before_any_b_root",
            "public_preregistration": False,
            "protocol_b_sha256": fixed_protocol_sha256,
            "predecessor_a2_config_sha256": fixed_a2_config_sha256,
            "environment_attestation_sha256": expected_attestation_sha256,
            "implementation_freeze_path": C.display_path(freeze_output, workspace),
            "implementation_freeze_sha256": freeze_sha256,
            "b_fresh_root_runs_observed_at_freeze": 0,
            "b_effect_estimates_computed_before_config": 0,
            "b_method_rankings_inspected_before_config": 0,
            "effect_inference_performed_before_config": False,
            "effect_inference_scope": "Experiment B only; prior A2 outcomes were known",
            "prior_a2_outcomes_known": True,
            "standalone_primary_analysis": True,
            "pool_with_a2": False,
        },
    }
    encoded = C.json_bytes(config)

    # Close the normal verification/capture time-of-check window.
    C.verify_file(protocol_path, fixed_protocol_sha256, "B protocol postcheck")
    C.verify_file(a2_config_path, fixed_a2_config_sha256, "A2 config postcheck")
    C.verify_file(attestation_path, expected_attestation_sha256, "B attestation postcheck")
    C.verify_file(smoke_path, expected_smoke_sha256, "B smoke postcheck")
    for label, record in inherited_preflights.items():
        C.verify_file(
            workspace / str(record["path"]),
            str(record["sha256"]),
            f"preflight {label} postcheck",
        )
    for label, record in frozen_artifacts.items():
        if record.get("verification") == "file_sha256":
            C.verify_file(
                workspace / str(record["path"]), str(record["sha256"]), f"{label} postcheck"
            )
    for path in formal_outcome_paths:
        checked = C.resolve_inside(workspace, path, "formal B outcome path postcheck")
        if checked.exists():
            raise FileExistsError(f"formal B outcome path appeared during freeze: {checked}")
    C.write_atomic_exclusive(freeze_output, freeze_encoded)
    C.write_atomic_exclusive(output, encoded)
    return {
        "path": str(output),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "implementation_freeze_path": str(freeze_output),
        "implementation_freeze_sha256": freeze_sha256,
        "execution_host": hostname,
        "jobs_per_scenario": jobs_per_scenario,
        "root_count": 40,
        "total_runs": 3840,
        "b_fresh_root_runs_observed": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("configs/same_call_confirmation_b.json"))
    parser.add_argument("--freeze-output", type=Path, default=Path("configs/same_call_implementation_freeze_b.json"))
    parser.add_argument("--attestation", type=Path, default=Path("reports/same_call_environment_attestation_b.json"))
    parser.add_argument("--expected-attestation-sha256", required=True)
    parser.add_argument("--smoke-report", type=Path, default=Path("reports/same_call_smoke_b.json"))
    parser.add_argument("--expected-smoke-sha256", required=True)
    parser.add_argument("--jobs-per-scenario", type=int, required=True)
    parser.add_argument("--a2-config", type=Path, default=Path("configs/same_call_confirmation_a2.json"))
    parser.add_argument("--protocol", type=Path, default=Path("EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-15_B.md"))
    parser.add_argument(
        "--expected-self-sha256",
        help=(
            "optional independent builder digest; when omitted, the builder is "
            "verified against the digest already sealed in the B attestation"
        ),
    )
    parser.add_argument("--b-results-dir", type=Path, default=Path("results/same_call_confirmation_b"))
    parser.add_argument("--b-logs-dir", type=Path, default=Path("logs/same_call_confirmation_b"))
    parser.add_argument("--b-analysis-json", type=Path, default=Path("reports/same_call_confirmation_b_analysis.json"))
    parser.add_argument("--b-analysis-md", type=Path, default=Path("reports/same_call_confirmation_b_analysis.md"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_config(
        workspace=args.workspace,
        output=args.output,
        freeze_output=args.freeze_output,
        attestation_path=args.attestation,
        expected_attestation_sha256=args.expected_attestation_sha256,
        smoke_path=args.smoke_report,
        expected_smoke_sha256=args.expected_smoke_sha256,
        jobs_per_scenario=args.jobs_per_scenario,
        a2_config_path=args.a2_config,
        protocol_path=args.protocol,
        self_path=Path(__file__),
        expected_self_sha256=args.expected_self_sha256,
        formal_outcome_paths=(
            args.b_results_dir,
            args.b_logs_dir,
            args.b_analysis_json,
            args.b_analysis_md,
        ),
    )
    print("SAME_CALL_CONFIRMATION_B_CONFIG_FROZEN " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
