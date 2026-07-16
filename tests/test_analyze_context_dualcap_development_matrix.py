import copy
import importlib.util
from pathlib import Path
import unittest

from tests import test_analyze_context_dualcap_dev10 as SINGLE_FIXTURE


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_context_dualcap_development_matrix.py"
)
SPEC = importlib.util.spec_from_file_location(
    "analyze_context_dualcap_development_matrix", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


CONFIG, _ = MODULE.load_frozen_config()


def _artifact(scenario, scenario_index):
    runs = []
    workload_bonus = {"stationary": 0, "abrupt": 5, "recurrent": 10}
    for seed_index, seed in enumerate(CONFIG["root_seeds"]):
        for workload in CONFIG["workloads"]:
            exact = 1000 + 20 * scenario_index + seed_index + workload_bonus[workload]
            tasks = {
                MODULE.SINGLE.EXACT: exact,
                MODULE.SINGLE.BOOTSTRAP: exact - 50,
                MODULE.SINGLE.CONTEXT: exact - 1,
                MODULE.SINGLE.DUALCAP: exact - 2,
            }
            for method in CONFIG["methods"]:
                run = SINGLE_FIXTURE._run(method, seed, workload, tasks[method])
                run["map_id"] = Path(scenario["map"]).stem
                # Scenario-specific exogenous identities remain paired across
                # the four methods in one seed/workload cell.
                suffix = f"{scenario['id']}-{seed}-{workload}"
                run["manifest_id"] = f"manifest-{suffix}"
                run["reset_causal_fingerprint"] = f"reset-{suffix}"
                run["release_projection_fingerprint"] = f"release-{suffix}"
                run["distribution_update_fingerprint"] = f"distribution-{suffix}"
                run["task_tape_identity"] = {
                    "mode": "absolute_release_queue_per_agent",
                    "manifest_sha256": f"tape-{suffix}",
                }
                runs.append(run)
    return {
        "schema": MODULE.SINGLE.SOURCE_SCHEMA,
        "status": "complete",
        "split": "development",
        "evidence_class": "development",
        "split_protocol": {
            "canonical_name": "development",
            "classification": "development",
            "preregistered_seeds": list(range(17, 28)),
            "sortation_maps_reserved_for_locked_test": True,
        },
        "seeds": list(CONFIG["root_seeds"]),
        "methods": list(CONFIG["methods"]),
        "workloads": list(CONFIG["workloads"]),
        "map_id": Path(scenario["map"]).stem,
        "map_path": f"/maps/{scenario['map']}",
        "map_sha256": scenario["map_sha256"],
        "period_on_sim_sha256": CONFIG["frozen_artifacts"][
            "period_on_sim_sha256"
        ],
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
            "context_memory_B25": {
                "recall_threshold": 0.05,
                "recall_margin": 0.02,
                "absolute_score_gate": 0.10,
            },
            "context_dualcap_G4S5": {
                "development_only": True,
                "base_controller": "context_memory_B25",
                "recall_threshold": 0.05,
                "recall_margin": 0.02,
                "absolute_score_gate": 0.10,
                "post_bootstrap_generation_cap": 4,
                "effective_guidance_switch_cap": 5,
                "total_generator_call_cap": 5,
                "mandatory_bootstrap_counts_toward_post_caps": False,
            },
            "jobs": 3,
            "exclusive_timing_declared": False,
            "timing_evidence_valid": False,
        },
        "generator": {
            "kind": "frozen_traffic_cnn_checkpoint",
            "file_sha256": CONFIG["frozen_artifacts"]["checkpoint_file_sha256"],
            "params_sha256": CONFIG["frozen_artifacts"][
                "checkpoint_params_sha256"
            ],
        },
        "runs": runs,
    }


def _matrix():
    return [
        _artifact(scenario, index)
        for index, scenario in enumerate(CONFIG["scenarios"])
    ]


def _dualcap_runs(artifacts):
    return [
        run
        for artifact in artifacts
        for run in artifact["runs"]
        if run["method"] == MODULE.SINGLE.DUALCAP
    ]


