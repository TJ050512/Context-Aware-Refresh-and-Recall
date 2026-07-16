from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPTURE = load_module(
    "test_capture_same_call_environment_b",
    "scripts/capture_same_call_environment_b.py",
)
BUILD = load_module(
    "test_build_same_call_confirmation_config_b",
    "scripts/build_same_call_confirmation_config_b.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root: Path):
        self.workspace = root
        self.protocol = self.write("EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-15_B.md", b"protocol-b\n")
        self.capture_script = self.write("scripts/capture_fixture.py", b"capture\n")
        self.builder_script = self.write("scripts/builder_fixture.py", b"builder\n")
        self.runner = self.write("scripts/runner_b.py", b"runner\n")
        self.analyzer = self.write("scripts/analyzer_b.py", b"analyzer\n")
        self.launcher = self.write("scripts/launcher_b.sh", b"launcher\n")
        self.test_file = self.write("tests/test_b.py", b"test\n")
        self.helper = self.write("scripts/environment_helper.py", b"helper\n")
        self.v1 = self.write("scripts/v1.py", b"v1\n")
        self.source = self.write("src/source.py", b"source\n")
        self.preflight_a1 = self.write_json(
            "reports/preflight_a1.json", {"status": "complete", "passed": True}
        )
        self.unit_preflight = self.write_json(
            "reports/unit_preflight.json", {"status": "complete", "passed": True}
        )
        self.backbone_paths = {
            "period_on_sim": "external/period_on_sim.so",
            "checkpoint_file": "external/checkpoint.json",
            "narrow_map": "external/narrow.map",
            "regular_map": "external/regular.map",
        }
        self.backbone_files = {
            "period_on_sim": self.write(self.backbone_paths["period_on_sim"], b"simulator\n"),
            "checkpoint_file": self.write(self.backbone_paths["checkpoint_file"], b"checkpoint\n"),
            "narrow_map": self.write(self.backbone_paths["narrow_map"], b"narrow\n"),
            "regular_map": self.write(self.backbone_paths["regular_map"], b"regular\n"),
        }
        self.backbone_sha = {label: sha(path) for label, path in self.backbone_files.items()}
        self.backbone_sha["checkpoint_params"] = "a" * 64
        self.environment = {
            "host": "fixture-host",
            "host_instance_fingerprint_sha256": "b" * 64,
            "thread_environment": {name: "1" for name in CAPTURE.THREAD_ENV},
            "gpu_inventory": {"returncode": 0, "output": "0, fixture-gpu"},
            "libraries": {"python": {"version": "fixture"}},
        }
        self.a2_config = self._write_a2_config()
        self.protocol_sha = sha(self.protocol)
        self.a2_config_sha = sha(self.a2_config)
        self.zero_paths = (
            Path("results/same_call_confirmation_b"),
            Path("logs/same_call_confirmation_b"),
            Path("configs/same_call_confirmation_b.json"),
            Path("configs/same_call_implementation_freeze_b.json"),
            Path("reports/same_call_confirmation_b_analysis.json"),
            Path("reports/same_call_confirmation_b_analysis.md"),
        )

    def write(self, relative: str, data: bytes) -> Path:
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def write_json(self, relative: str, value) -> Path:
        return self.write(
            relative,
            (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    def _write_a2_config(self) -> Path:
        frozen = {
            "legacy_replay_launcher": {
                "path": "scripts/environment_helper.py",
                "sha256": sha(self.helper),
                "verification": "file_sha256",
            },
            "validation_runner": {
                "path": "scripts/v1.py",
                "sha256": sha(self.v1),
                "verification": "file_sha256",
            },
            "source": {
                "path": "src/source.py",
                "sha256": sha(self.source),
                "verification": "file_sha256",
            },
            "period_on_sim": {
                "sha256": self.backbone_sha["period_on_sim"],
                "verification": "artifact_metadata",
            },
            "checkpoint_file": {
                "sha256": self.backbone_sha["checkpoint_file"],
                "verification": "artifact_metadata",
            },
            "checkpoint_params": {
                "sha256": self.backbone_sha["checkpoint_params"],
                "verification": "artifact_metadata",
            },
            "narrow_map": {
                "sha256": self.backbone_sha["narrow_map"],
                "verification": "artifact_metadata",
            },
            "regular_map": {
                "sha256": self.backbone_sha["regular_map"],
                "verification": "artifact_metadata",
            },
        }
        config = {
            "schema": "dai.same-call-confirmation/a2",
            "artifact_config_sha256_field": "development_matrix_config_sha256",
            "methods": list(CAPTURE.METHODS),
            "workloads": list(CAPTURE.WORKLOADS),
            "root_seeds": list(CAPTURE.A2_ROOTS),
            "root_derivation": {
                "source_sha256": CAPTURE.ROOT_SOURCE_SHA256,
                "domain": "fixture-a2",
            },
            "protocol": {
                "bootstrap_samples": 10000,
                "bootstrap_seed": 20260715,
                "cells_per_root_seed_per_method": 12,
                "decision_window": 20,
                "guard_suffix_tasks_per_agent": 4,
                "independent_inference_unit": "root_seed",
                "noninferiority_margin": 0.01,
                "release_interval_per_agent": 110,
                "scored_horizon": 2000,
                "total_runs": 960,
                "warmup_time": 200,
            },
            "scenarios": [
                {
                    "id": label,
                    "agents": agents,
                    "map_sha256": self.backbone_sha[map_label],
                }
                for label, agents, map_label in CAPTURE.SCENARIOS
            ],
            "frozen_artifacts": frozen,
            "required_frozen_artifacts": sorted(frozen),
            "preflight_evidence": {
                label: {
                    "path": "reports/preflight_a1.json",
                    "sha256": sha(self.preflight_a1),
                    "passed": True,
                }
                for label in (
                    "engineering_smoke",
                    "common_arm_reproducibility",
                    "repeated_arm_replay",
                    "future_suffix_metamorphic",
                    "rng_isolation",
                )
            },
        }
        config["preflight_evidence"]["unit_suite"] = {
            "path": "reports/unit_preflight.json",
            "sha256": sha(self.unit_preflight),
            "passed": True,
        }
        config["required_preflight_evidence"] = sorted(config["preflight_evidence"])
        path = self.workspace / "configs/same_call_confirmation_a2.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def projection(self, environment):
        return {
            "host": environment.get("host"),
            "host_instance_fingerprint_sha256": environment.get(
                "host_instance_fingerprint_sha256"
            ),
            "thread_environment": environment.get("thread_environment"),
            "libraries": environment.get("libraries"),
        }

    def b_specs(self):
        return [
            f"runner_b=scripts/runner_b.py={sha(self.runner)}",
            f"analyzer_b=scripts/analyzer_b.py={sha(self.analyzer)}",
            f"launcher_b=scripts/launcher_b.sh={sha(self.launcher)}",
            f"builder_b=scripts/builder_fixture.py={sha(self.builder_script)}",
            f"test_control_plane_b=tests/test_b.py={sha(self.test_file)}",
        ]

    def capture(self):
        output = self.workspace / "reports/same_call_environment_attestation_b.json"
        return CAPTURE.capture_attestation(
            workspace=self.workspace,
            output=output,
            a2_config_path=self.a2_config,
            protocol_path=self.protocol,
            self_path=self.capture_script,
            expected_self_sha256=sha(self.capture_script),
            b_artifact_specs=self.b_specs(),
            zero_paths=self.zero_paths,
            fixed_protocol_sha256=self.protocol_sha,
            fixed_a2_config_sha256=self.a2_config_sha,
            expected_v1_sha256=sha(self.v1),
            expected_backbone_sha256=self.backbone_sha,
            backbone_paths=self.backbone_paths,
            checkpoint_params_hasher=lambda workspace, checkpoint: self.backbone_sha[
                "checkpoint_params"
            ],
            environment_capture=lambda: dict(self.environment),
            environment_projection=self.projection,
            live_hostname="fixture-host",
        )

    def build(self, *, environment=None, hostname="fixture-host"):
        output = self.workspace / "configs/same_call_confirmation_b.json"
        freeze_output = self.workspace / "configs/same_call_implementation_freeze_b.json"
        attestation = self.workspace / "reports/same_call_environment_attestation_b.json"
        smoke = self.workspace / "reports/same_call_smoke_b.json"
        if not smoke.exists():
            self.write_json(
                "reports/same_call_smoke_b.json",
                {
                    "schema": "dai.same-call-engineering-smoke/b",
                    "status": "complete",
                    "passed": True,
                    "split": "development",
                    "root_seeds": [17],
                    "jobs_per_scenario": 30,
                    "b_root_runs_observed": 0,
                    "effect_inference_performed": False,
                },
            )
        return BUILD.build_config(
            workspace=self.workspace,
            output=output,
            freeze_output=freeze_output,
            attestation_path=attestation,
            expected_attestation_sha256=sha(attestation),
            smoke_path=smoke,
            expected_smoke_sha256=sha(smoke),
            jobs_per_scenario=30,
            a2_config_path=self.a2_config,
            protocol_path=self.protocol,
            self_path=self.builder_script,
            # Exercise the practical CLI path: the builder verifies itself
            # against the digest already sealed in the host attestation.
            expected_self_sha256=None,
            formal_outcome_paths=(
                self.zero_paths[0],
                self.zero_paths[1],
                self.zero_paths[4],
                self.zero_paths[5],
            ),
            fixed_protocol_sha256=self.protocol_sha,
            fixed_a2_config_sha256=self.a2_config_sha,
            expected_v1_sha256=sha(self.v1),
            expected_backbone_sha256=self.backbone_sha,
            backbone_paths=self.backbone_paths,
            checkpoint_params_hasher=lambda workspace, checkpoint: self.backbone_sha[
                "checkpoint_params"
            ],
            environment_capture=lambda: dict(environment or self.environment),
            environment_projection=self.projection,
            live_hostname=hostname,
        )


class CaptureEnvironmentBTests(unittest.TestCase):
    def test_capture_is_complete_zero_outcome_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            result = fixture.capture()
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], CAPTURE.ATTESTATION_SCHEMA)
            self.assertEqual(payload["b_fresh_root_runs_observed"], 0)
            self.assertFalse(payload["public_preregistration"])
            self.assertEqual(payload["experiment_b_contract"]["root_seeds"], list(CAPTURE.B_ROOTS))
            self.assertEqual(payload["experiment_b_contract"]["root_count"], 40)
            self.assertTrue(
                payload["experiment_b_contract"]["roots_disjoint_from_a1_and_a2"]
            )
            self.assertEqual(
                payload["experiment_b_contract"]["runs_per_scenario"], 960
            )
            self.assertEqual(
                payload["experiment_b_contract"][
                    "attempt_ledger_events_per_scenario"
                ],
                1920,
            )
            self.assertEqual(payload["experiment_b_contract"]["total_runs"], 3840)
            self.assertEqual(payload["execution_host"], "fixture-host")
            self.assertIn("environment_compatibility_projection", payload)
            with self.assertRaises(FileExistsError):
                fixture.capture()

    def test_capture_rejects_existing_formal_path(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            (fixture.workspace / fixture.zero_paths[0]).mkdir(parents=True)
            with self.assertRaisesRegex(FileExistsError, "zero B runs"):
                fixture.capture()


class BuildConfigBTests(unittest.TestCase):
    def test_builder_emits_40_root_3840_run_standalone_config(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.capture()
            result = fixture.build()
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], BUILD.CONFIG_SCHEMA)
            self.assertEqual(payload["execution_host"], "fixture-host")
            self.assertEqual(payload["root_seeds"], list(CAPTURE.B_ROOTS))
            self.assertEqual(payload["protocol"]["total_runs"], 3840)
            self.assertEqual(payload["protocol"]["runs_per_scenario"], 960)
            self.assertEqual(
                payload["protocol"]["attempt_ledger_events_per_scenario"], 1920
            )
            self.assertEqual(payload["execution"]["jobs_per_scenario"], 30)
            self.assertEqual(payload["execution"]["total_runs"], 3840)
            self.assertEqual(payload["process_identity_gate"]["unique_run_uuids_required"], 3840)
            self.assertTrue(payload["standalone_replication"])
            self.assertFalse(payload["primary_analysis_pools_with_a1_or_a2"])
            self.assertFalse(payload["public_preregistration"])
            freeze = json.loads(
                (fixture.workspace / "configs/same_call_implementation_freeze_b.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(freeze["target_environment"], payload["target_environment"])
            self.assertEqual(freeze["file_artifacts"], payload["frozen_artifacts"])
            self.assertEqual(freeze["execution"], payload["execution"])
            with self.assertRaises(FileExistsError):
                fixture.build()

    def test_builder_rejects_live_host_drift_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.capture()
            changed = dict(fixture.environment)
            changed["host_instance_fingerprint_sha256"] = "c" * 64
            with self.assertRaisesRegex(RuntimeError, "live host/runtime"):
                fixture.build(environment=changed)
            self.assertFalse((fixture.workspace / fixture.zero_paths[2]).exists())

    def test_builder_rejects_source_drift_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.capture()
            fixture.source.write_bytes(b"tampered\n")
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                fixture.build()
            self.assertFalse((fixture.workspace / fixture.zero_paths[2]).exists())


if __name__ == "__main__":
    unittest.main()
