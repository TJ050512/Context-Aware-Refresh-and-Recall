#!/usr/bin/env bash
set -euo pipefail

# Experiment B formal launcher.  This file launches only the frozen 40-root
# matrix and performs an effect-blind integrity audit.  Statistical analysis is
# deliberately a separate, one-shot command after this launcher reports PASS.

MODE="run"
if [[ "$#" -eq 1 && "$1" == "--preflight-only" ]]; then
  MODE="preflight"
elif [[ "$#" -ne 0 ]]; then
  echo "usage: $0 [--preflight-only]" >&2
  exit 64
fi

WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CONFIG="${SAME_CALL_CONFIG:-$WORKSPACE/configs/same_call_confirmation_b.json}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_b.py"
PROTOCOL="$WORKSPACE/EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-15_B.md"
OUTDIR="$WORKSPACE/results/same_call_confirmation_b"
LOGDIR="$WORKSPACE/logs/same_call_confirmation_b"
AUDIT_REPORT="$WORKSPACE/reports/same_call_confirmation_b_matrix_integrity.json"

readonly B_PROTOCOL_SHA256="35de3d61030803e58517b361b90a60a042e6bc68290171ff974e16270a859d06"
readonly B_DERIVATION_SOURCE_SHA256="6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
readonly B_DOMAIN="dai-same-call-confirmatory-b-power-extension"

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

for required in "$DAI_PYTHON" "$CONFIG" "$RUNNER" "$PROTOCOL"; do
  if [[ ! -f "$required" ]]; then
    echo "Experiment B required file is absent: $required" >&2
    exit 2
  fi
done

CONFIG_SHA="$($DAI_PYTHON - "$CONFIG" <<'PY'
import hashlib
import pathlib
import sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
CURRENT_HOST="$(hostname)"

TARGET_HOST="$($DAI_PYTHON - "$CONFIG" <<'PY'
import json
import pathlib
import sys
config = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
target = config.get("target_environment")
if not isinstance(target, dict) or not isinstance(target.get("execution_host"), str):
    raise SystemExit("B config lacks target_environment.execution_host")
print(target["execution_host"])
PY
)"

JOBS_PER_SCENARIO="$($DAI_PYTHON - "$CONFIG" <<'PY'
import json
import pathlib
import sys
config = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
execution = config.get("execution")
jobs = execution.get("jobs_per_scenario") if isinstance(execution, dict) else None
if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs < 1:
    raise SystemExit("B config execution.jobs_per_scenario must be a positive integer")
print(jobs)
PY
)"

if [[ "$CURRENT_HOST" != "$TARGET_HOST" ]]; then
  echo "Experiment B target-host mismatch: expected=$TARGET_HOST actual=$CURRENT_HOST" >&2
  exit 2
fi

