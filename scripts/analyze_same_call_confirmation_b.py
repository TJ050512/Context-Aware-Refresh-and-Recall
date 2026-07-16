#!/usr/bin/env python3
"""Audit and analyze the frozen 40-root Experiment B confirmation matrix.

Experiment B is a standalone replication of the A2 scientific contract.  This
fork verifies the byte-identical v1 analyzer, binds the 40 untouched B roots,
adapts matrix-size bookkeeping, retains the A2 process-instance correction,
and delegates every estimand, bootstrap, Holm, non-inferiority, and tier
calculation to the frozen v1 implementation.

The v1 exact sign-flip implementation enumerates ``2**n`` assignments and is
therefore intractable at ``n=40``.  For B, the *same exact test* is counted by
a meet-in-the-middle algorithm over exact integer representations of the input
binary64 values.  It is not a Monte Carlo or asymptotic replacement.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
V1_PATH = Path(__file__).with_name("analyze_same_call_confirmation_v1.py")
V1_SHA256 = "05fbed132204d6f6b6ea8ecaac6d425957413c921f47ef7d16189f47cb019c53"
FROZEN_RUNNER_SHA256 = (
    "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538"
)
B_PROTOCOL_PATH = ROOT / "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-15_B.md"
B_PROTOCOL_SHA256 = (
    "35de3d61030803e58517b361b90a60a042e6bc68290171ff974e16270a859d06"
)
B_DEFAULT_CONFIG = ROOT / "configs" / "same_call_confirmation_b.json"
B_DEFAULT_OUTPUT_JSON = ROOT / "reports" / "same_call_confirmation_b_analysis.json"
B_DEFAULT_OUTPUT_MD = ROOT / "reports" / "same_call_confirmation_b_analysis.md"
B_ANALYSIS_SCHEMA = "dai.same-call-confirmation-analysis/b"
B_CONFIG_SCHEMA = "dai.same-call-confirmation/b"
B_FREEZE_SCHEMA = "dai.same-call-implementation-freeze/b"
ANALYZER_REVISION = "dai.same-call-confirmation-analyzer/b-40-root-exact"
B_SMOKE_PREFLIGHT_KIND = "b_engineering_smoke"
B_ENVIRONMENT_PREFLIGHT_KIND = "b_environment_attestation"
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
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

B_DERIVATION_SOURCE_SHA256 = (
    "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
)
B_DOMAIN = "dai-same-call-confirmatory-b-power-extension"
B_DERIVATION_FORMULA = (
    "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)"
)
B_ROOTS = (
    880565,
    534821,
    257578,
    500976,
    294860,
    954705,
    190142,
    429853,
    398397,
    560584,
    175381,
    598292,
    461566,
    526869,
    115950,
    130998,
    655067,
    585455,
    362413,
    552654,
    664860,
    253714,
    962860,
    907962,
    381214,
    583444,
    371204,
    934561,
    491276,
    541256,
    523055,
    713041,
    537643,
    699809,
    204011,
    330180,
    113743,
    257704,
    152753,
    657283,
)
A1_ROOTS = (
    767369, 695428, 323681, 904171, 446020,
    434435, 488565, 514527, 544573, 838809,
)
A2_ROOTS = (
    691817, 376110, 263001, 293231, 296805,
    274330, 997942, 319782, 807287, 326454,
)
ROOTS = B_ROOTS
B_ROOT_COUNT = len(B_ROOTS)
B_TOTAL_RUNS = 8 * B_ROOT_COUNT * 4 * 3
B_RUNS_PER_SCENARIO = 8 * B_ROOT_COUNT * 3
B_PAIRED_CELLS_PER_METHOD = B_ROOT_COUNT * 4 * 3
B_LEDGER_EVENTS_PER_SCENARIO = 2 * B_RUNS_PER_SCENARIO

BARE_PID_FAILURE = {
    "category": "fresh_process",
    "check": "one_unique_os_process_per_arm",
}
PROCESS_INSTANCE_CHECK = "unique_host_pid_process_start_per_arm"
RUN_UUID_CHECK = "one_unique_run_uuid_per_arm"
EXACT_ENUMERATION_MAX_ROOTS = 20
SIGN_FLIP_TOLERANCE = 1e-15


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_frozen_v1() -> Any:
    actual = _sha256_file(V1_PATH)
    if actual != V1_SHA256:
        raise RuntimeError(
            "frozen v1 analyzer dependency SHA256 mismatch: "
            f"expected={V1_SHA256} actual={actual} path={V1_PATH}"
        )
    spec = importlib.util.spec_from_file_location(
        "same_call_confirmation_b_frozen_v1_dependency", V1_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen v1 analyzer: {V1_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_frozen_v1()
if _sha256_file(B_PROTOCOL_PATH) != B_PROTOCOL_SHA256:
    raise RuntimeError(
        "frozen B protocol SHA256 mismatch: "
        f"expected={B_PROTOCOL_SHA256} actual={_sha256_file(B_PROTOCOL_PATH)} "
        f"path={B_PROTOCOL_PATH}"
    )

_V1_ROOT_COUNT = len(V1.ROOTS)
_V1_TOTAL_RUNS = V1.TOTAL_RUNS
_ORIGINAL_VALIDATE_CONFIG = V1._validate_config
_ORIGINAL_VALIDATE_ARTIFACT_PROTOCOL = V1._validate_artifact_protocol
_ORIGINAL_VERIFY_ATTEMPT_LEDGER = V1._verify_attempt_ledger
_ORIGINAL_NORMALIZE_AND_AUDIT = V1._normalize_and_audit
_ORIGINAL_COMPARISON = V1._comparison
_ORIGINAL_EXACT_SIGN_FLIP = V1._exact_sign_flip
_ORIGINAL_ANALYZE_ARTIFACTS = V1.analyze_artifacts
_ORIGINAL_RENDER_MARKDOWN = V1.render_markdown

# Bind only B design cardinalities and report identity.  The cells per root,
# methods, workloads, scenarios, bootstrap, margins, and tier logic stay in v1.
V1.ROOTS = B_ROOTS
V1.DEFAULT_CONFIG = B_DEFAULT_CONFIG
V1.TOTAL_RUNS = B_TOTAL_RUNS
V1.RUNS_PER_SCENARIO = B_RUNS_PER_SCENARIO
V1.ANALYSIS_SCHEMA = B_ANALYSIS_SCHEMA
V1.REQUIRED_PREFLIGHT_KINDS = frozenset(
    {*V1.REQUIRED_PREFLIGHT_KINDS, B_SMOKE_PREFLIGHT_KIND}
)

# B.4 explicitly classifies parallel job count as execution-only and permits it
# to be selected from a pre-B smoke.  It is therefore audited by the launcher,
# not frozen to A2's historical value of six inside the scientific analyzer.
V1.ARTIFACT_PROTOCOL_CORE = dict(V1.ARTIFACT_PROTOCOL_CORE)
V1.ARTIFACT_PROTOCOL_CORE.pop("jobs", None)

SameCallConfirmationError = V1.SameCallConfirmationError


def _derive_b_roots() -> tuple[int, ...]:
    roots = []
    for index in range(B_ROOT_COUNT):
        payload = (
            f"{B_DERIVATION_SOURCE_SHA256}|{B_DOMAIN}|{index}".encode("utf-8")
        )
        digest = hashlib.sha256(payload).hexdigest()
        roots.append(100000 + (int(digest[:16], 16) % 900000))
    return tuple(roots)


def _frozen_digest(config: Mapping[str, Any], name: str) -> str:
    frozen = config.get("frozen_artifacts")
    if not isinstance(frozen, Mapping) or name not in frozen:
        raise SameCallConfirmationError(f"B config must freeze artifact {name}")
    record = frozen[name]
    digest = record if isinstance(record, str) else record.get("sha256")
    if not V1._is_sha256(digest):
        raise SameCallConfirmationError(f"frozen_artifacts.{name} lacks SHA-256")
    return str(digest)


def _validate_config_b(config: Mapping[str, Any]) -> None:
    """Apply v1 validation, then fail closed on B provenance and self-freeze."""

    _ORIGINAL_VALIDATE_CONFIG(config)
    if config.get("schema") != B_CONFIG_SCHEMA:
        raise SameCallConfirmationError(
            f"config.schema must equal {B_CONFIG_SCHEMA!r}"
        )
    if tuple(config.get("root_seeds", ())) != B_ROOTS or _derive_b_roots() != B_ROOTS:
        raise SameCallConfirmationError("B root vector is not the frozen derivation")
    if len(set(B_ROOTS)) != B_ROOT_COUNT or set(B_ROOTS) & (
        set(A1_ROOTS) | set(A2_ROOTS)
    ):
        raise SameCallConfirmationError("B roots overlap A1/A2 or contain duplicates")
    expected_top_level = {
        "status": "content_hashed_internal_pre_specification_frozen_before_b_matrix",
        "public_preregistration": False,
        "standalone_replication": True,
        "primary_analysis_pools_with_a1_or_a2": False,
    }
    if any(config.get(field) != value for field, value in expected_top_level.items()):
        raise SameCallConfirmationError("B standalone/freeze status fields differ")
    execution_host = config.get("execution_host")
    target = config.get("target_environment")
    if (
        not isinstance(execution_host, str)
        or not execution_host
        or not isinstance(target, Mapping)
        or target.get("execution_host") != execution_host
    ):
        raise SameCallConfirmationError(
            "B top-level execution_host must match target_environment"
        )

    execution = config.get("execution")
    expected_execution = {
        "scenario_processes": 4,
        "thread_environment": {name: "1" for name in THREAD_ENV},
        "runs_per_scenario": B_RUNS_PER_SCENARIO,
        "attempt_ledger_events_per_scenario": B_LEDGER_EVENTS_PER_SCENARIO,
        "total_runs": B_TOTAL_RUNS,
    }
    if (
        not isinstance(execution, Mapping)
        or not V1._is_positive_integer(execution.get("jobs_per_scenario"))
        or any(execution.get(field) != value for field, value in expected_execution.items())
    ):
        raise SameCallConfirmationError(
            "config.execution.jobs_per_scenario/thread contract/B cardinalities differ"
        )

    protocol = V1._mapping(config.get("protocol"), "config.protocol")
    expected_protocol = {
        "total_runs": B_TOTAL_RUNS,
        "runs_per_scenario": B_RUNS_PER_SCENARIO,
        "attempt_ledger_events_per_scenario": B_LEDGER_EVENTS_PER_SCENARIO,
        "attempt_starts_per_scenario": B_RUNS_PER_SCENARIO,
        "attempt_completions_per_scenario": B_RUNS_PER_SCENARIO,
        "split": V1.SPLIT,
        "fresh_process_per_arm": True,
        "noninferiority_point_estimate_gate": -0.005,
        "noninferiority_comparator": "exact_even_B25",
        "noninferiority_method": "context_memory_B25",
        "noninferiority_alpha": 0.05,
        "superiority_holm_family_size": 6,
    }
    if any(protocol.get(field) != value for field, value in expected_protocol.items()):
        raise SameCallConfirmationError("B protocol cardinality/inference fields differ")

    derivation = config.get("root_derivation")
    expected_derivation = {
        "source_sha256": B_DERIVATION_SOURCE_SHA256,
        "domain": B_DOMAIN,
        "formula": B_DERIVATION_FORMULA,
        "index_start": 0,
        "index_end": B_ROOT_COUNT - 1,
        "count": B_ROOT_COUNT,
    }
    if not isinstance(derivation, Mapping) or any(
        derivation.get(field) != value
        for field, value in expected_derivation.items()
    ):
        raise SameCallConfirmationError("config.root_derivation differs from B freeze")

    identity = config.get("process_identity_gate")
    if not isinstance(identity, Mapping) or (
        identity.get("bare_pid_uniqueness_is_gate") is not False
        or identity.get("unique_process_instances_required") != B_TOTAL_RUNS
        or identity.get("unique_run_uuids_required") != B_TOTAL_RUNS
        or tuple(identity.get("hard_identity", ()))
        != (
            "execution_host",
            "execution_process_id",
            "execution_process_start_ns",
        )
    ):
        raise SameCallConfirmationError("B process-identity gate is incomplete")

    provenance = config.get("provenance")
    zero_fields = (
        "b_effect_estimates_computed_before_config",
        "b_fresh_root_runs_observed_at_freeze",
        "b_method_rankings_inspected_before_config",
    )
    if not isinstance(provenance, Mapping) or any(
        provenance.get(field) != 0 for field in zero_fields
    ):
        raise SameCallConfirmationError("B provenance counters must all be zero")
    if provenance.get("effect_inference_performed_before_config") is not False:
        raise SameCallConfirmationError("B provenance must forbid prior inference")
    prior_disclosure = {
        "prior_a2_outcomes_known": True,
        "standalone_primary_analysis": True,
        "pool_with_a2": False,
    }
    if any(
        provenance.get(field) is not value
        for field, value in prior_disclosure.items()
    ):
        raise SameCallConfirmationError(
            "B provenance must disclose known A2 outcomes and standalone analysis"
        )
    if (
        not isinstance(provenance.get("implementation_freeze_path"), str)
        or not provenance.get("implementation_freeze_path")
        or not V1._is_sha256(provenance.get("implementation_freeze_sha256"))
    ):
        raise SameCallConfirmationError("B implementation-freeze provenance is missing")

    frozen = config.get("frozen_artifacts")
    required = set(config.get("required_frozen_artifacts", ()))
    if not isinstance(frozen, Mapping) or required != set(frozen):
        raise SameCallConfirmationError("B frozen-artifact manifest is not exact")
    b_required = {
        "analyzer_b",
        "builder_b",
        "capture_environment_b",
        "launcher_b",
        "protocol_b",
        "runner_b",
        "predecessor_a2_config",
    }
    if not b_required.issubset(required):
        raise SameCallConfirmationError("required_frozen_artifacts omits B control plane")
    if _frozen_digest(config, "analyzer") != V1_SHA256:
        raise SameCallConfirmationError("base analyzer is not the frozen v1 bytes")
    if _frozen_digest(config, "validation_runner") != FROZEN_RUNNER_SHA256:
        raise SameCallConfirmationError("behavior runner is not the frozen v1 bytes")
    if _frozen_digest(config, "analyzer_b") != _sha256_file(Path(__file__)):
        raise SameCallConfirmationError("B analyzer does not self-bind its bytes")
    if _frozen_digest(config, "protocol_b") != B_PROTOCOL_SHA256:
        raise SameCallConfirmationError("B config does not bind the frozen B protocol")
    if _frozen_digest(config, "a1_effect_blind_failure") != B_DERIVATION_SOURCE_SHA256:
        raise SameCallConfirmationError("B derivation source hash differs from protocol")

    preflight = config.get("preflight_evidence")
    required_preflight = set(config.get("required_preflight_evidence", ()))
    expected_preflight = {
        *INHERITED_PREFLIGHT_KINDS,
        B_SMOKE_PREFLIGHT_KIND,
        B_ENVIRONMENT_PREFLIGHT_KIND,
    }
    if (
        not isinstance(preflight, Mapping)
        or required_preflight != expected_preflight
        or set(preflight) != expected_preflight
    ):
        raise SameCallConfirmationError("B preflight manifest must be the six inherited gates plus B smoke/attestation")
    environment_preflight = preflight[B_ENVIRONMENT_PREFLIGHT_KIND]
    if (
        not isinstance(environment_preflight, Mapping)
        or environment_preflight.get("path") != target.get("path")
        or environment_preflight.get("sha256") != target.get("sha256")
        or environment_preflight.get("passed") is not True
        or environment_preflight.get("b_fresh_root_runs_observed") != 0
    ):
        raise SameCallConfirmationError("B environment preflight differs from target binding")

    analysis_contract = config.get("analysis_contract")
    expected_analysis = {
        "execute_after_complete_integrity_audit_only": True,
        "execute_content_hashed_analyzer_exactly_once": True,
        "whole_root_bootstrap_samples": 10000,
        "whole_root_bootstrap_seed": 20260715,
        "singleton_noninferiority_separate_from_holm_family": True,
        "report_regardless_of_direction": True,
    }
    if not isinstance(analysis_contract, Mapping) or dict(analysis_contract) != expected_analysis:
        raise SameCallConfirmationError("B one-shot analysis contract differs")


V1._validate_config = _validate_config_b


def _validate_artifact_protocol_b(
    artifact: Mapping[str, Any],
    scenario_id: str,
    config: Mapping[str, Any],
    expected_hashes: Mapping[str, str],
) -> None:
    _ORIGINAL_VALIDATE_ARTIFACT_PROTOCOL(
        artifact, scenario_id, config, expected_hashes
    )
    protocol = V1._mapping(artifact.get("protocol"), "artifact.protocol")
    expected_jobs = config["execution"]["jobs_per_scenario"]
    if protocol.get("jobs") != expected_jobs:
        raise SameCallConfirmationError(
            "artifact.protocol.jobs differs from frozen B execution.jobs_per_scenario"
        )


V1._validate_artifact_protocol = _validate_artifact_protocol_b


def _verify_hashed_json(
    config_path: Path, raw_path: Any, digest: Any, field: str
) -> Mapping[str, Any]:
    path = V1._resolve_path(config_path, raw_path, f"{field}.path")
    expected = V1._sha(digest, f"{field}.sha256")
    if not path.is_file() or _sha256_file(path) != expected:
        raise SameCallConfirmationError(f"{field} file/hash verification failed")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SameCallConfirmationError(f"{field} is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise SameCallConfirmationError(f"{field} top level must be an object")
    return payload


def _verify_b_provenance(config: Mapping[str, Any], config_path: Path) -> None:
    provenance = config["provenance"]
    freeze = _verify_hashed_json(
        config_path,
        provenance["implementation_freeze_path"],
        provenance["implementation_freeze_sha256"],
        "provenance.implementation_freeze",
    )
    if freeze.get("schema") != B_FREEZE_SCHEMA:
        raise SameCallConfirmationError("B implementation-freeze schema is invalid")
    for field in (
        "b_effect_estimates_computed",
        "b_fresh_root_runs_observed",
        "b_method_rankings_inspected",
    ):
        if freeze.get(field) != 0:
            raise SameCallConfirmationError(f"implementation freeze {field} must be zero")
    if freeze.get("effect_inference_performed") is not False:
        raise SameCallConfirmationError("implementation freeze records prior inference")
    for field, value in {
        "prior_a2_outcomes_known": True,
        "standalone_primary_analysis": True,
        "pool_with_a2": False,
    }.items():
        if freeze.get(field) is not value:
            raise SameCallConfirmationError(
                "implementation freeze must disclose A2 knowledge and no pooling"
            )
    if freeze.get("root_derivation") != config.get("root_derivation"):
        raise SameCallConfirmationError("implementation freeze root derivation differs")
    if tuple(freeze.get("confirmation_roots", ())) != B_ROOTS:
        raise SameCallConfirmationError("implementation freeze B roots differ")
    exact_freeze_bindings = {
        "methods": config.get("methods"),
        "workloads": config.get("workloads"),
        "scenarios": config.get("scenarios"),
        "execution": config.get("execution"),
        "file_artifacts": config.get("frozen_artifacts"),
        "preflight_evidence": config.get("preflight_evidence"),
        "protocol": config["frozen_artifacts"].get("protocol_b"),
        "b_engineering_smoke": config["preflight_evidence"].get(
            B_SMOKE_PREFLIGHT_KIND
        ),
    }
    if any(freeze.get(field) != value for field, value in exact_freeze_bindings.items()):
        raise SameCallConfirmationError(
            "implementation freeze and B config manifests are not identical"
        )
    predecessor = freeze.get("predecessor_a2_config")
    predecessor_artifact = config["frozen_artifacts"].get("predecessor_a2_config")
    if (
        not isinstance(predecessor, Mapping)
        or not isinstance(predecessor_artifact, Mapping)
        or predecessor.get("path") != predecessor_artifact.get("path")
        or predecessor.get("sha256") != predecessor_artifact.get("sha256")
        or predecessor.get("sha256")
        != config["provenance"].get("predecessor_a2_config_sha256")
    ):
        raise SameCallConfirmationError("B predecessor A2 binding differs")

    target = config.get("target_environment")
    if not isinstance(target, Mapping) or not isinstance(
        target.get("execution_host"), str
    ) or not target.get("execution_host"):
        raise SameCallConfirmationError("B target environment is incomplete")
    attestation = _verify_hashed_json(
        config_path,
        target.get("path"),
        target.get("sha256"),
        "target_environment",
    )
    attested_environment = attestation.get("environment")
    if freeze.get("target_environment") != target:
        raise SameCallConfirmationError(
            "implementation freeze target_environment differs from config"
        )
    if (
        config.get("execution_host") != target.get("execution_host")
        or
        attestation.get("execution_host") != target.get("execution_host")
        or not isinstance(attested_environment, Mapping)
        or attested_environment.get("host") != target.get("execution_host")
    ):
        raise SameCallConfirmationError("target environment host differs from attestation")
    expected_attestation_scalars = {
        "schema": "dai.same-call-environment-attestation/b",
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
    if any(
        attestation.get(field) != value
        for field, value in expected_attestation_scalars.items()
    ):
        raise SameCallConfirmationError("B target attestation safety fields differ")
    if attestation.get("protocol") != config["frozen_artifacts"].get("protocol_b"):
        raise SameCallConfirmationError("B target attestation protocol binding differs")
    expected_contract = {
        "root_seeds": list(B_ROOTS),
        "root_count": B_ROOT_COUNT,
        "roots_disjoint_from_a1_and_a2": True,
        "root_derivation": config.get("root_derivation"),
        "methods": config.get("methods"),
        "workloads": config.get("workloads"),
        "scenario_ids": [row["id"] for row in config.get("scenarios", ())],
        "runs_per_scenario": B_RUNS_PER_SCENARIO,
        "attempt_ledger_events_per_scenario": B_LEDGER_EVENTS_PER_SCENARIO,
        "paired_cells_per_method": B_PAIRED_CELLS_PER_METHOD,
        "total_runs": B_TOTAL_RUNS,
    }
    if attestation.get("experiment_b_contract") != expected_contract:
        raise SameCallConfirmationError("B target attestation scientific contract differs")
    attested_predecessor = attestation.get("predecessor_config")
    if (
        not isinstance(attested_predecessor, Mapping)
        or attested_predecessor.get("path") != predecessor.get("path")
        or attested_predecessor.get("sha256") != predecessor.get("sha256")
    ):
        raise SameCallConfirmationError("B attestation predecessor binding differs")
    compatibility_projection = attestation.get(
        "environment_compatibility_projection"
    )
    if (
        attested_environment.get("host_instance_fingerprint_sha256")
        != target.get("host_instance_fingerprint_sha256")
        or attestation.get("environment_compatibility_projection_sha256")
        != target.get("compatibility_projection_sha256")
        or _canonical_sha256(compatibility_projection)
        != target.get("compatibility_projection_sha256")
    ):
        raise SameCallConfirmationError("B target environment fingerprint differs")
    zero_records = attestation.get("zero_b_outcome_checks")
    if (
        not isinstance(zero_records, list)
        or not zero_records
        or any(
            not isinstance(record, Mapping) or record.get("exists") is not False
            for record in zero_records
        )
    ):
        raise SameCallConfirmationError("B target attestation zero-outcome record differs")
    frozen_artifacts = config["frozen_artifacts"]
    inherited_sources = attestation.get("inherited_file_sources")
    backbone_artifacts = attestation.get("backbone_artifacts")
    b_control_artifacts = attestation.get("b_control_plane_artifacts")
    if not all(
        isinstance(records, Mapping)
        for records in (inherited_sources, backbone_artifacts, b_control_artifacts)
    ):
        raise SameCallConfirmationError("B attestation artifact partitions are missing")
    expected_backbones = {
        "period_on_sim",
        "checkpoint_file",
        "checkpoint_params",
        "narrow_map",
        "regular_map",
    }
    required_b_controls = {
        "runner_b",
        "analyzer_b",
        "launcher_b",
        "builder_b",
        "capture_environment_b",
    }
    partitions = (
        set(inherited_sources), set(backbone_artifacts), set(b_control_artifacts)
    )
    if (
        set(backbone_artifacts) != expected_backbones
        or not required_b_controls.issubset(b_control_artifacts)
        or partitions[0] & partitions[1]
        or partitions[0] & partitions[2]
        or partitions[1] & partitions[2]
        or set().union(*partitions, {"protocol_b", "predecessor_a2_config"})
        != set(frozen_artifacts)
    ):
        raise SameCallConfirmationError(
            "B attestation artifact partitions differ from the frozen manifest"
        )
    for records in (inherited_sources, backbone_artifacts, b_control_artifacts):
        if any(frozen_artifacts.get(label) != record for label, record in records.items()):
            raise SameCallConfirmationError(
                "B attestation artifact record differs from the frozen manifest"
            )


def _has_failure(failures: Sequence[Mapping[str, Any]], check: str) -> bool:
    return any(
        item.get("category") == "fresh_process" and item.get("check") == check
        for item in failures
    )


def _validate_b_artifact_provenance(artifact: Mapping[str, Any]) -> None:
    metadata = artifact.get("split_protocol")
    if not isinstance(metadata, Mapping):
        raise SameCallConfirmationError("artifact.split_protocol is missing")
    expected = {
        "canonical_name": V1.SPLIT,
        "preregistered_seeds": list(B_ROOTS),
        "seed_derivation_source_sha256": B_DERIVATION_SOURCE_SHA256,
        "seed_derivation_domain": B_DOMAIN,
        "complete_same_call_method_family_required": True,
        "complete_workload_family_required": True,
        "artifact_overwrite_permitted": False,
    }
    if any(metadata.get(field) != value for field, value in expected.items()):
        raise SameCallConfirmationError(
            "artifact split/root derivation provenance differs from B protocol"
        )
    derivation = metadata.get("seed_derivation")
    if not isinstance(derivation, str) or not all(
        token in derivation
        for token in (B_DERIVATION_SOURCE_SHA256, B_DOMAIN, "i=0..39")
    ):
        raise SameCallConfirmationError("artifact seed derivation text is incomplete")


def _normalize_and_audit(
    artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    config_sha: str,
    expected_hashes: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Retain the A2 host/PID/start identity correction for Experiment B."""

    for artifact in artifacts:
        _validate_b_artifact_provenance(artifact)
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
    if (
        len(set(process_instances)) != len(runs)
        and not _has_failure(failures, PROCESS_INSTANCE_CHECK)
    ):
        failures.append({"category": "fresh_process", "check": PROCESS_INSTANCE_CHECK})
    if len(set(run_uuids)) != len(runs) and not _has_failure(
        failures, RUN_UUID_CHECK
    ):
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