class CombinedContextDualCapDevelopmentAnalysisTests(unittest.TestCase):
    def test_clean_four_scenario_matrix_passes_for_fresh_v3_only(self):
        artifacts = _matrix()
        before = copy.deepcopy(artifacts)
        report = MODULE.analyze_artifacts(
            artifacts, bootstrap_samples=500
        )
        self.assertEqual(artifacts, before)
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(report["design"]["n_scenarios"], 4)
        self.assertEqual(report["design"]["paired_cells_per_method"], 120)
        self.assertEqual(
            report["design"]["cells_per_root_seed_cluster_per_method"], 12
        )
        self.assertEqual(report["design"]["total_runs"], 480)
        self.assertTrue(report["screening"]["passed"])
        self.assertEqual(
            report["screening"]["recommendation"],
            "GO_FREEZE_UNCHANGED_CANDIDATE_FOR_FRESH_VALIDATION_V3_ONLY",
        )
        self.assertTrue(
            report["screening"][
                "development_only_no_paper_locked_test_or_sota_claim"
            ]
        )

    def test_each_comparison_clusters_all_twelve_scenario_cells_by_root(self):
        report = MODULE.analyze_artifacts(_matrix(), bootstrap_samples=200)
        for comparator in MODULE.SINGLE.COMPARATORS:
            row = report["comparisons"][comparator]
            self.assertEqual(row["n_paired_cells"], 120)
            self.assertEqual(row["n_root_seed_clusters"], 10)
            self.assertEqual(row["cells_per_root_seed_cluster"], 12)
            self.assertEqual(row["exact_sign_flip"]["assignments"], 1024)
            self.assertEqual(
                {item["n_paired_cells"] for item in row["workload_strata"].values()},
                {40},
            )
            self.assertEqual(
                {item["n_paired_cells"] for item in row["scenario_strata"].values()},
                {30},
            )

    def test_scenario_agent_cell_must_match_frozen_config(self):
        artifacts = _matrix()
        artifacts[0]["protocol"]["agents"] += 1
        with self.assertRaisesRegex(
            MODULE.CombinedDevelopmentError, "map/hash/agents"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_protocol_mismatch_across_artifacts_is_rejected(self):
        artifacts = _matrix()
        artifacts[1]["protocol"]["jobs"] = 2
        with self.assertRaisesRegex(
            MODULE.CombinedDevelopmentError, "protocol differs across artifacts"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_checkpoint_must_equal_frozen_config(self):
        artifacts = _matrix()
        artifacts[2]["generator"]["file_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.CombinedDevelopmentError, "checkpoint"):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_single_scenario_pairing_failure_propagates_to_combined_audit(self):
        artifacts = _matrix()
        dualcap = next(
            run
            for run in artifacts[0]["runs"]
            if run["method"] == MODULE.SINGLE.DUALCAP
        )
        dualcap["reset_causal_fingerprint"] = "mismatch"
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)
        self.assertFalse(report["audit"]["passed"])
        self.assertFalse(report["audit"]["paired_exogenous_inputs_match"])
        self.assertEqual(
            report["screening"]["recommendation"],
            "NO_GO_FIX_COMBINED_DEVELOPMENT_AUDIT",
        )

    def test_exact_minus_half_percent_gate_is_not_relaxed(self):
        artifacts = _matrix()
        for run in _dualcap_runs(artifacts):
            # About -0.8% vs exact, while remaining comfortably above bootstrap.
            exact = next(
                candidate
                for artifact in artifacts
                for candidate in artifact["runs"]
                if candidate["map_id"] == run["map_id"]
                and candidate["seed"] == run["seed"]
                and candidate["workload"] == run["workload"]
                and candidate["method"] == MODULE.SINGLE.EXACT
                and candidate["manifest_id"] == run["manifest_id"]
            )
            run["num_task_finished"] = exact["num_task_finished"] - 8
            run["throughput_per_timestep"] = run["num_task_finished"] / 2000
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=200)
        self.assertTrue(report["audit"]["passed"])
        self.assertFalse(
            report["screening"]["checks"][
                "dualcap_vs_exact_mean_at_least_minus_0_5pct"
            ]
        )
        self.assertEqual(
            report["screening"]["recommendation"],
            "NO_GO_COMBINED_DEVELOPMENT_SCREEN_FAILED",
        )

    def test_frozen_config_rejects_gate_relaxation_in_memory(self):
        changed = copy.deepcopy(CONFIG)
        changed["screen_gates"][
            "dualcap_vs_exact_mean_relative_effect_at_least"
        ] = -0.01
        with self.assertRaisesRegex(MODULE.CombinedDevelopmentError, "screen_gates"):
            MODULE._validate_frozen_config(changed)


if __name__ == "__main__":
    unittest.main()
