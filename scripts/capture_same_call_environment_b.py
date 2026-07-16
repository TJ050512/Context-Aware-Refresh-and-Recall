#!/usr/bin/env python3
"""Seal Experiment B's target-host environment before any B root is opened.

This is an internal, content-hashed pre-specification control.  It is not a
public preregistration.  The command verifies the frozen predecessor config,
every inherited file source, the simulator/checkpoint/maps, and the supplied B
control-plane files before capturing the full live environment.  The output is
created atomically with no-overwrite semantics.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sys
from typing import Any, Callable, Mapping, Sequence


PROTOCOL_B_SHA256 = "35de3d61030803e58517b361b90a60a042e6bc68290171ff974e16270a859d06"
A2_CONFIG_SHA256 = "e0763c409c900bbc21e9b69fff5e978261a89cba8ad883d16ef705d012c9d96f"
V1_RUNNER_SHA256 = "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538"
ROOT_SOURCE_SHA256 = "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
ROOT_DOMAIN = "dai-same-call-confirmatory-b-power-extension"
A2_ROOT_DOMAIN = "dai-same-call-confirmatory-a2-pid-reuse-correction"
ATTESTATION_SCHEMA = "dai.same-call-environment-attestation/b"

THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
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
A2_ROOTS = (
    691817, 376110, 263001, 293231, 296805,
    274330, 997942, 319782, 807287, 326454,
)
A1_ROOTS = (
    767369, 695428, 323681, 904171, 446020,
    434435, 488565, 514527, 544573, 838809,
)
B_ROOTS = (
    880565, 534821, 257578, 500976, 294860, 954705, 190142, 429853,
    398397, 560584, 175381, 598292, 461566, 526869, 115950, 130998,
    655067, 585455, 362413, 552654, 664860, 253714, 962860, 907962,
    381214, 583444, 371204, 934561, 491276, 541256, 523055, 713041,
    537643, 699809, 204011, 330180, 113743, 257704, 152753, 657283,
)
SCENARIOS = (
    ("narrow_r020", 218, "narrow_map"),
    ("narrow_r035", 382, "narrow_map"),
    ("regular_r020", 255, "regular_map"),
    ("regular_r035", 447, "regular_map"),
)
BACKBONE_PATHS = {
    "period_on_sim": (
        "external/OnlineGGO/CMAES/simulators/trafficMAPF_on/"
        "period_on_sim.cpython-39-x86_64-linux-gnu.so"
    ),
    "checkpoint_file": (
        "external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/"
        "checkpoints/optimal_update_model_10000.json"
    ),
    "narrow_map": (
        "external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
        "warehouse_small_narrow_kiva.map"
    ),
    "regular_map": (
        "external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
        "warehouse_small_kiva.map"
    ),
}
CANONICAL_BACKBONE_SHA256 = {
    "period_on_sim": "9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5",
    "checkpoint_file": "e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d",
    "checkpoint_params": "6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac",
    "narrow_map": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
    "regular_map": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
}
CORE_B_ARTIFACTS = frozenset(
    {"runner_b", "analyzer_b", "launcher_b", "builder_b"}
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def resolve_inside(workspace: Path, value: Path | str, label: str) -> Path:
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else (workspace / raw).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"{label} must lie inside the workspace: {path}") from exc
    return path


def display_path(path: Path, workspace: Path) -> str:
    return str(path.resolve().relative_to(workspace.resolve()))


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object: {path}")
    return value


def verify_file(path: Path, expected: str, label: str) -> dict[str, Any]:
    require_sha(expected, f"{label} expected digest")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is absent: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(
            f"{label} SHA-256 mismatch: expected={expected} actual={actual} path={path}"
        )
    return {
        "path": str(path),
        "sha256": actual,
        "verification": "file_sha256",
        "size_bytes": path.stat().st_size,
    }


def write_atomic_exclusive(path: Path, payload: bytes) -> None:
    """Atomically publish bytes at a path that must not already exist."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        linked = True
        os.chmod(path, 0o644)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        if not linked and path.exists():
            # The final path belongs to a prior writer; never remove it.
            pass


