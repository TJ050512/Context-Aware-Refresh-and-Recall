import hashlib
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT = WORKSPACE / "scripts" / "build_same_call_confirmation_config_a2.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("a2_config_builder", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


class SameCallConfirmationA2BuilderTests(unittest.TestCase):
    def test_canonical_protocol_and_failure_report_are_hash_bound(self):
        self.assertEqual(
            MODULE._sha256(
                WORKSPACE / "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md"
            ),
            MODULE.A2_PROTOCOL_SHA256,
        )
        self.assertEqual(
            MODULE._sha256(
                WORKSPACE / "reports/same_call_a1_effect_blind_execution_failure.json"
            ),
            MODULE.A1_FAILURE_SHA256,
        )
        self.assertEqual(
            MODULE._sha256(
                WORKSPACE / "configs/same_call_implementation_freeze_a1.json"
            ),
            MODULE.A1_FREEZE_SHA256,
        )

    def test_registered_roots_follow_the_effect_blind_derivation(self):
        source = MODULE.A1_FAILURE_SHA256
        domain = "dai-same-call-confirmatory-a2-pid-reuse-correction"
        derived = []
        for index in range(10):
            digest = hashlib.sha256(
                f"{source}|{domain}|{index}".encode("utf-8")
            ).hexdigest()
            derived.append(100000 + (int(digest[:16], 16) % 900000))
        self.assertEqual(tuple(derived), MODULE.A2_ROOTS)
        self.assertTrue(set(MODULE.A2_ROOTS).isdisjoint(MODULE.A1_ROOTS))

    def test_help_exposes_all_external_hash_gates(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=WORKSPACE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        for option in (
            "--expected-a1-preflight-sha256",
            "--expected-a2-runner-sha256",
            "--expected-a2-analyzer-sha256",
            "--expected-a2-launcher-sha256",
            "--expected-a2-runner-test-sha256",
            "--expected-a2-analyzer-test-sha256",
            "--expected-a2-launcher-test-sha256",
        ):
            self.assertIn(option, completed.stdout)

    def test_exclusive_writer_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sealed.json"
            MODULE._write_exclusive(output, b"first\n")
            with self.assertRaises(FileExistsError):
                MODULE._write_exclusive(output, b"second\n")
            self.assertEqual(output.read_bytes(), b"first\n")

    def test_parser_rejects_missing_required_hashes(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.build_parser().parse_args([])

    def test_effect_blind_fixture_seals_all_three_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)

            def write(relative, payload):
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(payload, dict):
                    path.write_text(
                        json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                else:
                    path.write_text(payload, encoding="utf-8")
                return path

            helper = write(
                "helper.py",
                "def _capture_environment():\n    raise AssertionError('injected in test')\n"
                "def _environment_compatibility_projection(value):\n    return dict(value)\n",
            )
            helper_sha = MODULE._sha256(helper)
            artifact_names = set(MODULE.BEHAVIOR_KEYS) | {"legacy_replay_launcher"}
            records = {
                name: {"path": "helper.py", "sha256": helper_sha}
                for name in artifact_names
            }
            a1_freeze_path = write(
                "a1-freeze.json",
                {
                    "schema": "dai.same-call-implementation-freeze/a1",
                    "fresh_root_runs_observed": 0,
                    "fresh_effect_estimates_computed": 0,
                    "fresh_method_rankings_inspected": 0,
                    "file_artifacts": records,
                    "metadata_artifacts": {},
                    "scientific_contract_unchanged": {"total_runs": 960},
                },
            )
            preflight_path = write(
                "a1-preflight.json",
                {
                    "schema": "fixture",
                    "status": "complete",
                    "passed": True,
                    "audit": {"effect_inference_performed": False},
                },
            )
            preflight_sha = MODULE._sha256(preflight_path)
            environment = {"host": socket.gethostname(), "fingerprint": "fixture"}
            environment_path = write(
                "environment.json",
                {
                    "schema": "dai.same-call-environment-attestation/a1",
                    "status": "complete",
                    "fresh_root_runs_observed": 0,
                    "fresh_effect_estimates_computed": 0,
                    "environment": environment,
                },
            )
            environment_sha = MODULE._sha256(environment_path)
            frozen = {
                name: {
                    "path": record["path"],
                    "sha256": record["sha256"],
                    "verification": "file_sha256",
                }
                for name, record in records.items()
            }
            a1_config_path = write(
                "a1-config.json",
                {
                    "schema": "dai.same-call-confirmation/a1",
                    "status": "frozen",
                    "artifact_config_sha256_field": "development_matrix_config_sha256",
                    "methods": list(MODULE.METHODS),
                    "root_seeds": list(MODULE.A1_ROOTS),
                    "workloads": list(MODULE.WORKLOADS),
                    "scenarios": [{"id": "fixture"}],
                    "protocol": {"total_runs": 960},
                    "required_frozen_artifacts": sorted(frozen),
                    "frozen_artifacts": frozen,
                    "required_preflight_evidence": ["a1_full_preflight"],
                    "preflight_evidence": {
                        "a1_full_preflight": {
                            "path": "a1-preflight.json",
                            "sha256": preflight_sha,
                            "passed": True,
                        }
                    },
                    "target_environment": {
                        "path": "environment.json",
                        "sha256": environment_sha,
                        "execution_host": socket.gethostname(),
                    },
                    "provenance": {
                        "fresh_root_runs_observed_at_freeze": 0,
                        "effect_inference_performed_before_config": False,
                    },
                },
            )
            a1_config_sha = MODULE._sha256(a1_config_path)
            failure_path = write(
                "failure.json",
                {
                    "schema": "dai.same-call-a1-effect-blind-execution-failure/v1",
                    "status": "a1_matrix_abandoned_before_effect_analysis",
                    "a1_protocol_sha256": MODULE.A1_PROTOCOL_SHA256,
                    "a1_config_sha256": a1_config_sha,
                    "audit": {
                        "runs": 960,
                        "unique_bare_pids": 959,
                        "unique_process_instances_host_pid_start_ns": 960,
                        "unique_run_uuids": 960,
                        "append_only_ledger_bindings_passed": True,
                    },
                },
            )
            protocol_path = write("protocol.md", "fixture protocol\n")
            a2_files = {}
            for name in ("runner", "analyzer", "launcher", "runner_test", "analyzer_test", "launcher_test"):
                a2_files[name] = write(f"{name}.py", f"# {name}\n")
            builder_test = write("builder_test.py", "# builder test\n")

            argv = [
                "--workspace", str(workspace),
                "--a1-final-config", str(a1_config_path),
                "--a1-implementation-freeze", str(a1_freeze_path),
                "--a1-preflight", str(preflight_path),
                "--expected-a1-preflight-sha256", preflight_sha,
                "--a2-protocol", str(protocol_path),
                "--a1-failure-report", str(failure_path),
                "--a2-runner", str(a2_files["runner"]),
                "--a2-analyzer", str(a2_files["analyzer"]),
                "--a2-launcher", str(a2_files["launcher"]),
                "--a2-runner-test", str(a2_files["runner_test"]),
                "--a2-analyzer-test", str(a2_files["analyzer_test"]),
                "--a2-launcher-test", str(a2_files["launcher_test"]),
                "--a2-builder-test", str(builder_test),
            ]
            for key in ("runner", "analyzer", "launcher", "runner_test", "analyzer_test", "launcher_test"):
                option = "--expected-a2-" + key.replace("_", "-") + "-sha256"
                argv.extend((option, MODULE._sha256(a2_files[key])))
            args = MODULE.build_parser().parse_args(argv)
            result = MODULE.seal(
                args,
                live_environment=environment,
                test_result={"passed": True, "tests_run": 1},
                fixed_protocol_sha256=MODULE._sha256(protocol_path),
                fixed_failure_sha256=MODULE._sha256(failure_path),
                fixed_a1_freeze_sha256=MODULE._sha256(a1_freeze_path),
            )
            for key in ("freeze_path", "preflight_path", "config_path"):
                self.assertTrue(Path(result[key]).is_file())
            config = json.loads(Path(result["config_path"]).read_text())
            self.assertEqual(config["root_seeds"], list(MODULE.A2_ROOTS))
            self.assertFalse(config["provenance"]["effect_inference_performed_before_config"])
            with self.assertRaises(FileExistsError):
                MODULE.seal(
                    args,
                    live_environment=environment,
                    test_result={"passed": True},
                    fixed_protocol_sha256=MODULE._sha256(protocol_path),
                    fixed_failure_sha256=MODULE._sha256(failure_path),
                    fixed_a1_freeze_sha256=MODULE._sha256(a1_freeze_path),
                )


if __name__ == "__main__":
    unittest.main()
