#!/usr/bin/env bash
set -euo pipefail

# A2 retains the frozen same_call_confirmation_v1 scientific split while its
# versioned control-plane entry point binds the untouched A2 replacement roots.
WORKSPACE="${WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
CKPT="${CKPT10:-$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json}"
MAPDIR="$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
RUNNER="$WORKSPACE/scripts/run_same_call_confirmation_a2.py"
CONFIG="${SAME_CALL_CONFIG:-$WORKSPACE/configs/same_call_confirmation_a2.json}"
OUTDIR="$WORKSPACE/results/same_call_confirmation_a2"
LOGDIR="$WORKSPACE/logs/same_call_confirmation_a2"

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
    raise SystemExit("A2 config target_environment must be an object")
host = target.get("execution_host")
if not isinstance(host, str) or not host:
    raise SystemExit("A2 config target_environment.execution_host is missing")
print(host)
PY
)"
CURRENT_HOST="$(hostname)"
if [[ "$CURRENT_HOST" != "$TARGET_HOST" ]]; then
  echo "A2 target-host mismatch before fresh roots: expected=$TARGET_HOST actual=$CURRENT_HOST" >&2
  exit 2
fi

# Verify the complete A2 implementation/preflight manifest, the sealed target
# environment attestation, and current hostname before opening any fresh root.
# Non-file identities are rechecked by the frozen runner and final analyzer.
"$DAI_PYTHON" - "$WORKSPACE" "$CONFIG" "$CURRENT_HOST" <<'PY'
import hashlib
import importlib.util
import json
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1]).resolve()
config_path = pathlib.Path(sys.argv[2]).resolve()
current_host = sys.argv[3]
config = json.loads(config_path.read_text(encoding="utf-8"))
expected_a2_roots = [
    691817, 376110, 263001, 293231, 296805,
    274330, 997942, 319782, 807287, 326454,
]
if config.get("schema") != "dai.same-call-confirmation/a2":
    raise SystemExit("A2 config schema is not dai.same-call-confirmation/a2")
if config.get("root_seeds") != expected_a2_roots:
    raise SystemExit("A2 config root vector differs from the frozen replacement roots")

required_frozen = config.get("required_frozen_artifacts")
frozen = config.get("frozen_artifacts")
if not isinstance(required_frozen, list) or not isinstance(frozen, dict):
    raise SystemExit("A2 config frozen-artifact manifest is incomplete")
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

a2_protocol_records = [
    frozen[name]
    for name in required_frozen
    if pathlib.Path(str(frozen[name].get("path", ""))).name
    == "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md"
]
if len(a2_protocol_records) != 1:
    raise SystemExit("A2 config must require exactly one A2 protocol artifact")
if a2_protocol_records[0].get("sha256") != (
    "c1caaf9532ac728b19761d0eab60628d8e32e4d3a101512b51fa0a5abeebf9dd"
):
    raise SystemExit("A2 protocol digest is not the frozen amendment digest")

a1_failure_records = [
    frozen[name]
    for name in required_frozen
    if pathlib.Path(str(frozen[name].get("path", ""))).name
    == "same_call_a1_effect_blind_execution_failure.json"
]
if len(a1_failure_records) != 1:
    raise SystemExit(
        "A2 config must require exactly one A1 effect-blind failure report"
    )
if a1_failure_records[0].get("sha256") != (
    "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
):
    raise SystemExit("A1 effect-blind failure report digest is not frozen")

required_preflight = config.get("required_preflight_evidence")
preflight = config.get("preflight_evidence")
if not isinstance(required_preflight, list) or not isinstance(preflight, dict):
    raise SystemExit("A2 config preflight-evidence manifest is incomplete")
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
    raise SystemExit("A2 config target_environment must be an object")
for key in ("path", "sha256", "execution_host"):
    if not isinstance(target.get(key), str) or not target[key]:
        raise SystemExit(f"A2 target_environment.{key} is missing")
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

attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
sealed_environment = attestation.get("environment")
if (
    attestation.get("schema") != "dai.same-call-environment-attestation/a1"
    or attestation.get("status") != "complete"
    or not isinstance(sealed_environment, dict)
):
    raise SystemExit("sealed target-environment attestation is incomplete")
