#!/usr/bin/env python3
"""Audit and analyze the frozen same-call confirmation matrix.

The analyzer is deliberately self-contained and one-shot.  It accepts exactly
four scenario artifacts and the frozen configuration, rejects any incomplete
or differently defined matrix, performs all integrity and resource audits
before inference, and mechanically assigns Tier A, B, or C from
``EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md``.

The root seed is the only independent sampling unit.  The twelve
map-density/workload observations sharing a root are averaged before any
bootstrap or sign-flip calculation.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any, Iterable, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "same_call_confirmation_v1.json"
ANALYSIS_SCHEMA = "dai.same-call-confirmation-analysis/v1"
SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
SPLIT = "same_call_confirmation_v1"

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
FOCAL = "context_memory_B25"
EXACT_B25 = "exact_even_B25"
BOOTSTRAP = "bootstrap_only"
NO_REACTIVATION = "context_no_reactivation_B25"
SUPERIORITY_COMPARATORS = (
    BOOTSTRAP,
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
    NO_REACTIVATION,
)
SPARSE_COMPARATORS = (
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
)
WORKLOADS = ("stationary", "abrupt", "recurrent")
ALLOWED_ROUTE_BUILD_REASONS = frozenset(
    {"init_pp", "task_change", "inherited_goal_route"}
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
SCENARIOS = {
    "narrow_r020": {
        "map_sha256": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        "agents": 218,
    },
    "narrow_r035": {
        "map_sha256": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        "agents": 382,
    },
    "regular_r020": {
        "map_sha256": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        "agents": 255,
    },
    "regular_r035": {
        "map_sha256": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        "agents": 447,
    },
}

BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_715
NI_MARGIN = 0.01
TOTAL_RUNS = 8 * 10 * 4 * 3
RUNS_PER_SCENARIO = 8 * 10 * 3
CELLS_PER_ROOT_METHOD = 4 * 3

REQUIRED_PREFLIGHT_KINDS = frozenset(
    {
        "unit_suite",
        "engineering_smoke",
        "common_arm_reproducibility",
        "repeated_arm_replay",
        "future_suffix_metamorphic",
        "rng_isolation",
    }
)
REQUIRED_FROZEN_ARTIFACTS = frozenset(
    {
        "claim_runner",
        "validation_runner",
        "publication_policy",
        "frozen_cnn_generator",
        "online_ggo_adapter",
        "trafficflow_online_env",
        "task_generator",
        "checkpoint_file",
        "checkpoint_params",
        "period_on_sim",
        "narrow_map",
        "regular_map",
        "protocol",
        "analyzer",
        "launcher",
    }
)

# Executable Python/C++ behavior must be verified from bytes available to the
# analyzer.  A digest copied into config and then echoed by an artifact is not
# independent source-manifest evidence.  The few immutable binary/data
# identities below may be metadata-bound because every scenario artifact also
# carries and is checked against the same digest.
METADATA_VERIFIABLE_ARTIFACTS = frozenset(
    {
        "checkpoint_file",
        "checkpoint_params",
        "period_on_sim",
        "narrow_map",
        "regular_map",
    }
)
REQUIRED_LOCAL_FROZEN_ARTIFACTS = REQUIRED_FROZEN_ARTIFACTS - METADATA_VERIFIABLE_ARTIFACTS
ATTEMPT_LEDGER_SCHEMA = "dai.same-call-attempt-ledger/v1"

ARTIFACT_PROTOCOL_CORE = {
    "warmup_time": 200,
    "scored_horizon": 2000,
    "decision_window": 20,
    "num_scored_windows": 100,
    "eligible_post_bootstrap_decisions": 99,
    "b25_budget": 25,
    "release_interval_per_agent": 110,
    "deterministic_agent_stagger": True,
    "guard_suffix_tasks_per_agent": 4,
    "future_suffix_variant": 0,
    "future_suffix_cutoff_absolute": 2200,
    "sigma": 0.75,
    "pacing_slack": 2,
    "minimum_history": 4,
    "method_order_randomized_with_independent_seed": True,
    "fresh_os_process_per_arm": True,
    "jobs": 6,
    "exclusive_timing_declared": False,
    "timing_evidence_valid": False,
}


class SameCallConfirmationError(ValueError):
    """An input is not the matrix frozen by the same-call protocol."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_hex(value: Any, length: int) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_finite_number(value: Any, *, minimum: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    result = float(value)
    return math.isfinite(result) and (minimum is None or result >= minimum)


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value.lower()


def _sha(value: Any, field: str) -> str:
    if not _is_sha256(value):
        raise SameCallConfirmationError(f"{field} must be a lowercase SHA-256")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SameCallConfirmationError(f"{field} must be an integer >= {minimum}")
    return int(value)


