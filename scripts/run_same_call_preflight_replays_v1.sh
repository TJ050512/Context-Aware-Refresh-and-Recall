#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAP="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps/warehouse_small_narrow_kiva.map"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_v1.py"
IMPLEMENTATION_FREEZE="$WORKSPACE/configs/same_call_implementation_freeze_v1.json"
OUTDIR="$WORKSPACE/results/same_call_preflight_v1"
LOGDIR="$WORKSPACE/logs/same_call_preflight_v1"

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
check_sha 9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41 "$WORKSPACE/EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md"
check_sha b4df56441942d8c3fcea8c67207026934a2de4bcc2921b2d307787dcd2520c26 "$IMPLEMENTATION_FREEZE"

mkdir -p "$OUTDIR" "$LOGDIR"

COMMON=(
  --workspace "$WORKSPACE"
  --checkpoint "$CKPT"
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac
  --split development
  --seeds 17
  --workloads stationary
  --methods context_memory_B25 exact_even_B25
  --map-path "$MAP"
  --agents 218
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
  --jobs 2
)

run_artifact() {
  local label="$1"
  shift
  local output="$OUTDIR/$label.json"
  local log="$LOGDIR/$label.log"
  local ledger="$OUTDIR/$label.attempts.jsonl"
  if [[ -e "$output" || -e "${output%.json}.csv" || -e "$log" || -e "$ledger" ]]; then
    echo "Refusing to overwrite preflight replay: $label" >&2
    exit 3
  fi
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" "$@" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1
  echo "completed preflight replay label=$label"
}

run_artifact repeat_a
run_artifact repeat_b
run_artifact future_suffix_base --future-suffix-cutoff 1400
run_artifact future_suffix_variant --future-suffix-cutoff 1400 --future-suffix-variant 1

"$DAI_PYTHON" - "$OUTDIR" <<'PY'
import json
import pathlib
import sys

outdir = pathlib.Path(sys.argv[1])
for label in ("repeat_a", "repeat_b", "future_suffix_base", "future_suffix_variant"):
    path = outdir / f"{label}.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("status") != "complete" or len(artifact.get("runs", ())) != 2:
        raise SystemExit(f"incomplete replay artifact {path}")
    if artifact.get("fresh_process_per_arm") is not True:
        raise SystemExit(f"fresh process attestation missing in {path}")
    pids = [run.get("execution_process_id") for run in artifact["runs"]]
    if None in pids or len(set(pids)) != 2:
        raise SystemExit(f"fresh process ids invalid in {path}")
print("SAME_CALL_PREFLIGHT_REPLAYS_COMPLETE")
PY