V1._normalize_and_audit = _normalize_and_audit


def _verify_attempt_ledger_b(
    artifact: Mapping[str, Any], runs: Sequence[Mapping[str, Any]], agents: int
) -> dict[str, int]:
    try:
        return _ORIGINAL_VERIFY_ATTEMPT_LEDGER(artifact, runs, agents)
    except SameCallConfirmationError as error:
        stale = f"exactly {2 * (_V1_TOTAL_RUNS // 4)} events"
        current = f"exactly {B_LEDGER_EVENTS_PER_SCENARIO} events"
        if stale in str(error):
            raise SameCallConfirmationError(str(error).replace(stale, current)) from error
        raise


V1._verify_attempt_ledger = _verify_attempt_ledger_b


def _comparison_b(
    candidate: str,
    comparator: str,
    indexed: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
) -> dict[str, Any]:
    result = _ORIGINAL_COMPARISON(candidate, comparator, indexed)
    result["n_root_seed_clusters"] = B_ROOT_COUNT
    result["n_paired_cells"] = B_PAIRED_CELLS_PER_METHOD
    return result


V1._comparison = _comparison_b


def _binary_integer(value: float) -> tuple[int, int]:
    numerator, denominator = float(value).as_integer_ratio()
    exponent = denominator.bit_length() - 1
    if denominator != 1 << exponent:
        raise AssertionError("binary64 denominator is not a power of two")
    return numerator, exponent