verify_control_plane() {
  "$DAI_PYTHON" - \
    "$WORKSPACE" "$CONFIG" "$CONFIG_SHA" "$CURRENT_HOST" \
    "$B_PROTOCOL_SHA256" "$B_DERIVATION_SOURCE_SHA256" "$B_DOMAIN" <<'PY'
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

(
    workspace_raw,
    config_raw,
    config_sha,
    current_host,
    expected_protocol_sha,
    derivation_source,
    derivation_domain,
) = sys.argv[1:]
workspace = Path(workspace_raw).resolve()
config_path = Path(config_raw).resolve()


def fail(message):
    raise SystemExit(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve(raw, label):
    if not isinstance(raw, str) or not raw:
        fail(f"{label} must be a non-empty path")
    path = Path(raw).expanduser()
    path = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    try:
        path.relative_to(workspace)
    except ValueError:
        fail(f"{label} escapes workspace: {path}")
    return path


if sha256_file(config_path) != config_sha:
    fail("B config changed after the launcher read its digest")
config = json.loads(config_path.read_text(encoding="utf-8"))
expected_roots = (
    880565, 534821, 257578, 500976, 294860, 954705, 190142, 429853,
    398397, 560584, 175381, 598292, 461566, 526869, 115950, 130998,
    655067, 585455, 362413, 552654, 664860, 253714, 962860, 907962,
    381214, 583444, 371204, 934561, 491276, 541256, 523055, 713041,
    537643, 699809, 204011, 330180, 113743, 257704, 152753, 657283,
)
expected_methods = (
    "bootstrap_only", "exact_even_G4", "exact_even_G5", "random_G5",
    "js_cap_G5", "context_no_reactivation_B25", "context_memory_B25",
    "exact_even_B25",
)
expected_workloads = ("stationary", "abrupt", "recurrent")
expected_scenarios = [
    {"id": "narrow_r020", "agents": 218, "map_sha256": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6"},
    {"id": "narrow_r035", "agents": 382, "map_sha256": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6"},
    {"id": "regular_r020", "agents": 255, "map_sha256": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"},
    {"id": "regular_r035", "agents": 447, "map_sha256": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"},
]

if config.get("schema") != "dai.same-call-confirmation/b":
    fail("B config schema is invalid")
if config.get("status") != "content_hashed_internal_pre_specification_frozen_before_b_matrix":
    fail("B config is not in its frozen pre-matrix state")
if config.get("execution_host") != current_host:
    fail(
        "B config top-level execution_host differs from the live host: "
        f"expected={config.get('execution_host')!r} actual={current_host!r}"
    )
if config.get("public_preregistration") is not False:
    fail("B config must honestly identify the freeze as internal")
if config.get("standalone_replication") is not True or config.get(
    "primary_analysis_pools_with_a1_or_a2"
) is not False:
    fail("B config must specify a standalone, unpooled primary analysis")
if tuple(config.get("root_seeds", ())) != expected_roots:
    fail("B config root vector differs from the frozen 40 roots")
derived = []
for index in range(40):
    token = f"{derivation_source}|{derivation_domain}|{index}".encode("utf-8")
    derived.append(
        100000 + int(hashlib.sha256(token).hexdigest()[:16], 16) % 900000
    )
if tuple(derived) != expected_roots or len(set(expected_roots)) != 40:
    fail("B roots do not reproduce the frozen derivation")
expected_derivation = {
    "source_sha256": derivation_source,
    "domain": derivation_domain,
    "formula": "100000 + (int(SHA256(source|domain|i)[0:16],16) mod 900000)",
    "index_start": 0,
    "index_end": 39,
    "count": 40,
}
if config.get("root_derivation") != expected_derivation:
    fail("B root-derivation record differs from the frozen contract")
if tuple(config.get("methods", ())) != expected_methods:
    fail("B method vector differs from the frozen eight-arm family")
if tuple(config.get("workloads", ())) != expected_workloads:
    fail("B workload vector differs from the frozen family")
if config.get("scenarios") != expected_scenarios:
    fail("B scenario matrix differs from the frozen map/agent contract")

protocol = config.get("protocol")
required_protocol = {
    "bootstrap_samples": 10000,
    "bootstrap_seed": 20260715,
    "cells_per_root_seed_per_method": 12,
    "decision_window": 20,
    "guard_suffix_tasks_per_agent": 4,
    "independent_inference_unit": "root_seed",
    "noninferiority_margin": 0.01,
    "release_interval_per_agent": 110,
    "scored_horizon": 2000,
    "total_runs": 3840,
    "warmup_time": 200,
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
if not isinstance(protocol, dict) or any(
    protocol.get(field) != value for field, value in required_protocol.items()
):
    fail("B scientific protocol fields differ from the frozen contract")

thread_contract = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
execution = config.get("execution")
if (
    not isinstance(execution, dict)
    or isinstance(execution.get("jobs_per_scenario"), bool)
    or not isinstance(execution.get("jobs_per_scenario"), int)
    or execution["jobs_per_scenario"] < 1
    or execution.get("scenario_processes") != 4
    or execution.get("thread_environment") != thread_contract
    or execution.get("runs_per_scenario") != 960
    or execution.get("attempt_ledger_events_per_scenario") != 1920
    or execution.get("total_runs") != 3840
):
    fail("B execution contract is incomplete or not frozen")
if any(os.environ.get(name) != value for name, value in thread_contract.items()):
    fail("live thread environment differs from the one-thread contract")

identity = config.get("process_identity_gate")
if not isinstance(identity, dict) or identity != {
    "hard_identity": [
        "execution_host", "execution_process_id", "execution_process_start_ns"
    ],
    "unique_process_instances_required": 3840,
    "unique_run_uuids_required": 3840,
    "bare_pid_uniqueness_is_gate": False,
}:
    fail("B process-instance identity gate differs from the frozen contract")
analysis = config.get("analysis_contract")
if not isinstance(analysis, dict) or analysis != {
    "execute_after_complete_integrity_audit_only": True,
    "execute_content_hashed_analyzer_exactly_once": True,
    "whole_root_bootstrap_samples": 10000,
    "whole_root_bootstrap_seed": 20260715,
    "singleton_noninferiority_separate_from_holm_family": True,
    "report_regardless_of_direction": True,
}:
    fail("B one-shot analysis contract differs from the freeze")

required = config.get("required_frozen_artifacts")
frozen = config.get("frozen_artifacts")
if (
    not isinstance(required, list)
    or not isinstance(frozen, dict)
    or set(required) != set(frozen)
):
    fail("B frozen-artifact manifest is incomplete")
for label in required:
    record = frozen.get(label)
    if not isinstance(record, dict):
        fail(f"invalid frozen artifact record: {label}")
    expected = record.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        fail(f"frozen artifact lacks SHA-256: {label}")
    if record.get("path") is not None:
        path = resolve(record["path"], f"frozen artifact {label}")
        if not path.is_file() or sha256_file(path) != expected:
            fail(f"frozen artifact file/hash mismatch: {label} path={path}")
    elif record.get("verification") != "artifact_metadata":
        fail(f"unverifiable frozen artifact: {label}")
if frozen.get("protocol_b", {}).get("sha256") != expected_protocol_sha:
    fail("B config does not bind the exact frozen B protocol")
if frozen.get("a1_effect_blind_failure", {}).get("sha256") != derivation_source:
    fail("B config does not bind the exact root-derivation source")
if frozen.get("validation_runner", {}).get("sha256") != (
    "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538"
):
    fail("B config does not bind the frozen v1 behavior runner")

provenance = config.get("provenance")
if not isinstance(provenance, dict):
    fail("B config provenance is missing")
for field in (
    "b_fresh_root_runs_observed_at_freeze",
    "b_effect_estimates_computed_before_config",
    "b_method_rankings_inspected_before_config",
):
    if provenance.get(field) != 0:
        fail(f"B provenance counter is not zero: {field}")
if (
    provenance.get("effect_inference_performed_before_config") is not False
    or provenance.get("prior_a2_outcomes_known") is not True
    or provenance.get("standalone_primary_analysis") is not True
    or provenance.get("pool_with_a2") is not False
):
    fail("B provenance disclosure/zero-inference contract is invalid")
freeze_path = resolve(
    provenance.get("implementation_freeze_path"), "implementation freeze"
)
freeze_sha = provenance.get("implementation_freeze_sha256")
if not freeze_path.is_file() or sha256_file(freeze_path) != freeze_sha:
    fail("B implementation-freeze file/hash mismatch")
freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
if (
    freeze.get("schema") != "dai.same-call-implementation-freeze/b"
    or freeze.get("status")
    != "content_hashed_internal_pre_specification_before_any_b_root"
    or tuple(freeze.get("confirmation_roots", ())) != expected_roots
    or tuple(freeze.get("methods", ())) != expected_methods
    or tuple(freeze.get("workloads", ())) != expected_workloads
    or freeze.get("root_derivation") != expected_derivation
    or freeze.get("scenarios") != config.get("scenarios")
    or freeze.get("file_artifacts") != frozen
    or freeze.get("preflight_evidence") != config.get("preflight_evidence")
    or freeze.get("protocol") != frozen.get("protocol_b")
    or freeze.get("b_engineering_smoke")
    != config.get("preflight_evidence", {}).get("b_engineering_smoke")
    or freeze.get("target_environment") != config.get("target_environment")
):
    fail("B implementation freeze differs from the config or protocol")
for field in (
    "b_fresh_root_runs_observed",
    "b_effect_estimates_computed",
    "b_method_rankings_inspected",
):
    if freeze.get(field) != 0:
        fail(f"implementation-freeze counter is not zero: {field}")
if freeze.get("effect_inference_performed") is not False:
    fail("implementation freeze records B effect inference")
freeze_execution = freeze.get("execution")
if not isinstance(freeze_execution, dict) or freeze_execution != execution:
    fail("implementation-freeze execution settings differ from config")

preflight = config.get("preflight_evidence")
required_preflight = config.get("required_preflight_evidence")
if (
    not isinstance(preflight, dict)
    or not isinstance(required_preflight, list)
    or set(preflight) != set(required_preflight)
    or "b_engineering_smoke" not in preflight
    or "b_environment_attestation" not in preflight
):
    fail("B preflight manifest is incomplete")
for label in required_preflight:
    record = preflight[label]
    path = resolve(record.get("path"), f"preflight {label}")
    if (
        record.get("passed") is not True
        or not path.is_file()
        or sha256_file(path) != record.get("sha256")
    ):
        fail(f"B preflight failed or drifted: {label}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    audit = payload.get("audit") if isinstance(payload, dict) else None
    passed = payload.get("passed") is True or (
        isinstance(audit, dict) and audit.get("passed") is True
    )
    explicitly_failed = payload.get("passed") is False or (
        isinstance(audit, dict) and audit.get("passed") is False
    )
    if not passed or explicitly_failed:
        fail(f"B preflight report does not report PASS: {label}")

target = config.get("target_environment")
if (
    not isinstance(target, dict)
    or config.get("execution_host") != target.get("execution_host")
    or target.get("execution_host") != current_host
):
    fail("B target-environment host differs from the live host")
attestation_path = resolve(target.get("path"), "B environment attestation")
if (
    not attestation_path.is_file()
    or sha256_file(attestation_path) != target.get("sha256")
):
    fail("B environment-attestation file/hash mismatch")
attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
sealed_environment = attestation.get("environment")
sealed_projection = attestation.get("environment_compatibility_projection")
if (
    attestation.get("schema") != "dai.same-call-environment-attestation/b"
    or attestation.get("status") != "complete"
    or attestation.get("passed") is not True
    or attestation.get("created_before_experiment_b") is not True
    or attestation.get("execution_host") != current_host
    or attestation.get("b_fresh_root_runs_observed") != 0
    or attestation.get("b_effect_estimates_computed") != 0
    or attestation.get("b_method_rankings_inspected") != 0
    or attestation.get("b_effect_inference_performed") is not False
    or attestation.get("prior_a2_outcomes_known") is not True
    or attestation.get("standalone_primary_analysis") is not True
    or attestation.get("pool_with_a2") is not False
    or not isinstance(sealed_environment, dict)
    or not isinstance(sealed_projection, dict)
):
    fail("B environment attestation is incomplete or not pre-outcome")
if canonical_sha256(sealed_projection) != attestation.get(
    "environment_compatibility_projection_sha256"
):
    fail("B sealed compatibility projection hash is invalid")
if target.get("host_instance_fingerprint_sha256") != sealed_environment.get(
    "host_instance_fingerprint_sha256"
):
    fail("B target fingerprint differs from the attestation")
if target.get("compatibility_projection_sha256") != attestation.get(
    "environment_compatibility_projection_sha256"
):
    fail("B target projection digest differs from the attestation")
attested_contract = attestation.get("experiment_b_contract")
if (
    not isinstance(attested_contract, dict)
    or tuple(attested_contract.get("root_seeds", ())) != expected_roots
    or tuple(attested_contract.get("methods", ())) != expected_methods
    or tuple(attested_contract.get("workloads", ())) != expected_workloads
    or tuple(attested_contract.get("scenario_ids", ()))
    != tuple(row["id"] for row in expected_scenarios)
    or attested_contract.get("total_runs") != 3840
):
    fail("B attested scientific contract differs from the frozen config")
if attestation.get("protocol") != frozen.get("protocol_b"):
    fail("B attestation protocol record differs from the frozen config")
attested_b_artifacts = attestation.get("b_control_plane_artifacts")
if not isinstance(attested_b_artifacts, dict) or any(
    frozen.get(label) != record for label, record in attested_b_artifacts.items()
):
    fail("B attested control-plane files differ from the frozen config")

helper_record = frozen.get("legacy_replay_launcher")
helper_path = resolve(helper_record.get("path"), "environment-capture helper")
spec = importlib.util.spec_from_file_location("b_launcher_environment_helper", helper_path)
if spec is None or spec.loader is None:
    fail(f"cannot import the frozen environment helper: {helper_path}")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
current_environment = helper._capture_environment()
current_projection = helper._environment_compatibility_projection(current_environment)
if current_environment.get("host") != current_host:
    fail("live environment helper reports another host")
if current_environment.get("host_instance_fingerprint_sha256") != sealed_environment.get(
    "host_instance_fingerprint_sha256"
):
    fail("live host-instance fingerprint differs from the sealed B host")
if current_environment.get("gpu_inventory") != sealed_environment.get("gpu_inventory"):
    fail("live ordered GPU inventory differs from the sealed B host")
if current_projection != sealed_projection:
    fail("live host/runtime projection differs from the sealed B environment")

print(
    "SAME_CALL_CONFIRMATION_B_PREFLIGHT_PASS "
    f"host={current_host} config_sha256={config_sha} "
    f"freeze_sha256={freeze_sha} attestation_sha256={target['sha256']} "
    f"jobs_per_scenario={execution['jobs_per_scenario']} roots=40 total_runs=3840"
)
PY
}

verify_control_plane
if [[ "$MODE" == "preflight" ]]; then
  exit 0
fi

# A formal B matrix is all-or-nothing.  Any prior output, ledger, log, CSV, or
# integrity report makes this launch fail closed; this is not a resume path.
for label in narrow_r020 narrow_r035 regular_r020 regular_r035; do
  output="$OUTDIR/$label.json"
  if [[ -e "$output" || -e "${output%.json}.csv" || \
        -e "$OUTDIR/$label.attempts.jsonl" || -e "$LOGDIR/$label.log" ]]; then
    echo "Refusing to overwrite or resume protected Experiment B artifact: $label" >&2
    exit 3
  fi
done
if [[ -e "$AUDIT_REPORT" ]]; then
  echo "Refusing to overwrite Experiment B integrity report: $AUDIT_REPORT" >&2
  exit 3
fi
mkdir -p "$OUTDIR" "$LOGDIR" "$(dirname "$AUDIT_REPORT")"

SEEDS_TEXT="$($DAI_PYTHON - "$CONFIG" <<'PY'
import json
import pathlib
import sys
roots = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["root_seeds"]
if len(roots) != 40 or any(isinstance(root, bool) or not isinstance(root, int) for root in roots):
    raise SystemExit("B config must contain exactly 40 integer roots")
print(" ".join(map(str, roots)))
PY
)"
read -r -a SEEDS <<< "$SEEDS_TEXT"
METHODS=(
  bootstrap_only
  exact_even_G4
  exact_even_G5
  random_G5
  js_cap_G5
  context_no_reactivation_B25
  context_memory_B25
  exact_even_B25
)
COMMON=(
  --workspace "$WORKSPACE"
  --checkpoint "$CKPT"
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac
  --development-matrix-config-sha256 "$CONFIG_SHA"
  --split same_call_confirmation_v1
  --seeds "${SEEDS[@]}"
  --workloads stationary abrupt recurrent
  --methods "${METHODS[@]}"
  --warmup-time 200
  --horizon 2000
  --decision-window 20
  --release-interval 110
  --guard-suffix 4
  --sigma 0.75
  --context-match-threshold 0.05
  --context-recall-margin 0.02
  --context-min-score 0.10
  --context-min-gap 6
  --context-maintenance-age 25
  --context-maintenance-stability 0.20
  --fresh-process-per-arm
  --jobs "$JOBS_PER_SCENARIO"
)

PIDS=()
LABELS=()

terminate_children() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 130
}
trap terminate_children INT TERM HUP

launch() {
  local label="$1"
  local map_name="$2"
  local agents="$3"
  local output="$OUTDIR/$label.json"
  local log="$LOGDIR/$label.log"
  local ledger="$OUTDIR/$label.attempts.jsonl"
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_name" \
    --agents "$agents" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$label")
  echo "started Experiment B label=$label pid=$! host=$TARGET_HOST jobs=$JOBS_PER_SCENARIO"
}

launch narrow_r020 warehouse_small_narrow_kiva.map 218
launch narrow_r035 warehouse_small_narrow_kiva.map 382
launch regular_r020 warehouse_small_kiva.map 255
launch regular_r035 warehouse_small_kiva.map 447

failed=0
for index in "${!PIDS[@]}"; do
  if wait "${PIDS[$index]}"; then
    echo "completed Experiment B label=${LABELS[$index]}"
  else
    echo "failed Experiment B label=${LABELS[$index]} log=$LOGDIR/${LABELS[$index]}.log" >&2
    failed=1
  fi
done
trap - INT TERM HUP
if [[ "$failed" -ne 0 ]]; then
  echo "Experiment B is incomplete; quarantine all formal paths and do not inspect effects." >&2
  exit 4
fi

# Close the execution time-of-check window before auditing emitted artifacts.
verify_control_plane

"$DAI_PYTHON" - "$OUTDIR" "$CONFIG" "$CONFIG_SHA" "$TARGET_HOST" "$AUDIT_REPORT" <<'PY'
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import uuid

outdir = Path(sys.argv[1]).resolve()
config_path = Path(sys.argv[2]).resolve()
config_sha = sys.argv[3]
target_host = sys.argv[4]
audit_path = Path(sys.argv[5]).resolve()
config = json.loads(config_path.read_text(encoding="utf-8"))
expected_roots = tuple(config["root_seeds"])
expected_methods = tuple(config["methods"])
expected_workloads = tuple(config["workloads"])
expected_scenarios = {
    "narrow_r020": (218, "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6"),
    "narrow_r035": (382, "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6"),
    "regular_r020": (255, "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"),
    "regular_r035": (447, "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"),
}
ledger_schema = "dai.same-call-attempt-ledger/v1"
identity_fields = {"split", "map_id", "agents", "seed", "workload", "method"}


def fail(message):
    raise SystemExit(message)


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def nonnegative_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value


def attempt_identity(run, agents):
    return {
        "split": str(run["split"]),
        "map_id": str(run["map_id"]),
        "agents": agents,
        "seed": int(run["seed"]),
        "workload": str(run["workload"]),
        "method": str(run["method"]),
    }


def exact_schedule(budget):
    return [
        decision
        for decision in range(1, 100)
        if (decision * budget) // 99 > ((decision - 1) * budget) // 99
    ]


def verify_ledger(artifact_path, artifact, runs, agents):
    record = artifact.get("attempt_ledger")
    if not isinstance(record, dict) or record.get("schema") != ledger_schema:
        fail(f"attempt-ledger record is invalid in {artifact_path}")
    raw_path = record.get("path")
    ledger_path = Path(raw_path).expanduser().resolve() if isinstance(raw_path, str) else None
    if (
        ledger_path is None
        or not ledger_path.is_file()
        or sha256_file(ledger_path) != record.get("sha256")
    ):
        fail(f"attempt-ledger file/hash mismatch in {artifact_path}")
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1920 or any(not line.strip() for line in lines):
        fail(f"attempt ledger must contain 1920 nonblank events: {ledger_path}")
    try:
        events = [json.loads(line) for line in lines]
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid JSONL attempt ledger: {ledger_path}") from error
    if record.get("started_events") != 960 or record.get("completed_events") != 960:
        fail(f"attempt-ledger declared counts are invalid: {ledger_path}")
    grouped = {}
    for event in events:
        if not isinstance(event, dict) or event.get("schema") != ledger_schema:
            fail(f"attempt-ledger event/schema drift: {ledger_path}")
        event_name = event.get("event")
        if event_name not in {"started", "completed"}:
            fail(f"attempt ledger contains failure/retry/unknown event: {ledger_path}")
        identity = event.get("identity")
        if not isinstance(identity, dict) or set(identity) != identity_fields:
            fail(f"attempt-ledger identity is invalid: {ledger_path}")
        attempt_id = event.get("attempt_id")
        if attempt_id != canonical_sha256(identity):
            fail(f"attempt id does not bind its identity: {ledger_path}")
        bucket = grouped.setdefault(attempt_id, {})
        if event_name in bucket:
            fail(f"attempt ledger contains duplicate/retry event: {ledger_path}")
        bucket[event_name] = event
    expected_by_id = {}
    for run in runs:
        identity = attempt_identity(run, agents)
        attempt_id = canonical_sha256(identity)
        if attempt_id in expected_by_id:
            fail(f"retained runs contain a duplicate arm: {artifact_path}")
        expected_by_id[attempt_id] = (identity, run)
    if len(expected_by_id) != 960 or set(grouped) != set(expected_by_id):
        fail(f"ledger does not cover retained arms exactly once: {artifact_path}")
    for attempt_id, (identity, run) in expected_by_id.items():
        bucket = grouped[attempt_id]
        if set(bucket) != {"started", "completed"}:
            fail(f"attempt ledger contains unfinished/deleted arm: {artifact_path}")
        started = bucket["started"]
        completed = bucket["completed"]
        if started.get("identity") != identity or completed.get("identity") != identity:
            fail(f"attempt identity changed during execution: {artifact_path}")
        start_time = started.get("time_ns")
        process_start = run.get("execution_process_start_ns")
        completion_time = completed.get("time_ns")
        if (
            not positive_integer(start_time)
            or not positive_integer(process_start)
            or not positive_integer(completion_time)
            or not start_time <= process_start <= completion_time
        ):
            fail(f"attempt timestamps are not causally ordered: {artifact_path}")
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
            or completed.get("run_sha256") != canonical_sha256(run)
        ):
            fail(f"attempt completion does not bind retained run: {artifact_path}")
    return str(ledger_path)


paths = {label: outdir / f"{label}.json" for label in expected_scenarios}
if any(not path.is_file() for path in paths.values()):
    fail("one or more of the four Experiment B scenario artifacts is missing")
unexpected = sorted(path.name for path in outdir.glob("*.json") if path not in paths.values())
if unexpected:
    fail(f"unexpected JSON artifact in formal output directory: {unexpected}")

frozen = config["frozen_artifacts"]
source_labels = (
    "claim_runner", "validation_runner", "publication_policy",
    "frozen_cnn_generator", "online_ggo_adapter", "trafficflow_online_env",
    "task_generator", "period_on_sim", "checkpoint_file", "protocol",
)
expected_sources = {label: frozen[label]["sha256"] for label in source_labels}
expected_thread_environment = config["execution"]["thread_environment"]
expected_jobs = config["execution"]["jobs_per_scenario"]
reference_environment = None
reference_environment_sha = None
all_process_instances = []
all_run_uuids = []
all_arm_keys = []
all_runs = []
ledger_paths = []
artifact_digests = {}
cell_groups = {}
random_schedules = {}

for scenario_id, path in paths.items():
    artifact_digests[scenario_id] = sha256_file(path)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    runs = artifact.get("runs")
    agents, map_sha = expected_scenarios[scenario_id]
    if (
        artifact.get("schema") != "dai.claim-aware-absolute-budget/v1"
        or artifact.get("status") != "complete"
        or not isinstance(runs, list)
        or len(runs) != 960
    ):
        fail(f"incomplete Experiment B scenario artifact: {path}")
    if (
        artifact.get("split") != "same_call_confirmation_v1"
        or artifact.get("evidence_class") != "same_call_confirmation_v1"
        or artifact.get("development_matrix_config_sha256") != config_sha
        or tuple(artifact.get("seeds", ())) != expected_roots
        or tuple(artifact.get("methods", ())) != expected_methods
        or tuple(artifact.get("workloads", ())) != expected_workloads
        or artifact.get("fresh_process_per_arm") is not True
        or artifact.get("map_sha256") != map_sha
        or artifact.get("period_on_sim_sha256") != frozen["period_on_sim"]["sha256"]
    ):
        fail(f"scenario identity/config/backbone drift: {path}")
    generator = artifact.get("generator")
    if (
        not isinstance(generator, dict)
        or generator.get("file_sha256") != frozen["checkpoint_file"]["sha256"]
        or generator.get("params_sha256") != frozen["checkpoint_params"]["sha256"]
    ):
        fail(f"checkpoint identity drift: {path}")
    protocol = artifact.get("protocol")
    expected_protocol = {
        "agents": agents,
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
        "jobs": expected_jobs,
        "exclusive_timing_declared": False,
        "timing_evidence_valid": False,
    }
    if not isinstance(protocol, dict) or any(
        protocol.get(field) != value for field, value in expected_protocol.items()
    ):
        fail(f"scenario scientific/execution protocol drift: {path}")
    if (
        protocol.get("context_memory_B25", {}).get("recall_threshold") != 0.05
        or protocol.get("context_memory_B25", {}).get("recall_margin") != 0.02
        or protocol.get("context_memory_B25", {}).get("absolute_score_gate") != 0.10
        or protocol.get("context_memory_B25", {}).get("min_gap_windows") != 6
        or protocol.get("context_memory_B25", {}).get("maintenance_age_windows") != 25
        or protocol.get("context_memory_B25", {}).get("maintenance_stability_gate") != 0.20
    ):
        fail(f"CARR controller parameters drifted: {path}")
    split_protocol = artifact.get("split_protocol")
    if (
        not isinstance(split_protocol, dict)
        or split_protocol.get("preregistered_seeds") != list(expected_roots)
        or split_protocol.get("seed_derivation_source_sha256")
        != config["root_derivation"]["source_sha256"]
        or split_protocol.get("seed_derivation_domain")
        != config["root_derivation"]["domain"]
        or split_protocol.get("artifact_overwrite_permitted") is not False
    ):
        fail(f"B split/root provenance is invalid: {path}")
    runtime = artifact.get("runtime_manifest")
    environment = runtime.get("environment") if isinstance(runtime, dict) else None
    sources = runtime.get("sources") if isinstance(runtime, dict) else None
    if not isinstance(environment, dict) or not isinstance(sources, dict):
        fail(f"runtime manifest is missing: {path}")
    for label, expected_digest in expected_sources.items():
        record = sources.get(label)
        if not isinstance(record, dict) or record.get("sha256") != expected_digest:
            fail(f"runtime source hash drift {label}: {path}")
    expected_map_digest = frozen[
        "narrow_map" if scenario_id.startswith("narrow_") else "regular_map"
    ]["sha256"]
    if sources.get("map", {}).get("sha256") != expected_map_digest:
        fail(f"runtime map source drift: {path}")
    if (
        environment.get("host") != target_host
        or environment.get("thread_environment") != expected_thread_environment
        or environment.get("torch_num_threads") != 1
        or environment.get("torch_num_interop_threads") != 1
    ):
        fail(f"runtime host/thread environment drift: {path}")
    environment_sha = canonical_sha256(environment)
    if reference_environment is None:
        reference_environment = environment
        reference_environment_sha = environment_sha
    elif environment != reference_environment:
        fail(
            "full runtime environment differs across scenarios: "
            f"reference={reference_environment_sha} actual={environment_sha} path={path}"
        )

    for run in runs:
        if not isinstance(run, dict):
            fail(f"run is not an object: {path}")
        root = run.get("root_seed", run.get("seed"))
        if (
            run.get("seed") != root
            or root not in expected_roots
            or run.get("method") not in expected_methods
            or run.get("workload") not in expected_workloads
            or run.get("split") != "same_call_confirmation_v1"
            or run.get("evidence_class") != "same_call_confirmation_v1"
            or run.get("map_id") != artifact.get("map_id")
            or run.get("scored_horizon") != 2000
            or run.get("decision_window") != 20
            or run.get("window_count") != 100
        ):
            fail(f"run arm/protocol identity drift: {path}")
        pid = run.get("execution_process_id")
        ppid = run.get("execution_parent_process_id")
        start_ns = run.get("execution_process_start_ns")
        host = run.get("execution_host")
        run_uuid = run.get("run_uuid")
        if (
            host != target_host
            or not positive_integer(pid)
            or not positive_integer(ppid)
            or pid == ppid
            or not positive_integer(start_ns)
            or not canonical_uuid(run_uuid)
        ):
            fail(f"run process-instance/UUID identity is invalid: {path}")
        safety = run.get("safety")
        invariants = run.get("invariants")
        if (
            not isinstance(safety, dict)
            or safety.get("passed") is not True
            or safety.get("collision_count") != 0
            or safety.get("edge_swap_count") != 0
            or safety.get("invalid_move_count") != 0
            or safety.get("endpoint_mismatch_count") != 0
            or safety.get("route_trace_invalid_count") != 0
            or safety.get("planner_timeout_count") != run.get("planner_timeouts")
            or not isinstance(invariants, dict)
            or invariants.get("passed") is not True
            or invariants.get("online_workload_rng_draws") != 0
            or invariants.get("tape_not_exhausted") is not True
            or invariants.get("reward_sum_matches_completed") is not True
            or invariants.get("unexposed_completions_excluded_from_cohorts") is not True
        ):
            fail(f"run safety/RNG/tape invariant failed: {path}")
        if (
            run.get("collisions") != 0
            or run.get("edge_swaps") != 0
            or run.get("invalid_moves") != 0
            or run.get("budget_violation_count") != 0
        ):
            fail(f"run flat safety/budget invariant failed: {path}")
        tape = run.get("task_tape_identity")
        arrival = run.get("workload_arrival")
        if (
            not isinstance(tape, dict)
            or tape.get("mode") != "absolute_release_queue_per_agent"
            or tape.get("schema_version") != "dai.kiva-absolute-release-tape/v1"
            or not isinstance(tape.get("start_locations"), list)
            or len(tape["start_locations"]) != agents
            or len(set(tape["start_locations"])) != agents
            or not isinstance(tape.get("per_agent_lengths"), list)
            or len(tape["per_agent_lengths"]) != agents
            or tape.get("total_tasks") != sum(tape["per_agent_lengths"])
            or not isinstance(arrival, dict)
            or arrival.get("root_seed") != root
            or arrival.get("workload") != run.get("workload")
            or arrival.get("warmup_time") != 200
            or arrival.get("scored_horizon") != 2000
            or arrival.get("release_interval_per_agent") != 110
            or arrival.get("guard_suffix_tasks_per_agent") != 4
            or arrival.get("guard_suffix_release_timestep") != 2199
            or arrival.get("schedule") != "deterministic_agent_stagger/v1"
        ):
            fail(f"run start/tape/workload/guard contract failed: {path}")
        budget = run.get("budget")
        if not isinstance(budget, dict):
            fail(f"run budget record is missing: {path}")
        publications = run.get("post_bootstrap_publication_count")
        generations = run.get("post_bootstrap_generation_count")
        reactivations = run.get("post_bootstrap_reactivation_count")
        calls = run.get("generator_calls")
        if (
            run.get("mandatory_bootstrap_calls") != 1
            or not all(nonnegative_integer(value) for value in (publications, generations, reactivations, calls))
            or generations + reactivations != publications
            or calls != 1 + generations
            or budget.get("budget_violation_attempts") != 0
            or budget.get("cap_satisfied") is not True
            or budget.get("generation_cap_satisfied") is not True
            or budget.get("total_generator_call_cap_satisfied") is not True
            or budget.get("generator_call_conservation_satisfied") is not True
        ):
            fail(f"run generator/budget conservation failed: {path}")
        method = run["method"]
        exact_quota = {
            "bootstrap_only": 0,
            "exact_even_G4": 4,
            "exact_even_G5": 5,
            "random_G5": 5,
            "exact_even_B25": 25,
        }
        if method in exact_quota:
            quota = exact_quota[method]
            if publications != quota or generations != quota or reactivations != 0:
                fail(f"exact method quota failed for {method}: {path}")
            if method in {"exact_even_G4", "exact_even_G5", "exact_even_B25"}:
                if run.get("precommitted_post_bootstrap_schedule") != exact_schedule(quota):
                    fail(f"exact schedule drift for {method}: {path}")
        elif method == "js_cap_G5" and (publications > 5 or publications != generations or reactivations != 0):
            fail(f"js_cap_G5 cap failed: {path}")
        elif method == "context_no_reactivation_B25" and (
            publications > 25 or publications != generations or reactivations != 0
        ):
            fail(f"no-reactivation B25 cap failed: {path}")
        elif method == "context_memory_B25" and (publications > 25 or generations > 25):
            fail(f"CARR B25 cap failed: {path}")
        timeline = run.get("publication_timeline")
        windows = run.get("windows")
        if (
            not isinstance(timeline, list)
            or len(timeline) != 100
            or [row.get("decision_index") for row in timeline] != list(range(100))
            or not isinstance(windows, list)
            or len(windows) != 100
            or [row.get("decision_index") for row in windows] != list(range(100))
        ):
            fail(f"complete 100-window evidence is absent: {path}")
        if method == "random_G5":
            schedule = tuple(run.get("precommitted_post_bootstrap_schedule") or ())
            if len(schedule) != 5 or len(set(schedule)) != 5 or any(not 1 <= item <= 99 for item in schedule):
                fail(f"random_G5 precommitted schedule is invalid: {path}")
            random_schedules.setdefault(root, set()).add(schedule)

        process_instance = (host, pid, start_ns)
        all_process_instances.append(process_instance)
        all_run_uuids.append(run_uuid)
        arm_key = (scenario_id, method, root, run["workload"])
        all_arm_keys.append(arm_key)
        all_runs.append(run)
        cell_groups.setdefault((scenario_id, root, run["workload"]), []).append(run)

    ledger_paths.append(verify_ledger(path, artifact, runs, agents))
    print(
        f"audited Experiment B {path.name} runs={len(runs)} "
        f"ledger_events=1920 environment_sha256={environment_sha}"
    )

if len(all_runs) != 3840:
    fail(f"expected exactly 3840 B runs, found {len(all_runs)}")
expected_arm_keys = set(
    itertools.product(expected_scenarios, expected_methods, expected_roots, expected_workloads)
)
if len(all_arm_keys) != 3840 or set(all_arm_keys) != expected_arm_keys:
    missing = sorted(expected_arm_keys - set(all_arm_keys), key=repr)[:5]
    extra = sorted(set(all_arm_keys) - expected_arm_keys, key=repr)[:5]
    fail(f"B matrix arm coverage failed: missing={missing} extra={extra}")
if len(set(all_process_instances)) != 3840:
    fail("one unique (host,PID,process_start_ns) instance per arm failed")
if len(set(all_run_uuids)) != 3840:
    fail("one canonical run UUID per arm failed")
if len(set(ledger_paths)) != 4:
    fail("each scenario must bind a distinct attempt ledger")
if set(random_schedules) != set(expected_roots) or any(
    len(schedules) != 1 for schedules in random_schedules.values()
):
    fail("random_G5 schedule is not root-keyed and identical across all 12 root cells")

paired_fields = (
    "manifest_id",
    "reset_causal_fingerprint",
    "release_projection_fingerprint",
    "distribution_update_fingerprint",
    "task_tape_identity",
    "workload_arrival",
)
if len(cell_groups) != 480:
    fail(f"expected 480 paired scenario/root/workload cells, found {len(cell_groups)}")
for key, arms in cell_groups.items():
    if len(arms) != 8 or {run["method"] for run in arms} != set(expected_methods):
        fail(f"paired cell lacks the full eight-arm family: {key}")
    for field in paired_fields:
        if len({canonical_sha256(run.get(field)) for run in arms}) != 1:
            fail(f"paired cell differs on {field}: {key}")

if audit_path.exists():
    fail(f"refusing to overwrite B integrity report: {audit_path}")
report = {
    "schema": "dai.same-call-confirmation-matrix-integrity/b",
    "status": "complete",
    "passed": True,
    "claim_scope": "effect-blind execution and integrity audit only",
    "effect_inference_performed": False,
    "method_rankings_inspected": False,
    "config_path": str(config_path),
    "config_sha256": config_sha,
    "execution_host": target_host,
    "root_count": 40,
    "scenario_count": 4,
    "runs_per_scenario": 960,
    "total_runs": 3840,
    "paired_cells": 480,
    "attempt_ledger_events_per_scenario": 1920,
    "attempt_started_per_scenario": 960,
    "attempt_completed_per_scenario": 960,
    "unique_process_instances": 3840,
    "unique_run_uuids": 3840,
    "environment_sha256": reference_environment_sha,
    "artifact_sha256": artifact_digests,
    "checks": {
        "complete_arm_cartesian_product": True,
        "no_missing_duplicate_retry_or_deleted_arm": True,
        "ledger_identity_and_run_hash_binding": True,
        "fresh_process_instance_and_uuid": True,
        "cross_method_pairing": True,
        "safety_rng_tape_and_future_access_invariants": True,
        "budget_schedule_and_generator_conservation": True,
        "checkpoint_source_map_and_config_binding": True,
        "runtime_environment_identical_across_scenarios": True,
        "formal_outputs_not_overwritten": True,
    },
    "next_step": "execute the separately frozen B analyzer exactly once",
}
audit_path.parent.mkdir(parents=True, exist_ok=True)
temporary = audit_path.with_name(f".{audit_path.name}.tmp")
temporary.write_bytes(json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
try:
    os.link(temporary, audit_path)
except FileExistsError:
    temporary.unlink(missing_ok=True)
    fail(f"refusing to overwrite B integrity report: {audit_path}")
temporary.unlink()
print(
    "SAME_CALL_CONFIRMATION_B_MATRIX_INTEGRITY_PASS "
    f"runs=3840 paired_cells=480 host={target_host} "
    f"environment_sha256={reference_environment_sha} report={audit_path}"
)
PY

echo "Experiment B matrix and effect-blind integrity audit passed."
echo "No treatment effect, rank, confidence interval, or p-value was computed."
echo "Run the separately frozen analyzer exactly once as the next step."
