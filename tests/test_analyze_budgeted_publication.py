import copy
import importlib.util
import math
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_budgeted_publication.py"
)
SPEC = importlib.util.spec_from_file_location(
    "analyze_budgeted_publication", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _run(method, seed, map_id, workload, tasks, *, horizon=2000):
    decision_window = 20
    window_count = horizon // decision_window
    budget = math.ceil(0.25 * (window_count - 1))
    suffix = f"{seed}-{map_id}-{workload}"
    return {
        "method": method,
        "seed": seed,
        "root_seed": seed,
        "map_id": map_id,
        "map_path": f"/maps/{map_id}.map",
        "workload": workload,
        "manifest_id": f"manifest-{suffix}",
        "num_task_finished": tasks,
        "throughput_per_timestep": tasks / horizon,
        "scored_horizon": horizon,
        "decision_window": decision_window,
        "window_count": window_count,
        "budget": {
            "mandatory_bootstrap_calls": 1,
            "post_bootstrap_budget": budget,
            "post_bootstrap_publication_count": budget,
            "total_generator_calls": 1 + budget,
            "budget_violation_attempts": 0,
            "exact_quota_required": True,
            "exact_quota_satisfied": True,
        },
        "post_bootstrap_publication_count": budget,
        "publication_budget": budget,
        "budget_violation_count": 0,
        "safety": {
            "collision_count": 0,
            "edge_swap_count": 0,
            "invalid_move_count": 0,
            "planner_timeout_count": 0,
            "route_trace_invalid_count": 0,
            "passed": True,
        },
        "invariants": {
            "passed": True,
            "online_workload_rng_draws": 0,
            "release_projection_count": 400,
        },
        "task_tape_identity": {
            "mode": "absolute_release_queue_per_agent",
            "schema_version": 1,
            "manifest_sha256": f"sha-{suffix}",
            "content_fnv1a64": f"fnv-{suffix}",
            "start_locations": [1, 2],
            "per_agent_lengths": [100, 100],
            "total_tasks": 200,
        },
        "final_task_tape_prefixes": {
            "released_prefix_lengths": [100, 100],
            "assigned_prefix_lengths": [90, 91],
            "completed_prefix_lengths": [89, 90],
            "all_released": True,
            "all_completed": False,
        },
        "reset_causal_fingerprint": f"reset-{suffix}",
        "release_projection_fingerprint": f"release-{suffix}",
        "distribution_update_fingerprint": f"distribution-{suffix}",
        "publication_timeline": [],
        "windows": [],
    }


def _artifact(*, split="locked_test", seeds=None, relative=0.03, horizon=2000):
    if seeds is None:
        seeds = list(range(1001, 1031))
    maps = ["warehouse_a", "warehouse_b"]
    workloads = ["stationary", "abrupt", "recurring", "gradual"]
    methods = [MODULE.BASELINE, MODULE.PROPOSED]
    runs = []
    for seed in seeds:
        for map_id in maps:
            for workload in workloads:
                baseline_tasks = 1000 + (seed % 5)
                proposed_tasks = round(baseline_tasks * (1.0 + relative))
                runs.append(
                    _run(
                        MODULE.BASELINE, seed, map_id, workload,
                        baseline_tasks, horizon=horizon,
                    )
                )
                runs.append(
                    _run(
                        MODULE.PROPOSED, seed, map_id, workload,
                        proposed_tasks, horizon=horizon,
                    )
                )
    return {
        "schema": MODULE.SOURCE_SCHEMA,
        "status": "complete",
        "evidence_class": split,
        "split": split,
        "seeds": seeds,
        "methods": methods,
        "workloads": workloads,
        "runs": runs,
    }


class AnalyzeBudgetedPublicationTests(unittest.TestCase):
    def test_positive_locked_test_passes_preregistered_gate(self):
        analysis = MODULE.analyze_artifact(
            _artifact(), bootstrap_samples=500, sign_flip_samples=2000
        )
        self.assertTrue(analysis["preregistered_quality_gate"]["passed"])
        self.assertEqual(
            analysis["preregistered_quality_gate"]["recommendation"],
            "GO_LOCKED_TEST_QUALITY_CLAIM",
        )
        self.assertEqual(
            analysis["evidence"]["analysis_evidence_class"],
            "locked_test_confirmatory",
        )
        self.assertGreater(
            analysis["effects"]["mean_relative_throughput_delta"], 0.02
        )
        self.assertEqual(
            analysis["effects"]["win_tie_loss_root_seeds"],
            {"wins": 30, "ties": 0, "losses": 0},
        )
        self.assertTrue(analysis["invariants"]["passed"])

    def test_small_negative_validation_is_explicitly_exploratory(self):
        analysis = MODULE.analyze_artifact(
            _artifact(
                split="validation", seeds=[101, 102, 103], relative=-0.03,
                horizon=1000,
            ),
            bootstrap_samples=200,
            sign_flip_samples=200,
        )
        self.assertTrue(analysis["evidence"]["exploratory"])
        self.assertFalse(analysis["evidence"]["locked_test_claim_permitted"])
        self.assertEqual(
            analysis["preregistered_quality_gate"]["recommendation"],
            "EXPLORATORY_SCREEN_FAIL",
        )
        self.assertLess(
            analysis["effects"]["mean_relative_throughput_delta"], 0.0
        )
        self.assertEqual(
            analysis["effects"]["one_sided_paired_sign_flip"]["method"],
            "exact",
        )

    def test_validation_falsely_marked_locked_claim_is_refused(self):
        artifact = _artifact(
            split="validation", seeds=[101, 102, 103], relative=0.03,
            horizon=1000,
        )
        artifact["locked_test_claim"] = True
        with self.assertRaisesRegex(
            MODULE.ArtifactValidationError, "falsely marked"
        ):
            MODULE.analyze_artifact(
                artifact, bootstrap_samples=20, sign_flip_samples=20
            )

    def test_fingerprint_and_budget_failures_force_no_go(self):
        artifact = _artifact()
        proposed = next(
            run for run in artifact["runs"]
            if run["method"] == MODULE.PROPOSED
        )
        proposed["task_tape_identity"]["manifest_sha256"] = "wrong-sha"
        proposed["budget"]["post_bootstrap_publication_count"] = 24
        proposed["post_bootstrap_publication_count"] = 24
        proposed["budget"]["mandatory_bootstrap_calls"] = 0
        proposed["budget"]["total_generator_calls"] = 25
        proposed["budget"]["exact_quota_satisfied"] = False
        analysis = MODULE.analyze_artifact(
            artifact, bootstrap_samples=100, sign_flip_samples=200
        )
        self.assertFalse(analysis["invariants"]["passed"])
        failed_checks = {
            item["check"] for item in analysis["invariants"]["failures"]
        }
        self.assertIn("paired_task_tape_identity", failed_checks)
        self.assertIn("nested_exact_fractional_budget_spend", failed_checks)
        self.assertIn("exactly_one_mandatory_bootstrap_call", failed_checks)
        self.assertFalse(analysis["preregistered_quality_gate"]["passed"])
        self.assertEqual(
            analysis["preregistered_quality_gate"]["recommendation"],
            "NO_GO_LOCKED_TEST_QUALITY_CLAIM",
        )

    def test_missing_required_field_hard_fails(self):
        artifact = _artifact(
            split="development", seeds=[17, 18, 19], relative=0.03,
            horizon=1000,
        )
        del artifact["runs"][0]["reset_causal_fingerprint"]
        with self.assertRaisesRegex(
            MODULE.ArtifactValidationError, "reset_causal_fingerprint is required"
        ):
            MODULE.analyze_artifact(
                artifact, bootstrap_samples=20, sign_flip_samples=20
            )

    def test_root_seed_is_a_supported_seed_alias(self):
        artifact = _artifact(
            split="development", seeds=[17, 18, 19], relative=0.03,
            horizon=1000,
        )
        for run in artifact["runs"]:
            del run["seed"]
        analysis = MODULE.analyze_artifact(
            artifact, bootstrap_samples=20, sign_flip_samples=20
        )
        self.assertEqual(analysis["design"]["root_seeds"], [17, 18, 19])
        self.assertTrue(analysis["evidence"]["exploratory"])

    def test_smoke_budget_is_derived_from_horizon_and_window(self):
        artifact = _artifact(
            split="development", seeds=[17, 18, 19], relative=0.03,
            horizon=600,
        )
        analysis = MODULE.analyze_artifact(
            artifact, bootstrap_samples=20, sign_flip_samples=20
        )
        self.assertEqual(
            analysis["invariants"]["target_budget"][
                "expected_post_bootstrap_publications"
            ],
            [8],
        )
        self.assertTrue(analysis["invariants"]["passed"])
        self.assertFalse(
            analysis["preregistered_quality_gate"]["checks"][
                "formal_scored_horizon_is_2000"
            ]
        )

    def test_window_count_must_equal_horizon_over_decision_window(self):
        artifact = _artifact(
            split="development", seeds=[17, 18, 19], relative=0.03,
            horizon=1000,
        )
        artifact["runs"][0]["window_count"] = 100
        with self.assertRaisesRegex(
            MODULE.ArtifactValidationError,
            "window_count must equal scored_horizon/decision_window",
        ):
            MODULE.analyze_artifact(
                artifact, bootstrap_samples=20, sign_flip_samples=20
            )

    def test_safety_failure_is_reported_but_timeout_is_only_an_outcome(self):
        artifact = _artifact()
        proposed = next(
            run for run in artifact["runs"]
            if run["method"] == MODULE.PROPOSED
        )
        proposed["safety"]["planner_timeout_count"] = 2
        timeout_analysis = MODULE.analyze_artifact(
            artifact, bootstrap_samples=50, sign_flip_samples=100
        )
        self.assertTrue(timeout_analysis["invariants"]["passed"])
        self.assertEqual(
            timeout_analysis["invariants"][
                "planner_timeouts_are_outcomes_not_exclusions"
            ],
            2,
        )

        unsafe = copy.deepcopy(artifact)
        unsafe_run = next(
            run for run in unsafe["runs"]
            if run["method"] == MODULE.PROPOSED
        )
        unsafe_run["safety"]["collision_count"] = 1
        unsafe_run["safety"]["passed"] = False
        unsafe_analysis = MODULE.analyze_artifact(
            unsafe, bootstrap_samples=50, sign_flip_samples=100
        )
        self.assertFalse(unsafe_analysis["invariants"]["passed"])
        self.assertFalse(unsafe_analysis["preregistered_quality_gate"]["passed"])


if __name__ == "__main__":
    unittest.main()
