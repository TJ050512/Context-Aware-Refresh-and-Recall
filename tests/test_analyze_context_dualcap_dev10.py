import copy
import importlib.util
import math
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_context_dualcap_dev10.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_context_dualcap_dev10", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


SEEDS = [17, 23, 31, 43, 59, 71, 89, 101, 127, 149]
WORKLOADS = list(MODULE.EXPECTED_WORKLOADS)
HORIZON = 2000
WINDOW_COUNT = 100
B25 = math.ceil(0.25 * (WINDOW_COUNT - 1))


def _resource_contract(method):
    if method == MODULE.EXACT:
        switches, generations, reactivations = B25, B25, 0
        registered, exact, semantics = B25, True, "exact"
    elif method == MODULE.BOOTSTRAP:
        switches, generations, reactivations = 0, 0, 0
        registered, exact, semantics = 0, True, "exact"
    elif method == MODULE.CONTEXT:
        switches, generations, reactivations = 6, 5, 1
        registered, exact, semantics = B25, False, "at_most_switch_and_generator"
    else:
        switches, generations, reactivations = 5, 4, 1
        registered, exact, semantics = 5, False, "generation_cap_4_switch_cap_5"
    return {
        "switches": switches,
        "generations": generations,
        "reactivations": reactivations,
        "registered": registered,
        "exact": exact,
        "semantics": semantics,
    }


def _timeline(method):
    contract = _resource_contract(method)
    rows = [
        {
            "decision_index": 0,
            "accepted": True,
            "charged_to_post_bootstrap_budget": False,
            "executed_operation": "bootstrap_generate",
        }
    ]
    operations = (
        ["generate"] * contract["generations"]
        + ["reactivate"] * contract["reactivations"]
    )
    binding_index = len(operations) + 1 if method == MODULE.DUALCAP else None
    for decision_index in range(1, WINDOW_COUNT):
        operation = operations[decision_index - 1] if decision_index <= len(operations) else "hold"
        accepted = operation in {"generate", "reactivate"}
        binding = decision_index == binding_index
        rows.append(
            {
                "decision_index": decision_index,
                "accepted": accepted,
                "charged_to_post_bootstrap_budget": accepted,
                "charged_to_generator_budget": operation == "generate",
                "executed_operation": operation,
                "generation_cap_candidate_suppressed": binding,
                "generation_cap_binding": binding,
                "generation_cap_blocked": binding,
            }
        )
    return rows


