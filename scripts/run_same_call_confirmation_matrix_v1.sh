#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_v1.py"
CONFIG="${SAME_CALL_CONFIG:-$WORKSPACE/configs/same_call_confirmation_v1.json}"
OUTDIR="$WORKSPACE/results/same_call_confirmation_v1"
LOGDIR="$WORKSPACE/logs/same_call_confirmation_v1"

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

# Verify the complete implementation/preflight manifest before opening any
# fresh root. Non-file identities (for example checkpoint parameter payloads)
# are rechecked by the runner and final analyzer against emitted metadata.
"$DAI_PYTHON" - "$WORKSPACE" "$CONFIG" <<'PY'
import hashlib
import json
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1]).resolve()
config_path = pathlib.Path(sys.argv[2]).resolve()
config = json.loads(config_path.read_text(encoding="utf-8"))
for name in config["required_frozen_artifacts"]:
    record = config["frozen_artifacts"][name]
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
for name in config["required_preflight_evidence"]:
    record = config["preflight_evidence"][name]
    path = pathlib.Path(record["path"])
    if not path.is_absolute():
        path = workspace / path
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if record.get("passed") is not True or actual != record["sha256"]:
        raise SystemExit(f"preflight evidence failed or drifted: {name}")
print("SAME_CALL_FREEZE_MANIFEST_VERIFIED")
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
    echo "Refusing to overwrite protected same-call artifact: $label" >&2
    exit 3
  fi
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_name" \
    --agents "$agents" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$label")
  echo "started same-call label=$label pid=$!"
}

launch narrow_r020 warehouse_small_narrow_kiva.map 218
launch narrow_r035 warehouse_small_narrow_kiva.map 382
launch regular_r020 warehouse_small_kiva.map 255
launch regular_r035 warehouse_small_kiva.map 447

failed=0
for index in "${!PIDS[@]}"; do
  if wait "${PIDS[$index]}"; then
    echo "completed same-call label=${LABELS[$index]}"
  else
    echo "failed same-call label=${LABELS[$index]} log=$LOGDIR/${LABELS[$index]}.log" >&2
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  exit 4
fi

"$DAI_PYTHON" - "$OUTDIR" "$CONFIG_SHA" <<'PY'
import glob
import json
import os
import sys

outdir, config_sha = sys.argv[1:]
paths = sorted(glob.glob(os.path.join(outdir, "*.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four confirmation artifacts, found {len(paths)}")
all_pids = []
for path in paths:
    with open(path, encoding="utf-8") as stream:
        artifact = json.load(stream)
    runs = artifact["runs"]
    if artifact["status"] != "complete" or len(runs) != 240:
        raise SystemExit(f"incomplete confirmation artifact {path}")
    if artifact.get("development_matrix_config_sha256") != config_sha:
        raise SystemExit(f"config digest mismatch in {path}")
    if artifact.get("fresh_process_per_arm") is not True:
        raise SystemExit(f"fresh-process flag missing in {path}")
    ledger = artifact.get("attempt_ledger")
    if not isinstance(ledger, dict) or ledger.get("started_events") != 240 or ledger.get("completed_events") != 240:
        raise SystemExit(f"attempt ledger attestation missing in {path}")
    pids = [run.get("execution_process_id") for run in runs]
    if None in pids or len(set(pids)) != len(pids):
        raise SystemExit(f"one-process-per-arm audit failed in {path}")
    all_pids.extend(pids)
    if any(not run["safety"]["passed"] for run in runs):
        raise SystemExit(f"safety failure in {path}")
    if any(not run["invariants"]["passed"] for run in runs):
        raise SystemExit(f"invariant failure in {path}")
    print(f"audited confirmation {os.path.basename(path)} runs={len(runs)}")
if len(set(all_pids)) != len(all_pids):
    raise SystemExit("execution process id was reused across scenario artifacts")
print("SAME_CALL_CONFIRMATION_MATRIX_COMPLETE")
PY