def _signed_sums(weights: Sequence[int]) -> list[int]:
    sums = [0]
    for weight in weights:
        prior = sums
        sums = [value - weight for value in prior]
        sums.extend(value + weight for value in prior)
    return sums


def _threshold_midpoint(
    values: Sequence[float], threshold: float
) -> tuple[list[int], int, bool]:
    """Return scaled weights and the exact rounding boundary below threshold.

    ``math.fsum`` rounds an exact real signed sum to binary64.  A rounded value
    is at least ``threshold`` exactly when its real value is above the midpoint
    between ``threshold`` and its predecessor; equality follows ties-to-even.
    """

    value_parts = [_binary_integer(value) for value in values]
    previous = math.nextafter(threshold, -math.inf)
    threshold_part = _binary_integer(threshold)
    previous_part = _binary_integer(previous)
    midpoint_base_exponent = max(threshold_part[1], previous_part[1])
    midpoint_numerator = (
        previous_part[0] << (midpoint_base_exponent - previous_part[1])
    ) + (threshold_part[0] << (midpoint_base_exponent - threshold_part[1]))
    midpoint_exponent = midpoint_base_exponent + 1
    common_exponent = max(
        midpoint_exponent, *(exponent for _, exponent in value_parts)
    )
    weights = [
        numerator << (common_exponent - exponent)
        for numerator, exponent in value_parts
    ]
    midpoint = midpoint_numerator << (common_exponent - midpoint_exponent)
    raw_bits = struct.unpack(">Q", struct.pack(">d", threshold))[0]
    threshold_is_even = (raw_bits & 1) == 0
    return weights, midpoint, threshold_is_even


