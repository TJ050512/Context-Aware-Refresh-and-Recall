#!/usr/bin/env bash
set -euo pipefail

# Pre-B engineering smoke.  This deliberately uses the historical development
# root 17 and never opens any of the 40 Experiment B confirmation roots.

if [[ "$#" -gt 1 ]]; then
  echo "usage: $0 [JOBS_PER_SCENARIO]" >&2
  exit 64
fi
JOBS_PER_SCENARIO="${1:-${B_SMOKE_JOBS_PER_SCENARIO:-24}}"
if [[ ! "$JOBS_PER_SCENARIO" =~ ^[1-9][0-9]*$ ]]; then
  echo "JOBS_PER_SCENARIO must be a positive integer" >&2
  exit 64
fi

WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_v1.py"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAP="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps/warehouse_small_kiva.map"
OUTDIR="$WORKSPACE/results/same_call_smoke_b"
LOGDIR="$WORKSPACE/logs/same_call_smoke_b"
OUTPUT="$OUTDIR/regular_r020_root17_stationary.json"
LEDGER="$OUTDIR/regular_r020_root17_stationary.attempts.jsonl"
LOG="$LOGDIR/regular_r020_root17_stationary.log"
REPORT="$WORKSPACE/reports/same_call_smoke_b.json"

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

for required in "$DAI_PYTHON" "$RUNNER" "$CKPT" "$MAP"; do
  if [[ ! -f "$required" ]]; then
    echo "B smoke required file is absent: $required" >&2
    exit 2
  fi
done
for protected in "$OUTPUT" "${OUTPUT%.json}.csv" "$LEDGER" "$LOG" "$REPORT"; do
  if [[ -e "$protected" ]]; then
    echo "Refusing to overwrite B engineering-smoke artifact: $protected" >&2
    exit 3
  fi
done
mkdir -p "$OUTDIR" "$LOGDIR" "$(dirname "$REPORT")"

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

"$DAI_PYTHON" "$RUNNER" \
  --workspace "$WORKSPACE" \
  --checkpoint "$CKPT" \
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d \
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac \
  --split development \
  --seeds 17 \
  --workloads stationary \
  --methods "${METHODS[@]}" \
  --map-path "$MAP" \
  --agents 255 \
  --warmup-time 200 \
  --horizon 2000 \
  --decision-window 20 \
  --release-interval 110 \
  --guard-suffix 4 \
  --sigma 0.75 \
  --context-match-threshold 0.05 \
  --context-recall-margin 0.02 \
  --context-min-score 0.10 \
  --context-min-gap 6 \
  --context-maintenance-age 25 \
  --context-maintenance-stability 0.20 \
  --fresh-process-per-arm \
  --jobs "$JOBS_PER_SCENARIO" \
  --attempt-ledger "$LEDGER" \
  --output "$OUTPUT" >"$LOG" 2>&1

"$DAI_PYTHON" - "$OUTPUT" "$LEDGER" "$REPORT" "$LOG" "$RUNNER" "$JOBS_PER_SCENARIO" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

artifact_path, ledger_path, report_path, log_path, runner_path = map(Path, sys.argv[1:6])
jobs = int(sys.argv[6])
B_ROOTS = {
    880565, 534821, 257578, 500976, 294860, 954705, 190142, 429853,
    398397, 560584, 175381, 598292, 461566, 526869, 115950, 130998,
    655067, 585455, 362413, 552654, 664860, 253714, 962860, 907962,
    381214, 583444, 371204, 934561, 491276, 541256, 523055, 713041,
    537643, 699809, 204011, 330180, 113743, 257704, 152753, 657283,
}
METHODS = (
    "bootstrap_only", "exact_even_G4", "exact_even_G5", "random_G5",
    "js_cap_G5", "context_no_reactivation_B25", "context_memory_B25",
    "exact_even_B25",
)


