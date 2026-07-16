#!/usr/bin/env bash
set -euo pipefail

# A1 remains the frozen same_call_confirmation_v1 scientific split.  This
# launcher only strengthens pre-root host/environment binding and uses
# versioned append-only output paths.
WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_v1.py"
CONFIG="${SAME_CALL_CONFIG:-$WORKSPACE/configs/same_call_confirmation_a1.json}"
OUTDIR="$WORKSPACE/results/same_call_confirmation_a1"
LOGDIR="$WORKSPACE/logs/same_call_confirmation_a1"

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

CONFIG_SHA="$($DAI_PYTHON - "$CONFIG" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"

TARGET_HOST="$($DAI_PYTHON - "$CONFIG" <<'PY'
import json
import pathlib
import sys

config = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
target = config.get("target_environment")
if not isinstance(target, dict):
    raise SystemExit("A1 config target_environment must be an object")
host = target.get("execution_host")
if not isinstance(host, str) or not host:
    raise SystemExit("A1 config target_environment.execution_host is missing")
print(host)
PY
)"
CURRENT_HOST="$(hostname)"
if [[ "$CURRENT_HOST" != "$TARGET_HOST" ]]; then
  echo "A1 target-host mismatch before fresh roots: expected=$TARGET_HOST actual=$CURRENT_HOST" >&2
  exit 2
fi

# Verify the complete A1 implementation/preflight manifest, the sealed target
# environment attestation, and current hostname before opening any fresh root.
# Non-file identities are rechecked by the frozen runner and final analyzer.
"$DAI_PYTHON" - "$WORKSPACE" "$CONFIG" "$CURRENT_HOST" <<'PY'
import hashlib
import json
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1]).resolve()
config_path = pathlib.Path(sys.argv[2]).resolve()
current_host = sys.argv[3]
config = json.loads(config_path.read_text(encoding="utf-8"))

required_frozen = config.get("required_frozen_artifacts")
frozen = config.get("frozen_artifacts")
if not isinstance(required_frozen, list) or not isinstance(frozen, dict):
    raise SystemExit("A1 config frozen-artifact manifest is incomplete")
for name in required_frozen:
    record = frozen[name]
    if record.get("verification") != "file_sha256":
        continue
    path = pathlib.Path(record["path"])
    if not path.is_absolute():
        path = workspace / path
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != record["sha256"]:
        raise SystemExit(
            f"frozen artifact mismatch {name}: expected={record['sha256']} "
            f"actual={actual} path={path}"
        )

a1_protocol_records = [
    frozen[name]
    for name in required_frozen
    if pathlib.Path(str(frozen[name].get("path", ""))).name
    == "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A1.md"
]
if len(a1_protocol_records) != 1:
    raise SystemExit("A1 config must require exactly one A1 protocol artifact")
if a1_protocol_records[0].get("sha256") != (
    "10f17682a9dc32f33fad2c77289e8c9dff659325de655b584f1d138066f05fdf"
):
    raise SystemExit("A1 protocol digest is not the frozen amendment digest")

required_preflight = config.get("required_preflight_evidence")
preflight = config.get("preflight_evidence")
if not isinstance(required_preflight, list) or not isinstance(preflight, dict):
    raise SystemExit("A1 config preflight-evidence manifest is incomplete")
for name in required_preflight:
    record = preflight[name]
    path = pathlib.Path(record["path"])
    if not path.is_absolute():
        path = workspace / path
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if record.get("passed") is not True or actual != record["sha256"]:
        raise SystemExit(f"preflight evidence failed or drifted: {name}")

target = config.get("target_environment")
if not isinstance(target, dict):
    raise SystemExit("A1 config target_environment must be an object")
for key in ("path", "sha256", "execution_host"):
    if not isinstance(target.get(key), str) or not target[key]:
        raise SystemExit(f"A1 target_environment.{key} is missing")
attestation_path = pathlib.Path(target["path"])
if not attestation_path.is_absolute():
    attestation_path = workspace / attestation_path
attestation_actual = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
if attestation_actual != target["sha256"]:
    raise SystemExit(
        "target-environment attestation mismatch: "
        f"expected={target['sha256']} actual={attestation_actual} "
        f"path={attestation_path}"
    )
if target["execution_host"] != current_host:
    raise SystemExit(
        "target execution host changed before fresh roots: "
        f"expected={target['execution_host']} actual={current_host}"
    )
print(
    "SAME_CALL_A1_FREEZE_AND_TARGET_ENVIRONMENT_VERIFIED "
    f"host={current_host} attestation_sha256={attestation_actual}"
)
PY

mkdir -p "$OUTDIR" "$LOGDIR"

SEEDS=(
  767369 695428 323681 904171 446020
  434435 488565 514527 544573 838809
)
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

# Perform a complete overwrite precheck before starting the first scenario so
# a stale later-scenario artifact cannot leave a new partial matrix running.
for label in narrow_r020 narrow_r035 regular_r020 regular_r035; do
  output="$OUTDIR/$label.json"
  log="$LOGDIR/$label.log"
  ledger="$OUTDIR/$label.attempts.jsonl"
  if [[ -e "$output" || -e "${output%.json}.csv" || -e "$log" || -e "$ledger" ]]; then
    echo "Refusing to overwrite protected A1 confirmation artifact: $label" >&2
    exit 3
  fi
