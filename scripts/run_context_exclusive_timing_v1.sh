#!/usr/bin/env bash
set -euo pipefail

# Frozen generator-only timing protocol.  The four scenarios are intentionally
# run one after another; every runner invocation is jobs=1 and declares
# exclusive timing.  Do not use these artifacts for throughput inference.

WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
SIM_SO="$WORKSPACE/external/OnlineGGO/CMAES/simulators/trafficMAPF_on/period_on_sim.cpython-39-x86_64-linux-gnu.so"
RUNNER="$WORKSPACE/scripts/run_claim_aware_budgeted_validation.py"
ANALYZER="$WORKSPACE/scripts/analyze_exclusive_timing.py"
CONFIG="$WORKSPACE/configs/context_exclusive_timing_protocol_v1.json"
OUTDIR="$WORKSPACE/results/official_exclusive_timing_v1"
LOGDIR="$WORKSPACE/logs/official_exclusive_timing_v1"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command is unavailable: $1" >&2
    exit 2
  fi
}

check_sha() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA mismatch: $path expected=$expected actual=$actual" >&2
    exit 3
  fi
}

assert_exclusive_idle() {
  local active_runner
  local active_validation
  local gpu_pids
  active_runner="$(pgrep -af '[r]un_claim_aware_budgeted_validation[.]py' || true)"
  if [[ -n "$active_runner" ]]; then
    echo "Refusing timing launch while a claim runner is active:" >&2
    echo "$active_runner" >&2
    exit 4
  fi
  active_validation="$(pgrep -af '[r]un_validation_v2_matrix[.]sh' || true)"
  if [[ -n "$active_validation" ]]; then
    echo "Refusing timing launch while the formal validation master is active:" >&2
    echo "$active_validation" >&2
    exit 4
  fi
  gpu_pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits 2>/dev/null | awk 'NF {print $1}')"
  if [[ -n "$gpu_pids" ]]; then
    echo "Refusing timing launch while GPU compute processes are active: $gpu_pids" >&2
    exit 4
  fi
}

require_command sha256sum
require_command pgrep
require_command nvidia-smi
require_command flock
if [[ ! -x "$DAI_PYTHON" ]]; then
  echo "DAI Python is not executable: $DAI_PYTHON" >&2
  exit 2
fi

check_sha f22f75bade792e5723367af91d15c9301206b42b7a28f58600375ccbb691bd7c "$WORKSPACE/src/dai_lmapf/claim_runner.py"
check_sha 93a0c9f7e97e64b1b89264b207e8a7a3505522a58f2a9cbaeb5f30bfb921e57f "$RUNNER"
check_sha aff4a620806faa0a34883dbe783b26aa4df7a0f5513b1cdfc14a535febf5a543 "$CONFIG"
check_sha 3f1a2b0bdd06c8deda390e1a690e3e4d46ab61833665e4f515828545a9ccef69 "$ANALYZER"
check_sha 98e8a99a8ad112b1b7024b28b21d141f3e471610a38b89d68f9248065fde475f "$WORKSPACE/configs/claim_validation_protocol_v2.json"
check_sha f91ab86df85d2343376bad1ad9beac377275bcb3976d8077eaa83103de1f43d9 "$WORKSPACE/configs/validation_v2_treatment_freeze_manifest.json"
check_sha e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d "$CKPT"
check_sha 9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5 "$SIM_SO"
check_sha 866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6 "$MAPDIR/warehouse_small_narrow_kiva.map"
check_sha 0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd "$MAPDIR/warehouse_small_kiva.map"

EXPECTED_OUTPUTS=(
  "$OUTDIR/narrow_r020_timing.json"
  "$OUTDIR/narrow_r020_timing.csv"
  "$OUTDIR/narrow_r035_timing.json"
  "$OUTDIR/narrow_r035_timing.csv"
  "$OUTDIR/regular_r020_timing.json"
  "$OUTDIR/regular_r020_timing.csv"
  "$OUTDIR/regular_r035_timing.json"
  "$OUTDIR/regular_r035_timing.csv"
  "$OUTDIR/context_exclusive_timing_v1_analysis.json"
  "$OUTDIR/context_exclusive_timing_v1_analysis.md"
  "$LOGDIR/narrow_r020.log"
  "$LOGDIR/narrow_r035.log"
  "$LOGDIR/regular_r020.log"
  "$LOGDIR/regular_r035.log"
)
for path in "${EXPECTED_OUTPUTS[@]}"; do
  if [[ -e "$path" ]]; then
    echo "Refusing to overwrite frozen timing output: $path" >&2
    exit 5
  fi
done

exec 9>"$WORKSPACE/.context_exclusive_timing_v1.lock"
if ! flock -n 9; then
  echo "Another context timing launcher holds the workspace lock" >&2
  exit 6
fi
assert_exclusive_idle
mkdir -p "$OUTDIR" "$LOGDIR"

SEEDS=(17 18 19 20 21)
COMMON=(
  --workspace "$WORKSPACE"
  --checkpoint "$CKPT"
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac
  --split development
  --seeds "${SEEDS[@]}"
  --workloads stationary abrupt recurrent
  --methods exact_even_B25 context_memory_B25
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
  --jobs 1
  --exclusive-timing
)

ARTIFACTS=()
run_scenario() {
  local label="$1"
  local map_file="$2"
  local agents="$3"
  local output="$OUTDIR/${label}_timing.json"
  local log="$LOGDIR/${label}.log"
  assert_exclusive_idle
  echo "EXCLUSIVE_TIMING start label=$label"
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_file" \
    --agents "$agents" \
    --output "$output" >"$log" 2>&1
  "$DAI_PYTHON" - "$output" "$label" <<'PY'
import json
import sys

path, label = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    artifact = json.load(stream)
if artifact.get("status") != "complete" or len(artifact.get("runs", [])) != 30:
    raise SystemExit(f"incomplete exclusive timing artifact: {label}")
if artifact.get("methods") != ["exact_even_B25", "context_memory_B25"]:
    raise SystemExit(f"method mismatch: {label}")
if artifact.get("protocol", {}).get("timing_evidence_valid") is not True:
    raise SystemExit(f"invalid timing declaration: {label}")
if any(run.get("timing_evidence_valid") is not True for run in artifact["runs"]):
    raise SystemExit(f"invalid run-level timing evidence: {label}")
print(f"EXCLUSIVE_TIMING audited label={label} runs=30")
PY
  ARTIFACTS+=("$output")
}

# This explicit order is part of the frozen protocol.
run_scenario narrow_r020 warehouse_small_narrow_kiva.map 218
run_scenario narrow_r035 warehouse_small_narrow_kiva.map 382
run_scenario regular_r020 warehouse_small_kiva.map 255
run_scenario regular_r035 warehouse_small_kiva.map 447

"$DAI_PYTHON" "$ANALYZER" "${ARTIFACTS[@]}" \
  --config "$CONFIG" \
  --output-json "$OUTDIR/context_exclusive_timing_v1_analysis.json" \
  --output-md "$OUTDIR/context_exclusive_timing_v1_analysis.md"

echo "CONTEXT_EXCLUSIVE_TIMING_V1_COMPLETE total_runs=120"
