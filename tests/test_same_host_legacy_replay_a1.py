from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


arm = _load("legacy_arm_a1_test", ROOT / "scripts/run_same_host_legacy_arm_a1.py")
replay = _load(
    "legacy_replay_a1_test", ROOT / "scripts/run_same_host_legacy_replay_a1.py"
)


class LegacyArmWrapperTests(unittest.TestCase):
    def _spec(self, workspace: Path):
        return {
            "workspace": str(workspace.resolve()),
            "checkpoint": str(workspace / "checkpoint.json"),
            "checkpoint_sha256": replay.CHECKPOINT_FILE_SHA256,
            "checkpoint_params_sha256": replay.CHECKPOINT_PARAMS_SHA256,
            "split": "development",
            "map_path": str(workspace / "map.map"),
            "agents": 218,
            "warmup_time": 200,
            "horizon": 2000,
            "decision_window": 20,
            "release_interval": 110,
            "guard_suffix": 4,
            "sigma": 0.75,
            "pacing_slack": 2,
            "minimum_history": 4,
            "context_match_threshold": 0.05,
            "context_recall_margin": 0.02,
            "context_min_score": 0.10,
            "context_min_gap": 6,
            "context_maintenance_age": 25,
            "context_maintenance_stability": 0.20,
            "timing_evidence_valid": False,
            "seed": 17,
            "workload": "stationary",
            "method": "bootstrap_only",
        }

    def test_exact_frozen_spec_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            arm._validate_spec(self._spec(workspace), workspace)

    def test_spec_rejects_wrong_root_method_and_extra_field(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            for field, value in (
                ("seed", 18),
                ("method", "context_eventreserve_G5S6"),
                ("context_match_threshold", 0.10),
            ):
                spec = self._spec(workspace)
                spec[field] = value
                with self.assertRaises(ValueError):
                    arm._validate_spec(spec, workspace)
            spec = self._spec(workspace)
            spec["unregistered"] = 1
            with self.assertRaises(ValueError):
                arm._validate_spec(spec, workspace)


class LedgerTests(unittest.TestCase):
    def test_hash_chained_append_only_ledger_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.jsonl"
            path.touch()
            previous = None
            sequence = 0
            for pid in (101, 102):
                arm_fields = {
                    "label": f"scenario-{pid}",
                    "workload": "stationary",
                    "method": "bootstrap_only",
                }
                sequence += 1
                previous = replay._append_ledger_event(
                    path,
                    {"event": "started", "pid": pid, **arm_fields},
                    sequence,
                    previous,
                )
                sequence += 1
                previous = replay._append_ledger_event(
                    path,
                    {
                        "event": "completed",
                        "pid": pid,
                        "boot_id": "boot",
                        "process_start_ticks": pid * 10,
                        **arm_fields,
                    },
                    sequence,
                    previous,
                )
            summary = replay._validate_ledger(path)
            self.assertEqual(summary["started_events"], 2)
            self.assertEqual(summary["completed_events"], 2)
            self.assertEqual(summary["failed_events"], 0)
            self.assertEqual(summary["unique_process_count"], 2)
            self.assertEqual(summary["unique_process_instance_count"], 2)
            self.assertEqual(summary["unique_arm_count"], 2)
            self.assertEqual(summary["matched_start_complete_arms"], 2)
            self.assertEqual(summary["final_event_hash"], previous)

    def test_ledger_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.jsonl"
            path.touch()
            replay._append_ledger_event(
                path, {"event": "started", "pid": 1}, 1, None
            )
            event = json.loads(path.read_text(encoding="utf-8"))
            event["pid"] = 2
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                replay._validate_ledger(path)


class EnvironmentAttestationTests(unittest.TestCase):
    def _environment(self):
        return {
            "host": "host-a",
            "host_instance_fingerprint_sha256": "f" * 64,
            "uname": {"release": "kernel"},
            "platform": "linux",
            "architecture": ["64bit", "ELF"],
            "os_release": "ID=test",
            "glibc": ["glibc", "2.35"],
            "cpu": {
                "models": ["cpu"],
                "logical_count_os": 2,
                "flags": ["sse"],
                "cpuinfo_sha256": "volatile",
            },
            "gpu_inventory": {"output": "0, GPU, uuid, driver, vbios"},
            "compilers_and_native_runtime": {"gcc": "x"},
            "libraries": {"numpy": {"version": "1"}},
            "thread_environment": {name: "1" for name in replay.THREAD_ENV},
            "device_policy": {"cnn_inference_device": "cpu"},
            "rng_and_determinism_environment": {"PYTHONHASHSEED": None},
        }

    def test_volatile_cpuinfo_digest_is_not_a_host_mismatch(self):
        first = self._environment()
        second = self._environment()
        second["cpu"]["cpuinfo_sha256"] = "different-mhz-snapshot"
        self.assertEqual(
            replay._environment_compatibility_projection(first),
            replay._environment_compatibility_projection(second),
        )

    def test_existing_attestation_requires_static_and_runtime_identity(self):
        environment = self._environment()
        kwargs = {
            "protocol": {"sha256": "a"},
            "sources": {"claim_runner": {"sha256": "b"}},
            "maps": {"narrow": {"sha256": "c"}},
            "launchers": {"legacy_replay": {"sha256": "d"}},
            "additional_frozen_files": {},
            "thread_contract": {name: "1" for name in replay.THREAD_ENV},
            "execution_plan": {"common_arm_run_count": 36},
            "current_environment": environment,
        }
        attestation = {
            "schema": replay.ENVIRONMENT_SCHEMA,
            "status": "complete",
            "created_before_legacy_replay": True,
            "fresh_root_runs_observed": 0,
            "fresh_effect_estimates_computed": 0,
            "fresh_method_rankings_inspected": 0,
            "protocol": kwargs["protocol"],
            "sources": kwargs["sources"],
            "maps": kwargs["maps"],
            "launchers": kwargs["launchers"],
            "additional_frozen_files": {},
            "thread_contract": kwargs["thread_contract"],
            "execution_plan": kwargs["execution_plan"],
            "environment": environment,
        }
        replay._validate_existing_environment_attestation(attestation, **kwargs)
        changed = json.loads(json.dumps(attestation))
        changed["environment"]["host"] = "host-b"
        with self.assertRaises(RuntimeError):
            replay._validate_existing_environment_attestation(changed, **kwargs)


class ArtifactTests(unittest.TestCase):
    @staticmethod
    def _run(method: str, workload: str):
        paired = f"pair-{workload}"
        return {
            "method": method,
            "seed": 17,
            "map_id": "warehouse_small_narrow_kiva",
            "workload": workload,
            "num_task_finished": 100,
            "throughput_per_timestep": 0.05,
            "mandatory_bootstrap_calls": 1,
            "post_bootstrap_publication_count": 0,
            "publication_budget": 0,
            "budget_violation_count": 0,
            "generator_seconds": 0.1,
            "simulator_seconds": 1.0,
            "elapsed_seconds": 1.1,
            "manifest_id": paired,
            "reset_causal_fingerprint": paired,
            "task_tape_identity": {"sha": paired},
            "release_projection_fingerprint": paired,
            "distribution_update_fingerprint": paired,
            "safety": {"passed": True},
            "invariants": {"passed": True},
        }

    def test_four_way_contract_builds_nine_run_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            output_root = workspace / "results/replay"
            (output_root / "artifacts").mkdir(parents=True)
            arms = []
            pid = 100
            for workload in replay.WORKLOADS:
                for method in replay.COMMON_METHODS:
                    pid += 1
                    stem = f"{workload}-{method}"
                    raw_path = output_root / f"{stem}.raw.json"
                    log_path = output_root / f"{stem}.log"
                    spec_path = output_root / f"{stem}.spec.json"
                    raw_path.write_text("{}\n", encoding="utf-8")
                    log_path.write_text("ok\n", encoding="utf-8")
                    spec_path.write_text("{}\n", encoding="utf-8")
                    arms.append(
                        {
                            "raw": {
                                "run": self._run(method, workload),
                                "execution": {
                                    "boot_id": "boot",
                                    "pid": pid,
                                    "process_start_ticks": pid * 10,
                                },
                            },
                            "spec": {"method": method, "workload": workload},
                            "raw_path": raw_path,
                            "log_path": log_path,
                            "spec_path": spec_path,
                            "command": ["python", "wrapper"],
                        }
                    )
            identity, csv_identity = replay._write_scenario_artifact(
                workspace,
                output_root,
                "narrow_r020",
                "warehouse_small_narrow_kiva.map",
                218,
                arms,
                "e" * 64,
                {"path": "protocol.md", "sha256": "a" * 64},
            )
            artifact = json.loads(
                (workspace / identity["path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["schema"], replay.ARTIFACT_SCHEMA)
            self.assertEqual(artifact["common_arm_run_count"], 9)
            self.assertEqual(len(artifact["runs"]), 9)
            self.assertTrue(artifact["fresh_process_per_arm"])
            self.assertEqual(artifact["protocol_identity"]["sha256"], "a" * 64)
            self.assertEqual(artifact["run_protocol"]["scored_horizon"], 2000)
            self.assertTrue((workspace / csv_identity["path"]).is_file())

    def test_pairing_mismatch_is_rejected(self):
        runs = [
            self._run(method, workload)
            for workload in replay.WORKLOADS
            for method in replay.COMMON_METHODS
        ]
        runs[0]["release_projection_fingerprint"] = "wrong"
        with self.assertRaises(RuntimeError):
            replay._pairing_gate(runs)


if __name__ == "__main__":
    unittest.main()
