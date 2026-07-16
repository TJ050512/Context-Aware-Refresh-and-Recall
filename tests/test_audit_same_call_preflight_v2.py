import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest


WORKSPACE = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load(
    "audit_same_call_preflight_v2",
    WORKSPACE / "scripts" / "audit_same_call_preflight_v2.py",
)
V1TEST = _load(
    "test_audit_same_call_preflight_v1_helpers",
    WORKSPACE / "tests" / "test_audit_same_call_preflight_v1.py",
)


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SameCallPreflightV2Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.smoke_paths = []
        self.smoke = {}
        pid = 100
        for (map_id, agents), (label, _) in MODULE.EXPECTED_SCENARIOS.items():
            path, artifact = V1TEST._write_artifact(
                self.root,
                label,
                map_id,
                agents,
                MODULE.METHODS,
                MODULE.WORKLOADS,
                pid,
            )
            pid += 24
            artifact["runtime_manifest"]["sources"] = {
                "protocol": {
                    "path": "/workspace/EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md",
                    "sha256": MODULE.PREDECESSOR_PROTOCOL_SHA256,
                }
            }
            path.write_text(json.dumps(artifact, sort_keys=True))
            self.smoke_paths.append(path)
            self.smoke[label] = artifact

        self.archive_sources = {
            "claim_runner": b"synthetic frozen legacy claim runner\n",
            "validation_runner": b"synthetic frozen legacy validation runner\n",
            "config": b'{"synthetic":"frozen legacy config"}\n',
        }
        self.source_hashes = {name: _sha_bytes(value) for name, value in self.archive_sources.items()}
        self.source_hashes.update(
            checkpoint_file=MODULE.CHECKPOINT_SHA256,
            period_on_sim=MODULE.SIMULATOR_SHA256,
        )
        self.archive = self.write_archive(output_drift=True)
        self.environment_attestation = self.write_environment_attestation()
        self.legacy_paths = self.write_legacy_artifacts()
        self.replay_attestation = self.write_replay_attestation()

        self.repeat_a, _ = V1TEST._write_artifact(
            self.root,
            "repeat_a",
            "warehouse_small_narrow_kiva",
            218,
            MODULE.REPLAY_ARMS,
            ("stationary",),
            1000,
        )
        self.repeat_b, _ = V1TEST._write_artifact(
            self.root,
            "repeat_b",
            "warehouse_small_narrow_kiva",
            218,
            MODULE.REPLAY_ARMS,
            ("stationary",),
            1100,
        )
        self.suffix_base, _ = V1TEST._write_artifact(
            self.root,
            "future_suffix_base",
            "warehouse_small_narrow_kiva",
            218,
            MODULE.REPLAY_ARMS,
            ("stationary",),
            1200,
            cutoff=1400,
        )
        self.suffix_variant, _ = V1TEST._write_artifact(
            self.root,
            "future_suffix_variant",
            "warehouse_small_narrow_kiva",
            218,
            MODULE.REPLAY_ARMS,
            ("stationary",),
            1300,
            suffix_variant=1,
            cutoff=1400,
        )

    def tearDown(self):
        self.temp.cleanup()

    def write_archive(self, *, output_drift, input_drift=False):
        path = self.root / ("archive_drift.tgz" if output_drift else "archive_equal.tgz")
        with tarfile.open(path, "w:gz") as archive:
            for label, source in self.smoke.items():
                artifact = copy.deepcopy(source)
                artifact["methods"] = list(MODULE.COMMON_ARMS)
                artifact["runs"] = [
                    run for run in artifact["runs"] if run["method"] in MODULE.COMMON_ARMS
                ]
                artifact["development_matrix_config_sha256"] = self.source_hashes["config"]
                if output_drift:
                    for run in artifact["runs"]:
                        run["windows"][0]["reward"] += 0.25
                if input_drift:
                    artifact["runs"][0]["reset_causal_fingerprint"] = "altered-input"
                payload = json.dumps(artifact, sort_keys=True).encode()
                info = tarfile.TarInfo(
                    f"results/development_eventreserve/matrix_v1_{label}.json"
                )
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            for name, member_path in MODULE.ARCHIVE_MEMBER_PATHS.items():
                payload = self.archive_sources[name]
                info = tarfile.TarInfo(member_path)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return path

    def write_legacy_artifacts(self):
        target = self.root / "legacy" / "artifacts"
        target.mkdir(parents=True)
        paths = []
        process_id = 1000
        for label, smoke in self.smoke.items():
            runs = [
                copy.deepcopy(run)
                for run in smoke["runs"]
                if run["method"] in MODULE.COMMON_ARMS
            ]
            arm_executions = []
            for index, run in enumerate(runs):
                identities = {}
                for role in ("raw_arm", "log", "spec"):
                    bound = target / f"{label}_{run['workload']}_{run['method']}.{role}"
                    bound.write_text(f"{label}:{run['workload']}:{run['method']}:{role}\n")
                    identities[f"{role}_path"] = str(bound)
                    identities[f"{role}_sha256"] = _sha_file(bound)
                arm_executions.append(
                    {
                        "method": run["method"],
                        "workload": run["workload"],
                        **identities,
                        "command_argv": ["python", "wrapper.py"],
                        "execution": {
                            "host": "test-host",
                            "pid": process_id,
                            "boot_id": "synthetic-boot",
                            "process_start_ticks": 5000 + process_id,
                        },
                    }
                )
                process_id += 1
            artifact = {
                "schema": MODULE.LEGACY_CURRENT_ARTIFACT_SCHEMA,
                "status": "complete",
                "evidence_class": "engineering_compatibility_only_no_effect_inference",
                "root_seed": 17,
                "scenario": label,
                "agents": smoke["protocol"]["agents"],
                "map_path": smoke["map_path"],
                "map_sha256": smoke["map_sha256"],
                "common_methods": list(MODULE.COMMON_ARMS),
                "workloads": list(MODULE.WORKLOADS),
                "common_arm_run_count": 9,
                "fresh_process_per_arm": True,
                "environment_attestation_sha256": _sha_file(self.environment_attestation),
                "protocol_identity": self.protocol_record(),
                "run_protocol": {
                    "warmup_time": 200,
                    "scored_horizon": 2000,
                    "decision_window": 20,
                    "release_interval_per_agent": 110,
                    "guard_suffix_tasks_per_agent": 4,
                    "sigma": 0.75,
                    "context_match_threshold": 0.05,
                    "context_recall_margin": 0.02,
                    "context_min_score": 0.10,
                    "context_min_gap": 6,
                    "context_maintenance_age": 25,
                    "context_maintenance_stability": 0.20,
                    "timing_evidence_valid": False,
                },
                "arm_executions": arm_executions,
                "runs": runs,
            }
            path = target / f"{label}.json"
            path.write_text(json.dumps(artifact, sort_keys=True))
            paths.append(path)
        return paths

    def source_records(self):
        return {
            name: {
                "path": f"/workspace/{name}",
                "sha256": sha,
                "expected_sha256": sha,
            }
            for name, sha in self.source_hashes.items()
        }

    def protocol_record(self):
        return {
            "path": f"/workspace/{MODULE.AMENDMENT_A1_PROTOCOL_BASENAME}",
            "sha256": MODULE.AMENDMENT_A1_PROTOCOL_SHA256,
            "expected_sha256": MODULE.AMENDMENT_A1_PROTOCOL_SHA256,
        }

    def map_records(self):
        hashes = sorted({value[1] for value in MODULE.EXPECTED_SCENARIOS.values()})
        return {
            "narrow": {
                "path": "/workspace/narrow.map",
                "sha256": hashes[1],
                "expected_sha256": hashes[1],
            },
            "regular": {
                "path": "/workspace/regular.map",
                "sha256": hashes[0],
                "expected_sha256": hashes[0],
            },
        }

    def write_environment_attestation(self):
        path = self.root / "same_call_environment_attestation_a1.json"
        value = {
            "schema": MODULE.ENVIRONMENT_ATTESTATION_SCHEMA,
            "status": "complete",
            "created_before_legacy_replay": True,
            "fresh_root_runs_observed": 0,
            "fresh_effect_estimates_computed": 0,
            "environment": {
                "host": "test-host",
                "host_instance_fingerprint_sha256": "a" * 64,
            },
            "protocol": self.protocol_record(),
            "sources": self.source_records(),
            "maps": self.map_records(),
            "launchers": {
                "legacy_replay": {"path": "replay.sh", "sha256": "b" * 64},
                "legacy_arm_wrapper": {"path": "wrapper.py", "sha256": "c" * 64},
            },
            "thread_contract": {
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
                "VECLIB_MAXIMUM_THREADS": "1",
            },
        }
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def write_replay_attestation(self):
        path = self.root / "replay_attestation.json"
        environment_sha = _sha_file(self.environment_attestation)
        ledger_path = self.root / "legacy_attempts.jsonl"
        events = []
        previous = None
        sequence = 0
        pid = 2000
        for label in sorted(self.smoke):
            for workload in MODULE.WORKLOADS:
                for method in MODULE.COMMON_ARMS:
                    for kind in ("started", "completed"):
                        sequence += 1
                        event = {
                            "schema": MODULE.LEGACY_LEDGER_EVENT_SCHEMA,
                            "sequence": sequence,
                            "recorded_utc": "2026-07-14T00:00:00Z",
                            "previous_event_sha256": previous,
                            "event": kind,
                            "label": label,
                            "workload": workload,
                            "method": method,
                            "pid": pid,
                        }
                        if kind == "completed":
                            event.update(
                                boot_id="synthetic-boot",
                                process_start_ticks=10_000 + pid,
                                returncode=0,
                            )
                        event["event_sha256"] = MODULE.V1._strict_sha(event)
                        previous = event["event_sha256"]
                        events.append(event)
                    pid += 1
        ledger_path.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
        artifacts = []
        for artifact_path in self.legacy_paths:
            artifacts.append(
                {
                    "label": artifact_path.stem,
                    "path": f"results/same_call_legacy_replay_a1/artifacts/{artifact_path.name}",
                    "sha256": _sha_file(artifact_path),
                    "size_bytes": artifact_path.stat().st_size,
                }
            )
        value = {
            "schema": MODULE.ATTESTATION_SCHEMA,
            "status": "complete",
            "root_seed": 17,
            "environment": {
                "host": "test-host",
                "host_instance_fingerprint_sha256": "a" * 64,
            },
            "protocol": self.protocol_record(),
            "common_methods": list(MODULE.COMMON_ARMS),
            "common_arm_run_count": 36,
            "raw_legacy_run_count": 36,
            "fresh_process_per_arm": True,
            "sources": self.source_records(),
            "maps": self.map_records(),
            "artifacts": artifacts,
            "ledger": {
                "path": str(ledger_path),
                "sha256": _sha_file(ledger_path),
                "schema": MODULE.LEGACY_LEDGER_EVENT_SCHEMA,
                "event_count": 72,
                "started_events": 36,
                "completed_events": 36,
                "failed_events": 0,
                "unique_process_count": 36,
                "unique_process_instance_count": 36,
                "unique_arm_count": 36,
                "matched_start_complete_arms": 36,
                "final_event_hash": previous,
            },
            "environment_attestation_sha256": environment_sha,
            "environment_attestation": {
                "path": f"reports/{self.environment_attestation.name}",
                "sha256": environment_sha,
            },
        }
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def reattest_artifacts(self):
        value = json.loads(self.replay_attestation.read_text())
        by_label = {path.stem: path for path in self.legacy_paths}
        for record in value["artifacts"]:
            path = by_label[record["label"]]
            record["sha256"] = _sha_file(path)
            record["size_bytes"] = path.stat().st_size
        self.replay_attestation.write_text(json.dumps(value, sort_keys=True))

    def run_full(self, **overrides):
        args = {
            "smoke_artifacts": self.smoke_paths,
            "archived_evidence": self.archive,
            "legacy_current_artifacts": self.legacy_paths,
            "legacy_current_attestation": self.replay_attestation,
            "environment_attestation": self.environment_attestation,
            "repeat_a": self.repeat_a,
            "repeat_b": self.repeat_b,
            "future_suffix_base": self.suffix_base,
            "future_suffix_variant": self.suffix_variant,
            "expected_archive_sha256": None,
            "expected_legacy_source_sha256": None,
        }
        args.update(overrides)
        return MODULE.run_audit(**args)


