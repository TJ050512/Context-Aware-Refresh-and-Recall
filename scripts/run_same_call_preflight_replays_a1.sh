#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAP="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps/warehouse_small_narrow_kiva.map"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_v1.py"
ATTESTATION="${SAME_CALL_ENV_ATTESTATION:-$WORKSPACE/reports/same_call_environment_attestation_a1.json}"
ATTESTATION_SHA256="${SAME_CALL_ENV_ATTESTATION_SHA256:?set SAME_CALL_ENV_ATTESTATION_SHA256 to the sealed target-host attestation digest}"
OUTDIR="$WORKSPACE/results/same_call_preflight_a1"
LOGDIR="$WORKSPACE/logs/same_call_preflight_a1"

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
check_sha 10f17682a9dc32f33fad2c77289e8c9dff659325de655b584f1d138066f05fdf "$WORKSPACE/EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A1.md"
check_sha "$ATTESTATION_SHA256" "$ATTESTATION"

if [[ -e "$OUTDIR" || -e "$LOGDIR" ]]; then
  echo "Refusing to overwrite A1 preflight replay directories" >&2
  exit 3
fi
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
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" "$@" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1
  echo "completed A1 preflight replay label=$label"
}

run_artifact repeat_a
run_artifact repeat_b
run_artifact future_suffix_base --future-suffix-cutoff 1400
run_artifact future_suffix_variant --future-suffix-cutoff 1400 --future-suffix-variant 1

"$DAI_PYTHON" - "$OUTDIR" "$ATTESTATION" "$ATTESTATION_SHA256" <<'PY'
import hashlib
import json
import pathlib
import sys

outdir = pathlib.Path(sys.argv[1])
attestation = pathlib.Path(sys.argv[2])
attestation_sha = sys.argv[3]
hosts = set()
artifacts = {}
for label in ("repeat_a", "repeat_b", "future_suffix_base", "future_suffix_variant"):
    path = outdir / f"{label}.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("status") != "complete" or len(artifact.get("runs", ())) != 2:
        raise SystemExit(f"incomplete A1 replay artifact {path}")
    if artifact.get("fresh_process_per_arm") is not True:
        raise SystemExit(f"fresh-process attestation missing in {path}")
    identities = {
        (run.get("execution_host"), run.get("execution_process_id"), run.get("execution_process_start_ns"))
        for run in artifact["runs"]
    }
    if len(identities) != 2 or any(None in identity for identity in identities):
        raise SystemExit(f"fresh process identities invalid in {path}")
    hosts.update(run.get("execution_host") for run in artifact["runs"])
    artifacts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
if len(hosts) != 1:
    raise SystemExit(f"A1 replays crossed hosts: {sorted(hosts)}")
binding = {
    "schema": "dai.same-call-a1-artifact-binding/v1",
    "stage": "repeat_and_future_suffix",
    "effect_inference_performed": False,
    "root_seed": 17,
    "execution_host": next(iter(hosts)),
    "environment_attestation": {"path": str(attestation), "sha256": attestation_sha},
    "artifacts": artifacts,
    "ledgers": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(outdir.glob("*.attempts.jsonl"))
    },
    "passed": True,
}
(outdir / "A1_BINDING.json").write_text(
    json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print("SAME_CALL_A1_PREFLIGHT_REPLAYS_COMPLETE")
PY