def _run(method, seed, workload, tasks):
    contract = _resource_contract(method)
    suffix = f"{seed}-{workload}"
    calls = 1 + contract["generations"]
    generation_cap = 4 if method == MODULE.DUALCAP else contract["registered"]
    switch_cap = contract["registered"]
    total_call_cap = 1 + generation_cap
    binding_count = 1 if method == MODULE.DUALCAP else 0
    return {
        "method": method,
        "seed": seed,
        "root_seed": seed,
        "split": "development",
        "evidence_class": "development",
        "map_id": "warehouse_dev",
        "workload": workload,
        "manifest_id": f"manifest-{suffix}",
        "num_task_finished": tasks,
        "throughput_per_timestep": tasks / HORIZON,
        "scored_horizon": HORIZON,
        "decision_window": 20,
        "window_count": WINDOW_COUNT,
        "mandatory_bootstrap_calls": 1,
        "post_bootstrap_publication_count": contract["switches"],
        "post_bootstrap_generation_count": contract["generations"],
        "post_bootstrap_reactivation_count": contract["reactivations"],
        "effective_guidance_switch_count": contract["switches"],
        "publication_budget": contract["registered"],
        "budget_violation_count": 0,
        "generator_calls": calls,
        "budget": {
            "mandatory_bootstrap_calls": 1,
            "post_bootstrap_budget": contract["registered"],
            "effective_guidance_switch_cap": switch_cap,
            "post_bootstrap_generation_cap": generation_cap,
            "total_generator_call_cap": total_call_cap,
            "post_bootstrap_publication_count": contract["switches"],
            "post_bootstrap_generation_count": contract["generations"],
            "post_bootstrap_reactivation_count": contract["reactivations"],
            "effective_guidance_switch_count": contract["switches"],
            "total_generator_calls": calls,
            "generation_cap_candidate_suppression_count": binding_count,
            "generation_cap_block_count": binding_count,
            "generation_cap_binding_count": binding_count,
            "generation_cap_binding_audit_satisfied": True,
            "budget_violation_attempts": 0,
            "budget_semantics": contract["semantics"],
            "cap_satisfied": True,
            "switch_cap_satisfied": True,
            "generation_cap_satisfied": True,
            "total_generator_call_cap_satisfied": True,
            "exact_quota_required": contract["exact"],
            "exact_quota_satisfied": contract["exact"],
        },
        "safety": {
            "collision_count": 0,
            "edge_swap_count": 0,
            "endpoint_mismatch_count": 0,
            "invalid_move_count": 0,
            "planner_timeout_count": 0,
            "route_trace_invalid_count": 0,
            "passed": True,
        },
        "invariants": {
            "passed": True,
            "online_workload_rng_draws": 0,
            "tape_not_exhausted": True,
            "reward_sum_matches_completed": True,
            "unexposed_completions_excluded_from_cohorts": True,
        },
        "cohort_attribution_audit": {
            # This counter covers warmup too and can exceed scored completions.
            "route_exposed_completion_count": tasks + 10,
            "unexposed_zero_route_completion_count": 0,
            "unexposed_zero_route_completions_excluded": True,
            "route_build_reason_counts": {
                "init_pp": 2,
                "task_change": 100,
                "inherited_goal_route": 3,
            },
        },
        "route_build_reason_counts": {
            "init_pp": 2,
            "task_change": 100,
            "inherited_goal_route": 3,
        },
        "task_tape_identity": {
            "mode": "absolute_release_queue_per_agent",
            "manifest_sha256": f"tape-{suffix}",
        },
        "final_task_tape_prefixes": {
            "released_prefix_lengths": [10, 10],
            "assigned_prefix_lengths": [tasks % 11, tasks % 13],
            "completed_prefix_lengths": [tasks % 7, tasks % 17],
        },
        "reset_causal_fingerprint": f"reset-{suffix}",
        "release_projection_fingerprint": f"release-{suffix}",
        "distribution_update_fingerprint": f"distribution-{suffix}",
        "publication_timeline": _timeline(method),
        "timing_evidence_valid": False,
    }


def _artifact():
    runs = []
    workload_bonus = {"stationary": 0, "abrupt": 5, "recurrent": 10}
    for seed_index, seed in enumerate(SEEDS):
        for workload in WORKLOADS:
            exact = 1000 + seed_index + workload_bonus[workload]
            tasks = {
                MODULE.EXACT: exact,
                MODULE.BOOTSTRAP: exact - 50,
                MODULE.CONTEXT: exact - 1,
                MODULE.DUALCAP: exact - 2,
            }
            for method in MODULE.TARGET_METHODS:
                runs.append(_run(method, seed, workload, tasks[method]))
    return {
        "schema": MODULE.SOURCE_SCHEMA,
        "status": "complete",
        "split": "development",
        "evidence_class": "development",
        "seeds": list(SEEDS),
        "methods": list(MODULE.TARGET_METHODS),
        "workloads": list(WORKLOADS),
        "map_id": "warehouse_dev",
        "runs": runs,
    }


def _find(artifact, method, seed=SEEDS[0], workload="stationary"):
    return next(
        run
        for run in artifact["runs"]
        if run["method"] == method
        and run["seed"] == seed
        and run["workload"] == workload
    )


