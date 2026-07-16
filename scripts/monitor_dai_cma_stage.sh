#!/usr/bin/env bash
# One-shot status summary for run_dai_cma_stage.sh.
set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 LOGDIR [RUN_LOG]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/autodl_env.sh"
LOGDIR="$1"
RUN_LOG="${2:-}"

"$DAI_PYTHON" - "$LOGDIR/metrics.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print("metrics: not written yet")
    raise SystemExit
data = json.loads(path.read_text())
metrics = data["metrics"]
def last(name):
    values = metrics[name]["data"]
    return values[-1] if values else None
print(
    "metrics:",
    f"iterations={data['total_itrs']}",
    f"evals={last('Total Evals')}",
    f"best_objective={last('Best Objective')}",
    f"cumulative_seconds={last('Cum Time')}",
)
PY

if [[ -f "$LOGDIR/dashboard_status.txt" ]]; then
  echo -n "dashboard: "
  cat "$LOGDIR/dashboard_status.txt"
  echo
fi
pgrep -af 'dask-scheduler|dask-worker|env_search/main.py' || true
nvidia-smi --query-gpu=index,utilization.gpu,memory.used \
  --format=csv,noheader 2>/dev/null || true
if [[ -n "$RUN_LOG" && -f "$RUN_LOG" ]]; then
  echo "--- tail $RUN_LOG ---"
  tail -n 30 "$RUN_LOG"
fi
