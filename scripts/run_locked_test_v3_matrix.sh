#!/usr/bin/env bash
set -euo pipefail

# Prepared-only one-shot locked-test launcher.  Do not execute until the frozen
# validation analysis has passed at least one candidate path and the user has
# explicitly confirmed after seeing that decision.

if [[ "$#" -ne 1 || "$1" != "--confirm-locked-test-v3" ]]; then
  echo "Refusing locked test: pass the explicit --confirm-locked-test-v3 flag." >&2
  exit 10
fi

required_environment=(WORKSPACE DAI_PYTHON CKPT10 VALIDATION_GATE_JSON DAI_LOCKED_TEST_CONFIRM)
for variable in "${required_environment[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Refusing locked test: required environment variable $variable is unset." >&2
    exit 11
  fi
done

if [[ "$DAI_LOCKED_TEST_CONFIRM" != "I_CONFIRM_ONE_SHOT_LOCKED_TEST_V3" ]]; then
  echo "Refusing locked test: DAI_LOCKED_TEST_CONFIRM has the wrong acknowledgement." >&2
  exit 12
fi
if [[ ! -x "$DAI_PYTHON" ]]; then
  echo "Refusing locked test: DAI_PYTHON is not executable: $DAI_PYTHON" >&2
  exit 13
fi
if [[ ! -f "$VALIDATION_GATE_JSON" ]]; then
  echo "Refusing locked test: validation decision JSON not found: $VALIDATION_GATE_JSON" >&2
  exit 14
fi
for command in sha256sum pgrep flock; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Refusing locked test: required command is unavailable: $command" >&2
    exit 14
  fi
done

# A one-shot confirmatory matrix must not share CPU state with another runner.
# This check is performed before creating any result or log path.
active_evaluation="$(pgrep -af '[r]un_claim_aware_budgeted_validation[.]py|[r]un_validation_v2_matrix[.]sh|[r]un_context_exclusive_timing_v1[.]sh' || true)"
if [[ -n "$active_evaluation" ]]; then
  echo "Refusing locked test while another evaluation is active:" >&2
  echo "$active_evaluation" >&2
  exit 14
fi

exec 9>"$WORKSPACE/.locked_test_v3.lock"
if ! flock -n 9; then
  echo "Refusing locked test: another v3 launcher holds the workspace lock." >&2
  exit 14
fi

MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
OUTDIR="$WORKSPACE/results/official_locked_test_v3"
LOGDIR="$WORKSPACE/logs/official_locked_test_v3"
RUNNER="$WORKSPACE/scripts/run_claim_aware_budgeted_validation.py"
AUDITOR="$WORKSPACE/scripts/audit_locked_test_v3.py"
PROTOCOL="$WORKSPACE/configs/locked_test_protocol_v3.json"
REPORT="$WORKSPACE/reports/LOCKED_TEST_PROTOCOL_AMENDMENT_V3.md"
SIM_SO="$WORKSPACE/external/OnlineGGO/CMAES/simulators/trafficMAPF_on/period_on_sim.cpython-39-x86_64-linux-gnu.so"

check_sha() {
  local expected="$1"
  local path="$2"
  local actual
  if [[ ! -f "$path" ]]; then
    echo "Missing frozen input: $path" >&2
    exit 15
  fi
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA mismatch: $path expected=$expected actual=$actual" >&2
    exit 16
  fi
}

check_sha f22f75bade792e5723367af91d15c9301206b42b7a28f58600375ccbb691bd7c "$WORKSPACE/src/dai_lmapf/claim_runner.py"
check_sha 93a0c9f7e97e64b1b89264b207e8a7a3505522a58f2a9cbaeb5f30bfb921e57f "$RUNNER"
check_sha 95ccff7fe33cedd3468222b14baad9c4b2671c681a0e67b6fb4b9532c89053b7 "$PROTOCOL"
check_sha 3093155eb37d2c7e42caec3a2ad0f2c2301297befc668b917c98dfd7556939ce "$REPORT"
check_sha 7d95ff55f2db4a00c96c3d7682087c0127c730a10c0294759acd74fb0e24e0d0 "$AUDITOR"
check_sha e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d "$CKPT10"
check_sha 9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5 "$SIM_SO"
check_sha 29bde647469ea50e0ec6f605396f0893a24b0a43696014734b095bda89ce60f1 "$MAPDIR/warehouse_60x100_kiva.map"
check_sha 7a2ec55f0afc2e5969f15cdb19fefea47d2dbab2aafb51632d54e5e7f9c4e2e1 "$MAPDIR/sortation_small_kiva.map"

# This reads decision booleans and structural counts only; it does not rank or
# reinterpret validation outcomes.  A no-go result hard-blocks the launch.
"$DAI_PYTHON" "$AUDITOR" \
  --protocol "$PROTOCOL" \
  --map-dir "$MAPDIR" \
  --validation-gate "$VALIDATION_GATE_JSON" \
  --require-validation-candidate \
  --preflight-only

labels=(warehouse_r020 warehouse_r035 sortation_r020 sortation_r035)
for label in "${labels[@]}"; do
  for suffix in json csv; do
    path="$OUTDIR/$label.$suffix"
    if [[ -e "$path" ]]; then
      echo "Refusing to overwrite protected locked-test artifact: $path" >&2
      exit 17
    fi
  done
  if [[ -e "$LOGDIR/$label.log" ]]; then
    echo "Refusing to replace an existing locked-test log: $LOGDIR/$label.log" >&2
    exit 18
  fi
done

mkdir -p "$OUTDIR" "$LOGDIR"

SEEDS=(
  1001 1002 1003 1004 1005 1006 1007 1008 1009 1010
  1011 1012 1013 1014 1015 1016 1017 1018 1019 1020
  1021 1022 1023 1024 1025 1026 1027 1028 1029 1030
)
COMMON=(
  --workspace "$WORKSPACE"
  --checkpoint "$CKPT10"
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac
  --split locked_test
  --confirm-locked-test
  --seeds "${SEEDS[@]}"
  --workloads stationary abrupt recurrent
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
  --jobs 3
)

PIDS=()
LABELS=()

launch() {
  local label="$1"
  local map_name="$2"
  local agents="$3"
  local output="$OUTDIR/$label.json"
  local log="$LOGDIR/$label.log"
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_name" \
    --agents "$agents" \
    --output "$output" >"$log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$label")
  echo "started locked label=$label pid=$!"
}

launch warehouse_r020 warehouse_60x100_kiva.map 737
launch warehouse_r035 warehouse_60x100_kiva.map 1290
launch sortation_r020 sortation_small_kiva.map 313
launch sortation_r035 sortation_small_kiva.map 547

failed=0
for index in "${!PIDS[@]}"; do
  if wait "${PIDS[$index]}"; then
    echo "completed locked label=${LABELS[$index]}"
  else
    echo "failed locked label=${LABELS[$index]} log=$LOGDIR/${LABELS[$index]}.log" >&2
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  echo "LOCKED_TEST_V3_INCOMPLETE: preserve all outputs and logs; do not delete or overwrite." >&2
  exit 19
fi

"$DAI_PYTHON" "$AUDITOR" \
  --protocol "$PROTOCOL" \
  --map-dir "$MAPDIR" \
  --artifact-dir "$OUTDIR"

echo "LOCKED_TEST_V3_MATRIX_COMPLETE"