class ContextDualCapDev10AnalysisTests(unittest.TestCase):
    def test_clean_dev10_passes_and_only_nominates_fresh_validation(self):
        artifact = _artifact()
        before = copy.deepcopy(artifact)
        report = MODULE.analyze(
            artifact, source_sha256="fixture", bootstrap_samples=500
        )
        self.assertEqual(artifact, before)
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(report["design"]["paired_cells_per_method"], 30)
        self.assertEqual(report["design"]["n_root_seed_clusters"], 10)
        self.assertEqual(report["design"]["total_runs"], 120)
        self.assertTrue(report["screening"]["passed"])
        self.assertEqual(
            report["screening"]["recommendation"],
            "GO_FREEZE_CANDIDATE_FOR_FRESH_VALIDATION_ONLY",
        )
        self.assertTrue(
            report["screening"]["development_only_no_paper_or_sota_claim"]
        )
        self.assertGreaterEqual(
            report["screening"]["resource_effects"][
                "generator_call_reduction_vs_exact"
            ],
            0.80,
        )

    def test_comparisons_keep_three_cells_in_each_root_cluster(self):
        report = MODULE.analyze(
            _artifact(), source_sha256="fixture", bootstrap_samples=200
        )
        for comparator in MODULE.COMPARATORS:
            comparison = report["comparisons"][comparator]
            self.assertEqual(comparison["n_paired_cells"], 30)
            self.assertEqual(comparison["n_root_seed_clusters"], 10)
            self.assertEqual(comparison["cells_per_root_seed_cluster"], 3)
            self.assertEqual(
                comparison["exact_sign_flip"]["assignments"], 1024
            )
            self.assertEqual(
                set(comparison["workload_strata"]), set(WORKLOADS)
            )

    def test_non_development_source_is_rejected(self):
        artifact = _artifact()
        artifact["split"] = "validation_v2"
        with self.assertRaisesRegex(MODULE.DualCapArtifactError, "development"):
            MODULE.analyze(artifact, source_sha256="fixture", bootstrap_samples=20)

    def test_incomplete_four_method_grid_is_rejected(self):
        artifact = _artifact()
        artifact["runs"].pop()
        with self.assertRaisesRegex(MODULE.DualCapArtifactError, "120 runs"):
            MODULE.analyze(artifact, source_sha256="fixture", bootstrap_samples=20)

    def test_cross_method_fingerprint_mismatch_fails_audit(self):
        artifact = _artifact()
        _find(artifact, MODULE.DUALCAP)["distribution_update_fingerprint"] = "mismatch"
        report = MODULE.analyze(
            artifact, source_sha256="fixture", bootstrap_samples=20
        )
        self.assertFalse(report["audit"]["passed"])
        self.assertFalse(report["audit"]["paired_exogenous_inputs_match"])
        self.assertIn(
            "paired_distribution_update_fingerprint",
            {failure["check"] for failure in report["audit"]["failures"]},
        )

    def test_timeout_is_a_hard_dev10_audit_failure(self):
        artifact = _artifact()
        _find(artifact, MODULE.DUALCAP)["safety"]["planner_timeout_count"] = 1
        report = MODULE.analyze(
            artifact, source_sha256="fixture", bootstrap_samples=20
        )
        self.assertFalse(report["audit"]["passed"])
        self.assertEqual(report["screening"]["recommendation"], "NO_GO_FIX_DEV10_AUDIT")
        self.assertEqual(report["audit"]["totals"]["planner_timeout_count"], 1)

    def test_binding_may_never_exceed_candidate_suppression(self):
        artifact = _artifact()
        run = _find(artifact, MODULE.DUALCAP)
        run["budget"]["generation_cap_candidate_suppression_count"] = 0
        report = MODULE.analyze(
            artifact, source_sha256="fixture", bootstrap_samples=20
        )
        checks = {failure["check"] for failure in report["audit"]["failures"]}
        self.assertIn("binding_not_greater_than_candidate", checks)
        self.assertIn("timeline_candidate_count_match", checks)
        self.assertFalse(report["audit"]["budget_and_dualcap_contracts_passed"])

    def test_one_nonpositive_bootstrap_root_fails_direction_gate(self):
        artifact = _artifact()
        for workload in WORKLOADS:
            bootstrap = _find(artifact, MODULE.BOOTSTRAP, SEEDS[0], workload)
            dualcap = _find(artifact, MODULE.DUALCAP, SEEDS[0], workload)
            dualcap["num_task_finished"] = bootstrap["num_task_finished"]
            dualcap["throughput_per_timestep"] = (
                dualcap["num_task_finished"] / HORIZON
            )
        report = MODULE.analyze(
            artifact, source_sha256="fixture", bootstrap_samples=200
        )
        self.assertTrue(report["audit"]["passed"])
        self.assertFalse(
            report["screening"]["checks"][
                "vs_bootstrap_all_10_root_directions_positive"
            ]
        )
        self.assertEqual(
            report["screening"]["recommendation"],
            "NO_GO_DUALCAP_DEVELOPMENT_SCREEN_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