def _number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SameCallConfirmationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise SameCallConfirmationError(f"{field} must be a finite number")
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SameCallConfirmationError(f"{field} must be an object")
    return value


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise SameCallConfirmationError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise ValueError("invalid percentile request")
    ordered = sorted(float(value) for value in values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def exact_schedule(budget: int) -> list[int]:
    """Return the frozen global decision indices in ``1..99``."""

    if budget < 0 or budget > 99:
        raise ValueError("budget must lie in [0, 99]")
    return [
        decision
        for decision in range(1, 100)
        if (decision * budget) // 99 > ((decision - 1) * budget) // 99
    ]


def _keyed_uint32(*parts: object) -> int:
    encoded = "\x1f".join(map(str, parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:4], "big")


def random_g5_schedule(root_seed: int) -> list[int]:
    """Reconstruct the keyed schedule committed by the runner."""

    policy_seed = _keyed_uint32("publication-policy", root_seed, "random_G5")
    return sorted(index + 1 for index in random.Random(policy_seed).sample(range(99), 5))


def _resolve_path(config_path: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise SameCallConfirmationError(f"{field} must be a non-empty path")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        root_candidate = ROOT / candidate
        config_candidate = config_path.parent / candidate
        candidate = root_candidate if root_candidate.exists() else config_candidate
    return candidate.resolve()


def load_config(path: Path = DEFAULT_CONFIG) -> tuple[dict[str, Any], str, Path]:
    resolved = path.expanduser().resolve()
    try:
        config = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SameCallConfirmationError(f"cannot read frozen config {resolved}: {error}") from error
    if not isinstance(config, dict):
        raise SameCallConfirmationError("config top level must be an object")
    _validate_config(config)
    return config, _sha256(resolved), resolved


def _validate_config(config: Mapping[str, Any]) -> None:
    if not isinstance(config.get("schema"), str) or "same-call" not in config["schema"]:
        raise SameCallConfirmationError("config.schema must identify same-call confirmation")
    if tuple(config.get("methods", ())) != METHODS:
        raise SameCallConfirmationError("config methods differ from the frozen eight-arm family")
    if tuple(config.get("root_seeds", ())) != ROOTS:
        raise SameCallConfirmationError("config root vector differs from the frozen fresh roots")
    if tuple(config.get("workloads", ())) != WORKLOADS:
        raise SameCallConfirmationError("config workloads differ from the frozen family")
    if config.get("artifact_config_sha256_field") != "development_matrix_config_sha256":
        raise SameCallConfirmationError("config must retain the declared artifact config-hash field")

    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 4:
        raise SameCallConfirmationError("config must contain exactly four scenarios")
    observed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(scenarios):
        row = _mapping(row, f"config.scenarios[{index}]")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise SameCallConfirmationError("each scenario requires a non-empty id")
        if identifier in observed:
            raise SameCallConfirmationError("scenario ids must be unique")
        observed[identifier] = {
            "map_sha256": _sha(row.get("map_sha256"), f"scenario {identifier} map hash"),
            "agents": _integer(row.get("agents"), f"scenario {identifier} agents", minimum=1),
        }
    if observed != SCENARIOS:
        raise SameCallConfirmationError("scenario map hashes or agent counts differ from protocol")

    protocol = _mapping(config.get("protocol"), "config.protocol")
    required_protocol = {
        "warmup_time": 200,
        "scored_horizon": 2000,
        "decision_window": 20,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "independent_inference_unit": "root_seed",
        "cells_per_root_seed_per_method": 12,
        "total_runs": TOTAL_RUNS,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }
    for field, expected in required_protocol.items():
        if protocol.get(field) != expected:
            raise SameCallConfirmationError(
                f"config.protocol.{field} must equal {expected!r}"
            )
    if _number(protocol.get("noninferiority_margin"), "noninferiority_margin") != NI_MARGIN:
        raise SameCallConfirmationError("non-inferiority margin must remain 1%")

    frozen = _mapping(config.get("frozen_artifacts"), "config.frozen_artifacts")
    required = set(config.get("required_frozen_artifacts", REQUIRED_FROZEN_ARTIFACTS))
    if not REQUIRED_FROZEN_ARTIFACTS.issubset(required):
        raise SameCallConfirmationError("required_frozen_artifacts omits protocol sources")
    if not required.issubset(frozen):
        raise SameCallConfirmationError("config.frozen_artifacts is incomplete")
    preflight = _mapping(config.get("preflight_evidence"), "config.preflight_evidence")
    if not REQUIRED_PREFLIGHT_KINDS.issubset(preflight):
        raise SameCallConfirmationError("config.preflight_evidence is incomplete")


def _verify_frozen_artifacts(
    config: Mapping[str, Any], config_path: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    frozen = _mapping(config["frozen_artifacts"], "config.frozen_artifacts")
    required = set(config.get("required_frozen_artifacts", REQUIRED_FROZEN_ARTIFACTS))
    verified: dict[str, Any] = {}
    expected_hashes: dict[str, str] = {}
    for name in sorted(required):
        raw = frozen[name]
        if isinstance(raw, str):
            digest = _sha(raw, f"frozen_artifacts.{name}")
            record: Mapping[str, Any] = {"sha256": digest, "verification": "artifact_metadata"}
        else:
            record = _mapping(raw, f"frozen_artifacts.{name}")
            digest = _sha(record.get("sha256"), f"frozen_artifacts.{name}.sha256")
        expected_hashes[name] = digest
        if record.get("path") is not None:
            path = _resolve_path(config_path, record["path"], f"frozen_artifacts.{name}.path")
            if not path.is_file():
                raise SameCallConfirmationError(f"frozen artifact {name} is missing: {path}")
            observed = _sha256(path)
            if observed != digest:
                raise SameCallConfirmationError(
                    f"frozen artifact {name} hash mismatch: {observed} != {digest}"
                )
            verified[name] = {"path": str(path), "sha256": observed, "verified": True}
        elif (
            name in METADATA_VERIFIABLE_ARTIFACTS
            and record.get("verification") == "artifact_metadata"
        ):
            verified[name] = {
                "sha256": digest,
                "verified": "pending emitted-artifact metadata binding",
            }
        else:
            raise SameCallConfirmationError(
                f"frozen behavior source {name} requires a local path and byte hash"
                if name in REQUIRED_LOCAL_FROZEN_ARTIFACTS
                else f"frozen artifact {name} needs a path or allowed metadata binding"
            )
    return verified, expected_hashes


def _report_passed(payload: Mapping[str, Any]) -> bool:
    audit = payload.get("audit")
    # Explicit failure anywhere wins.  In particular, ``status: complete``
    # means only that a report finished; it can never turn ``passed: false``
    # into evidence of a successful preflight.
    if payload.get("passed") is False:
        return False
    if isinstance(audit, Mapping) and audit.get("passed") is False:
        return False
    return bool(
        payload.get("passed") is True
        or (isinstance(audit, Mapping) and audit.get("passed") is True)
    )


def _verify_preflight(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    preflight = _mapping(config["preflight_evidence"], "config.preflight_evidence")
    verified: dict[str, Any] = {}
    for name in sorted(REQUIRED_PREFLIGHT_KINDS):
        record = _mapping(preflight[name], f"preflight_evidence.{name}")
        if record.get("passed") is not True:
            raise SameCallConfirmationError(f"preflight {name} is not declared passed")
        path = _resolve_path(config_path, record.get("path"), f"preflight_evidence.{name}.path")
        digest = _sha(record.get("sha256"), f"preflight_evidence.{name}.sha256")
        if not path.is_file() or _sha256(path) != digest:
            raise SameCallConfirmationError(f"preflight {name} file/hash verification failed")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SameCallConfirmationError(f"preflight {name} is not valid JSON") from error
        if not isinstance(payload, Mapping) or not _report_passed(payload):
            raise SameCallConfirmationError(f"preflight report {name} does not report PASS")
        verified[name] = {"path": str(path), "sha256": digest, "passed": True}
    return verified


def _expected_metadata_hash(expected: Mapping[str, str], token: str) -> str | None:
    matches = [digest for name, digest in expected.items() if token in name]
    if not matches:
        return None
    if len(set(matches)) != 1:
        raise SameCallConfirmationError(f"ambiguous frozen hash for {token}")
    return matches[0]


def _require_subset(
    observed: Mapping[str, Any], expected: Mapping[str, Any], field: str
) -> None:
    for name, value in expected.items():
        if observed.get(name) != value:
            raise SameCallConfirmationError(
                f"{field}.{name} must equal the frozen value {value!r}"
            )


def _validate_artifact_protocol(
    artifact: Mapping[str, Any],
    scenario_id: str,
    config: Mapping[str, Any],
    expected_hashes: Mapping[str, str],
) -> None:
    protocol = _mapping(artifact.get("protocol"), "artifact.protocol")
    expected_core = dict(ARTIFACT_PROTOCOL_CORE)
    config_protocol = _mapping(config.get("protocol"), "config.protocol")
    for field in (
        "warmup_time",
        "scored_horizon",
        "decision_window",
        "release_interval_per_agent",
        "guard_suffix_tasks_per_agent",
    ):
        expected_core[field] = config_protocol[field]
    _require_subset(protocol, expected_core, "artifact.protocol")
    if protocol.get("agents") != SCENARIOS[scenario_id]["agents"]:
        raise SameCallConfirmationError("artifact protocol agent count differs from scenario")

    exact_contracts = {
        "exact_even_G4": {
            "development_only": True,
            "post_bootstrap_generation_and_switch_quota": 4,
            "mandatory_bootstrap_counts_toward_post_quota": False,
            "total_generator_calls": 5,
            "quota_rule": "exact_even_over_99_eligible_decisions",
        },
        "exact_even_G5": {
            "development_only": True,
            "post_bootstrap_generation_and_switch_quota": 5,
            "mandatory_bootstrap_counts_toward_post_quota": False,
            "total_generator_calls": 6,
            "quota_rule": "exact_even_over_99_eligible_decisions",
        },
        "random_G5": {
            "development_only": True,
            "post_bootstrap_generation_and_switch_quota": 5,
            "mandatory_bootstrap_counts_toward_post_quota": False,
            "total_generator_calls": 6,
            "schedule_rng": "root-keyed local publication-policy stream",
            "quota_rule": "exact_random_without_replacement",
        },
        "js_cap_G5": {
            "development_only": True,
            "score": "active_goal_js_since_last_publication",
            "score_quantile": 0.75,
            "min_gap_windows": 2,
            "minimum_effect_windows": 3,
            "post_bootstrap_generation_and_switch_cap": 5,
            "total_generator_call_cap": 6,
            "quota_rule": "at_most_G5_with_no_catch_up_or_forced_fill",
        },
        FOCAL: {
            "actions": ["hold", "reactivate", "generate"],
            "score": "release_only_4x4_fast2_vs_prior6_js",
            "score_quantile": 0.75,
            "absolute_score_gate": 0.10,
            "active_route_fraction_gate": 0.5,
            "min_gap_windows": 6,
            "maintenance_age_windows": 25,
            "maintenance_stability_gate": 0.20,
            "minimum_effect_windows": 3,
            "context": "causal_active_goal_4x4",
            "recall_threshold": 0.05,
            "recall_margin": 0.02,
            "quota_rule": "at_most_B25_for_both_switches_and_generations",
        },
        NO_REACTIVATION: {
            "development_only": True,
            "base_controller": FOCAL,
            "actions": ["hold", "generate"],
            "forbidden_action": "reactivate",
            "score": "release_only_4x4_fast2_vs_prior6_js",
            "score_quantile": 0.75,
            "absolute_score_gate": 0.10,
            "active_route_fraction_gate": 0.5,
            "min_gap_windows": 6,
            "maintenance_age_windows": 25,
            "maintenance_stability_gate": 0.20,
            "minimum_effect_windows": 3,
            "context": "causal_active_goal_4x4",
            "post_bootstrap_generation_and_switch_cap": 25,
            "quota_rule": "at_most_B25_without_reactivation",
        },
    }
    for method, expected in exact_contracts.items():
        _require_subset(
            _mapping(protocol.get(method), f"artifact.protocol.{method}"),
            expected,
            f"artifact.protocol.{method}",
        )

    runtime = _mapping(artifact.get("runtime_manifest"), "artifact.runtime_manifest")
    sources = _mapping(runtime.get("sources"), "artifact.runtime_manifest.sources")
    source_expectations = {
        name: expected_hashes[name]
        for name in (
            "claim_runner",
            "validation_runner",
            "publication_policy",
            "frozen_cnn_generator",
            "online_ggo_adapter",
            "trafficflow_online_env",
            "task_generator",
            "period_on_sim",
            "checkpoint_file",
            "protocol",
        )
    }
    source_expectations["map"] = expected_hashes[
        "narrow_map" if scenario_id.startswith("narrow_") else "regular_map"
    ]
    for name, expected_digest in source_expectations.items():
        record = _mapping(sources.get(name), f"runtime_manifest.sources.{name}")
        if not isinstance(record.get("path"), str) or not record["path"]:
            raise SameCallConfirmationError(f"runtime source {name} lacks its path")
        if _sha(record.get("sha256"), f"runtime source {name} hash") != expected_digest:
            raise SameCallConfirmationError(f"runtime source {name} differs from frozen config")
    environment = _mapping(runtime.get("environment"), "artifact.runtime_manifest.environment")
    for field in ("platform", "python", "numpy", "torch"):
        if not isinstance(environment.get(field), str) or not environment[field]:
            raise SameCallConfirmationError(f"runtime environment lacks {field}")
    for field in ("torch_num_threads", "torch_num_interop_threads"):
        if environment.get(field) != 1:
            raise SameCallConfirmationError(f"runtime environment {field} must equal 1")
    if not _is_positive_integer(environment.get("cpu_count")):
        raise SameCallConfirmationError("runtime environment cpu_count is invalid")
    if not isinstance(environment.get("torch_cuda_available"), bool):
        raise SameCallConfirmationError("runtime environment CUDA availability is invalid")
    thread_environment = _mapping(
        environment.get("thread_environment"), "runtime thread environment"
    )
    for field in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        if thread_environment.get(field) != "1":
            raise SameCallConfirmationError(
                f"runtime thread environment {field} must equal '1'"
            )


def _validate_pairing_payload(run: Mapping[str, Any], agents: int) -> None:
    manifest_id = run.get("manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id:
        raise SameCallConfirmationError("run manifest_id must be non-empty")
    identity = _mapping(run.get("task_tape_identity"), "run.task_tape_identity")
    required_identity = {
        "mode",
        "schema_version",
        "manifest_sha256",
        "content_fnv1a64",
        "start_locations",
        "per_agent_lengths",
        "total_tasks",
    }
    if not required_identity.issubset(identity):
        raise SameCallConfirmationError("task-tape identity is incomplete")
    if identity.get("mode") != "absolute_release_queue_per_agent":
        raise SameCallConfirmationError("task-tape mode is not absolute release")
    if identity.get("schema_version") != "dai.kiva-absolute-release-tape/v1":
        raise SameCallConfirmationError("task-tape schema differs from the frozen tape")
    manifest_sha = _sha(identity.get("manifest_sha256"), "task tape manifest hash")
    if not _is_hex(identity.get("content_fnv1a64"), 16):
        raise SameCallConfirmationError("task tape FNV identity is invalid")
    starts = identity.get("start_locations")
    lengths = identity.get("per_agent_lengths")
    if (
        not isinstance(starts, list)
        or len(starts) != agents
        or not all(_is_nonnegative_integer(item) for item in starts)
        or len(set(starts)) != agents
    ):
        raise SameCallConfirmationError("task-tape starts are invalid")
    if (
        not isinstance(lengths, list)
        or len(lengths) != agents
        or not all(_is_positive_integer(item) for item in lengths)
        or identity.get("total_tasks") != sum(lengths)
    ):
        raise SameCallConfirmationError("task-tape lengths are invalid")
    expected_fragment = f":{run['workload']}:{run['root_seed']}:{manifest_sha[:16]}"
    if not manifest_id.endswith(expected_fragment):
        raise SameCallConfirmationError("manifest_id does not bind workload/root/tape hash")
    for field in (
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    ):
        _sha(run.get(field), f"run.{field}")
    arrival = _mapping(run.get("workload_arrival"), "run.workload_arrival")
    expected_arrival = {
        "name": "dai_claim_absolute_workload/v1",
        "root_seed": run["root_seed"],
        "workload": run["workload"],
        "warmup_time": 200,
        "scored_horizon": 2000,
        "release_interval_per_agent": 110,
        "guard_suffix_tasks_per_agent": 4,
        "schedule": "deterministic_agent_stagger/v1",
    }
    _require_subset(arrival, expected_arrival, "run.workload_arrival")
    if not _is_nonnegative_integer(arrival.get("task_seed")):
        raise SameCallConfirmationError("workload arrival task_seed is invalid")


def _attempt_identity(run: Mapping[str, Any], agents: int) -> dict[str, Any]:
    return {
        "split": str(run["split"]),
        "map_id": str(run["map_id"]),
        "agents": agents,
        "seed": int(run["seed"]),
        "workload": str(run["workload"]),
        "method": str(run["method"]),
    }


def _verify_attempt_ledger(
    artifact: Mapping[str, Any], runs: Sequence[Mapping[str, Any]], agents: int
) -> dict[str, int]:
    record = _mapping(artifact.get("attempt_ledger"), "artifact.attempt_ledger")
    if record.get("schema") != ATTEMPT_LEDGER_SCHEMA:
        raise SameCallConfirmationError("attempt ledger schema is invalid")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise SameCallConfirmationError("attempt ledger path is missing")
    path = Path(raw_path).expanduser().resolve()
    digest = _sha(record.get("sha256"), "attempt ledger hash")
    if not path.is_file() or _sha256(path) != digest:
        raise SameCallConfirmationError("attempt ledger file/hash verification failed")
    events: list[Mapping[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                raise SameCallConfirmationError(
                    f"attempt ledger contains a blank line at {line_number}"
                )
            event = json.loads(line)
            if not isinstance(event, Mapping):
                raise SameCallConfirmationError("attempt ledger events must be objects")
            events.append(event)
    except json.JSONDecodeError as error:
        raise SameCallConfirmationError("attempt ledger is not valid JSONL") from error
    if len(events) != 2 * RUNS_PER_SCENARIO:
        raise SameCallConfirmationError("attempt ledger must contain exactly 480 events")
    if record.get("started_events") != RUNS_PER_SCENARIO or record.get(
        "completed_events"
    ) != RUNS_PER_SCENARIO:
        raise SameCallConfirmationError("attempt ledger declared counts are invalid")

    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for event in events:
        if event.get("schema") != ATTEMPT_LEDGER_SCHEMA:
            raise SameCallConfirmationError("attempt ledger contains another schema")
        event_name = event.get("event")
        if event_name not in {"started", "completed"}:
            raise SameCallConfirmationError("attempt ledger contains failure/retry/unknown events")
        identity = _mapping(event.get("identity"), "attempt identity")
        if set(identity) != {"split", "map_id", "agents", "seed", "workload", "method"}:
            raise SameCallConfirmationError("attempt identity fields are incomplete or expanded")
        attempt_id = _sha(event.get("attempt_id"), "attempt id")
        if attempt_id != _canonical_sha256(identity):
            raise SameCallConfirmationError("attempt id does not hash its identity")
        bucket = grouped.setdefault(attempt_id, {})
        if event_name in bucket:
            raise SameCallConfirmationError("attempt ledger contains a duplicate/retry event")
        bucket[event_name] = event

    expected_by_id = {
        _canonical_sha256(identity): (identity, run)
        for run in runs
        for identity in [_attempt_identity(run, agents)]
    }
    if len(expected_by_id) != RUNS_PER_SCENARIO or set(grouped) != set(expected_by_id):
        raise SameCallConfirmationError("attempt ledger identities do not cover final arms exactly")
    for attempt_id, (expected_identity, run) in expected_by_id.items():
        bucket = grouped[attempt_id]
        if set(bucket) != {"started", "completed"}:
            raise SameCallConfirmationError("attempt ledger contains an unfinished/deleted arm")
        started = bucket["started"]
        completed = bucket["completed"]
        if started["identity"] != expected_identity or completed["identity"] != expected_identity:
            raise SameCallConfirmationError("attempt ledger identity changed during execution")
        start_time = started.get("time_ns")
        completion_time = completed.get("time_ns")
        process_start = run.get("execution_process_start_ns")
        if not all(_is_positive_integer(item) for item in (start_time, process_start, completion_time)):
            raise SameCallConfirmationError("attempt timestamps are invalid")
        if not int(start_time) <= int(process_start) <= int(completion_time):
            raise SameCallConfirmationError("attempt timestamps are not causally ordered")
        if (
            started.get("runner_parent_process_id") != run.get("execution_parent_process_id")
            or completed.get("runner_parent_process_id") != run.get("execution_parent_process_id")
            or completed.get("execution_process_id") != run.get("execution_process_id")
            or completed.get("execution_host") != run.get("execution_host")
            or completed.get("execution_process_start_ns") != process_start
            or completed.get("run_uuid") != run.get("run_uuid")
            or completed.get("planner_timeouts") != run.get("planner_timeouts")
            or completed.get("safety_passed") is not True
            or completed.get("invariants_passed") is not True
        ):
            raise SameCallConfirmationError("attempt completion differs from retained run")
        emitted_run = {key: value for key, value in run.items() if key != "scenario_id"}
        if completed.get("run_sha256") != _canonical_sha256(emitted_run):
            raise SameCallConfirmationError("attempt completion run hash differs from artifact")
    return {
        "started": RUNS_PER_SCENARIO,
        "completed": RUNS_PER_SCENARIO,
        "failed_or_retry_events": 0,
        "unfinished": 0,
    }


def _schedule_from_timeline(run: Mapping[str, Any]) -> tuple[list[int], dict[str, Any]]:
    timeline = run.get("publication_timeline")
    if not isinstance(timeline, list) or len(timeline) != 100:
        raise SameCallConfirmationError("each run requires a 100-decision publication timeline")
    if not all(isinstance(item, Mapping) for item in timeline):
        raise SameCallConfirmationError("publication timeline rows must be objects")
    if [item.get("decision_index") for item in timeline] != list(range(100)):
        raise SameCallConfirmationError("publication timeline indices must be 0..99")
    post = timeline[1:]
    schedule = [
        int(item["decision_index"])
        for item in post
        if item.get("accepted") is True
    ]
    counts = {
        "switches": len(schedule),
        "generations": sum(item.get("executed_operation") == "generate" for item in post),
        "reactivations": sum(item.get("executed_operation") == "reactivate" for item in post),
        "generation_schedule": [
            int(item["decision_index"])
            for item in post
            if item.get("executed_operation") == "generate"
        ],
        "reactivation_schedule": [
            int(item["decision_index"])
            for item in post
            if item.get("executed_operation") == "reactivate"
        ],
        "charged_switches": sum(
            item.get("charged_to_post_bootstrap_budget") is True for item in post
        ),
        "charged_generations": sum(
            item.get("charged_to_generator_budget") is True for item in post
        ),
    }
    return schedule, counts


def _audit_timeline_contract(
    run: Mapping[str, Any], failures: list[dict[str, Any]]
) -> None:
    timeline = run.get("publication_timeline")
    if not isinstance(timeline, list) or len(timeline) != 100 or not all(
        isinstance(row, Mapping) for row in timeline
    ):
        _failure(failures, "budget", "timeline_complete_objects", run)
        return
    checks: dict[str, bool] = {
        "timeline_indices_0_to_99": [row.get("decision_index") for row in timeline]
        == list(range(100)),
    }
    bootstrap = timeline[0]
    checks.update(
        {
            "bootstrap_exact_timing": bootstrap.get("scored_timestep") == 0
            and bootstrap.get("absolute_timestep") == 200,
            "bootstrap_is_mandatory_generation": bootstrap.get("requested") is True
            and bootstrap.get("accepted") is True
            and bootstrap.get("requested_operation") == "bootstrap_generate"
            and bootstrap.get("executed_operation") == "bootstrap_generate",
            "bootstrap_outside_all_post_budgets": all(
                bootstrap.get(field) is False
                for field in (
                    "charged_to_post_bootstrap_budget",
                    "charged_to_post_bootstrap_switch_cap",
                    "charged_to_post_bootstrap_generation_cap",
                    "charged_to_generator_budget",
                )
            ),
            "bootstrap_guidance_identity": bootstrap.get(
                "guidance_version_before_decision"
            )
            == 0
            and bootstrap.get("guidance_version_installed_for_window") == 1
            and bootstrap.get("active_generation_id_after") == 1,
        }
    )
    expected_version = 1
    known_generation_ids = {1}
    next_generation_id = 2
    active_generation_id = 1
    row_contract = True
    version_contract = True
    generation_contract = True
    timing_contract = True
    for decision, row in enumerate(timeline[1:], 1):
        operation = row.get("executed_operation")
        accepted = row.get("accepted")
        is_switch = operation in {"generate", "reactivate"}
        row_contract &= (
            operation in {"hold", "generate", "reactivate"}
            and isinstance(accepted, bool)
            and accepted is is_switch
            and row.get("charged_to_post_bootstrap_budget") is is_switch
            and row.get("charged_to_post_bootstrap_switch_cap") is is_switch
            and row.get("charged_to_post_bootstrap_generation_cap")
            is (operation == "generate")
            and row.get("charged_to_generator_budget") is (operation == "generate")
        )
        timing_contract &= row.get("scored_timestep") == decision * 20 and row.get(
            "absolute_timestep"
        ) == 200 + decision * 20
        before = row.get("guidance_version_before_decision")
        installed = row.get("guidance_version_installed_for_window")
        version_contract &= before == expected_version
        if is_switch:
            expected_version += 1
        version_contract &= installed == expected_version
        if operation == "generate":
            generation_contract &= row.get("target_generation_id") is None
            generation_contract &= row.get("active_generation_id_after") == next_generation_id
            active_generation_id = next_generation_id
            known_generation_ids.add(next_generation_id)
            next_generation_id += 1
        elif operation == "reactivate":
            target = row.get("target_generation_id")
            generation_contract &= (
                _is_positive_integer(target)
                and target in known_generation_ids
                and target != active_generation_id
                and row.get("active_generation_id_after") == target
            )
            if _is_positive_integer(target):
                active_generation_id = int(target)
        else:
            generation_contract &= row.get("active_generation_id_after") == active_generation_id
    checks["post_row_operation_charge_bijection"] = row_contract
    checks["timeline_exact_scored_and_absolute_times"] = timing_contract
    checks["timeline_guidance_versions_exact"] = version_contract
    checks["timeline_generation_id_semantics"] = generation_contract
    for check, passed in checks.items():
        if not passed:
            _failure(failures, "budget", check, run)


def _run_budget(run: Mapping[str, Any]) -> dict[str, int]:
    budget = _mapping(run.get("budget"), "run.budget")
    values = {
        "mandatory": _integer(budget.get("mandatory_bootstrap_calls"), "mandatory bootstrap"),
        "registered": _integer(budget.get("post_bootstrap_budget"), "post budget"),
        "publications": _integer(budget.get("post_bootstrap_publication_count"), "post publications"),
        "generations": _integer(budget.get("post_bootstrap_generation_count"), "post generations"),
        "reactivations": _integer(budget.get("post_bootstrap_reactivation_count"), "post reactivations"),
        "switches": _integer(budget.get("effective_guidance_switch_count"), "effective switches"),
        "calls": _integer(budget.get("total_generator_calls"), "total calls"),
        "violations": _integer(budget.get("budget_violation_attempts"), "budget violations"),
    }
    return values


def _failure(
    failures: list[dict[str, Any]], category: str, check: str, run: Mapping[str, Any], detail: Any = None
) -> None:
    item: dict[str, Any] = {
        "category": category,
        "check": check,
        "cell": {
            "scenario_id": run.get("scenario_id"),
            "method": run.get("method"),
            "root_seed": run.get("root_seed", run.get("seed")),
            "workload": run.get("workload"),
        },
    }
    if detail is not None:
        item["detail"] = detail
    failures.append(item)


def _audit_budget(run: Mapping[str, Any], failures: list[dict[str, Any]]) -> None:
    method = str(run["method"])
    budget = _mapping(run.get("budget"), "run.budget")
    values = _run_budget(run)
    _audit_timeline_contract(run, failures)
    schedule, timeline = _schedule_from_timeline(run)
    checks: dict[str, bool] = {
        "mandatory_bootstrap_is_one": values["mandatory"] == 1,
        "operation_partition": values["generations"] + values["reactivations"] == values["publications"],
        "switch_count_matches_publications": values["switches"] == values["publications"],
        "generator_conservation": values["calls"] == 1 + values["generations"],
        "timeline_switches_match": timeline["switches"] == values["switches"],
        "timeline_generations_match": timeline["generations"] == values["generations"],
        "timeline_reactivations_match": timeline["reactivations"] == values["reactivations"],
        "timeline_switch_charges_match": timeline["charged_switches"] == values["switches"],
        "timeline_generator_charges_match": timeline["charged_generations"] == values["generations"],
        "flat_calls_match": run.get("generator_calls") == values["calls"],
        "flat_publications_match": run.get("post_bootstrap_publication_count") == values["publications"],
        "flat_generations_match": run.get("post_bootstrap_generation_count") == values["generations"],
        "flat_reactivations_match": run.get("post_bootstrap_reactivation_count") == values["reactivations"],
        "zero_budget_violations": values["violations"] == 0 and run.get("budget_violation_count") == 0,
        "runner_cap_passed": budget.get("cap_satisfied") is True,
        "runner_generation_cap_passed": budget.get("generation_cap_satisfied") is True,
        "runner_call_cap_passed": budget.get("total_generator_call_cap_satisfied") is True,
    }

    exact_budget = {
        BOOTSTRAP: 0,
        "exact_even_G4": 4,
        "exact_even_G5": 5,
        "random_G5": 5,
        EXACT_B25: 25,
    }
    if method in exact_budget:
        quota = exact_budget[method]
        checks.update(
            {
                "exact_registered_quota": values["registered"] == quota,
                "exact_publication_quota": values["publications"] == quota,
                "exact_generation_quota": values["generations"] == quota,
                "exact_zero_reactivation": values["reactivations"] == 0,
                "exact_quota_required": budget.get("exact_quota_required") is True,
                "exact_quota_satisfied": budget.get("exact_quota_satisfied") is True,
                "exact_semantics": budget.get("budget_semantics") == "exact",
            }
        )
    elif method == "js_cap_G5":
        checks.update(
            {
                "js_registered_cap_5": values["registered"] == 5,
                "js_at_most_5": values["publications"] <= 5,
                "js_generation_only": values["publications"] == values["generations"] and values["reactivations"] == 0,
                "js_not_exact": budget.get("exact_quota_required") is False,
            }
        )
    elif method == NO_REACTIVATION:
        checks.update(
            {
                "no_reactivation_b25_cap": values["registered"] == 25 and values["publications"] <= 25,
                "no_reactivation_generation_only": values["publications"] == values["generations"],
                "no_reactivation_zero_recalls": values["reactivations"] == 0,
                "no_reactivation_not_exact": budget.get("exact_quota_required") is False,
            }
        )
    elif method == FOCAL:
        checks.update(
            {
                "context_b25_switch_cap": values["registered"] == 25 and values["publications"] <= 25,
                "context_generation_cap": values["generations"] <= 25,
                "context_not_exact": budget.get("exact_quota_required") is False,
            }
        )

    declared = run.get("precommitted_post_bootstrap_schedule")
    if method == "exact_even_G4":
        checks["g4_schedule"] = (
            declared
            == exact_schedule(4)
            == schedule
            == timeline["generation_schedule"]
        )
    elif method == "exact_even_G5":
        checks["g5_schedule"] = (
            declared
            == exact_schedule(5)
            == schedule
            == timeline["generation_schedule"]
        )
    elif method == EXACT_B25:
        checks["b25_schedule"] = (
            declared
            == exact_schedule(25)
            == schedule
            == timeline["generation_schedule"]
        )
    elif method == "random_G5":
        expected = random_g5_schedule(int(run["root_seed"]))
        checks.update(
            {
                "random_schedule_precommitted": declared == expected,
                "random_schedule_executed": schedule
                == expected
                == timeline["generation_schedule"],
                "random_schedule_unique_in_range": len(set(schedule)) == 5 and all(1 <= item <= 99 for item in schedule),
            }
        )
    elif declared not in (None, []):
        checks["adaptive_method_has_no_precommitted_schedule"] = False

    if method == NO_REACTIVATION:
        checks["timeline_has_no_reactivate"] = all(
            item.get("executed_operation") != "reactivate"
            for item in run["publication_timeline"]
        )
    for check, passed in checks.items():
        if not passed:
            _failure(failures, "budget", check, run)


def _audit_window_evidence(
    run: Mapping[str, Any], failures: list[dict[str, Any]]
) -> None:
    windows = run.get("windows")
    timeline = run.get("publication_timeline")
    checks: dict[str, bool] = {}
    if (
        not isinstance(windows, list)
        or len(windows) != 100
        or not all(isinstance(row, Mapping) for row in windows)
        or not isinstance(timeline, list)
        or len(timeline) != 100
        or not all(isinstance(row, Mapping) for row in timeline)
    ):
        _failure(failures, "integrity", "complete_window_and_timeline_evidence", run)
        return
    checks["window_indices_contiguous"] = [
        row.get("decision_index") for row in windows
    ] == list(range(100))
    checks["window_exact_timestep_bounds"] = all(
        row.get("window_start_timestep") == 200 + 20 * index
        and row.get("window_end_timestep") == 220 + 20 * index
        for index, row in enumerate(windows)
    )

    reward_sum = 0.0
    previous_tasks = 0
    previous_assigned: int | None = None
    previous_completed: int | None = None
    prefix_baseline: int | None = None
    task_contract = True
    prefix_contract = True
    guidance_contract = True
    guidance_by_generation: dict[int, tuple[str, str]] = {}
    for index, (window, publication) in enumerate(zip(windows, timeline)):
        reward = window.get("reward")
        tasks = window.get("num_task_finished")
        assigned = window.get("assigned_prefix_total")
        completed = window.get("completed_prefix_total")
        if not (
            _is_finite_number(reward, minimum=0.0)
            and _is_nonnegative_integer(tasks)
            and _is_nonnegative_integer(assigned)
            and _is_nonnegative_integer(completed)
        ):
            task_contract = False
            prefix_contract = False
        else:
            reward_sum = math.fsum((reward_sum, float(reward)))
            task_contract &= tasks >= previous_tasks and math.isclose(
                float(tasks), reward_sum, rel_tol=0.0, abs_tol=1e-9
            )
            previous_tasks = int(tasks)
            prefix_contract &= int(completed) <= int(assigned)
            if previous_assigned is not None and previous_completed is not None:
                prefix_contract &= int(assigned) >= previous_assigned
                prefix_contract &= int(completed) >= previous_completed
            previous_assigned = int(assigned)
            previous_completed = int(completed)
            baseline = int(completed) - int(tasks)
            if prefix_baseline is None:
                prefix_baseline = baseline
            prefix_contract &= baseline == prefix_baseline and baseline >= 0

        raw_hash = window.get("guidance_sha256")
        applied_hash = window.get("applied_guidance_sha256")
        generation_id = window.get("generation_id")
        installed = window.get("installation_version")
        guidance_version = window.get("guidance_version")
        guidance_contract &= (
            _is_sha256(raw_hash)
            and _is_sha256(applied_hash)
            and _is_positive_integer(generation_id)
            and _is_positive_integer(installed)
            and guidance_version == installed
            and installed == publication.get("guidance_version_installed_for_window")
            and generation_id == publication.get("active_generation_id_after")
            and window.get("guidance_operation")
            == ("hold" if index == 0 else publication.get("executed_operation"))
            and window.get("guidance_switched_post_bootstrap")
            is (index > 0 and publication.get("accepted") is True)
            and window.get("refreshed_post_bootstrap")
            is (index > 0 and publication.get("executed_operation") == "generate")
        )
        if _is_positive_integer(generation_id) and _is_sha256(raw_hash) and _is_sha256(
            applied_hash
        ):
            pair = (str(raw_hash), str(applied_hash))
            if int(generation_id) in guidance_by_generation:
                guidance_contract &= guidance_by_generation[int(generation_id)] == pair
            else:
                guidance_by_generation[int(generation_id)] = pair

    declared_tasks = run.get("num_task_finished")
    checks["num_task_finished_is_nonnegative_integer"] = _is_nonnegative_integer(
        declared_tasks
    )
    checks["window_reward_and_completion_trajectory_recomputed"] = bool(
        task_contract
        and _is_nonnegative_integer(declared_tasks)
        and previous_tasks == declared_tasks
        and math.isclose(reward_sum, float(declared_tasks), rel_tol=0.0, abs_tol=1e-9)
    )
    checks["assignment_completion_prefix_totals_monotone"] = prefix_contract
    checks["window_guidance_identity_and_installation_exact"] = guidance_contract
    checks["throughput_recomputed"] = bool(
        _is_finite_number(run.get("throughput_per_timestep"), minimum=0.0)
        and _is_nonnegative_integer(declared_tasks)
        and math.isclose(
            float(run["throughput_per_timestep"]),
            float(declared_tasks) / 2000.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )

    identity = run.get("task_tape_identity")
    final_prefixes = run.get("final_task_tape_prefixes")
    final_contract = isinstance(identity, Mapping) and isinstance(final_prefixes, Mapping)
    if final_contract:
        lengths = identity.get("per_agent_lengths")
        released = final_prefixes.get("released_prefix_lengths")
        assigned = final_prefixes.get("assigned_prefix_lengths")
        completed = final_prefixes.get("completed_prefix_lengths")
        agents = len(identity.get("start_locations", []))
        final_contract = bool(
            isinstance(lengths, list)
            and isinstance(released, list)
            and isinstance(assigned, list)
            and isinstance(completed, list)
            and len(lengths) == len(released) == len(assigned) == len(completed) == agents
            and agents > 0
            and all(
                _is_nonnegative_integer(c)
                and _is_nonnegative_integer(a)
                and _is_nonnegative_integer(r)
                and _is_positive_integer(limit)
                and c <= a <= r <= limit
                for c, a, r, limit in zip(completed, assigned, released, lengths)
            )
            and sum(assigned) == previous_assigned
            and sum(completed) == previous_completed
            and final_prefixes.get("all_released")
            is all(r == limit for r, limit in zip(released, lengths))
            and final_prefixes.get("all_completed")
            is all(c == limit for c, limit in zip(completed, lengths))
            and all(a < limit for a, limit in zip(assigned, lengths))
        )
    checks["final_task_tape_prefixes_recomputed"] = final_contract

    catalog = run.get("guidance_catalog")
    catalog_contract = isinstance(catalog, list) and all(
        isinstance(row, Mapping) for row in catalog
    )
    if catalog_contract and run.get("method") in {FOCAL, NO_REACTIVATION}:
        budgets = _run_budget(run)
        generation_schedule = [
            row["decision_index"]
            for row in timeline[1:]
            if row.get("executed_operation") == "generate"
        ]
        expected_decisions = [0, *generation_schedule]
        catalog_contract = len(catalog) == 1 + budgets["generations"]
        for expected_id, expected_decision, row in zip(
            range(1, len(catalog) + 1), expected_decisions, catalog
        ):
            context = row.get("context")
            catalog_contract &= (
                row.get("generation_id") == expected_id
                and row.get("generated_at_decision") == expected_decision
                and row.get("source")
                == ("bootstrap" if expected_id == 1 else "generated")
                and isinstance(context, list)
                and len(context) == 16
                and all(_is_finite_number(value, minimum=0.0) for value in context)
                and _is_sha256(row.get("context_sha256"))
                and row.get("context_sha256") == _canonical_sha256(context)
                and _is_sha256(row.get("raw_guidance_sha256"))
                and _is_sha256(row.get("applied_guidance_sha256"))
                and guidance_by_generation.get(expected_id)
                == (
                    row.get("raw_guidance_sha256"),
                    row.get("applied_guidance_sha256"),
                )
            )
    elif catalog_contract:
        catalog_contract = catalog == []
    checks["guidance_catalog_contiguous_and_hash_bound"] = catalog_contract
    checks["generated_guidance_ids_contiguous"] = set(guidance_by_generation) == set(
        range(1, _run_budget(run)["calls"] + 1)
    )
    for check, passed in checks.items():
        if not passed:
            _failure(failures, "integrity", check, run)


def _audit_integrity(run: Mapping[str, Any], failures: list[dict[str, Any]]) -> None:
    safety = _mapping(run.get("safety"), "run.safety")
    invariants = _mapping(run.get("invariants"), "run.invariants")
    cohort = _mapping(run.get("cohort_attribution_audit"), "run.cohort_attribution_audit")
    route_reasons = run.get("route_build_reason_counts")
    nested_route_reasons = cohort.get("route_build_reason_counts")
    valid_route_reasons = bool(
        isinstance(route_reasons, Mapping)
        and route_reasons
        and route_reasons == nested_route_reasons
        and all(
            reason in ALLOWED_ROUTE_BUILD_REASONS
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
            for reason, count in route_reasons.items()
        )
    )
    exposed = cohort.get("route_exposed_completion_count")
    unexposed = cohort.get("unexposed_zero_route_completion_count")
    checks = {
        "safety_passed": safety.get("passed") is True,
        "zero_collisions": safety.get("collision_count") == 0
        and run.get("collisions") == 0,
        "zero_edge_swaps": safety.get("edge_swap_count") == 0
        and run.get("edge_swaps") == 0,
        "zero_invalid_moves": safety.get("invalid_move_count") == 0
        and run.get("invalid_moves") == 0,
        "zero_endpoint_mismatch": safety.get("endpoint_mismatch_count") == 0,
        "zero_route_trace_errors": safety.get("route_trace_invalid_count") == 0,
        "planner_timeouts_retained_and_consistent": _is_nonnegative_integer(
            run.get("planner_timeouts")
        )
        and safety.get("planner_timeout_count") == run.get("planner_timeouts"),
        "runner_invariants_passed": invariants.get("passed") is True,
        "zero_online_workload_rng": invariants.get("online_workload_rng_draws") == 0,
        "tape_not_exhausted": invariants.get("tape_not_exhausted") is True,
        "reward_sum_matches": invariants.get("reward_sum_matches_completed") is True,
        # A minimum-latency completion can legitimately have no exposed route.
        # It is valid evidence only when the runner explicitly excluded it from
        # the route cohort; the count itself need not be zero.
        "route_exposed_completion_count_valid": isinstance(exposed, int)
        and not isinstance(exposed, bool)
        and exposed >= 0,
        "unexposed_zero_route_completion_count_valid": isinstance(unexposed, int)
        and not isinstance(unexposed, bool)
        and unexposed >= 0,
        "unexposed_zero_route_completions_excluded": cohort.get(
            "unexposed_zero_route_completions_excluded"
        )
        is True,
        "unexposed_completions_excluded_from_cohorts": invariants.get(
            "unexposed_completions_excluded_from_cohorts"
        )
        is True,
        "recognized_route_build_reasons": valid_route_reasons,
    }
    windows = run.get("windows")
    timeline = run.get("publication_timeline")
    if not isinstance(windows, list) or len(windows) != 100:
        checks["one_hundred_windows"] = False
    else:
        checks["window_indices_contiguous"] = [row.get("decision_index") for row in windows] == list(range(100))
        checks["guidance_hashes_complete"] = all(
            _is_sha256(row.get("guidance_sha256"))
            and _is_sha256(row.get("applied_guidance_sha256"))
            for row in windows
        )
        if isinstance(timeline, list) and len(timeline) == 100:
            expected_version = 1
            contiguous = True
            for index, (window, publication) in enumerate(zip(windows, timeline)):
                if index > 0 and publication.get("accepted") is True:
                    expected_version += 1
                contiguous &= window.get("guidance_version") == expected_version
            checks["guidance_versions_contiguous"] = contiguous
    for check, passed in checks.items():
        if not passed:
            _failure(failures, "integrity", check, run)
    _audit_window_evidence(run, failures)


def _artifact_scenario(artifact: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    map_sha = artifact.get("map_sha256")
    agents = _mapping(artifact.get("protocol"), "artifact.protocol").get("agents")
    candidates = [
        row["id"]
        for row in config["scenarios"]
        if row.get("map_sha256") == map_sha and row.get("agents") == agents
    ]
    if len(candidates) != 1:
        raise SameCallConfirmationError("artifact does not match one frozen scenario")
    return str(candidates[0])


def _normalize_and_audit(
    artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    config_sha: str,
    expected_hashes: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if len(artifacts) != 4:
        raise SameCallConfirmationError("exactly four scenario artifacts are required")
    failures: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    scenario_ids: set[str] = set()
    process_ids: list[int] = []
    process_identities: list[tuple[str, int, int]] = []
    run_uuids: list[str] = []
    ledger_paths: list[str] = []
    ledger_totals = {"started": 0, "completed": 0, "failed_or_retry_events": 0, "unfinished": 0}
    config_field = str(config["artifact_config_sha256_field"])
    checkpoint_hash = _expected_metadata_hash(expected_hashes, "checkpoint_file")
    params_hash = _expected_metadata_hash(expected_hashes, "checkpoint_params")
    period_hash = _expected_metadata_hash(expected_hashes, "period_on_sim")

    for artifact_index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping):
            raise SameCallConfirmationError("artifact top levels must be objects")
        scenario_id = _artifact_scenario(artifact, config)
        if scenario_id in scenario_ids:
            raise SameCallConfirmationError("duplicate scenario artifact")
        scenario_ids.add(scenario_id)
        if artifact.get("schema") != SOURCE_SCHEMA or artifact.get("status") != "complete":
            raise SameCallConfirmationError("source artifact is not a complete claim-runner artifact")
        if artifact.get("split") != SPLIT or artifact.get("evidence_class") != SPLIT:
            raise SameCallConfirmationError("artifact split is not the frozen confirmation split")
        if artifact.get(config_field) != config_sha:
            raise SameCallConfirmationError("artifact does not bind the frozen config hash")
        if tuple(artifact.get("methods", ())) != METHODS:
            raise SameCallConfirmationError("artifact methods differ from the frozen family")
        if tuple(artifact.get("seeds", ())) != ROOTS:
            raise SameCallConfirmationError("artifact roots differ from the frozen vector")
        if tuple(artifact.get("workloads", ())) != WORKLOADS:
            raise SameCallConfirmationError("artifact workloads differ from the frozen family")
        _validate_artifact_protocol(artifact, scenario_id, config, expected_hashes)
        protocol = _mapping(artifact.get("protocol"), "artifact.protocol")
        if protocol.get("fresh_os_process_per_arm") is not True or artifact.get("fresh_process_per_arm") is not True:
            raise SameCallConfirmationError("artifact lacks fresh-process-per-arm attestation")
        generator = _mapping(artifact.get("generator"), "artifact.generator")
        if checkpoint_hash and generator.get("file_sha256") != checkpoint_hash:
            raise SameCallConfirmationError("checkpoint file hash differs from config")
        if params_hash and generator.get("params_sha256") != params_hash:
            raise SameCallConfirmationError("checkpoint parameter hash differs from config")
        if period_hash and artifact.get("period_on_sim_sha256") != period_hash:
            raise SameCallConfirmationError("period_on_sim hash differs from config")
        expected_map_hash = expected_hashes[
            "narrow_map" if scenario_id.startswith("narrow_") else "regular_map"
        ]
        if artifact.get("map_sha256") != expected_map_hash:
            raise SameCallConfirmationError("artifact map hash differs from frozen config")
        if not isinstance(artifact.get("map_id"), str) or not artifact["map_id"]:
            raise SameCallConfirmationError("artifact map_id is missing")
        raw_runs = artifact.get("runs")
        if not isinstance(raw_runs, list) or len(raw_runs) != RUNS_PER_SCENARIO:
            raise SameCallConfirmationError(
                f"scenario {scenario_id} must contain {RUNS_PER_SCENARIO} runs"
            )
        scenario_runs: list[dict[str, Any]] = []
        for raw in raw_runs:
            if not isinstance(raw, Mapping):
                raise SameCallConfirmationError("run must be an object")
            run = dict(raw)
            run["scenario_id"] = scenario_id
            if run.get("method") not in METHODS:
                raise SameCallConfirmationError("run contains an unknown method")
            seed = run.get("root_seed", run.get("seed"))
            if seed not in ROOTS or run.get("seed") != seed:
                raise SameCallConfirmationError("run root/seed is invalid")
            if run.get("workload") not in WORKLOADS:
                raise SameCallConfirmationError("run workload is invalid")
            if run.get("split") != SPLIT or run.get("evidence_class") != SPLIT:
                raise SameCallConfirmationError("run split is invalid")
            run["root_seed"] = seed
            if (
                run.get("map_id") != artifact.get("map_id")
                or run.get("scored_horizon") != 2000
                or run.get("decision_window") != 20
                or run.get("window_count") != 100
            ):
                raise SameCallConfirmationError("run protocol/map fields differ from artifact")
            _integer(run.get("num_task_finished"), "num_task_finished", minimum=0)
            _validate_pairing_payload(run, SCENARIOS[scenario_id]["agents"])
            pid = _integer(run.get("execution_process_id"), "execution_process_id", minimum=1)
            ppid = _integer(run.get("execution_parent_process_id"), "execution_parent_process_id", minimum=1)
            host = run.get("execution_host")
            start_ns = _integer(
                run.get("execution_process_start_ns"),
                "execution_process_start_ns",
                minimum=1,
            )
            run_uuid = run.get("run_uuid")
            if not isinstance(host, str) or not host:
                raise SameCallConfirmationError("execution_host must be non-empty")
            if not _is_uuid(run_uuid):
                raise SameCallConfirmationError("run_uuid must be a canonical UUID")
            process_ids.append(pid)
            process_identities.append((host, pid, start_ns))
            run_uuids.append(str(run_uuid))
            if pid == ppid:
                _failure(failures, "fresh_process", "child_pid_differs_from_parent", run)
            _audit_integrity(run, failures)
            _audit_budget(run, failures)
            runs.append(run)
            scenario_runs.append(run)
        ledger = _verify_attempt_ledger(
            artifact, scenario_runs, SCENARIOS[scenario_id]["agents"]
        )
        ledger_path = str(Path(artifact["attempt_ledger"]["path"]).expanduser().resolve())
        ledger_paths.append(ledger_path)
        for field in ledger_totals:
            ledger_totals[field] += ledger[field]

    if scenario_ids != set(SCENARIOS):
        raise SameCallConfirmationError("the four frozen scenarios are not complete")
    expected_keys = set(itertools.product(SCENARIOS, METHODS, ROOTS, WORKLOADS))
    observed_keys = {
        (run["scenario_id"], run["method"], run["root_seed"], run["workload"])
        for run in runs
    }
    if len(runs) != TOTAL_RUNS or observed_keys != expected_keys:
        raise SameCallConfirmationError("matrix is missing, duplicating, or replacing a required arm")
    if len(set(process_ids)) != TOTAL_RUNS:
        failures.append(
            {"category": "fresh_process", "check": "one_unique_os_process_per_arm"}
        )
    if len(set(process_identities)) != TOTAL_RUNS:
        failures.append(
            {
                "category": "fresh_process",
                "check": "unique_host_pid_process_start_per_arm",
            }
        )
    if len(set(run_uuids)) != TOTAL_RUNS:
        failures.append(
            {"category": "fresh_process", "check": "one_unique_run_uuid_per_arm"}
        )
    if len(set(ledger_paths)) != 4:
        failures.append(
            {"category": "integrity", "check": "one_unique_attempt_ledger_per_scenario"}
        )

    by_cell: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_cell[(run["scenario_id"], run["root_seed"], run["workload"])].append(run)
    pairing_fields = (
        "manifest_id",
        "task_tape_identity",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
        "workload_arrival",
    )
    for key, arms in by_cell.items():
        for field in pairing_fields:
            if len({_canonical(run[field]) for run in arms}) != 1:
                failures.append(
                    {"category": "pairing", "check": f"paired_{field}", "cell": key}
                )

    random_by_root: dict[int, set[tuple[int, ...]]] = defaultdict(set)
    for run in runs:
        if run["method"] == "random_G5":
            random_by_root[run["root_seed"]].add(
                tuple(run.get("precommitted_post_bootstrap_schedule") or ())
            )
    for root_seed, schedules in random_by_root.items():
        if schedules != {tuple(random_g5_schedule(root_seed))}:
            failures.append(
                {
                    "category": "budget",
                    "check": "random_schedule_identical_across_all_12_root_cells",
                    "root_seed": root_seed,
                }
            )
    totals = {
        "runs": len(runs),
        "unique_execution_processes": len(set(process_ids)),
        "planner_timeouts": sum(int(run.get("planner_timeouts", 0)) for run in runs),
        "route_exposed_completion_count": sum(
            int(run["cohort_attribution_audit"]["route_exposed_completion_count"])
            for run in runs
        ),
        "unexposed_zero_route_completion_count": sum(
            int(run["cohort_attribution_audit"]["unexposed_zero_route_completion_count"])
            for run in runs
        ),
        "attempts_started": ledger_totals["started"],
        "attempts_completed": ledger_totals["completed"],
        "method_failure_or_retry_events": ledger_totals["failed_or_retry_events"],
        "unfinished_attempts": ledger_totals["unfinished"],
        "method_failures_deleted": ledger_totals["unfinished"],
        "timeout_deletions": 0,
        "selective_cells_deleted": TOTAL_RUNS - ledger_totals["completed"],
    }
    return runs, failures, totals


def _root_bootstrap(
    root_relative: Sequence[float], root_absolute: Sequence[float]
) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    relative_draws: list[float] = []
    absolute_draws: list[float] = []
    n = len(root_relative)
    for _ in range(BOOTSTRAP_SAMPLES):
        indices = [rng.randrange(n) for _ in range(n)]
        relative_draws.append(_mean(root_relative[index] for index in indices))
        absolute_draws.append(_mean(root_absolute[index] for index in indices))
    return {
        "method": "whole_root_percentile_bootstrap",
        "independent_unit": "root_seed",
        "samples": BOOTSTRAP_SAMPLES,
        "rng_seed": BOOTSTRAP_SEED,
        "confidence_level": 0.95,
        "mean_relative_effect_ci": [
            _percentile(relative_draws, 0.025),
            _percentile(relative_draws, 0.975),
        ],
        "mean_absolute_task_delta_ci": [
            _percentile(absolute_draws, 0.025),
            _percentile(absolute_draws, 0.975),
        ],
    }


def _exact_sign_flip(root_effects: Sequence[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in root_effects if value != 0.0]
    observed = math.fsum(nonzero)
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
    extreme = 0
    tolerance = 1e-15
    for bits in range(assignments):
        statistic = math.fsum(
            value if bits & (1 << index) else -value
            for index, value in enumerate(nonzero)
        )
        extreme += statistic >= observed - tolerance
    return {
        "method": "exact_root_seed_sign_flip",
        "alternative": "greater",
        "nonzero_root_seeds": len(nonzero),
        "ties_omitted": len(root_effects) - len(nonzero),
        "assignments": assignments,
        "p_greater": extreme / assignments,
    }


def _comparison(
    candidate: str,
    comparator: str,
    indexed: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    by_root_relative: dict[int, list[float]] = defaultdict(list)
    by_root_absolute: dict[int, list[float]] = defaultdict(list)
    for scenario_id, root_seed, workload in itertools.product(SCENARIOS, ROOTS, WORKLOADS):
        left = indexed[(scenario_id, candidate, root_seed, workload)]
        right = indexed[(scenario_id, comparator, root_seed, workload)]
        candidate_tasks = float(left["num_task_finished"])
        comparator_tasks = float(right["num_task_finished"])
        if comparator_tasks <= 0.0:
            raise SameCallConfirmationError("relative-effect comparator completed no tasks")
        relative = (candidate_tasks - comparator_tasks) / comparator_tasks
        absolute = candidate_tasks - comparator_tasks
        map_group = "narrow" if scenario_id.startswith("narrow_") else "regular"
        cell = {
            "scenario_id": scenario_id,
            "map_group": map_group,
            "root_seed": root_seed,
            "workload": workload,
            "candidate_tasks": candidate_tasks,
            "comparator_tasks": comparator_tasks,
            "relative_effect": relative,
            "absolute_task_delta": absolute,
        }
        cells.append(cell)
        by_root_relative[root_seed].append(relative)
        by_root_absolute[root_seed].append(absolute)
    root_relative = [_mean(by_root_relative[root]) for root in ROOTS]
    root_absolute = [_mean(by_root_absolute[root]) for root in ROOTS]
    leave_one_out = {
        str(root): _mean(value for index, value in enumerate(root_relative) if index != rank)
        for rank, root in enumerate(ROOTS)
    }

    def direction(field: str, value: str) -> dict[str, Any]:
        selected = [cell for cell in cells if cell[field] == value]
        return {
            "n_cells": len(selected),
            "mean_relative_effect": _mean(cell["relative_effect"] for cell in selected),
            "mean_absolute_task_delta": _mean(cell["absolute_task_delta"] for cell in selected),
        }

    return {
        "candidate": candidate,
        "comparator": comparator,
        "independent_unit": "root_seed",
        "n_root_seed_clusters": 10,
        "n_paired_cells": 120,
        "root_relative_effects": [
            {"root_seed": root, "relative_effect": effect, "absolute_task_delta": root_absolute[index]}
            for index, (root, effect) in enumerate(zip(ROOTS, root_relative))
        ],
        "mean_relative_effect": _mean(root_relative),
        "mean_relative_effect_percent": 100.0 * _mean(root_relative),
        "median_root_relative_effect": statistics.median(root_relative),
        "mean_absolute_task_delta": _mean(root_absolute),
        "root_win_tie_loss": {
            "wins": sum(value > 0.0 for value in root_relative),
            "ties": sum(value == 0.0 for value in root_relative),
            "losses": sum(value < 0.0 for value in root_relative),
        },
        "cluster_bootstrap": _root_bootstrap(root_relative, root_absolute),
        "exact_sign_flip": _exact_sign_flip(root_relative),
        "map_effects": {name: direction("map_group", name) for name in ("narrow", "regular")},
        "workload_effects": {name: direction("workload", name) for name in WORKLOADS},
        "scenario_effects": {name: direction("scenario_id", name) for name in SCENARIOS},
        "leave_one_root_out_means": leave_one_out,
    }


def _holm_adjust(comparisons: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    raw = {
        comparator: float(comparisons[comparator]["exact_sign_flip"]["p_greater"])
        for comparator in SUPERIORITY_COMPARATORS
    }
    ordered = sorted(raw, key=lambda name: (raw[name], name))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, comparator in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * raw[comparator]))
        adjusted[comparator] = running
    for comparator, value in adjusted.items():
        comparisons[comparator]["exact_sign_flip"]["p_greater_holm"] = value
    return {
        "method": "Holm step-down",
        "familywise_alpha": 0.05,
        "family_size": 6,
        "ordered_comparators": ordered,
        "raw_p_greater": raw,
        "adjusted_p_greater": adjusted,
    }


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    return {
        "mean": _mean(values),
        "median": statistics.median(values),
        "p90": _percentile(values, 0.90),
        "maximum": max(values),
        "minimum": min(values),
    }


def _method_summaries(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for method in METHODS:
        selected = [run for run in runs if run["method"] == method]
        tasks = [float(run["num_task_finished"]) for run in selected]
        budgets = [_run_budget(run) for run in selected]
        calls = [float(item["calls"]) for item in budgets]
        generations = [float(item["generations"]) for item in budgets]
        switches = [float(item["switches"]) for item in budgets]
        reactivations = [float(item["reactivations"]) for item in budgets]
        result[method] = {
            "n_runs": len(selected),
            "tasks": _distribution(tasks),
            "total_generator_calls": {
                **_distribution(calls),
                "fraction_at_most_5": sum(value <= 5.0 for value in calls) / len(calls),
                "fraction_at_most_6": sum(value <= 6.0 for value in calls) / len(calls),
            },
            "post_bootstrap_generations": _distribution(generations),
            "effective_switches": _distribution(switches),
            "reactivations": _distribution(reactivations),
        }
    return result


def _pareto(summaries: Mapping[str, Any]) -> dict[str, Any]:
    points = {
        method: {
            "mean_tasks": float(summaries[method]["tasks"]["mean"]),
            "mean_total_generator_calls": float(
                summaries[method]["total_generator_calls"]["mean"]
            ),
        }
        for method in METHODS
    }
    dominates: dict[str, list[str]] = {method: [] for method in METHODS}
    for candidate, target in itertools.permutations(METHODS, 2):
        left = points[candidate]
        right = points[target]
        if (
            left["mean_tasks"] >= right["mean_tasks"]
            and left["mean_total_generator_calls"] <= right["mean_total_generator_calls"]
            and (
                left["mean_tasks"] > right["mean_tasks"]
                or left["mean_total_generator_calls"] < right["mean_total_generator_calls"]
            )
        ):
            dominates[target].append(candidate)
    return {
        "definition": "no fewer mean tasks and no more mean calls, with at least one strict",
        "points": points,
        "dominators": dominates,
        "frontier_methods": [method for method in METHODS if not dominates[method]],
        "focal_not_point_dominated": not dominates[FOCAL],
    }


def _assign_tier(
    audit: Mapping[str, Any],
    comparisons: Mapping[str, Mapping[str, Any]],
    ni: Mapping[str, Any],
    summaries: Mapping[str, Any],
    pareto: Mapping[str, Any],
) -> dict[str, Any]:
    bootstrap = comparisons[BOOTSTRAP]
    context_calls = float(summaries[FOCAL]["total_generator_calls"]["mean"])
    exact_calls = float(summaries[EXACT_B25]["total_generator_calls"]["mean"])
    call_reduction = 1.0 - context_calls / exact_calls
    superiority = {
        comparator: {
            "holm_p_below_0_05": comparisons[comparator]["exact_sign_flip"]["p_greater_holm"] < 0.05,
            "ci_lower_above_zero": comparisons[comparator]["cluster_bootstrap"]["mean_relative_effect_ci"][0] > 0.0,
            "mean_positive": comparisons[comparator]["mean_relative_effect"] > 0.0,
        }
        for comparator in SUPERIORITY_COMPARATORS
    }
    bootstrap_maps_positive = all(
        item["mean_relative_effect"] > 0.0
        for item in bootstrap["map_effects"].values()
    )
    bootstrap_workloads_positive = all(
        item["mean_relative_effect"] > 0.0
        for item in bootstrap["workload_effects"].values()
    )
    g5 = comparisons["exact_even_G5"]
    g5_maps_positive = all(
        item["mean_relative_effect"] > 0.0 for item in g5["map_effects"].values()
    )
    g5_workloads_positive = sum(
        item["mean_relative_effect"] > 0.0
        for item in g5["workload_effects"].values()
    ) >= 2
    stationary_ok = g5["workload_effects"]["stationary"]["mean_relative_effect"] >= -0.01

    tier_b_checks = {
        "all_audits_pass": audit["passed"] is True,
        "bootstrap_mean_at_least_2pct": bootstrap["mean_relative_effect"] >= 0.02,
        "bootstrap_ci_lower_above_zero": bootstrap["cluster_bootstrap"]["mean_relative_effect_ci"][0] > 0.0,
        "bootstrap_holm_p_below_0_05": bootstrap["exact_sign_flip"]["p_greater_holm"] < 0.05,
        "exact_b25_1pct_noninferiority": ni["passed"] is True,
        "mean_calls_at_most_6": context_calls <= 6.0,
        "call_reduction_at_least_75pct": call_reduction >= 0.75,
        "focal_not_point_dominated": pareto["focal_not_point_dominated"] is True,
        "bootstrap_positive_both_maps": bootstrap_maps_positive,
        "bootstrap_positive_all_workloads": bootstrap_workloads_positive,
        "zero_selective_deletion": audit["totals"]["selective_cells_deleted"] == 0,
    }
    tier_b = all(tier_b_checks.values())
    tier_a_extra = {
        "all_six_holm_p_below_0_05": all(row["holm_p_below_0_05"] for row in superiority.values()),
        "all_six_ci_lower_above_zero": all(row["ci_lower_above_zero"] for row in superiority.values()),
        "all_sparse_control_means_positive": all(superiority[name]["mean_positive"] for name in SPARSE_COMPARATORS),
        "historical_recall_mean_positive": superiority[NO_REACTIVATION]["mean_positive"],
        "g5_positive_both_maps": g5_maps_positive,
        "g5_positive_at_least_two_workloads": g5_workloads_positive,
        "g5_stationary_degradation_no_worse_than_1pct": stationary_ok,
    }
    tier_a = tier_b and all(tier_a_extra.values())
    tier = "A" if tier_a else "B" if tier_b else "C"
    return {
        "tier": tier,
        "recommendation": {
            "A": "TIER_A_STRONG_MECHANISM_EVIDENCE",
            "B": "TIER_B_SCOPED_DAI_PARETO_RESULT",
            "C": "TIER_C_NO_GO_CURRENT_CONTEXT_MEMORY_PAPER",
        }[tier],
        "tier_a_passed": tier_a,
        "tier_b_passed": tier_b,
        "tier_c_no_go": not tier_b,
        "tier_b_checks": tier_b_checks,
        "tier_a_additional_checks": tier_a_extra,
        "superiority_checks": superiority,
        "mean_context_calls": context_calls,
        "call_reduction_vs_exact_b25": call_reduction,
        "failed_tier_b_checks": [name for name, passed in tier_b_checks.items() if not passed],
        "failed_tier_a_checks": [name for name, passed in tier_a_extra.items() if not passed],
    }


def analyze_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    config_path: Path = DEFAULT_CONFIG,
    source_labels: Sequence[str] | None = None,
    source_sha256: Sequence[str] | None = None,
) -> dict[str, Any]:
    config, config_sha, resolved_config = load_config(config_path)
    frozen_verified, expected_hashes = _verify_frozen_artifacts(config, resolved_config)
    preflight_verified = _verify_preflight(config, resolved_config)
    labels = list(source_labels or [f"artifact_{index}" for index in range(len(artifacts))])
    hashes = list(source_sha256 or ["synthetic_or_in_memory"] * len(artifacts))
    if len(labels) != len(artifacts) or len(hashes) != len(artifacts):
        raise SameCallConfirmationError("source labels/hashes must align with artifacts")
    for index, digest in enumerate(hashes):
        if digest != "synthetic_or_in_memory":
            _sha(digest, f"source_sha256[{index}]")

    runs, failures, totals = _normalize_and_audit(
        artifacts, config, config_sha, expected_hashes
    )
    audit = {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "totals": totals,
        "complete_960_run_matrix": len(runs) == TOTAL_RUNS,
        "source_and_config_hashes_verified": True,
        "preflight_evidence_verified": True,
        "paired_exogenous_inputs_match": not any(item["category"] == "pairing" for item in failures),
        "safety_and_invariants_pass": not any(item["category"] == "integrity" for item in failures),
        "budget_and_schedule_contracts_pass": not any(item["category"] == "budget" for item in failures),
        "fresh_process_per_arm_pass": not any(item["category"] == "fresh_process" for item in failures),
    }
    if failures:
        first = failures[0]
        raise SameCallConfirmationError(
            "mandatory pre-inference audit failed: "
            f"{first.get('category')}/{first.get('check')} "
            f"({len(failures)} failure(s)); no treatment effects were calculated"
        )
    for record in frozen_verified.values():
        if record.get("verified") == "pending emitted-artifact metadata binding":
            record["verified"] = "bound to all applicable emitted artifact metadata"
    indexed = {
        (run["scenario_id"], run["method"], run["root_seed"], run["workload"]): run
        for run in runs
    }
    comparisons: dict[str, dict[str, Any]] = {
        comparator: _comparison(FOCAL, comparator, indexed)
        for comparator in SUPERIORITY_COMPARATORS
    }
    multiplicity = _holm_adjust(comparisons)
    exact_comparison = _comparison(FOCAL, EXACT_B25, indexed)
    shifted = [
        float(row["relative_effect"]) + NI_MARGIN
        for row in exact_comparison["root_relative_effects"]
    ]
    ni_test = _exact_sign_flip(shifted)
    ni_checks = {
        "mean_at_least_minus_0_5pct": exact_comparison["mean_relative_effect"] >= -0.005,
        "ci_lower_strictly_above_minus_1pct": exact_comparison["cluster_bootstrap"]["mean_relative_effect_ci"][0] > -0.01,
        "shifted_one_sided_p_below_0_05": ni_test["p_greater"] < 0.05,
    }
    noninferiority = {
        "candidate": FOCAL,
        "comparator": EXACT_B25,
        "relative_margin": -NI_MARGIN,
        "comparison": exact_comparison,
        "shifted_exact_sign_flip": ni_test,
        "checks": ni_checks,
        "passed": all(ni_checks.values()),
        "disclosure": "The retained 1% margin predates this post-validation Pareto protocol.",
    }
    summaries = _method_summaries(runs)
    pareto = _pareto(summaries)
    tier = _assign_tier(audit, comparisons, noninferiority, summaries, pareto)
    return {
        "schema": ANALYSIS_SCHEMA,
        "evidence_scope": "fresh post-validation same-backbone confirmation; never global LMAPF SOTA",
        "sources": [
            {"label": label, "sha256": digest}
            for label, digest in zip(labels, hashes)
        ],
        "frozen_config": {
            "path": str(resolved_config),
            "sha256": config_sha,
            "schema": config["schema"],
            "artifact_declaration_field": config["artifact_config_sha256_field"],
        },
        "frozen_artifacts": frozen_verified,
        "preflight_evidence": preflight_verified,
        "design": {
            "methods": list(METHODS),
            "root_seeds": list(ROOTS),
            "scenarios": list(SCENARIOS),
            "workloads": list(WORKLOADS),
            "total_runs": TOTAL_RUNS,
            "paired_cells_per_method": 120,
            "cells_per_root_method": CELLS_PER_ROOT_METHOD,
            "independent_unit": "root_seed",
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
        },
        "audit": audit,
        "method_summaries": summaries,
        "superiority_comparisons": comparisons,
        "multiplicity": multiplicity,
        "noninferiority_vs_exact_even_B25": noninferiority,
        "pareto": pareto,
        "outcome_tier": tier,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    audit = report["audit"]
    tier = report["outcome_tier"]
    lines = [
        "# Same-call confirmation v1",
        "",
        f"- Audit: **{'PASS' if audit['passed'] else 'FAIL'}**",
        f"- Outcome: **{tier['recommendation']}**",
        f"- Config SHA-256: `{report['frozen_config']['sha256']}`",
        "- Independent observations: 10 root clusters; 12 equally weighted cells per root and method",
        "",
        "## Six frozen superiority contrasts",
        "",
        "| Comparator | Mean Δ% | 95% root CI | Root W/T/L | raw p> | Holm p> |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for comparator in SUPERIORITY_COMPARATORS:
        row = report["superiority_comparisons"][comparator]
        ci = row["cluster_bootstrap"]["mean_relative_effect_ci"]
        wtl = row["root_win_tie_loss"]
        test = row["exact_sign_flip"]
        lines.append(
            f"| `{comparator}` | {row['mean_relative_effect_percent']:+.2f}% | "
            f"[{100*ci[0]:+.2f}%, {100*ci[1]:+.2f}%] | "
            f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} | "
            f"{test['p_greater']:.4g} | {test['p_greater_holm']:.4g} |"
        )
    ni = report["noninferiority_vs_exact_even_B25"]
    ni_row = ni["comparison"]
    ni_ci = ni_row["cluster_bootstrap"]["mean_relative_effect_ci"]
    lines.extend(
        [
            "",
            "## Separate 1% non-inferiority test",
            "",
            f"- Mean Δ: {ni_row['mean_relative_effect_percent']:+.2f}%",
            f"- 95% root CI: [{100*ni_ci[0]:+.2f}%, {100*ni_ci[1]:+.2f}%]",
            f"- Shifted one-sided exact p: {ni['shifted_exact_sign_flip']['p_greater']:.4g}",
            f"- Result: **{'PASS' if ni['passed'] else 'FAIL'}**",
            "",
            "## Calls and Pareto points",
            "",
            "| Method | Mean tasks | Calls mean/median/P90/max | Calls ≤5 / ≤6 | Post generations mean | Switches mean | Reactivations mean |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in METHODS:
        row = report["method_summaries"][method]
        calls = row["total_generator_calls"]
        lines.append(
            f"| `{method}` | {row['tasks']['mean']:.2f} | "
            f"{calls['mean']:.2f}/{calls['median']:.2f}/{calls['p90']:.2f}/{calls['maximum']:.0f} | "
            f"{100*calls['fraction_at_most_5']:.1f}% / {100*calls['fraction_at_most_6']:.1f}% | "
            f"{row['post_bootstrap_generations']['mean']:.2f} | "
            f"{row['effective_switches']['mean']:.2f} | {row['reactivations']['mean']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Pareto frontier: {', '.join(f'`{name}`' for name in report['pareto']['frontier_methods'])}",
            "",
            "## Mechanical tier checks",
            "",
        ]
    )
    for name, passed in tier["tier_b_checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — Tier B `{name}`")
    for name, passed in tier["tier_a_additional_checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — Tier A `{name}`")
    if audit["failures"]:
        lines.extend(["", "## Audit failures", ""])
        for item in audit["failures"]:
            lines.append(f"- `{item['category']}/{item['check']}`: `{item.get('cell', item.get('root_seed', 'matrix'))}`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    paths = [path.expanduser().resolve() for path in args.artifacts]
    try:
        artifacts = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        report = analyze_artifacts(
            artifacts,
            config_path=args.config,
            source_labels=[str(path) for path in paths],
            source_sha256=[_sha256(path) for path in paths],
        )
    except (OSError, json.JSONDecodeError, SameCallConfirmationError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "audit_passed": report["audit"]["passed"],
                "outcome_tier": report["outcome_tier"]["tier"],
                "recommendation": report["outcome_tier"]["recommendation"],
                "output_json": str(args.output_json.resolve()),
                "output_md": str(args.output_md.resolve()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
