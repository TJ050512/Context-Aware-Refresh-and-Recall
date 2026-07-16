#!/usr/bin/env bash
set -euo pipefail

# Engineering-only smoke. Root 17 is contaminated development data and no
# effect estimate may be computed from these outputs.
WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_v1.py"
IMPLEMENTATION_FREEZE="$WORKSPACE/configs/same_call_implementation_freeze_v1.json"
OUTDIR="$WORKSPACE/results/same_call_engineering_smoke_v1"
LOGDIR="$WORKSPACE/logs/same_call_engineering_smoke_v1"

# AutoDL may preset these to the host core count. Override rather than using
# shell-default expansion so 24 spawned arms cannot each create 24 BLAS teams.
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

check_sha() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA mismatch: $path expected=$expected actual=$actual" >&2
    exit 2
  fi
}

check_sha 53fe48d7fda7638dbd79423d01f4f07de5e13a04938d9a1516855347413ef495 "$WORKSPACE/src/dai_lmapf/same_call_claim_runner.py"
check_sha 9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538 "$RUNNER"
check_sha d860af7cc664ff30eaed6bad099313c27f74e99e933f95503d668d57b0ec6d88 "$WORKSPACE/src/dai_lmapf/publication_policy.py"
check_sha 023126dd8ce34e8a65ae011f8a7dbb0cca754220b62920db812237de0285b7f2 "$WORKSPACE/src/dai_lmapf/frozen_cnn_generator.py"
check_sha 013cae2734aa67782ae560e55eeb9b51c9be7343ab27e6ef2e3836ffcc1e913b "$WORKSPACE/src/dai_lmapf/online_ggo_adapter.py"
check_sha 9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41 "$WORKSPACE/EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md"
check_sha b4df56441942d8c3fcea8c67207026934a2de4bcc2921b2d307787dcd2520c26 "$IMPLEMENTATION_FREEZE"
check_sha e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d "$CKPT"
check_sha 9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5 "$WORKSPACE/external/OnlineGGO/CMAES/simulators/trafficMAPF_on/period_on_sim.cpython-39-x86_64-linux-gnu.so"
check_sha 866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6 "$MAPDIR/warehouse_small_narrow_kiva.map"
check_sha 0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd "$MAPDIR/warehouse_small_kiva.map"

mkdir -p "$OUTDIR" "$LOGDIR"

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
  --split development
  --seeds 17
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
    echo "Refusing to overwrite smoke artifact: $label" >&2
    exit 3
  fi
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_name" \
    --agents "$agents" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$label")
  echo "started smoke label=$label pid=$!"
}

launch narrow_r020 warehouse_small_narrow_kiva.map 218
launch narrow_r035 warehouse_small_narrow_kiva.map 382
launch regular_r020 warehouse_small_kiva.map 255
launch regular_r035 warehouse_small_kiva.map 447

failed=0
for index in "${!PIDS[@]}"; do
  if wait "${PIDS[$index]}"; then
    echo "completed smoke label=${LABELS[$index]}"
  else
    echo "failed smoke label=${LABELS[$index]} log=$LOGDIR/${LABELS[$index]}.log" >&2
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  exit 4
fi

"$DAI_PYTHON" - "$OUTDIR" <<'PY'
import glob
import json
import os
import sys

outdir = sys.argv[1]
paths = sorted(glob.glob(os.path.join(outdir, "*.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four smoke artifacts, found {len(paths)}")
for path in paths:
    with open(path, encoding="utf-8") as stream:
        artifact = json.load(stream)
    runs = artifact["runs"]
    if artifact["status"] != "complete" or len(runs) != 24:
        raise SystemExit(f"incomplete smoke artifact {path}")
    if artifact.get("fresh_process_per_arm") is not True:
        raise SystemExit(f"fresh-process flag missing in {path}")
    ledger = artifact.get("attempt_ledger")
    if not isinstance(ledger, dict) or ledger.get("started_events") != 24 or ledger.get("completed_events") != 24:
        raise SystemExit(f"attempt ledger attestation missing in {path}")
    pids = [run.get("execution_process_id") for run in runs]
    if None in pids or len(set(pids)) != len(pids):
        raise SystemExit(f"one-process-per-arm audit failed in {path}")
    if any(not run["safety"]["passed"] for run in runs):
        raise SystemExit(f"safety failure in {path}")
    if any(not run["invariants"]["passed"] for run in runs):
        raise SystemExit(f"invariant failure in {path}")
    print(f"audited smoke {os.path.basename(path)} runs={len(runs)}")
print("SAME_CALL_ENGINEERING_SMOKE_COMPLETE")
PY
