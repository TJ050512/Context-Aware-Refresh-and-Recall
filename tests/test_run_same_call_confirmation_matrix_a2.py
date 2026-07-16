import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid


WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT = WORKSPACE / "scripts" / "run_same_call_confirmation_matrix_a2.sh"
ROOTS = (
    691817, 376110, 263001, 293231, 296805,
    274330, 997942, 319782, 807287, 326454,
)
METHODS = (
    "bootstrap_only",
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
    "context_no_reactivation_B25",
    "context_memory_B25",
    "exact_even_B25",
)
WORKLOADS = ("stationary", "abrupt", "recurrent")
SCENARIOS = {
    "narrow_r020": 218,
    "narrow_r035": 382,
    "regular_r020": 255,
    "regular_r035": 447,
}


def _canonical_sha256(value):
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SameCallConfirmationMatrixA2StaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_a2_has_dedicated_config_output_and_log_paths(self):
        self.assertIn("configs/same_call_confirmation_a2.json", self.source)
        self.assertIn("results/same_call_confirmation_a2", self.source)
        self.assertIn("logs/same_call_confirmation_a2", self.source)
        self.assertNotIn("configs/same_call_confirmation_a1.json", self.source)
        self.assertNotIn("results/same_call_confirmation_a1", self.source)
        self.assertNotIn("logs/same_call_confirmation_a1", self.source)

    def test_a2_binds_protocol_failure_report_and_control_plane_runner(self):
        self.assertIn("run_same_call_confirmation_a2.py", self.source)
        self.assertIn(
            "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md", self.source
        )
        self.assertIn(
            "c1caaf9532ac728b19761d0eab60628d8e32e4d3a101512b51fa0a5abeebf9dd",
            self.source,
        )
        self.assertIn(
            "same_call_a1_effect_blind_execution_failure.json", self.source
        )
        self.assertIn(
            "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48",
            self.source,
        )
        self.assertIn('config.get("schema") != "dai.same-call-confirmation/a2"', self.source)

    def test_roots_come_from_a2_config_and_retired_vector_is_absent(self):
        self.assertIn('roots = config.get("root_seeds")', self.source)
        self.assertIn('--seeds "${SEEDS[@]}"', self.source)
        self.assertIn("--split same_call_confirmation_v1", self.source)
        for retired in (
            "767369",
            "695428",
            "323681",
            "904171",
            "446020",
            "434435",
            "488565",
            "514527",
            "544573",
            "838809",
        ):
            self.assertNotIn(retired, self.source)

    def test_process_instance_and_uuid_are_the_only_global_identity_gates(self):
        self.assertNotIn("all_pids", self.source)
        self.assertNotIn("len(set(pids))", self.source)
        self.assertIn("len(set(all_process_identities))", self.source)
        self.assertIn("len(set(all_run_uuids))", self.source)

    def test_live_environment_is_recaptured_and_compared_before_roots(self):
        self.assertIn("current_environment = helper._capture_environment()", self.source)
        self.assertIn("host_instance_fingerprint_sha256", self.source)
        self.assertIn("sealed_gpu_inventory", self.source)
        self.assertIn("current_gpu_inventory", self.source)
        self.assertIn("helper._environment_compatibility_projection", self.source)
        self.assertIn("current_projection != sealed_projection", self.source)

    def test_postcheck_replays_per_arm_ledger_and_exact_matrix(self):
        self.assertIn("def canonical_uuid(value):", self.source)
        self.assertIn("if pid == parent_pid:", self.source)
        self.assertIn('completed.get("run_sha256") != canonical_sha256(run)', self.source)
        self.assertIn("def verify_attempt_ledger(", self.source)
        self.assertIn("set(grouped) != set(expected_by_id)", self.source)
        self.assertIn("expected_arm_keys = set(", self.source)
        self.assertIn("itertools.product(", self.source)
        self.assertIn("observed_arm_keys != expected_arm_keys", self.source)

    def test_postcheck_requires_a2_split_derivation_provenance(self):
        self.assertIn('split_protocol.get("preregistered_seeds")', self.source)
        self.assertIn('split_protocol.get("seed_derivation_source_sha256")', self.source)
        self.assertIn('split_protocol.get("seed_derivation_domain")', self.source)
        self.assertIn(
            "dai-same-call-confirmatory-a2-pid-reuse-correction", self.source
        )

    def test_postcheck_accepts_a_complete_control_fixture_and_rejects_hash_drift(self):
        marker = (
            '"$DAI_PYTHON" - "$OUTDIR" "$CONFIG_SHA" "$TARGET_HOST" '
            '"$CONFIG" <<\'PY\'\n'
        )
        postcheck = self.source.rsplit(marker, 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outdir = root / "results"
            outdir.mkdir()
            config_path = root / "config.json"
            script_path = root / "postcheck.py"
            config_sha = "a" * 64
            config_path.write_text(json.dumps({
                "root_seeds": list(ROOTS),
                "methods": list(METHODS),
                "workloads": list(WORKLOADS),
            }))
            script_path.write_text(postcheck, encoding="utf-8")
            environment = {
                "host": "a2-test-host",
                "thread_environment": {
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                    "VECLIB_MAXIMUM_THREADS": "1",
                },
                "torch_num_threads": 1,
                "torch_num_interop_threads": 1,
            }
            global_index = 0
            artifact_paths = []
            ledger_paths = []
            for scenario_id, agents in SCENARIOS.items():
                runs = []
                events = []
                for method, seed, workload in itertools.product(
                    METHODS, ROOTS, WORKLOADS
                ):
                    global_index += 1
                    process_start = 1_000_000 + global_index * 10
                    run = {
                        "split": "same_call_confirmation_v1",
                        "map_id": scenario_id,
                        "seed": seed,
                        "root_seed": seed,
                        "workload": workload,
                        "method": method,
                        "execution_host": "a2-test-host",
                        "execution_process_id": 10_000 + global_index,
                        "execution_parent_process_id": 7,
                        "execution_process_start_ns": process_start,
                        "run_uuid": str(uuid.UUID(int=global_index)),
                        "planner_timeouts": 0,
                        "safety": {"passed": True},
                        "invariants": {"passed": True},
                    }
                    identity = {
                        "split": run["split"],
                        "map_id": run["map_id"],
                        "agents": agents,
                        "seed": seed,
                        "workload": workload,
                        "method": method,
                    }
                    attempt_id = _canonical_sha256(identity)
                    events.extend((
                        {
                            "schema": "dai.same-call-attempt-ledger/v1",
                            "event": "started",
                            "attempt_id": attempt_id,
                            "identity": identity,
                            "runner_parent_process_id": 7,
                            "time_ns": process_start - 1,
                        },
                        {
                            "schema": "dai.same-call-attempt-ledger/v1",
                            "event": "completed",
                            "attempt_id": attempt_id,
                            "identity": identity,
                            "runner_parent_process_id": 7,
                            "execution_process_id": run["execution_process_id"],
                            "execution_host": run["execution_host"],
                            "execution_process_start_ns": process_start,
                            "run_uuid": run["run_uuid"],
                            "run_sha256": _canonical_sha256(run),
                            "planner_timeouts": 0,
                            "safety_passed": True,
                            "invariants_passed": True,
                            "time_ns": process_start + 1,
                        },
                    ))
                    runs.append(run)
                ledger_path = outdir / f"{scenario_id}.attempts.jsonl"
                ledger_path.write_text(
                    "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
                    encoding="utf-8",
                )
                artifact = {
                    "status": "complete",
                    "split": "same_call_confirmation_v1",
                    "development_matrix_config_sha256": config_sha,
                    "seeds": list(ROOTS),
                    "methods": list(METHODS),
                    "workloads": list(WORKLOADS),
                    "fresh_process_per_arm": True,
                    "protocol": {"agents": agents},
                    "split_protocol": {
                        "preregistered_seeds": list(ROOTS),
                        "seed_derivation_source_sha256": (
                            "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
                        ),
                        "seed_derivation_domain": (
                            "dai-same-call-confirmatory-a2-pid-reuse-correction"
                        ),
                    },
                    "attempt_ledger": {
                        "schema": "dai.same-call-attempt-ledger/v1",
                        "path": str(ledger_path),
                        "sha256": _sha256_file(ledger_path),
                        "started_events": 240,
                        "completed_events": 240,
                    },
                    "runtime_manifest": {"environment": environment},
                    "runs": runs,
                }
                artifact_path = outdir / f"{scenario_id}.json"
                artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
                artifact_paths.append(artifact_path)
                ledger_paths.append(ledger_path)

            command = [
                sys.executable,
                str(script_path),
                str(outdir),
                config_sha,
                "a2-test-host",
                str(config_path),
            ]
            passed = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertIn("SAME_CALL_CONFIRMATION_A2_MATRIX_COMPLETE", passed.stdout)

            events = [
                json.loads(line)
                for line in ledger_paths[0].read_text(encoding="utf-8").splitlines()
            ]
            completed = next(event for event in events if event["event"] == "completed")
            completed["run_sha256"] = "0" * 64
            ledger_paths[0].write_text(
                "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )
            artifact = json.loads(artifact_paths[0].read_text(encoding="utf-8"))
            artifact["attempt_ledger"]["sha256"] = _sha256_file(ledger_paths[0])
            artifact_paths[0].write_text(json.dumps(artifact), encoding="utf-8")
            failed = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn(
                "ledger completion does not bind retained run",
                failed.stdout + failed.stderr,
            )

    def test_a2_messages_and_overwrite_paths_are_versioned(self):
        self.assertNotIn("protected A1 confirmation artifact", self.source)
        self.assertNotIn("started A1 confirmation", self.source)
        self.assertNotIn("completed A1 confirmation", self.source)
        self.assertNotIn("SAME_CALL_CONFIRMATION_A1_MATRIX_COMPLETE", self.source)
        self.assertIn("protected A2 confirmation artifact", self.source)
        self.assertIn("SAME_CALL_CONFIRMATION_A2_MATRIX_COMPLETE", self.source)

    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


if __name__ == "__main__":
    unittest.main()