def _exact_sign_flip_meet_in_the_middle(root_effects: Sequence[float]) -> dict[str, Any]:
    """Count the frozen one-sided exact sign-flip test in ``O(2**(n/2))``."""

    nonzero = [float(value) for value in root_effects if value != 0.0]
    assignments = 1 << len(nonzero)
    if not nonzero:
        return {
            "method": "exact_root_seed_sign_flip",
            "alternative": "greater",
            "nonzero_root_seeds": 0,
            "ties_omitted": len(root_effects),
            "assignments": 1,
            "p_greater": 1.0,
        }
    observed = math.fsum(nonzero)
    threshold = observed - SIGN_FLIP_TOLERANCE
    if not math.isfinite(threshold):
        raise SameCallConfirmationError("sign-flip statistic must remain finite")
    weights, boundary, inclusive = _threshold_midpoint(nonzero, threshold)
    split = len(weights) // 2
    left = _signed_sums(weights[:split])
    right = _signed_sums(weights[split:])
    right.sort()
    extreme = 0
    if inclusive:
        for partial in left:
            extreme += len(right) - bisect_left(right, boundary - partial)
    else:
        for partial in left:
            extreme += len(right) - bisect_right(right, boundary - partial)
    return {
        "method": "exact_root_seed_sign_flip",
        "alternative": "greater",
        "nonzero_root_seeds": len(nonzero),
        "ties_omitted": len(root_effects) - len(nonzero),
        "assignments": assignments,
        "p_greater": extreme / assignments,
    }