helper_record = frozen.get("legacy_replay_launcher")
if not isinstance(helper_record, dict):
    raise SystemExit("A2 frozen manifest lacks the environment-capture helper")
helper_path = pathlib.Path(str(helper_record.get("path", "")))
if not helper_path.is_absolute():
    helper_path = workspace / helper_path
spec = importlib.util.spec_from_file_location(
    "a2_launch_environment_helper", helper_path
)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot import frozen environment helper: {helper_path}")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
current_environment = helper._capture_environment()

sealed_fingerprint = sealed_environment.get("host_instance_fingerprint_sha256")
current_fingerprint = current_environment.get("host_instance_fingerprint_sha256")
if (
    not isinstance(sealed_fingerprint, str)
    or current_fingerprint != sealed_fingerprint
):
    raise SystemExit(
        "live host-instance fingerprint differs from sealed A1 target: "
        f"expected={sealed_fingerprint} actual={current_fingerprint}"
    )
sealed_gpu_inventory = sealed_environment.get("gpu_inventory")
current_gpu_inventory = current_environment.get("gpu_inventory")
if current_gpu_inventory != sealed_gpu_inventory:
    raise SystemExit(
        "live ordered GPU UUID/name/driver/VBIOS inventory differs from "
        "sealed A1 target"
    )
sealed_projection = helper._environment_compatibility_projection(
    sealed_environment
)
current_projection = helper._environment_compatibility_projection(
    current_environment
)
if current_projection != sealed_projection:
    raise SystemExit(
        "live host/runtime critical-version projection differs from sealed "
        "A1 target"
    )

def canonical_sha256(value):
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

projection_sha256 = canonical_sha256(current_projection)
print(
    "SAME_CALL_A2_FREEZE_AND_TARGET_ENVIRONMENT_VERIFIED "
    f"host={current_host} attestation_sha256={attestation_actual} "
    f"host_instance_fingerprint_sha256={current_fingerprint} "
    f"compatibility_projection_sha256={projection_sha256}"
)
PY

mkdir -p "$OUTDIR" "$LOGDIR"

SEEDS_TEXT="$($DAI_PYTHON - "$CONFIG" <<'PY'
import json
import pathlib
import sys

config = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
roots = config.get("root_seeds")
if not isinstance(roots, list) or len(roots) != 10:
    raise SystemExit("A2 config must contain exactly ten root seeds")
if any(not isinstance(root, int) or isinstance(root, bool) for root in roots):
    raise SystemExit("A2 root seeds must be integers")
print(" ".join(str(root) for root in roots))
PY
)"
read -r -a SEEDS <<< "$SEEDS_TEXT"
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
    echo "Refusing to overwrite protected A2 confirmation artifact: $label" >&2
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
    echo "Refusing to overwrite protected A2 confirmation artifact: $label" >&2
    exit 3
  fi
  "$DAI_PYTHON" "$RUNNER" "${COMMON[@]}" \
    --map-path "$MAPDIR/$map_name" \
    --agents "$agents" \
    --attempt-ledger "$ledger" \
    --output "$output" >"$log" 2>&1 &
  PIDS+=("$!")
  LABELS+=("$label")
  echo "started A2 confirmation label=$label pid=$! host=$TARGET_HOST"
}

launch narrow_r020 warehouse_small_narrow_kiva.map 218
launch narrow_r035 warehouse_small_narrow_kiva.map 382
launch regular_r020 warehouse_small_kiva.map 255
launch regular_r035 warehouse_small_kiva.map 447

failed=0
for index in "${!PIDS[@]}"; do
  if wait "${PIDS[$index]}"; then
    echo "completed A2 confirmation label=${LABELS[$index]}"
  else
    echo "failed A2 confirmation label=${LABELS[$index]} log=$LOGDIR/${LABELS[$index]}.log" >&2
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  exit 4
fi

"$DAI_PYTHON" - "$OUTDIR" "$CONFIG_SHA" "$TARGET_HOST" "$CONFIG" <<'PY'
import glob
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import uuid

