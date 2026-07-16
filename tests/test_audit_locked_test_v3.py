import copy
import importlib.util
import json
from pathlib import Path
import unittest


WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT = WORKSPACE / "scripts" / "audit_locked_test_v3.py"
SPEC = importlib.util.spec_from_file_location("audit_locked_test_v3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _run(seed, workload, method, map_id):
    paired = f"{seed}-{workload}"
    return {
        "seed": seed,
        "root_seed": seed,
        "workload": workload,
        "method": method,
        "map_id": map_id,
        "split": "locked_test",
        "evidence_class": "locked_test",
        "scored_horizon": 2000,
        "decision_window": 20,
        "window_count": 100,
        "timing_evidence_valid": False,
        "manifest_id": f"manifest-{paired}",
        "reset_causal_fingerprint": f"reset-{paired}",
        "release_projection_fingerprint": f"release-{paired}",
        "distribution_update_fingerprint": f"distribution-{paired}",
        "planner_timeouts": 0,
        "collisions": 0,
        "edge_swaps": 0,
        "invalid_moves": 0,
        "budget_violation_count": 0,
        "safety": {
            "passed": True,
            "collision_count": 0,
            "edge_swap_count": 0,
            "endpoint_mismatch_count": 0,
            "invalid_move_count": 0,
            "planner_timeout_count": 0,
            "route_trace_invalid_count": 0,
        },
        "invariants": {"passed": True},
        "budget": {
            "cap_satisfied": True,
            "generation_cap_satisfied": True,
            "budget_violation_attempts": 0,
        },
    }


def _artifact(label="warehouse_r020"):
    scenario = MODULE.EXPECTED_SCENARIOS[label]
    runs = [
        _run(seed, workload, method, scenario["map_id"])
        for seed in MODULE.LOCKED_SEEDS
        for workload in MODULE.WORKLOADS
        for method in MODULE.METHODS
    ]
    return {
        "schema": MODULE.ARTIFACT_SCHEMA,
        "status": "complete",
        "split": "locked_test",
        "evidence_class": "locked_test",
        "seeds": list(MODULE.LOCKED_SEEDS),
        "methods": list(MODULE.METHODS),
        "workloads": list(MODULE.WORKLOADS),
        "map_id": scenario["map_id"],
        "map_path": f"/maps/{scenario['map_file']}",
        "map_sha256": scenario["map_sha256"],
        "period_on_sim_sha256": MODULE.SIMULATOR_SHA256,
        "generator": {
            "file_sha256": MODULE.CHECKPOINT_SHA256,
            "params_sha256": MODULE.CHECKPOINT_PARAMS_SHA256,
        },
        "split_protocol": {
            "classification": "sealed_locked_test",
            "preregistered_seeds": list(MODULE.LOCKED_SEEDS),
        },
        "protocol": {
            "agents": scenario["agents"],
            "warmup_time": 200,
            "scored_horizon": 2000,
            "decision_window": 20,
            "num_scored_windows": 100,
            "eligible_post_bootstrap_decisions": 99,
            "b25_budget": 25,
            "release_interval_per_agent": 110,
            "guard_suffix_tasks_per_agent": 4,
            "sigma": 0.75,
            "jobs": 3,
            "exclusive_timing_declared": False,
            "timing_evidence_valid": False,
            "context_memory_B25": {
                "recall_threshold": 0.05,
                "recall_margin": 0.02,
                "absolute_score_gate": 0.10,
                "min_gap_windows": 6,
                "maintenance_age_windows": 25,
                "maintenance_stability_gate": 0.20,
            },
        },
        "runs": runs,
    }


def _validation_report(causal=False, context=True):
    return {
        "schema": MODULE.VALIDATION_ANALYSIS_SCHEMA,
        "evidence": {
            "source_evidence_class": "validation_v2",
            "fresh_validation_v2": True,
        },
        "audit": {"passed": True, "integrity_gate_passed": True},
        "design": {
            "n_root_seed_clusters": 10,
            "maps": 2,
            "densities": 2,
            "workloads": 3,
            "total_runs": 1560,
        },
        "preregistered_go_no_go": {
            "causal_quality_go": {"passed": causal},
            "context_validation_candidate": {"passed": context},
            "passed_any_candidate_path": causal or context,
        },
    }


class LockedProtocolPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads(
            (WORKSPACE / "configs" / "locked_test_protocol_v3.json").read_text()
        )
        cls.map_dir = (
            WORKSPACE
            / "external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
        )

    def test_protocol_and_repaired_maps_match_freeze(self):
        MODULE.validate_protocol(self.protocol)
        maps = MODULE.audit_maps(self.protocol, self.map_dir)
        self.assertEqual(maps["warehouse_60x100_kiva.map"]["free_cells"], 3686)
        self.assertEqual(maps["sortation_small_kiva.map"]["free_cells"], 1564)

    def test_validation_gate_requires_a_real_candidate_path(self):
        result = MODULE.audit_validation_gate(_validation_report())
        self.assertTrue(result["context_validation_candidate"])
        with self.assertRaisesRegex(MODULE.LockedAuditError, "neither predeclared"):
            MODULE.audit_validation_gate(_validation_report(False, False))


class LockedArtifactAuditTests(unittest.TestCase):
    def test_complete_synthetic_artifact_passes(self):
        result = MODULE.audit_artifact(_artifact(), "warehouse_r020")
        self.assertEqual(result["runs"], 1170)
        self.assertEqual(result["paired_cells"], 90)

    def test_missing_arm_is_rejected(self):
        artifact = _artifact()
        artifact["runs"].pop()
        with self.assertRaisesRegex(MODULE.LockedAuditError, "run count"):
            MODULE.audit_artifact(artifact, "warehouse_r020")

    def test_cross_method_pairing_mismatch_is_rejected(self):
        artifact = _artifact()
        artifact["runs"][0]["release_projection_fingerprint"] = "wrong"
        with self.assertRaisesRegex(MODULE.LockedAuditError, "pairing mismatch"):
            MODULE.audit_artifact(artifact, "warehouse_r020")

    def test_locked_protocol_parameters_are_exact(self):
        artifact = _artifact()
        artifact["protocol"]["release_interval_per_agent"] = 109
        with self.assertRaisesRegex(MODULE.LockedAuditError, "release_interval"):
            MODULE.audit_artifact(artifact, "warehouse_r020")


if __name__ == "__main__":
    unittest.main()