class SameCallPreflightV2PassTests(SameCallPreflightV2Fixture):
    def test_cross_instance_output_zero_of_36_is_non_gating(self):
        result = self.run_full()
        diagnostic = result["audit"]["archived_cross_instance"][
            "cross_instance_output_diagnostic"
        ]
        self.assertTrue(result["passed"])
        self.assertEqual(diagnostic["bitwise_equal_on_legacy_projection"], 0)
        self.assertEqual(diagnostic["bitwise_different_on_legacy_projection"], 36)
        self.assertFalse(diagnostic["used_as_gate"])
        self.assertFalse(diagnostic["used_for_effect"])
        self.assertEqual(
            result["audit"]["current_host_legacy_new_equivalence"]["comparisons"],
            36,
        )

    def test_cross_instance_output_equality_also_does_not_control_gate(self):
        equal_archive = self.write_archive(output_drift=False)
        result = self.run_full(archived_evidence=equal_archive)
        diagnostic = result["audit"]["archived_cross_instance"][
            "cross_instance_output_diagnostic"
        ]
        self.assertTrue(result["passed"])
        self.assertEqual(diagnostic["bitwise_equal_on_legacy_projection"], 36)
        self.assertFalse(diagnostic["used_as_gate"])

    def test_report_contains_no_effect_estimate(self):
        result = self.run_full()
        rendered = json.dumps(result, sort_keys=True)
        self.assertFalse(result["audit"]["effect_inference_performed"])
        self.assertNotIn("mean_throughput", rendered)
        self.assertNotIn("relative_effect", rendered)
        self.assertNotIn("p_value", rendered)