outdir, config_sha, target_host, config_path = sys.argv[1:]
config = json.loads(open(config_path, encoding="utf-8").read())
expected_roots = tuple(config["root_seeds"])
expected_methods = (
    "bootstrap_only",
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
    "context_no_reactivation_B25",
    "context_memory_B25",
    "exact_even_B25",
)
expected_workloads = ("stationary", "abrupt", "recurrent")
expected_scenarios = {
    "narrow_r020": 218,
    "narrow_r035": 382,
    "regular_r020": 255,
    "regular_r035": 447,
}
expected_derivation_source = (
    "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
)
expected_derivation_domain = (
    "dai-same-call-confirmatory-a2-pid-reuse-correction"
)
ledger_schema = "dai.same-call-attempt-ledger/v1"
identity_fields = {"split", "map_id", "agents", "seed", "workload", "method"}


def canonical_sha256(value):
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value


def attempt_identity(run, agents):
    return {
        "split": str(run["split"]),
        "map_id": str(run["map_id"]),
        "agents": agents,
        "seed": int(run["seed"]),
        "workload": str(run["workload"]),
        "method": str(run["method"]),
    }


def verify_attempt_ledger(artifact_path, artifact, runs, agents):
    record = artifact.get("attempt_ledger")
    if not isinstance(record, dict) or record.get("schema") != ledger_schema:
        raise SystemExit(f"attempt ledger record is invalid in {artifact_path}")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise SystemExit(f"attempt ledger path is missing in {artifact_path}")
    ledger_path = Path(raw_path).expanduser().resolve()
    if (
        not ledger_path.is_file()
        or not isinstance(record.get("sha256"), str)
        or sha256_file(ledger_path) != record["sha256"]
    ):
        raise SystemExit(f"attempt ledger file/hash mismatch in {artifact_path}")
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 480 or any(not line.strip() for line in lines):
        raise SystemExit(f"attempt ledger must contain 480 nonblank events: {ledger_path}")
    try:
        events = [json.loads(line) for line in lines]
    except json.JSONDecodeError as error:
        raise SystemExit(f"attempt ledger is invalid JSONL: {ledger_path}") from error
    if not all(isinstance(event, dict) for event in events):
        raise SystemExit(f"attempt ledger events must be objects: {ledger_path}")
    if record.get("started_events") != 240 or record.get("completed_events") != 240:
        raise SystemExit(f"attempt ledger declared counts are invalid: {ledger_path}")

    grouped = {}
    for event in events:
        if event.get("schema") != ledger_schema:
            raise SystemExit(f"attempt ledger schema drift: {ledger_path}")
        event_name = event.get("event")
        if event_name not in {"started", "completed"}:
            raise SystemExit(f"attempt ledger contains retry/failure/unknown event: {ledger_path}")
        identity = event.get("identity")
        if not isinstance(identity, dict) or set(identity) != identity_fields:
            raise SystemExit(f"attempt ledger identity fields are invalid: {ledger_path}")
        attempt_id = event.get("attempt_id")
        if attempt_id != canonical_sha256(identity):
            raise SystemExit(f"attempt id does not bind its identity: {ledger_path}")
        bucket = grouped.setdefault(attempt_id, {})
        if event_name in bucket:
            raise SystemExit(f"attempt ledger contains a duplicate/retry event: {ledger_path}")
        bucket[event_name] = event

    expected_by_id = {}
    for run in runs:
        identity = attempt_identity(run, agents)
        attempt_id = canonical_sha256(identity)
        if attempt_id in expected_by_id:
            raise SystemExit(f"retained runs contain a duplicate arm: {artifact_path}")
        expected_by_id[attempt_id] = (identity, run)
    if len(expected_by_id) != 240 or set(grouped) != set(expected_by_id):
        raise SystemExit(f"ledger does not cover retained arms exactly once: {artifact_path}")

    for attempt_id, (identity, run) in expected_by_id.items():
        bucket = grouped[attempt_id]
        if set(bucket) != {"started", "completed"}:
            raise SystemExit(f"ledger contains an unfinished/deleted arm: {artifact_path}")
        started = bucket["started"]
        completed = bucket["completed"]
        if started.get("identity") != identity or completed.get("identity") != identity:
            raise SystemExit(f"ledger arm identity changed during execution: {artifact_path}")
        start_time = started.get("time_ns")
        process_start = run.get("execution_process_start_ns")
        completion_time = completed.get("time_ns")
        if (
            not positive_integer(start_time)
            or not positive_integer(process_start)
            or not positive_integer(completion_time)
            or not start_time <= process_start <= completion_time
        ):
            raise SystemExit(f"ledger timestamps are not causally ordered: {artifact_path}")
        if (
            started.get("runner_parent_process_id")
            != run.get("execution_parent_process_id")
            or completed.get("runner_parent_process_id")
            != run.get("execution_parent_process_id")
            or completed.get("execution_process_id")
            != run.get("execution_process_id")
            or completed.get("execution_host") != run.get("execution_host")
            or completed.get("execution_process_start_ns") != process_start
            or completed.get("run_uuid") != run.get("run_uuid")
            or completed.get("planner_timeouts") != run.get("planner_timeouts")
            or completed.get("safety_passed") is not True
            or completed.get("invariants_passed") is not True
            or completed.get("run_sha256") != canonical_sha256(run)
        ):
            raise SystemExit(f"ledger completion does not bind retained run: {artifact_path}")
    return str(ledger_path)


