#!/usr/bin/env bash
# Safely resume one bounded OnlineGGO CMA-ES stage on a bare AutoDL instance.
#
# Usage:
#   bash scripts/run_dai_cma_stage.sh CONFIG LOGDIR [NUM_WORKERS]
#
# Run this script under nohup or tmux.  It snapshots the pre-stage reload state,
# uses only CPU workers (the official evaluator has no CUDA path), and extracts
# a hash-audited checkpoint after the requested max_evals is reached.

set -Eeuo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 CONFIG LOGDIR [NUM_WORKERS]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/autodl_env.sh"

CMA_DIR="$DAI_ONLINEGGO/CMAES"
CONFIG="$1"
LOGDIR="$2"
# The new instance has a 24-CPU cgroup quota.  Leave two CPUs for the Dask
# scheduler, CMA ask/tell process, and OS; 22 single-threaded workers avoids
# oversubscription and matches the audited launch plan.
NUM_WORKERS="${3:-22}"
EXPECTED_2K_CHECKPOINT_SHA256="356101296acf64fa29777ff550a5d65eb439fc979bb5c660d605a2779c10c01b"

if [[ "$CONFIG" != /* ]]; then
  CONFIG="$CMA_DIR/$CONFIG"
fi
if [[ "$LOGDIR" != /* ]]; then
  LOGDIR="$CMA_DIR/$LOGDIR"
fi
CONFIG="$(realpath "$CONFIG")"
LOGDIR="$(realpath "$LOGDIR")"

[[ -x "$DAI_PYTHON" ]] || { echo "Python not executable: $DAI_PYTHON" >&2; exit 1; }
[[ -f "$CONFIG" ]] || { echo "Config not found: $CONFIG" >&2; exit 1; }
[[ -f "$LOGDIR/reload.pkl" ]] || { echo "reload.pkl not found: $LOGDIR" >&2; exit 1; }
[[ "$NUM_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid worker count" >&2; exit 2; }

mkdir -p "$DAI_WORKSPACE/.stage_runs" "$DAI_WORKSPACE/.dask-worker-space"
exec 9>"$LOGDIR/.dai_cma_stage.lock"
if ! flock -n 9; then
  echo "Another CMA stage already holds $LOGDIR/.dai_cma_stage.lock" >&2
  exit 1
fi

read -r CURRENT_EVALS CURRENT_ITRS < <(
  "$DAI_PYTHON" - "$LOGDIR/reload.pkl" <<'PY'
import pickle
import sys
with open(sys.argv[1], "rb") as stream:
    state = pickle.load(stream)
print(int(state["total_evals"]), int(state["outer_itrs_completed"]))
PY
)

TARGET_EVALS="$({
  cd "$CMA_DIR"
  "$DAI_PYTHON" - "$CONFIG" <<'PY'
import sys
import gin
import env_search.main  # Registers all configurables before parsing includes.
gin.parse_config_file(sys.argv[1])
print(int(gin.query_parameter("Manager.max_evals")))
PY
} | tail -n 1)"

if (( TARGET_EVALS <= CURRENT_EVALS )); then
  echo "Target $TARGET_EVALS must exceed current $CURRENT_EVALS" >&2
  exit 1
fi

if (( CURRENT_EVALS == 2000 )); then
  echo "$EXPECTED_2K_CHECKPOINT_SHA256  $LOGDIR/optimal_update_model.json" | sha256sum --check --status || {
    echo "Refusing resume: the frozen 2k checkpoint hash does not match" >&2
    exit 1
  }
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SNAPSHOT="$LOGDIR/provenance/pre_${CURRENT_EVALS}_to_${TARGET_EVALS}_${STAMP}"
mkdir -p "$SNAPSHOT/archive"
for name in README.md client.json config.gin metrics.json archive_history.pkl seed \
  failed_levels.pkl dashboard_status.txt optimal_update_model.json reload.pkl; do
  if [[ -f "$LOGDIR/$name" ]]; then
    cp --reflink=auto --preserve=all "$LOGDIR/$name" "$SNAPSHOT/$name"
  fi
done
if [[ -f "$LOGDIR/archive/archive_${CURRENT_ITRS}.pkl" ]]; then
  cp --reflink=auto --preserve=all \
    "$LOGDIR/archive/archive_${CURRENT_ITRS}.pkl" "$SNAPSHOT/archive/"
fi
# Preserve every previously extracted stage checkpoint before a later resume.
# These files are small and are not regenerated from a later one-elite archive.
if [[ -d "$LOGDIR/checkpoints" ]]; then
  cp --reflink=auto --preserve=all -R "$LOGDIR/checkpoints" "$SNAPSHOT/"
fi
cp --preserve=all "$CONFIG" "$SNAPSHOT/requested_stage_config.gin"
(
  cd "$SNAPSHOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)

SCHEDULER_FILE="/tmp/dai-cma-scheduler-${$}.json"
SCHEDULER_PID=""
WORKER_PID=""
cleanup() {
  local status=$?
  [[ -n "$WORKER_PID" ]] && kill "$WORKER_PID" 2>/dev/null || true
  [[ -n "$SCHEDULER_PID" ]] && kill "$SCHEDULER_PID" 2>/dev/null || true
  rm -f "$SCHEDULER_FILE"
  exit "$status"
}
trap cleanup EXIT INT TERM

cd "$CMA_DIR"
echo "[$(date -Is)] snapshot=$SNAPSHOT"
echo "[$(date -Is)] resuming evals=$CURRENT_EVALS->$TARGET_EVALS workers=$NUM_WORKERS"

"$(dirname "$DAI_PYTHON")/dask-scheduler" \
  --host 127.0.0.1 --port 0 --no-dashboard \
  --scheduler-file "$SCHEDULER_FILE" &
SCHEDULER_PID=$!
for _ in $(seq 1 100); do
  [[ -s "$SCHEDULER_FILE" ]] && break
  sleep 0.1
done
[[ -s "$SCHEDULER_FILE" ]] || { echo "Dask scheduler did not start" >&2; exit 1; }

"$(dirname "$DAI_PYTHON")/dask-worker" \
  --scheduler-file "$SCHEDULER_FILE" \
  --nprocs "$NUM_WORKERS" --nthreads 1 --memory-limit 7GB \
  --no-dashboard --local-directory "$DAI_WORKSPACE/.dask-worker-space" &
WORKER_PID=$!

ADDRESS="$($DAI_PYTHON - "$SCHEDULER_FILE" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1]))["address"])
PY
)"
"$DAI_PYTHON" - "$ADDRESS" "$NUM_WORKERS" <<'PY'
import sys
from dask.distributed import Client
client = Client(sys.argv[1])
client.wait_for_workers(int(sys.argv[2]), timeout=180)
print(f"ready_workers={len(client.ncores())}")
client.close()
PY

"$DAI_PYTHON" env_search/main.py \
  --config "$CONFIG" \
  --address "$ADDRESS" \
  --seed 17 \
  --logdir_root logs \
  --reload "$LOGDIR"

FINAL_ITRS=$(( TARGET_EVALS / 100 ))
ARCHIVE="$LOGDIR/archive/archive_${FINAL_ITRS}.pkl"
CHECKPOINT="$LOGDIR/checkpoints/optimal_update_model_${TARGET_EVALS}.json"
SIMULATOR="$CMA_DIR/simulators/trafficMAPF_on/period_on_sim.cpython-39-x86_64-linux-gnu.so"
"$DAI_PYTHON" "$WORKSPACE/scripts/extract_best_traffic_cnn.py" \
  --archive "$ARCHIVE" \
  --output "$CHECKPOINT" \
  --config "$CONFIG" \
  --simulator "$SIMULATOR" \
  --total-evals "$TARGET_EVALS"

echo "[$(date -Is)] complete checkpoint=$CHECKPOINT"