done

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
  --jobs 6
)

PIDS=()
LABELS=()

launch() {
  local label="$1"
  local map_name="$2"
  local agents="$3"
  local output="$OUTDIR/$label.json"
  local log="$LOGDIR/$label.log"
  local ledger="$OUTDIR/$label.attempts.jsonl"
  if [[ -e "$output" || -e "${output%.json}.csv" || -e "$log" || -e "$ledger" ]]; then
    echo "Refusing to overwrite protected A1 confirmation artifact: $label" >&2
    exit 3
  fi
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_name" \
    --agents "$agents" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$label")
  echo "started A1 confirmation label=$label pid=$! host=$TARGET_HOST"
}

launch narrow_r020 warehouse_small_narrow_kiva.map 218
launch narrow_r035 warehouse_small_narrow_kiva.map 382
launch regular_r020 warehouse_small_kiva.map 255
launch regular_r035 warehouse_small_kiva.map 447

failed=0
for index in "${!PIDS[@]}"; do
  if wait "${PIDS[$index]}"; then
    echo "completed A1 confirmation label=${LABELS[$index]}"
  else
    echo "failed A1 confirmation label=${LABELS[$index]} log=$LOGDIR/${LABELS[$index]}.log" >&2
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  exit 4
fi

"$DAI_PYTHON" - "$OUTDIR" "$CONFIG_SHA" "$TARGET_HOST" <<'PY'
import glob
import hashlib
import json
import os
import sys

outdir, config_sha, target_host = sys.argv[1:]
paths = sorted(glob.glob(os.path.join(outdir, "*.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four A1 confirmation artifacts, found {len(paths)}")

expected_thread_environment = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
reference_environment = None
reference_environment_sha = None
all_pids = []
total_runs = 0
for path in paths:
    with open(path, encoding="utf-8") as stream:
        artifact = json.load(stream)
    runs = artifact["runs"]
    total_runs += len(runs)
    if artifact.get("status") != "complete" or len(runs) != 240:
        raise SystemExit(f"incomplete A1 confirmation artifact {path}")
    if artifact.get("split") != "same_call_confirmation_v1":
        raise SystemExit(f"frozen scientific split changed in {path}")
    if artifact.get("development_matrix_config_sha256") != config_sha:
        raise SystemExit(f"config digest mismatch in {path}")
    if artifact.get("fresh_process_per_arm") is not True:
        raise SystemExit(f"fresh-process flag missing in {path}")
    ledger = artifact.get("attempt_ledger")
    if (
        not isinstance(ledger, dict)
        or ledger.get("started_events") != 240
        or ledger.get("completed_events") != 240
    ):
        raise SystemExit(f"attempt ledger attestation missing in {path}")

    runtime = artifact.get("runtime_manifest")
    if not isinstance(runtime, dict):
        raise SystemExit(f"runtime manifest missing in {path}")
    environment = runtime.get("environment")
    if not isinstance(environment, dict):
        raise SystemExit(f"runtime environment missing in {path}")
    if environment.get("host") != target_host:
        raise SystemExit(
            f"artifact runtime host mismatch in {path}: "
            f"expected={target_host} actual={environment.get('host')}"
        )
    if environment.get("thread_environment") != expected_thread_environment:
        raise SystemExit(f"thread environment drift in {path}")
    if environment.get("torch_num_threads") != 1:
        raise SystemExit(f"torch_num_threads drift in {path}")
    if environment.get("torch_num_interop_threads") != 1:
        raise SystemExit(f"torch_num_interop_threads drift in {path}")
    environment_sha = hashlib.sha256(
        json.dumps(
            environment, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()
    if reference_environment is None:
        reference_environment = environment
        reference_environment_sha = environment_sha
    elif environment != reference_environment:
        raise SystemExit(
            "full runtime environment differs across A1 scenarios: "
            f"reference_sha256={reference_environment_sha} "
            f"actual_sha256={environment_sha} path={path}"
        )

    pids = [run.get("execution_process_id") for run in runs]
    if None in pids or len(set(pids)) != len(pids):
        raise SystemExit(f"one-process-per-arm audit failed in {path}")
    all_pids.extend(pids)
    run_hosts = {run.get("execution_host") for run in runs}
    if run_hosts != {target_host}:
        raise SystemExit(
            f"run host mismatch in {path}: expected={target_host} "
            f"actual={sorted(str(host) for host in run_hosts)}"
        )
    if any(run.get("split") != "same_call_confirmation_v1" for run in runs):
        raise SystemExit(f"run scientific split changed in {path}")
    if any(not run["safety"]["passed"] for run in runs):
        raise SystemExit(f"safety failure in {path}")
    if any(not run["invariants"]["passed"] for run in runs):
        raise SystemExit(f"invariant failure in {path}")
    print(
        f"audited A1 confirmation {os.path.basename(path)} runs={len(runs)} "
        f"host={target_host} environment_sha256={environment_sha}"
    )

if total_runs != 960:
    raise SystemExit(f"expected exactly 960 A1 runs, found {total_runs}")
if len(set(all_pids)) != len(all_pids):
    raise SystemExit("execution process id was reused across scenario artifacts")
print(
    "SAME_CALL_CONFIRMATION_A1_MATRIX_COMPLETE "
    f"runs={total_runs} host={target_host} "
    f"environment_sha256={reference_environment_sha}"
)
PY
