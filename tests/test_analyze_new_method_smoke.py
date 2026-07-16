import copy
import importlib.util
import math
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_new_method_smoke.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_new_method_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _run(method, workload, tasks):
    horizon = 600
    windows = 30
    b25 = math.ceil(0.25 * (windows - 1))
    post = 4 if method == "js_cap_B25" else 0 if method == "bootstrap_only" else b25
    budget = 0 if method == "bootstrap_only" else b25
    suffix = f"17-{workload}"
    released = [4, 4]
    return {
        "method": method,
        "seed": 17,
        "root_seed": 17,
        "map_id": "warehouse",
        "workload": workload,
        "manifest_id": f"manifest-{suffix}",
        "num_task_finished": tasks,
        "throughput_per_timestep": tasks / horizon,
        "scored_horizon": horizon,
        "decision_window": 20,
        "window_count": windows,
        "budget": {
            "mandatory_bootstrap_calls": 1,
            "post_bootstrap_budget": budget,
            "post_bootstrap_publication_count": post,
            "total_generator_calls": 1 + post,
            "budget_violation_attempts": 0,
            "budget_semantics": "at_most" if method == "js_cap_B25" else "exact",
            "cap_satisfied": True,
            "exact_quota_required": method != "js_cap_B25",
            "exact_quota_satisfied": method != "js_cap_B25",
        },
        "generator_calls": 1 + post,
        "post_bootstrap_publication_count": post,
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
            "release_projection_count": 8,
            "tape_not_exhausted": True,
            "reward_sum_matches_completed": True,
            "unexposed_completions_excluded_from_cohorts": True,
        },
        "task_tape_identity": {
            "mode": "absolute_release_queue_per_agent",
            "manifest_sha256": f"tape-{suffix}",
        },
        "final_task_tape_prefixes": {
            "released_prefix_lengths": released,
            # These are endogenous outcomes and intentionally method-specific.
            "assigned_prefix_lengths": [tasks % 7, tasks % 11],
            "completed_prefix_lengths": [tasks % 5, tasks % 13],
        },
        "reset_causal_fingerprint": f"reset-{suffix}",
        "release_projection_fingerprint": f"release-{suffix}",
        "distribution_update_fingerprint": f"distribution-{suffix}",
        "route_build_reason_counts": {
            "init_pp": 10,
            "task_change": 20,
            "inherited_goal_route": 1,
        },
        "cohort_attribution_audit": {
            "route_exposed_completion_count": tasks,
            "unexposed_zero_route_completion_count": 0,
            "unexposed_zero_route_completions_excluded": True,
            "route_build_reason_counts": {
                "init_pp": 10,
                "task_change": 20,
                "inherited_goal_route": 1,
            },
        },
    }


def _artifact():
    workloads = ["stationary", "abrupt", "recurrent"]
    exact_tasks = {"stationary": 1000, "abrupt": 1000, "recurrent": 1000}
    runs = []
    for workload in workloads:
        for method in MODULE.TARGET_METHODS:
            tasks = exact_tasks[workload]
            if method == "bootstrap_only":
                tasks = 1005
            elif method == "causal_block_B25":
                tasks = 1020
            elif method == "js_cap_B25":
                tasks = 1015
            elif method == "js_B25":
                tasks = 1008
            elif method == "proposed_no_cohort_B25":
                tasks = 1010
            runs.append(_run(method, workload, tasks))
    return {
        "schema": MODULE.SOURCE_SCHEMA,
        "status": "complete",
        "split": "development",
        "evidence_class": "development",
        "seeds": [17],
        "methods": list(MODULE.TARGET_METHODS),
        "workloads": workloads,
        "runs": runs,
    }


class NewMethodSmokeAnalysisTests(unittest.TestCase):
    def test_clean_smoke_passes_and_authorizes_dev10_only(self):
        report = MODULE.analyze(_artifact(), source_sha256="fixture")
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(
            report["screening"]["recommendation"], "GO_DEV10_SCREEN_ONLY"
        )
        self.assertTrue(
            report["screening"]["causal_block_track"]["passes_signal_screen"]
        )
        self.assertTrue(
            report["screening"]["js_cap_track"]["passes_signal_screen"]
        )
        self.assertTrue(
            report["screening"]["one_seed_smoke_never_supports_paper_or_sota_claim"]
        )

    def test_released_prefix_mismatch_fails_pairing(self):
        artifact = _artifact()
        run = next(item for item in artifact["runs"] if item["method"] == "js_B25")
        run["final_task_tape_prefixes"]["released_prefix_lengths"] = [3, 4]
        report = MODULE.analyze(artifact, source_sha256="fixture")
        self.assertFalse(report["audit"]["passed"])
        self.assertEqual(
            report["screening"]["recommendation"], "NO_GO_FIX_INVARIANTS"
        )
        self.assertIn(
            "paired_released_prefixes",
            {item["check"] for item in report["audit"]["failures"]},
        )

    def test_nonzero_unexposed_completion_blocks_escalation(self):
        artifact = _artifact()
        artifact["runs"][0]["cohort_attribution_audit"][
            "unexposed_zero_route_completion_count"
        ] = 1
        report = MODULE.analyze(artifact, source_sha256="fixture")
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(
            report["screening"]["recommendation"],
            "NO_GO_FIX_RUNTIME_OR_ATTRIBUTION_EVIDENCE",
        )

    def test_unknown_route_reason_is_a_hard_attribution_failure(self):
        artifact = _artifact()
        reasons = {"mystery": 1}
        artifact["runs"][0]["route_build_reason_counts"] = reasons
        artifact["runs"][0]["cohort_attribution_audit"][
            "route_build_reason_counts"
        ] = reasons
        report = MODULE.analyze(artifact, source_sha256="fixture")
        self.assertEqual(
            report["screening"]["recommendation"], "NO_GO_FIX_INVARIANTS"
        )
        self.assertIn(
            "recognized_route_reason",
            {item["check"] for item in report["audit"]["failures"]},
        )


if __name__ == "__main__":
    unittest.main()