class SameCallPreflightV2FailureTests(SameCallPreflightV2Fixture):
    def test_archived_input_drift_is_a_hard_failure(self):
        archive = self.write_archive(output_drift=True, input_drift=True)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "archive registered input"):
            self.run_full(archived_evidence=archive)

    def test_archived_source_mismatch_is_a_hard_failure(self):
        replay = json.loads(self.replay_attestation.read_text())
        replay["sources"]["claim_runner"]["sha256"] = "d" * 64
        replay["sources"]["claim_runner"]["expected_sha256"] = "d" * 64
        self.replay_attestation.write_text(json.dumps(replay, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "archive/current legacy source identity"):
            self.run_full()

    def test_current_host_legacy_output_drift_is_a_hard_failure(self):
        path = self.legacy_paths[0]
        artifact = json.loads(path.read_text())
        artifact["runs"][0]["windows"][5]["reward"] += 1
        path.write_text(json.dumps(artifact, sort_keys=True))
        self.reattest_artifacts()
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "current-host legacy/new bitwise"):
            self.run_full()

    def test_legacy_artifact_hash_mismatch_is_rejected(self):
        replay = json.loads(self.replay_attestation.read_text())
        replay["artifacts"][0]["sha256"] = "e" * 64
        self.replay_attestation.write_text(json.dumps(replay, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "attested artifact.*sha256"):
            self.run_full()

    def test_host_mismatch_is_rejected(self):
        replay = json.loads(self.replay_attestation.read_text())
        replay["environment"]["host"] = "another-host"
        self.replay_attestation.write_text(json.dumps(replay, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "current host"):
            self.run_full()

    def test_environment_digest_mismatch_is_rejected(self):
        replay = json.loads(self.replay_attestation.read_text())
        replay["environment_attestation_sha256"] = "f" * 64
        self.replay_attestation.write_text(json.dumps(replay, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "replay/environment attestation digest"):
            self.run_full()

    def test_predecessor_protocol_mismatch_in_smoke_is_rejected(self):
        path = self.smoke_paths[0]
        artifact = json.loads(path.read_text())
        artifact["runtime_manifest"]["sources"]["protocol"]["sha256"] = "0" * 64
        path.write_text(json.dumps(artifact, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "predecessor protocol"):
            self.run_full()

    def test_a1_protocol_mismatch_in_attestation_is_rejected(self):
        replay = json.loads(self.replay_attestation.read_text())
        replay["protocol"]["sha256"] = "1" * 64
        self.replay_attestation.write_text(json.dumps(replay, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "legacy A1 protocol"):
            self.run_full()

    def test_thread_contract_mismatch_is_rejected(self):
        environment = json.loads(self.environment_attestation.read_text())
        environment["thread_contract"]["OMP_NUM_THREADS"] = "2"
        self.environment_attestation.write_text(json.dumps(environment, sort_keys=True))
        replay = json.loads(self.replay_attestation.read_text())
        digest = _sha_file(self.environment_attestation)
        replay["environment_attestation_sha256"] = digest
        replay["environment_attestation"]["sha256"] = digest
        self.replay_attestation.write_text(json.dumps(replay, sort_keys=True))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "thread contract"):
            self.run_full()

    def test_repeat_drift_is_rejected(self):
        artifact = json.loads(self.repeat_b.read_text())
        artifact["runs"][0]["windows"][5]["reward"] += 1
        fixture = V1TEST.SameCallPreflightFixture
        fixture.rewrite_ledger(self, self.repeat_b, artifact)
        with self.assertRaisesRegex(MODULE.V1.PreflightAuditError, "repeatability"):
            self.run_full()

    def test_future_suffix_pre_cutoff_drift_is_rejected(self):
        artifact = json.loads(self.suffix_variant.read_text())
        artifact["runs"][0]["windows"][5]["guidance_sha256"] = "changed-too-early"
        fixture = V1TEST.SameCallPreflightFixture
        fixture.rewrite_ledger(self, self.suffix_variant, artifact)
        with self.assertRaisesRegex(MODULE.V1.PreflightAuditError, "pre-cutoff windows"):
            self.run_full()


if __name__ == "__main__":
    unittest.main()
