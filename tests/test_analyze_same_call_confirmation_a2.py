import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load(
    "analyze_same_call_confirmation_a2",
    ROOT / "scripts" / "analyze_same_call_confirmation_a2.py",
)
V1TEST = _load(
    "test_analyze_same_call_confirmation_v1_fixture",
    ROOT / "tests" / "test_analyze_same_call_confirmation_v1.py",
)


class SameCallConfirmationA2ProcessIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the comprehensive synthetic v1 fixture generator with only
        # the A2 replacement vector substituted before it emits any artifact.
        V1TEST.MODULE.ROOTS = MODULE.A2_ROOTS
        cls.fixture = V1TEST.SameCallConfirmationAnalyzerTests
        cls.fixture.setUpClass()
        cls.artifacts = cls.fixture.artifacts
        cls.config_path = cls.fixture.config_path
        cls.ledger_temp = tempfile.TemporaryDirectory()
        cls.ledger_root = Path(cls.ledger_temp.name)
        cls.audit_counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.ledger_temp.cleanup()
        cls.fixture.tearDownClass()

    def _audit_only(self, artifacts):
        self.__class__.audit_counter += 1
        artifacts = copy.deepcopy(artifacts)
        for index, artifact in enumerate(artifacts):
            scenario_id = next(
                scenario
                for scenario, values in MODULE.V1.SCENARIOS.items()
                if values["map_sha256"] == artifact["map_sha256"]
                and values["agents"] == artifact["protocol"]["agents"]
            )
            ledger_path = self.ledger_root / (
                f"a2-ledger-{self.audit_counter}-{index}.jsonl"
            )
            artifact["attempt_ledger"] = V1TEST._write_attempt_ledger(
                ledger_path,
                artifact["runs"],
                MODULE.V1.SCENARIOS[scenario_id]["agents"],
            )
        config, config_sha, resolved = MODULE.V1.load_config(self.config_path)
        _, expected_hashes = MODULE.V1._verify_frozen_artifacts(config, resolved)
        return MODULE._normalize_and_audit(
            artifacts, config, config_sha, expected_hashes
        )

    def test_a2_protocol_and_replacement_roots_are_frozen(self):
        self.assertEqual(MODULE.ROOTS, MODULE.A2_ROOTS)
        self.assertEqual(MODULE.V1.ROOTS, MODULE.A2_ROOTS)
        self.assertEqual(
            MODULE._sha256_file(MODULE.A2_PROTOCOL_PATH),
            MODULE.A2_PROTOCOL_SHA256,
        )
        self.assertEqual(
            MODULE.A2_ROOTS,
            (
                691817,
                376110,
                263001,
                293231,
                296805,
                274330,
                997942,
                319782,
                807287,
                326454,
            ),
        )

    def test_same_pid_with_different_start_and_uuid_passes(self):
        artifacts = copy.deepcopy(self.artifacts)
        source = artifacts[0]["runs"][0]
        target = artifacts[1]["runs"][0]
        self.assertNotEqual(source["execution_process_start_ns"], target["execution_process_start_ns"])
        self.assertNotEqual(source["run_uuid"], target["run_uuid"])
        target["execution_process_id"] = source["execution_process_id"]

        runs, failures, totals = self._audit_only(artifacts)

        self.assertEqual(len(runs), MODULE.V1.TOTAL_RUNS)
        self.assertFalse(
            any(item.get("category") == "fresh_process" for item in failures),
            failures,
        )
        self.assertEqual(totals["unique_bare_pids"], MODULE.V1.TOTAL_RUNS - 1)
        self.assertEqual(totals["unique_process_instances"], MODULE.V1.TOTAL_RUNS)
        self.assertEqual(totals["unique_run_uuids"], MODULE.V1.TOTAL_RUNS)
        self.assertEqual(totals["bare_pid_reuse_count"], 1)
        self.assertFalse(totals["bare_pid_uniqueness_is_gate"])
        self.assertTrue(totals["process_instance_uniqueness_is_gate"])

    def test_repeated_host_pid_start_tuple_fails(self):
        artifacts = copy.deepcopy(self.artifacts)
        source = artifacts[0]["runs"][0]
        target = artifacts[1]["runs"][0]
        target["execution_host"] = source["execution_host"]
        target["execution_process_id"] = source["execution_process_id"]
        target["execution_process_start_ns"] = source["execution_process_start_ns"]
        self.assertNotEqual(source["run_uuid"], target["run_uuid"])

        _, failures, totals = self._audit_only(artifacts)

        checks = {
            item.get("check")
            for item in failures
            if item.get("category") == "fresh_process"
        }
        self.assertIn(MODULE.PROCESS_INSTANCE_CHECK, checks)
        self.assertNotIn(MODULE.BARE_PID_FAILURE["check"], checks)
        self.assertEqual(totals["unique_process_instances"], MODULE.V1.TOTAL_RUNS - 1)

    def test_repeated_run_uuid_fails(self):
        artifacts = copy.deepcopy(self.artifacts)
        source = artifacts[0]["runs"][0]
        target = artifacts[1]["runs"][0]
        self.assertNotEqual(
            (source["execution_host"], source["execution_process_id"], source["execution_process_start_ns"]),
            (target["execution_host"], target["execution_process_id"], target["execution_process_start_ns"]),
        )
        target["run_uuid"] = source["run_uuid"]

        _, failures, totals = self._audit_only(artifacts)

        checks = {
            item.get("check")
            for item in failures
            if item.get("category") == "fresh_process"
        }
        self.assertIn(MODULE.RUN_UUID_CHECK, checks)
        self.assertEqual(totals["unique_process_instances"], MODULE.V1.TOTAL_RUNS)
        self.assertEqual(totals["unique_run_uuids"], MODULE.V1.TOTAL_RUNS - 1)


if __name__ == "__main__":
    unittest.main()