def derive_roots(source_sha256: str, domain: str, count: int) -> tuple[int, ...]:
    result = []
    for index in range(count):
        token = f"{source_sha256}|{domain}|{index}".encode("utf-8")
        result.append(100000 + int(hashlib.sha256(token).hexdigest()[:16], 16) % 900000)
    return tuple(result)


def parse_b_artifacts(
    workspace: Path, values: Sequence[str]
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for value in values:
        parts = value.split("=", 2)
        if len(parts) != 3:
            raise ValueError("--b-artifact must be LABEL=RELATIVE_PATH=SHA256")
        label, relative, digest = parts
        if not label or label in records or not re.fullmatch(r"[a-z0-9_]+", label):
            raise ValueError(f"invalid or duplicate B artifact label: {label!r}")
        raw_path = Path(relative)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise ValueError(f"B artifact path must be safe and relative: {relative}")
        path = resolve_inside(workspace, raw_path, f"B artifact {label}")
        record = verify_file(path, require_sha(digest, label), f"B artifact {label}")
        record["path"] = display_path(path, workspace)
        records[label] = record
    missing = CORE_B_ARTIFACTS - set(records)
    if missing:
        raise ValueError(f"required B artifacts are missing: {sorted(missing)}")
    if "capture_environment_b" in records:
        raise ValueError("capture_environment_b is bound by --expected-self-sha256")
    return records


def _validate_a2_scientific_identity(
    config: Mapping[str, Any],
    *,
    expected_v1_sha256: str,
    expected_backbone_sha256: Mapping[str, str],
) -> None:
    if config.get("schema") != "dai.same-call-confirmation/a2":
        raise ValueError("unexpected A2 template schema")
    if tuple(config.get("methods", ())) != METHODS:
        raise ValueError("A2 method vector differs from the frozen contract")
    if tuple(config.get("workloads", ())) != WORKLOADS:
        raise ValueError("A2 workload vector differs from the frozen contract")
    if tuple(config.get("root_seeds", ())) != A2_ROOTS:
        raise ValueError("A2 root vector is not canonical")
    derivation = config.get("root_derivation")
    if not isinstance(derivation, Mapping) or derivation.get("source_sha256") != ROOT_SOURCE_SHA256:
        raise ValueError("A2 root source identity is unexpected")
    protocol = config.get("protocol")
    expected_protocol = {
        "bootstrap_samples": 10000,
        "bootstrap_seed": 20260715,
        "cells_per_root_seed_per_method": 12,
        "decision_window": 20,
        "guard_suffix_tasks_per_agent": 4,
        "independent_inference_unit": "root_seed",
        "noninferiority_margin": 0.01,
        "release_interval_per_agent": 110,
        "scored_horizon": 2000,
        "total_runs": 960,
        "warmup_time": 200,
    }
    if protocol != expected_protocol:
        raise ValueError("A2 scientific protocol differs from the frozen contract")
    scenarios = config.get("scenarios")
    expected_scenarios = [
        {
            "id": label,
            "agents": agents,
            "map_sha256": expected_backbone_sha256[map_label],
        }
        for label, agents, map_label in SCENARIOS
    ]
    if scenarios != expected_scenarios:
        raise ValueError("A2 scenario matrix differs from the frozen contract")
    frozen = config.get("frozen_artifacts")
    required = config.get("required_frozen_artifacts")
    if not isinstance(frozen, Mapping) or set(required or ()) != set(frozen):
        raise ValueError("A2 frozen-artifact manifest is incomplete")
    validation_runner = frozen.get("validation_runner")
    if not isinstance(validation_runner, Mapping) or validation_runner.get("sha256") != expected_v1_sha256:
        raise ValueError("A2 template does not bind the frozen v1 runner")
    for label, expected in expected_backbone_sha256.items():
        record = frozen.get(label)
        if not isinstance(record, Mapping) or record.get("sha256") != expected:
            raise ValueError(f"A2 template backbone identity differs: {label}")


def _checkpoint_params_sha256(workspace: Path, checkpoint: Path) -> str:
    generator_path = workspace / "src/dai_lmapf/frozen_cnn_generator.py"
    spec = importlib.util.spec_from_file_location("b_frozen_cnn_generator", generator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import checkpoint verifier: {generator_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module.load_frozen_cnn_checkpoint(checkpoint).params_sha256
    finally:
        sys.modules.pop(spec.name, None)


def verify_frozen_inputs(
    workspace: Path,
    a2_config_path: Path,
    *,
    fixed_a2_config_sha256: str = A2_CONFIG_SHA256,
    expected_v1_sha256: str = V1_RUNNER_SHA256,
    expected_backbone_sha256: Mapping[str, str] = CANONICAL_BACKBONE_SHA256,
    backbone_paths: Mapping[str, str] = BACKBONE_PATHS,
    checkpoint_params_hasher: Callable[[Path, Path], str] = _checkpoint_params_sha256,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    verify_file(a2_config_path, fixed_a2_config_sha256, "canonical A2 config")
    config = load_object(a2_config_path, "A2 config")
    _validate_a2_scientific_identity(
        config,
        expected_v1_sha256=expected_v1_sha256,
        expected_backbone_sha256=expected_backbone_sha256,
    )
    frozen = config["frozen_artifacts"]
    sources: dict[str, dict[str, Any]] = {}
    for label in sorted(frozen):
        record = frozen[label]
        if not isinstance(record, Mapping):
            raise TypeError(f"invalid A2 artifact record: {label}")
        if record.get("verification") != "file_sha256":
            continue
        relative = record.get("path")
        expected = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError(f"incomplete A2 file artifact: {label}")
        path = resolve_inside(workspace, relative, f"A2 artifact {label}")
        observed = verify_file(path, expected, f"A2 artifact {label}")
        observed["path"] = display_path(path, workspace)
        sources[label] = observed

    backbones: dict[str, dict[str, Any]] = {}
    for label in ("period_on_sim", "checkpoint_file", "narrow_map", "regular_map"):
        path = resolve_inside(workspace, backbone_paths[label], f"backbone {label}")
        observed = verify_file(path, expected_backbone_sha256[label], f"backbone {label}")
        observed["path"] = display_path(path, workspace)
        backbones[label] = observed
    params_actual = checkpoint_params_hasher(
        workspace, resolve_inside(workspace, backbone_paths["checkpoint_file"], "checkpoint")
    )
    if params_actual != expected_backbone_sha256["checkpoint_params"]:
        raise RuntimeError(
            "checkpoint parameter SHA-256 mismatch: "
            f"expected={expected_backbone_sha256['checkpoint_params']} actual={params_actual}"
        )
    backbones["checkpoint_params"] = {
        "checkpoint_path": backbone_paths["checkpoint_file"],
        "sha256": params_actual,
        # The frozen v1 analyzer permits this pathless identity only under its
        # historical artifact_metadata spelling.  Capture/build still verify
        # the effective float32 payload directly before writing this record.
        "verification": "artifact_metadata",
        "effective_float32_parameter_sha256_verified": True,
    }
    return config, sources, backbones


def load_environment_helpers(
    helper_path: Path,
) -> tuple[Callable[[], Mapping[str, Any]], Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    spec = importlib.util.spec_from_file_location("b_environment_helper", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen environment helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._capture_environment, module._environment_compatibility_projection


def capture_attestation(
    *,
    workspace: Path,
    output: Path,
    a2_config_path: Path,
    protocol_path: Path,
    self_path: Path,
    expected_self_sha256: str,
    b_artifact_specs: Sequence[str],
    zero_paths: Sequence[Path],
    fixed_protocol_sha256: str = PROTOCOL_B_SHA256,
    fixed_a2_config_sha256: str = A2_CONFIG_SHA256,
    expected_v1_sha256: str = V1_RUNNER_SHA256,
    expected_backbone_sha256: Mapping[str, str] = CANONICAL_BACKBONE_SHA256,
    backbone_paths: Mapping[str, str] = BACKBONE_PATHS,
    checkpoint_params_hasher: Callable[[Path, Path], str] = _checkpoint_params_sha256,
    environment_capture: Callable[[], Mapping[str, Any]] | None = None,
    environment_projection: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    live_hostname: str | None = None,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    output = resolve_inside(workspace, output, "attestation output")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite B environment attestation: {output}")
    for path in zero_paths:
        checked = resolve_inside(workspace, path, "B zero-outcome path")
        if checked.exists():
            raise FileExistsError(
                f"cannot attest zero B runs/effects because path exists: {checked}"
            )

    protocol_path = resolve_inside(workspace, protocol_path, "B protocol")
    protocol_record = verify_file(protocol_path, fixed_protocol_sha256, "B protocol")
    protocol_record["path"] = display_path(protocol_path, workspace)
    a2_config_path = resolve_inside(workspace, a2_config_path, "A2 config")
    _, sources, backbones = verify_frozen_inputs(
        workspace,
        a2_config_path,
        fixed_a2_config_sha256=fixed_a2_config_sha256,
        expected_v1_sha256=expected_v1_sha256,
        expected_backbone_sha256=expected_backbone_sha256,
        backbone_paths=backbone_paths,
        checkpoint_params_hasher=checkpoint_params_hasher,
    )
    self_path = resolve_inside(workspace, self_path, "B environment capture script")
    self_record = verify_file(
        self_path, expected_self_sha256, "B environment capture script"
    )
    self_record["path"] = display_path(self_path, workspace)
    b_artifacts = parse_b_artifacts(workspace, b_artifact_specs)
    b_artifacts["capture_environment_b"] = self_record

    if derive_roots(ROOT_SOURCE_SHA256, A2_ROOT_DOMAIN, 10) != A2_ROOTS:
        raise RuntimeError("root derivation no longer reproduces the frozen A2 vector")
    if derive_roots(ROOT_SOURCE_SHA256, ROOT_DOMAIN, 40) != B_ROOTS:
        raise RuntimeError("B root derivation no longer reproduces the frozen vector")
    if len(set(B_ROOTS)) != 40 or set(B_ROOTS) & (set(A1_ROOTS) | set(A2_ROOTS)):
        raise RuntimeError("B roots are duplicated or overlap A1/A2")

    if environment_capture is None or environment_projection is None:
        helper = sources.get("legacy_replay_launcher")
        if not isinstance(helper, Mapping):
            raise RuntimeError("A2 source manifest lacks the environment helper")
        capture, projection = load_environment_helpers(workspace / str(helper["path"]))
        environment_capture = environment_capture or capture
        environment_projection = environment_projection or projection
    for name in THREAD_ENV:
        os.environ[name] = "1"
    environment = dict(environment_capture())
    hostname = live_hostname or socket.gethostname()
    if environment.get("host") != hostname:
        raise RuntimeError(
            f"captured environment host differs from live hostname: "
            f"captured={environment.get('host')!r} live={hostname!r}"
        )
    fingerprint = environment.get("host_instance_fingerprint_sha256")
    if not isinstance(fingerprint, str) or not SHA_RE.fullmatch(fingerprint):
        raise RuntimeError("captured environment lacks a valid host fingerprint")
    thread_environment = environment.get("thread_environment")
    if not isinstance(thread_environment, Mapping) or any(
        thread_environment.get(name) != "1" for name in THREAD_ENV
    ):
        raise RuntimeError("captured environment violates the one-thread contract")
    projection = dict(environment_projection(environment))
    projection_sha = canonical_sha256(projection)

    zero_records = [
        {"path": display_path(resolve_inside(workspace, path, "zero path"), workspace), "exists": False}
        for path in zero_paths
    ]
    payload = {
        "schema": ATTESTATION_SCHEMA,
        "status": "complete",
        "passed": True,
        "created_utc": utc_now(),
        "created_before_experiment_b": True,
        "execution_host": hostname,
        "b_fresh_root_runs_observed": 0,
        "b_effect_estimates_computed": 0,
        "b_method_rankings_inspected": 0,
        "b_effect_inference_performed": False,
        "prior_a2_outcomes_known": True,
        "standalone_primary_analysis": True,
        "pool_with_a2": False,
        "evidence_class": "content_hashed_internal_pre_specification_host_environment_no_b_outcomes",
        "public_preregistration": False,
        "protocol": protocol_record,
        "predecessor_config": {
            "path": display_path(a2_config_path, workspace),
            "sha256": fixed_a2_config_sha256,
            "role": "scientific-contract template; prior A2 outcomes were known and informed B power design",
        },
        "experiment_b_contract": {
            "root_seeds": list(B_ROOTS),
            "root_count": 40,
            "roots_disjoint_from_a1_and_a2": True,
            "root_derivation": {
                "source_sha256": ROOT_SOURCE_SHA256,
                "domain": ROOT_DOMAIN,
                "formula": "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)",
                "index_start": 0,
                "index_end": 39,
                "count": 40,
            },
            "methods": list(METHODS),
            "workloads": list(WORKLOADS),
            "scenario_ids": [item[0] for item in SCENARIOS],
            "runs_per_scenario": 960,
            "attempt_ledger_events_per_scenario": 1920,
            "paired_cells_per_method": 480,
            "total_runs": 3840,
        },
        "thread_contract": {name: "1" for name in THREAD_ENV},
        "zero_b_outcome_checks": zero_records,
        "inherited_file_sources": sources,
        "backbone_artifacts": backbones,
        "b_control_plane_artifacts": b_artifacts,
        "environment": environment,
        "environment_compatibility_projection": projection,
        "environment_compatibility_projection_sha256": projection_sha,
    }
    encoded = json_bytes(payload)

    # Close the normal capture/verification time-of-check window.
    verify_file(protocol_path, fixed_protocol_sha256, "B protocol postcheck")
    verify_file(a2_config_path, fixed_a2_config_sha256, "A2 config postcheck")
    for label, record in {**sources, **b_artifacts}.items():
        verify_file(workspace / str(record["path"]), str(record["sha256"]), f"{label} postcheck")
    for label, record in backbones.items():
        if record.get("verification") == "file_sha256":
            verify_file(workspace / str(record["path"]), str(record["sha256"]), f"{label} postcheck")
    for path in zero_paths:
        checked = resolve_inside(workspace, path, "B zero-outcome path postcheck")
        if checked.exists():
            raise FileExistsError(f"B outcome path appeared during capture: {checked}")
    write_atomic_exclusive(output, encoded)
    return {
        "path": str(output),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "execution_host": hostname,
        "host_instance_fingerprint_sha256": fingerprint,
        "environment_compatibility_projection_sha256": projection_sha,
        "b_fresh_root_runs_observed": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("reports/same_call_environment_attestation_b.json"))
    parser.add_argument("--a2-config", type=Path, default=Path("configs/same_call_confirmation_a2.json"))
    parser.add_argument("--protocol", type=Path, default=Path("EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-15_B.md"))
    parser.add_argument("--expected-self-sha256", required=True)
    parser.add_argument(
        "--b-artifact", action="append", default=[], metavar="LABEL=RELATIVE_PATH=SHA256",
        help="frozen B runner/analyzer/launcher/builder and optional test identity",
    )
    parser.add_argument("--b-results-dir", type=Path, default=Path("results/same_call_confirmation_b"))
    parser.add_argument("--b-logs-dir", type=Path, default=Path("logs/same_call_confirmation_b"))
    parser.add_argument("--b-config-output", type=Path, default=Path("configs/same_call_confirmation_b.json"))
    parser.add_argument("--b-freeze-output", type=Path, default=Path("configs/same_call_implementation_freeze_b.json"))
    parser.add_argument("--b-analysis-json", type=Path, default=Path("reports/same_call_confirmation_b_analysis.json"))
    parser.add_argument("--b-analysis-md", type=Path, default=Path("reports/same_call_confirmation_b_analysis.md"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = capture_attestation(
        workspace=args.workspace,
        output=args.output,
        a2_config_path=args.a2_config,
        protocol_path=args.protocol,
        self_path=Path(__file__),
        expected_self_sha256=args.expected_self_sha256,
        b_artifact_specs=args.b_artifact,
        zero_paths=(
            args.b_results_dir,
            args.b_logs_dir,
            args.b_config_output,
            args.b_freeze_output,
            args.b_analysis_json,
            args.b_analysis_md,
        ),
    )
    print("SAME_CALL_ENVIRONMENT_ATTESTATION_B_CAPTURED " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