def fail(message):
    raise SystemExit(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
runs = artifact.get("runs")
if (
    artifact.get("schema") != "dai.claim-aware-absolute-budget/v1"
    or artifact.get("status") != "complete"
    or artifact.get("split") != "development"
    or artifact.get("evidence_class") != "development"
    or artifact.get("seeds") != [17]
    or set(artifact.get("seeds", ())) & B_ROOTS
    or tuple(artifact.get("methods", ())) != METHODS
    or artifact.get("workloads") != ["stationary"]
    or artifact.get("map_sha256") != "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"
    or artifact.get("fresh_process_per_arm") is not True
    or not isinstance(runs, list)
    or len(runs) != 8
):
    fail("B engineering smoke artifact identity/cardinality failed")
protocol = artifact.get("protocol")
expected_protocol = {
    "agents": 255,
    "warmup_time": 200,
    "scored_horizon": 2000,
    "decision_window": 20,
    "num_scored_windows": 100,
    "eligible_post_bootstrap_decisions": 99,
    "b25_budget": 25,
    "release_interval_per_agent": 110,
    "guard_suffix_tasks_per_agent": 4,
    "future_suffix_variant": 0,
    "future_suffix_cutoff_absolute": 2200,
    "sigma": 0.75,
    "pacing_slack": 2,
    "minimum_history": 4,
    "method_order_randomized_with_independent_seed": True,
    "fresh_os_process_per_arm": True,
    "jobs": jobs,
    "exclusive_timing_declared": False,
    "timing_evidence_valid": False,
}
if not isinstance(protocol, dict) or any(
    protocol.get(field) != value for field, value in expected_protocol.items()
):
    fail("B engineering smoke did not exercise the full frozen scientific parameters")
if (
    protocol.get("context_memory_B25", {}).get("recall_threshold") != 0.05
    or protocol.get("context_memory_B25", {}).get("recall_margin") != 0.02
    or protocol.get("context_memory_B25", {}).get("absolute_score_gate") != 0.10
    or protocol.get("context_memory_B25", {}).get("min_gap_windows") != 6
    or protocol.get("context_memory_B25", {}).get("maintenance_age_windows") != 25
    or protocol.get("context_memory_B25", {}).get("maintenance_stability_gate") != 0.20
):
    fail("B engineering smoke CARR parameters drifted")
environment = artifact.get("runtime_manifest", {}).get("environment")
thread_contract = {
    "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
if (
    not isinstance(environment, dict)
    or environment.get("thread_environment") != thread_contract
    or environment.get("torch_num_threads") != 1
    or environment.get("torch_num_interop_threads") != 1
):
    fail("B engineering smoke thread environment failed")

process_instances = set()
run_uuids = set()
pairing = {}
for run in runs:
    if (
        run.get("seed") != 17
        or run.get("root_seed") != 17
        or run.get("method") not in METHODS
        or run.get("workload") != "stationary"
        or run.get("split") != "development"
        or run.get("evidence_class") != "development"
        or run.get("scored_horizon") != 2000
        or run.get("decision_window") != 20
        or run.get("window_count") != 100
    ):
        fail("B engineering smoke run identity/protocol failed")
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
        or not isinstance(invariants, dict)
        or invariants.get("passed") is not True
        or invariants.get("online_workload_rng_draws") != 0
        or invariants.get("tape_not_exhausted") is not True
        or invariants.get("reward_sum_matches_completed") is not True
        or invariants.get("unexposed_completions_excluded_from_cohorts") is not True
        or run.get("budget_violation_count") != 0
    ):
        fail("B engineering smoke safety/invariant gate failed")
    pid = run.get("execution_process_id")
    start_ns = run.get("execution_process_start_ns")
    host = run.get("execution_host")
    token = run.get("run_uuid")
    try:
        canonical = str(uuid.UUID(token)) == token
    except (TypeError, ValueError, AttributeError):
        canonical = False
    if not host or not isinstance(pid, int) or pid < 1 or not isinstance(start_ns, int) or start_ns < 1 or not canonical:
        fail("B engineering smoke fresh-process identity failed")
    process_instances.add((host, pid, start_ns))
    run_uuids.add(token)
    for field in (
        "manifest_id", "reset_causal_fingerprint", "release_projection_fingerprint",
        "distribution_update_fingerprint", "task_tape_identity", "workload_arrival",
    ):
        pairing.setdefault(field, set()).add(canonical_sha256(run.get(field)))
if len(process_instances) != 8 or len(run_uuids) != 8 or any(len(values) != 1 for values in pairing.values()):
    fail("B engineering smoke process uniqueness or eight-arm pairing failed")

lines = ledger_path.read_text(encoding="utf-8").splitlines()
if len(lines) != 16 or any(not line.strip() for line in lines):
    fail("B engineering smoke ledger must contain eight starts and eight completions")
events = [json.loads(line) for line in lines]
started = [event for event in events if event.get("event") == "started"]
completed = [event for event in events if event.get("event") == "completed"]
if len(started) != 8 or len(completed) != 8 or any(
    event.get("schema") != "dai.same-call-attempt-ledger/v1" for event in events
):
    fail("B engineering smoke ledger event contract failed")
by_method = {run["method"]: run for run in runs}
for event in events:
    identity = event.get("identity")
    if not isinstance(identity, dict) or event.get("attempt_id") != canonical_sha256(identity):
        fail("B engineering smoke attempt identity hash failed")
    if identity.get("seed") != 17 or identity.get("workload") != "stationary":
        fail("B engineering smoke ledger used an unauthorized root/workload")
    if event.get("event") == "completed":
        run = by_method.get(identity.get("method"))
        if run is None or event.get("run_sha256") != canonical_sha256(run):
            fail("B engineering smoke completion does not bind the retained run")

if report_path.exists():
    fail(f"refusing to overwrite B smoke report: {report_path}")
report = {
    "schema": "dai.same-call-engineering-smoke/b",
    "status": "complete",
    "passed": True,
    "claim_scope": "engineering preflight only; no performance estimate or ranking",
    "split": "development",
    "root_seeds": [17],
    "b_root_runs_observed": 0,
    "effect_inference_performed": False,
    "method_rankings_inspected": False,
    "methods": list(METHODS),
    "workloads": ["stationary"],
    "scenario": {"id": "regular_r020", "agents": 255},
    "jobs_per_scenario": jobs,
    "execution": {"jobs_per_scenario": jobs, "fresh_process_per_arm": True},
    "checks": {
        "historical_development_root_only": True,
        "zero_confirmation_roots_opened": True,
        "complete_eight_method_family": True,
        "full_scientific_parameters": True,
        "one_thread_environment": True,
        "fresh_process_and_uuid_per_arm": True,
        "paired_task_tape_and_workload": True,
        "safety_invariants_and_budget": True,
        "ledger_exactly_once_and_run_hash_bound": True,
    },
    "artifacts": {
        "runner": {"path": str(runner_path.resolve()), "sha256": sha256_file(runner_path)},
        "output": {"path": str(artifact_path.resolve()), "sha256": sha256_file(artifact_path)},
        "attempt_ledger": {"path": str(ledger_path.resolve()), "sha256": sha256_file(ledger_path)},
        "log": {"path": str(log_path.resolve()), "sha256": sha256_file(log_path)},
    },
}
temporary = report_path.with_name(f".{report_path.name}.tmp")
temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
try:
    os.link(temporary, report_path)
except FileExistsError:
    temporary.unlink(missing_ok=True)
    fail(f"refusing to overwrite B smoke report: {report_path}")
temporary.unlink()
print(
    "SAME_CALL_ENGINEERING_SMOKE_B_PASS "
    f"root=17 methods=8 runs=8 jobs_per_scenario={jobs} report={report_path}"
)
PY