if tuple(config.get("methods", ())) != expected_methods:
    raise SystemExit("A2 config method family differs from the frozen matrix")
if tuple(config.get("workloads", ())) != expected_workloads:
    raise SystemExit("A2 config workload family differs from the frozen matrix")
paths = sorted(glob.glob(os.path.join(outdir, "*.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four A2 confirmation artifacts, found {len(paths)}")
scenario_ids = [Path(path).stem for path in paths]
if len(set(scenario_ids)) != 4 or set(scenario_ids) != set(expected_scenarios):
    raise SystemExit(f"A2 scenario artifact set is invalid: {scenario_ids}")

expected_thread_environment = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
reference_environment = None
reference_environment_sha = None
all_process_identities = []
all_run_uuids = []
all_arm_keys = []
ledger_paths = []
total_runs = 0
for path in paths:
    scenario_id = Path(path).stem
    with open(path, encoding="utf-8") as stream:
        artifact = json.load(stream)
    runs = artifact.get("runs")
    if not isinstance(runs, list):
        raise SystemExit(f"runs must be a list in {path}")
    total_runs += len(runs)
    if artifact.get("status") != "complete" or len(runs) != 240:
        raise SystemExit(f"incomplete A2 confirmation artifact {path}")
    if artifact.get("split") != "same_call_confirmation_v1":
        raise SystemExit(f"frozen scientific split changed in {path}")
    if artifact.get("development_matrix_config_sha256") != config_sha:
        raise SystemExit(f"config digest mismatch in {path}")
    if tuple(artifact.get("seeds", ())) != expected_roots:
        raise SystemExit(f"A2 root vector mismatch in {path}")
    if artifact.get("fresh_process_per_arm") is not True:
        raise SystemExit(f"fresh-process flag missing in {path}")
    if tuple(artifact.get("methods", ())) != expected_methods:
        raise SystemExit(f"frozen method family changed in {path}")
    if tuple(artifact.get("workloads", ())) != expected_workloads:
        raise SystemExit(f"frozen workload family changed in {path}")
    protocol = artifact.get("protocol")
    if (
        not isinstance(protocol, dict)
        or protocol.get("agents") != expected_scenarios[scenario_id]
    ):
        raise SystemExit(f"scenario agent contract changed in {path}")
    split_protocol = artifact.get("split_protocol")
    if (
        not isinstance(split_protocol, dict)
        or split_protocol.get("preregistered_seeds") != list(expected_roots)
        or split_protocol.get("seed_derivation_source_sha256")
        != expected_derivation_source
        or split_protocol.get("seed_derivation_domain")
        != expected_derivation_domain
    ):
        raise SystemExit(f"A2 split derivation provenance is invalid in {path}")

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
            "full runtime environment differs across A2 scenarios: "
            f"reference_sha256={reference_environment_sha} "
            f"actual_sha256={environment_sha} path={path}"
        )

    process_identities = []
    run_uuids = []
    scenario_arm_keys = []
    for run in runs:
        if not isinstance(run, dict):
            raise SystemExit(f"run must be an object in {path}")
        pid = run.get("execution_process_id")
        parent_pid = run.get("execution_parent_process_id")
        start_ns = run.get("execution_process_start_ns")
        host = run.get("execution_host")
        run_uuid = run.get("run_uuid")
        if (
            not isinstance(host, str)
            or not host
            or not positive_integer(pid)
            or not positive_integer(parent_pid)
            or not positive_integer(start_ns)
        ):
            raise SystemExit(f"process identity fields are invalid in {path}")
        if pid == parent_pid:
            raise SystemExit(f"child PID equals runner parent PID in {path}")
        if not canonical_uuid(run_uuid):
            raise SystemExit(f"run UUID is not canonical in {path}")
        root = run.get("root_seed", run.get("seed"))
        if run.get("seed") != root:
            raise SystemExit(f"run root_seed/seed binding differs in {path}")
        process_identities.append((host, pid, start_ns))
        run_uuids.append(run_uuid)
        scenario_arm_keys.append(
            (scenario_id, run.get("method"), root, run.get("workload"))
        )
    if len(set(process_identities)) != len(process_identities):
        raise SystemExit(f"one-process-instance-per-arm audit failed in {path}")
    if len(set(run_uuids)) != len(run_uuids):
        raise SystemExit(f"one-run-uuid-per-arm audit failed in {path}")
    all_process_identities.extend(process_identities)
    all_run_uuids.extend(run_uuids)
    all_arm_keys.extend(scenario_arm_keys)
    run_hosts = {run.get("execution_host") for run in runs}
    if run_hosts != {target_host}:
        raise SystemExit(
            f"run host mismatch in {path}: expected={target_host} "
            f"actual={sorted(str(host) for host in run_hosts)}"
        )
    if any(run.get("split") != "same_call_confirmation_v1" for run in runs):
        raise SystemExit(f"run scientific split changed in {path}")
    if {run.get("root_seed", run.get("seed")) for run in runs} != set(expected_roots):
        raise SystemExit(f"run root vector differs from A2 config in {path}")
    if any(not run["safety"]["passed"] for run in runs):
        raise SystemExit(f"safety failure in {path}")
    if any(not run["invariants"]["passed"] for run in runs):
        raise SystemExit(f"invariant failure in {path}")
    ledger_paths.append(
        verify_attempt_ledger(
            path, artifact, runs, expected_scenarios[scenario_id]
        )
    )
    print(
        f"audited A2 confirmation {os.path.basename(path)} runs={len(runs)} "
        f"host={target_host} environment_sha256={environment_sha}"
    )

if total_runs != 960:
    raise SystemExit(f"expected exactly 960 A2 runs, found {total_runs}")
expected_arm_keys = set(
    itertools.product(
        expected_scenarios, expected_methods, expected_roots, expected_workloads
    )
)
observed_arm_keys = set(all_arm_keys)
if len(all_arm_keys) != 960 or observed_arm_keys != expected_arm_keys:
    missing = sorted(expected_arm_keys - observed_arm_keys, key=repr)[:5]
    extra = sorted(observed_arm_keys - expected_arm_keys, key=repr)[:5]
    raise SystemExit(
        "matrix is missing, duplicating, or replacing a frozen arm: "
        f"unique={len(observed_arm_keys)} missing_sample={missing} "
        f"extra_sample={extra}"
    )
if len(set(all_process_identities)) != len(all_process_identities):
    raise SystemExit("host/pid/start process identity was reused across scenario artifacts")
if len(set(all_run_uuids)) != len(all_run_uuids):
    raise SystemExit("run UUID was reused across scenario artifacts")
if len(set(ledger_paths)) != 4:
    raise SystemExit("each scenario must bind a distinct attempt ledger")
print(
    "SAME_CALL_CONFIRMATION_A2_MATRIX_COMPLETE "
    f"runs={total_runs} host={target_host} "
    f"environment_sha256={reference_environment_sha}"
)
PY