def _exact_sign_flip_b(root_effects: Sequence[float]) -> dict[str, Any]:
    nonzero_count = sum(float(value) != 0.0 for value in root_effects)
    if nonzero_count <= EXACT_ENUMERATION_MAX_ROOTS:
        return _ORIGINAL_EXACT_SIGN_FLIP(root_effects)
    return _exact_sign_flip_meet_in_the_middle(root_effects)


V1._exact_sign_flip = _exact_sign_flip_b


def _postprocess_report(report: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(report)
    result["schema"] = B_ANALYSIS_SCHEMA
    audit = dict(result["audit"])
    audit.pop(f"complete_{_V1_TOTAL_RUNS}_run_matrix", None)
    audit[f"complete_{B_TOTAL_RUNS}_run_matrix"] = (
        audit["totals"]["runs"] == B_TOTAL_RUNS
    )
    result["audit"] = audit
    design = dict(result["design"])
    design.update(
        {
            "root_seeds": list(B_ROOTS),
            "n_root_seed_clusters": B_ROOT_COUNT,
            "total_runs": B_TOTAL_RUNS,
            "runs_per_scenario": B_RUNS_PER_SCENARIO,
            "paired_cells_per_method": B_PAIRED_CELLS_PER_METHOD,
            "root_derivation": {
                "source_sha256": B_DERIVATION_SOURCE_SHA256,
                "domain": B_DOMAIN,
                "formula": B_DERIVATION_FORMULA,
            },
        }
    )
    result["design"] = design
    result["analyzer_revision"] = ANALYZER_REVISION
    result["analyzer_lineage"] = {
        "frozen_v1_path": str(V1_PATH),
        "frozen_v1_sha256": V1_SHA256,
        "b_protocol_path": str(B_PROTOCOL_PATH),
        "b_protocol_sha256": B_PROTOCOL_SHA256,
        "b_root_seeds": list(B_ROOTS),
        "b_root_derivation_domain": B_DOMAIN,
        "correction_scope": (
            "B roots/cardinalities, exact MITM counting, and execution-identity "
            "audit only; estimand, bootstrap, margins, Holm family, three NI "
            "gates, and tier logic unchanged"
        ),
        "sign_flip_counting": "exact meet-in-the-middle for more than 20 nonzero roots",
    }
    return result


def analyze_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    config_path: Path,
    source_labels: Sequence[str] | None = None,
    source_sha256: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run the frozen B analysis after all fail-closed provenance checks."""

    config, _, resolved_config = V1.load_config(config_path)
    _verify_b_provenance(config, resolved_config)
    report = _ORIGINAL_ANALYZE_ARTIFACTS(
        artifacts,
        config_path=resolved_config,
        source_labels=source_labels,
        source_sha256=source_sha256,
    )
    return _postprocess_report(report)


V1.analyze_artifacts = analyze_artifacts


def render_markdown(report: Mapping[str, Any]) -> str:
    text = _ORIGINAL_RENDER_MARKDOWN(report)
    text = text.replace("# Same-call confirmation v1", "# Same-call confirmation B")
    text = text.replace(
        f"Independent observations: {_V1_ROOT_COUNT} root clusters;",
        f"Independent observations: {B_ROOT_COUNT} root clusters;",
    )
    return text


V1.render_markdown = render_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=B_DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=B_DEFAULT_OUTPUT_MD)
    args = parser.parse_args()
    paths = [path.expanduser().resolve() for path in args.artifacts]
    output_json = args.output_json.expanduser().resolve()
    output_md = args.output_md.expanduser().resolve()
    if output_json.exists() or output_md.exists():
        raise SystemExit("ERROR: refusing to overwrite an existing B analysis output")
    try:
        artifacts = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        report = analyze_artifacts(
            artifacts,
            config_path=args.config,
            source_labels=[str(path) for path in paths],
            source_sha256=[_sha256_file(path) for path in paths],
        )
    except (OSError, json.JSONDecodeError, SameCallConfirmationError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "audit_passed": report["audit"]["passed"],
                "outcome_tier": report["outcome_tier"]["tier"],
                "recommendation": report["outcome_tier"]["recommendation"],
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
