import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests import test_analyze_context_dualcap_dev10 as BASE_FIXTURE


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_context_eventreserve_development_matrix.py"
SPEC = importlib.util.spec_from_file_location(
    "analyze_context_eventreserve_development_matrix", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

CONFIG_PATH = ROOT / "configs" / "context_eventreserve_development_matrix_v1.json"
CONFIG, CONFIG_SHA, _ = MODULE.load_config(CONFIG_PATH)


def _event_timeline():
    operations = ["generate"] * 4 + ["reactivate"]
    rows = [
        {
            "decision_index": 0,
            "accepted": True,
            "charged_to_post_bootstrap_budget": False,
            "charged_to_generator_budget": False,
            "executed_operation": "bootstrap_generate",
        }
    ]
    event_fields = {
        field: False for field in MODULE.EVENT_TIMELINE_FIELDS
    }
    for decision_index in range(1, 100):
        operation = (
            operations[decision_index - 1]
            if decision_index <= len(operations)
            else "hold"
        )
        accepted = operation in {"generate", "reactivate"}
        rows.append(
            {
                "decision_index": decision_index,
                "accepted": accepted,
                "charged_to_post_bootstrap_budget": accepted,
                "charged_to_generator_budget": operation == "generate",
                "executed_operation": operation,
                "uncapped_proposed_operation": operation,
                **event_fields,
            }
        )
    return rows


def _event_run(seed, workload, tasks):
    run = copy.deepcopy(BASE_FIXTURE._run(MODULE.CONTEXT, seed, workload, tasks))
    run.update(
        {
            "method": MODULE.EVENTRESERVE,
            "post_bootstrap_publication_count": 5,
            "post_bootstrap_generation_count": 4,
            "post_bootstrap_reactivation_count": 1,
            "effective_guidance_switch_count": 5,
            "publication_budget": 6,
            "generator_calls": 5,
            "publication_timeline": _event_timeline(),
        }
    )
    run["budget"] = {
        "mandatory_bootstrap_calls": 1,
        "mandatory_bootstrap_counts_toward_post_caps": False,
        "post_bootstrap_budget": 6,
        "effective_guidance_switch_cap": 6,
        "post_bootstrap_generation_cap": 5,
        "total_generator_call_cap": 6,
        "post_bootstrap_publication_count": 5,
        "post_bootstrap_generation_count": 4,
        "post_bootstrap_reactivation_count": 1,
        "effective_guidance_switch_count": 5,
        "total_generator_calls": 5,
        "generation_cap_candidate_count": 0,
        "generation_cap_binding_count": 0,
        "generation_cap_binding_audit_satisfied": True,
        "eventreserve_candidate_count": 0,
        "eventreserve_preview_accept_count": 0,
        "eventreserve_qualified_count": 0,
        "eventreserve_binding_count": 0,
        "eventreserve_generation_cap_binding_count": 0,
        "eventreserve_execution_count": 0,
        "eventreserve_audit_conservation_satisfied": True,
        "budget_violation_attempts": 0,
        "budget_semantics": "generation_cap_5_switch_cap_6_event_reserved_sixth",
        "cap_satisfied": True,
        "switch_cap_satisfied": True,
        "generation_cap_satisfied": True,
        "total_generator_call_cap_satisfied": True,
        "exact_quota_required": False,
        "exact_quota_satisfied": False,
    }
    return run


def _artifact(scenario, scenario_index):
    runs = []
    workload_bonus = {"stationary": 0, "abrupt": 5, "recurrent": 10}
    for seed_index, seed in enumerate(CONFIG["root_seeds"]):
        for workload in CONFIG["workloads"]:
            exact = 1000 + 20 * scenario_index + seed_index + workload_bonus[workload]
            tasks = {
                MODULE.EXACT: exact,
                MODULE.BOOTSTRAP: exact - 50,
                MODULE.CONTEXT: exact - 1,
                MODULE.DUALCAP: exact - 3,
                MODULE.EVENTRESERVE: exact - 2,
            }
            for method in CONFIG["methods"]:
                run = (
                    _event_run(seed, workload, tasks[method])
                    if method == MODULE.EVENTRESERVE
                    else BASE_FIXTURE._run(method, seed, workload, tasks[method])
                )
                suffix = f"{scenario['id']}-{seed}-{workload}"
                run["map_id"] = Path(scenario["map"]).stem
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
        "schema": MODULE.SOURCE_SCHEMA,
        "status": "complete",
        "split": "development",
        "evidence_class": "development",
        MODULE.CONFIG_SHA_FIELD: CONFIG_SHA,
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
            MODULE.CONTEXT: {
                "recall_threshold": 0.05,
                "recall_margin": 0.02,
                "absolute_score_gate": 0.10,
            },
            MODULE.DUALCAP: {
                "development_only": True,
                "base_controller": MODULE.CONTEXT,
                "recall_threshold": 0.05,
                "post_bootstrap_generation_cap": 4,
                "effective_guidance_switch_cap": 5,
                "total_generator_call_cap": 5,
                "mandatory_bootstrap_counts_toward_post_caps": False,
            },
            MODULE.EVENTRESERVE: {
                "development_only": True,
                "base_controller": MODULE.CONTEXT,
                "recall_threshold": 0.05,
                "post_bootstrap_generation_cap": 5,
                "effective_guidance_switch_cap": 6,
                "total_generator_call_cap": 6,
                "mandatory_bootstrap_counts_toward_post_caps": False,
                "generation_cap_state": (
                    "past_executed_post_bootstrap_generations_only"
                ),
                "sixth_switch_reserve": (
                    "fresh_generation_only_with_accepted_triggered_"
                    "unconstrained_preview_and_not_maintenance_only"
                ),
                "reactivation_generation_charge": 0,
                "quota_rule": (
                    "at_most_G5_fresh_generations_and_S6_switches_with_"
                    "event_reserved_sixth_switch"
                ),
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


def _event_runs(artifacts):
    return [
        run
        for artifact in artifacts
        for run in artifact["runs"]
        if run["method"] == MODULE.EVENTRESERVE
    ]


class ContextEventReserveDevelopmentMatrixTests(unittest.TestCase):
    def test_clean_matrix_passes_for_fresh_validation_only(self):
        artifacts = _matrix()
        before = copy.deepcopy(artifacts)
        report = MODULE.analyze_artifacts(
            artifacts,
            config_path=CONFIG_PATH,
            bootstrap_samples=300,
        )
        self.assertEqual(artifacts, before)
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(report["design"]["total_runs"], 600)
        self.assertEqual(report["design"]["paired_cells_per_method"], 120)
        self.assertEqual(
            report["design"]["cells_per_root_seed_cluster_per_method"], 12
        )
        self.assertTrue(report["screening"]["passed"])
        self.assertEqual(
            report["screening"]["recommendation"],
            "GO_FREEZE_UNCHANGED_EVENTRESERVE_FOR_FRESH_VALIDATION_V3_ONLY",
        )
        self.assertTrue(
            report["screening"]["dualcap_point_estimate"][
                "eventreserve_strictly_better"
            ]
        )
        self.assertFalse(
            report["screening"]["dualcap_point_estimate"]["is_screen_gate"]
        )

    def test_comparisons_cluster_twelve_cells_and_report_holm(self):
        report = MODULE.analyze_artifacts(
            _matrix(), config_path=CONFIG_PATH, bootstrap_samples=100,
            verify_local_sources=False,
        )
        for comparator in MODULE.COMPARATORS:
            comparison = report["comparisons"][comparator]
            self.assertEqual(comparison["n_paired_cells"], 120)
            self.assertEqual(comparison["n_root_seed_clusters"], 10)
            self.assertEqual(comparison["cells_per_root_seed_cluster"], 12)
            self.assertIn("p_greater_holm", comparison["exact_sign_flip"])
            self.assertGreaterEqual(
                comparison["exact_sign_flip"]["p_greater_holm"],
                comparison["exact_sign_flip"]["p_greater"],
            )
        self.assertEqual(report["multiplicity"]["family_size"], 4)

    def test_artifacts_must_declare_exact_frozen_config_sha(self):
        artifacts = _matrix()
        artifacts[0][MODULE.CONFIG_SHA_FIELD] = "0" * 64
        with self.assertRaisesRegex(
            MODULE.EventReserveDevelopmentError, MODULE.CONFIG_SHA_FIELD
        ):
            MODULE.analyze_artifacts(
                artifacts, config_path=CONFIG_PATH, bootstrap_samples=20,
                verify_local_sources=False,
            )

    def test_config_file_is_sha_locked(self):
        changed = copy.deepcopy(CONFIG)
        changed["rationale"] += " changed"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.EventReserveDevelopmentError, "config SHA-256"
            ):
                MODULE.load_config(path)

    def test_duplicate_or_missing_grid_cell_is_rejected(self):
        artifacts = _matrix()
        artifacts[0]["runs"][-1] = copy.deepcopy(artifacts[0]["runs"][-2])
        with self.assertRaisesRegex(
            MODULE.EventReserveDevelopmentError, "duplicate run cells"
        ):
            MODULE.analyze_artifacts(
                artifacts, config_path=CONFIG_PATH, bootstrap_samples=20,
                verify_local_sources=False,
            )

    def test_eventreserve_conservation_mismatch_fails_audit(self):
        artifacts = _matrix()
        run = _event_runs(artifacts)[0]
        run["budget"]["eventreserve_qualified_count"] = 1
        report = MODULE.analyze_artifacts(
            artifacts, config_path=CONFIG_PATH, bootstrap_samples=20,
            verify_local_sources=False,
        )
        self.assertFalse(report["audit"]["passed"])
        self.assertFalse(
            report["audit"]["eventreserve_budget_and_conservation_passed"]
        )
        checks = {item["check"] for item in report["audit"]["failures"]}
        self.assertIn("eventreserve_qualified_match_timeline", checks)
        self.assertIn("eventreserve_preview_partition", checks)

    def test_invalid_timeline_implication_fails_audit(self):
        artifacts = _matrix()
        run = _event_runs(artifacts)[0]
        row = run["publication_timeline"][20]
        row["constraint_candidate"] = True
        report = MODULE.analyze_artifacts(
            artifacts, config_path=CONFIG_PATH, bootstrap_samples=20,
            verify_local_sources=False,
        )
        checks = {item["check"] for item in report["audit"]["failures"]}
        self.assertIn("eventreserve_timeline_implications_valid", checks)

    def test_cross_method_exogenous_mismatch_fails_pairing_audit(self):
        artifacts = _matrix()
        _event_runs(artifacts)[0]["distribution_update_fingerprint"] = "mismatch"
        report = MODULE.analyze_artifacts(
            artifacts, config_path=CONFIG_PATH, bootstrap_samples=20,
            verify_local_sources=False,
        )
        self.assertFalse(report["audit"]["paired_exogenous_inputs_match"])
        self.assertEqual(
            report["screening"]["recommendation"],
            "NO_GO_FIX_EVENTRESERVE_DEVELOPMENT_AUDIT",
        )

    def test_exact_point_gate_is_not_relaxed(self):
        artifacts = _matrix()
        for run in _event_runs(artifacts):
            exact = next(
                item
                for artifact in artifacts
                for item in artifact["runs"]
                if item["map_id"] == run["map_id"]
                and item["seed"] == run["seed"]
                and item["workload"] == run["workload"]
                and item["method"] == MODULE.EXACT
                and item["manifest_id"] == run["manifest_id"]
            )
            run["num_task_finished"] = exact["num_task_finished"] - 8
            run["throughput_per_timestep"] = run["num_task_finished"] / 2000
        report = MODULE.analyze_artifacts(
            artifacts, config_path=CONFIG_PATH, bootstrap_samples=100,
            verify_local_sources=False,
        )
        self.assertTrue(report["audit"]["passed"])
        self.assertFalse(
            report["screening"]["checks"][
                "eventreserve_vs_exact_mean_at_least_minus_0_5pct"
            ]
        )
        self.assertEqual(
            report["screening"]["recommendation"],
            "NO_GO_EVENTRESERVE_DEVELOPMENT_SCREEN_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
