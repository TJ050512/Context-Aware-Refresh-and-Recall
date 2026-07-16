import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analyze_exclusive_timing.py"
SPEC = importlib.util.spec_from_file_location("analyze_exclusive_timing", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads(
    (ROOT / "configs/context_exclusive_timing_protocol_v1.json").read_text(
        encoding="utf-8"
    )
)


def _run(label, map_id, seed, workload, method, *, context_seconds=0.10):
    suffix = f"{label}-{seed}-{workload}"
    exact = method == MODULE.EXACT
    calls = 26 if exact else 3
    generations = 25 if exact else 2
    reactivations = 0 if exact else 1
    publications = generations + reactivations
    return {
        "method": method,
        "seed": seed,
        "root_seed": seed,
        "map_id": map_id,
        "workload": workload,
        "split": "development",
        "evidence_class": "development",
        "manifest_id": f"manifest-{suffix}",
        "reset_causal_fingerprint": f"reset-{suffix}",
        "release_projection_fingerprint": f"release-{suffix}",
        "distribution_update_fingerprint": f"distribution-{suffix}",
        "task_tape_identity": {"manifest_sha256": f"tape-{suffix}"},
        "scored_horizon": 2000,
        "decision_window": 20,
        "window_count": 100,
        "generator_calls": calls,
        "generator_seconds": 1.0 if exact else context_seconds,
        "mandatory_bootstrap_calls": 1,
        "post_bootstrap_generation_count": generations,
        "post_bootstrap_reactivation_count": reactivations,
        "post_bootstrap_publication_count": publications,
        "publication_budget": 25,
        "budget_violation_count": 0,
        "budget": {"cap_satisfied": True},
        "safety": {"passed": True},
        "planner_timeouts": 0,
        "invariants": {"passed": True},
        "timing_evidence_valid": True,
    }


def _artifact(scenario, *, context_seconds=0.10):
    label, map_id, map_sha256, agents = scenario
    runs = []
    for seed in MODULE.EXPECTED_SEEDS:
        for workload in MODULE.EXPECTED_WORKLOADS:
            for method in MODULE.EXPECTED_METHODS:
                runs.append(
                    _run(
                        label,
                        map_id,
                        seed,
                        workload,
                        method,
                        context_seconds=context_seconds,
                    )
                )
    return {
        "schema": MODULE.SOURCE_SCHEMA,
        "status": "complete",
        "split": "development",
        "evidence_class": "development",
        "seeds": list(MODULE.EXPECTED_SEEDS),
        "methods": list(MODULE.EXPECTED_METHODS),
        "workloads": list(MODULE.EXPECTED_WORKLOADS),
        "map_id": map_id,
        "map_sha256": map_sha256,
        "period_on_sim_sha256": MODULE.EXPECTED_SIMULATOR_SHA256,
        "generator": {
            "file_sha256": MODULE.EXPECTED_CHECKPOINT_FILE_SHA256,
            "params_sha256": MODULE.EXPECTED_CHECKPOINT_PARAMS_SHA256,
        },
        "protocol": {
            "agents": agents,
            "warmup_time": 200,
            "scored_horizon": 2000,
            "decision_window": 20,
            "num_scored_windows": 100,
            "b25_budget": 25,
            "release_interval_per_agent": 110,
            "guard_suffix_tasks_per_agent": 4,
            "sigma": 0.75,
            "jobs": 1,
            "exclusive_timing_declared": True,
            "timing_evidence_valid": True,
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


def _matrix(*, context_seconds=0.10):
    return [
        (scenario[0], _artifact(scenario, context_seconds=context_seconds))
        for scenario in MODULE.EXPECTED_SCENARIOS
    ]


class ExclusiveTimingAnalysisTests(unittest.TestCase):
    def test_clean_matrix_passes_both_frozen_time_gates(self):
        report = MODULE.analyze(_matrix(), config=CONFIG)
        self.assertTrue(report["audit"]["timing_evidence_valid"])
        self.assertTrue(report["primary_timing_gate"]["passed"])
        self.assertAlmostEqual(report["primary_timing_gate"]["pooled_reduction"], 0.9)
        self.assertAlmostEqual(
            report["primary_timing_gate"]["mean_paired_cell_reduction"], 0.9
        )
        self.assertFalse(report["claim_scope"]["throughput_inference_permitted"])
        self.assertEqual(report["cluster_diagnostics"]["sign_flip_assignments"], 32)

    def test_below_eighty_percent_fails_without_changing_audit(self):
        report = MODULE.analyze(_matrix(context_seconds=0.25), config=CONFIG)
        self.assertTrue(report["audit"]["passed"])
        self.assertFalse(report["primary_timing_gate"]["passed"])
        self.assertEqual(
            report["primary_timing_gate"]["decision"],
            "FAIL_GENERATOR_TIME_REDUCTION_GATE",
        )

    def test_nonexclusive_artifact_is_rejected(self):
        matrix = _matrix()
        matrix[0][1]["protocol"]["exclusive_timing_declared"] = False
        with self.assertRaisesRegex(MODULE.ExclusiveTimingAuditError, "exclusive"):
            MODULE.analyze(matrix, config=CONFIG)

    def test_run_level_invalid_timing_is_rejected(self):
        matrix = _matrix()
        matrix[0][1]["runs"][0]["timing_evidence_valid"] = False
        with self.assertRaisesRegex(MODULE.ExclusiveTimingAuditError, "timing_evidence"):
            MODULE.analyze(matrix, config=CONFIG)

    def test_pairing_mismatch_is_rejected(self):
        matrix = _matrix()
        run = next(
            item
            for item in matrix[0][1]["runs"]
            if item["method"] == MODULE.CONTEXT
        )
        run["release_projection_fingerprint"] = "mismatch"
        with self.assertRaisesRegex(MODULE.ExclusiveTimingAuditError, "paired"):
            MODULE.analyze(matrix, config=CONFIG)

    def test_generator_call_timeline_mismatch_is_rejected(self):
        matrix = _matrix()
        run = next(
            item
            for item in matrix[0][1]["runs"]
            if item["method"] == MODULE.CONTEXT
        )
        run["generator_calls"] += 1
        with self.assertRaisesRegex(MODULE.ExclusiveTimingAuditError, "generator-call"):
            MODULE.analyze(matrix, config=CONFIG)

    def test_config_cannot_enable_throughput_inference(self):
        config = copy.deepcopy(CONFIG)
        config["scope_restrictions"]["throughput_inference_permitted"] = True
        with self.assertRaisesRegex(MODULE.ExclusiveTimingAuditError, "throughput"):
            MODULE.analyze(_matrix(), config=config)

    def test_cluster_bootstrap_is_reproducible(self):
        first = MODULE.analyze(_matrix(), config=CONFIG)
        second = MODULE.analyze(_matrix(), config=CONFIG)
        self.assertEqual(first["cluster_diagnostics"], second["cluster_diagnostics"])


if __name__ == "__main__":
    unittest.main()
