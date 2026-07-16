import copy
import importlib.util
import math
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "analyze_combined_validation_v2.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_combined_validation_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


METHOD_TASKS = {
    "uniform": 700,
    "bootstrap_only": 950,
    "always": 990,
    "exact_even_B25": 1000,
    "period_80": 985,
    "random_B25": 1005,
    "js_B25": 992,
    "js_cap_B25": 994,
    "causal_block_B25": 1020,
    "context_memory_B25": 998,
    "throughput_drop_B25": 991,
    "proposed_cohort_B25": 993,
    "proposed_no_cohort_B25": 996,
    "random_memory_B25": 1010,
}


def _method_budget(method):
    if method == "uniform":
        return 0, 0, 0, 0
    if method == "bootstrap_only":
        return 0, 0, 0, 1
    if method == "always":
        return 99, 99, 99, 100
    if method == "period_80":
        return 24, 24, 24, 25
    if method == "context_memory_B25":
        return 25, 5, 3, 4
    if method == "js_cap_B25":
        return 25, 20, 20, 21
    if method == "random_memory_B25":
        return 25, 20, 15, 16
    return 25, 25, 25, 26


def _run(method, seed, map_id, agents, workload):
    tasks = METHOD_TASKS[method]
    registered, publications, generations, generator_calls = _method_budget(method)
    reactivations = publications - generations
    suffix = f"{seed}-{map_id}-{agents}-{workload}"
    mandatory = 0 if method == "uniform" else 1
    exact = method in (
        set(MODULE.FORMAL_EXACT_B25_METHODS)
        | {"uniform", "bootstrap_only", "always"}
    )
    return {
        "method": method,
        "seed": seed,
        "root_seed": seed,
        "split": "validation_v2",
        "evidence_class": "validation_v2",
        "map_id": map_id,
        "map_path": f"/maps/{map_id}.map",
        "workload": workload,
        "manifest_id": f"manifest-{suffix}",
        "num_task_finished": tasks,
        "throughput_per_timestep": tasks / 2000,
        "scored_horizon": 2000,
        "decision_window": 20,
        "window_count": 100,
        "mandatory_bootstrap_calls": mandatory,
        "post_bootstrap_publication_count": publications,
        "post_bootstrap_generation_count": generations,
        "post_bootstrap_reactivation_count": reactivations,
        "publication_budget": registered,
        "budget_violation_count": 0,
        "generator_calls": generator_calls,
        "generator_seconds": float(generator_calls),
        "planner_timeouts": 0,
        "budget": {
            "mandatory_bootstrap_calls": mandatory,
            "post_bootstrap_budget": registered,
            "post_bootstrap_publication_count": publications,
            "post_bootstrap_generation_count": generations,
            "post_bootstrap_reactivation_count": reactivations,
            "total_generator_calls": generator_calls,
            "budget_violation_attempts": 0,
            "cap_satisfied": True,
            "generation_cap_satisfied": True,
            "exact_quota_required": exact,
            "exact_quota_satisfied": exact,
        },
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
            "tape_not_exhausted": True,
            "reward_sum_matches_completed": True,
            "unexposed_completions_excluded_from_cohorts": True,
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
        "route_build_reason_counts": {
            "init_pp": 10,
            "task_change": 20,
            "inherited_goal_route": 1,
        },
        "task_tape_identity": {
            "mode": "absolute_release_queue_per_agent",
            "manifest_sha256": f"tape-{suffix}",
        },
        "final_task_tape_prefixes": {
            "released_prefix_lengths": [5, 5],
            # Assignment/completion prefixes are endogenous and may differ.
            "assigned_prefix_lengths": [tasks % 11, tasks % 13],
            "completed_prefix_lengths": [tasks % 7, tasks % 17],
        },
        "reset_causal_fingerprint": f"reset-{suffix}",
        "release_projection_fingerprint": f"release-{suffix}",
        "distribution_update_fingerprint": f"distribution-{suffix}",
        "timing_evidence_valid": False,
    }


def _artifact(map_id, agents, *, include_random_memory=False, split="validation_v2"):
    seeds = list(MODULE.EXPECTED_VALIDATION_V2_SEEDS)
    workloads = list(MODULE.EXPECTED_WORKLOADS)
    methods = list(MODULE.EXPECTED_FORMAL_METHODS)
    if include_random_memory:
        methods.append("random_memory_B25")
    runs = [
        _run(method, seed, map_id, agents, workload)
        for seed in seeds
        for workload in workloads
        for method in methods
    ]
    evidence = split
    if split in {"validation", "contaminated_pilot_validation"}:
        seeds = list(range(101, 111))
        runs = [
            _run(method, seed, map_id, agents, workload)
            for seed in seeds
            for workload in workloads
            for method in methods
        ]
        for run in runs:
            run["split"] = split
            run["evidence_class"] = split
    return {
        "schema": MODULE.SOURCE_SCHEMA,
        "status": "complete",
        "split": split,
        "evidence_class": evidence,
        "seeds": seeds,
        "methods": methods,
        "workloads": workloads,
        "map_id": map_id,
        "map_path": f"/maps/{map_id}.map",
        "map_sha256": {
            "warehouse_small_narrow_kiva": (
                "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6"
            ),
            "warehouse_small_kiva": (
                "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd"
            ),
        }[map_id],
        "period_on_sim_sha256": MODULE.EXPECTED_SIMULATOR_SHA256,
        "split_protocol": {
            "canonical_name": "validation_v2",
            "classification": "fresh_validation_v2",
            "preregistered_seeds": list(MODULE.EXPECTED_VALIDATION_V2_SEEDS),
            "seed_derivation_source_development_artifact_sha256": (
                MODULE.EXPECTED_SOURCE_DEVELOPMENT_SHA256
            ),
            "complete_registered_method_family_required": True,
            "complete_workload_family_required": True,
            "artifact_overwrite_permitted": False,
        },
        "protocol": {
            "agents": agents,
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
                "min_gap_windows": 6,
                "maintenance_age_windows": 25,
                "maintenance_stability_gate": 0.20,
            },
            "jobs": 8,
            "timing_evidence_valid": False,
        },
        "generator": {
            "file_sha256": MODULE.EXPECTED_CHECKPOINT_FILE_SHA256,
            "params_sha256": MODULE.EXPECTED_CHECKPOINT_PARAMS_SHA256,
        },
        "runs": runs,
    }


def _matrix(*, include_random_memory=False, split="validation_v2"):
    return [
        _artifact(map_id, agents, include_random_memory=include_random_memory, split=split)
        for map_id, agents in (
            ("warehouse_small_narrow_kiva", 218),
            ("warehouse_small_narrow_kiva", 382),
            ("warehouse_small_kiva", 255),
            ("warehouse_small_kiva", 447),
        )
    ]


def _set_method_tasks(artifacts, method, tasks):
    for artifact in artifacts:
        for run in artifact["runs"]:
            if run["method"] == method:
                run["num_task_finished"] = tasks
                run["throughput_per_timestep"] = tasks / 2000


class CombinedValidationV2AnalysisTests(unittest.TestCase):
    def test_clean_matrix_clusters_twelve_cells_by_ten_root_seeds(self):
        report = MODULE.analyze_artifacts(_matrix(), bootstrap_samples=200)
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(report["design"]["n_root_seed_clusters"], 10)
        self.assertEqual(report["design"]["scenario_cells_per_method"], 120)
        self.assertEqual(
            report["design"]["cells_per_root_seed_cluster_per_method"], 12
        )
        comparison = report["registered_comparisons"]["causal_vs_exact"]
        self.assertEqual(comparison["n_root_seed_clusters"], 10)
        self.assertEqual(comparison["n_paired_scenario_cells"], 120)
        self.assertEqual(comparison["exact_sign_flip"]["assignments"], 1024)
        self.assertEqual(
            comparison["cluster_bootstrap"]["independent_unit"], "root_seed"
        )

    def test_clean_fixture_passes_validation_gates_but_timing_remains_pending(self):
        report = MODULE.analyze_artifacts(_matrix(), bootstrap_samples=100)
        gate = report["preregistered_go_no_go"]
        self.assertTrue(gate["causal_quality_go"]["passed"])
        self.assertTrue(gate["context_validation_candidate_passed"])
        self.assertFalse(gate["context_full_efficiency_claim_ready"])
        self.assertEqual(
            gate["context_full_efficiency_claim"]["status"],
            "pending_external_exclusive_timing",
        )
        self.assertEqual(
            gate["context_full_efficiency_claim"][
                "parallel_generator_seconds_classification"
            ],
            "diagnostic_only_not_eligible_for_time_gate",
        )
        self.assertTrue(gate["context_near_exact_language"]["permitted"])
        self.assertTrue(gate["pure_throughput_best_evaluated_controller"]["passed"])
        self.assertEqual(
            gate["pure_throughput_best_evaluated_controller"]["selected_top_method"],
            "causal_block_B25",
        )
        self.assertEqual(
            gate["recommendation"],
            "GO_CAUSAL_QUALITY_AND_CONTEXT_VALIDATION_CANDIDATE_PENDING_EXCLUSIVE_TIMING",
        )
        self.assertGreater(
            gate["context_validation_candidate"][
                "generator_call_reduction_vs_exact_B25"
            ],
            0.80,
        )

    def test_optional_random_memory_is_ranked_without_becoming_a_registered_test(self):
        # The frozen formal v2 family excludes this development-only method.
        # A legacy/contaminated diagnostic may still summarize it, but cannot GO.
        report = MODULE.analyze_artifacts(
            _matrix(include_random_memory=True, split="validation"),
            bootstrap_samples=50,
        )
        ranked = [row["method"] for row in report["method_macro_ranking"]]
        self.assertIn("random_memory_B25", ranked)
        compared = {
            row["candidate"]
            for row in report["registered_comparisons"].values()
        } | {
            row["comparator"]
            for row in report["registered_comparisons"].values()
        }
        self.assertNotIn("random_memory_B25", compared)

        without = MODULE.analyze_artifacts(
            _matrix(include_random_memory=False), bootstrap_samples=50
        )
        self.assertNotIn(
            "random_memory_B25",
            [row["method"] for row in without["method_macro_ranking"]],
        )

    def test_pairing_mismatch_is_a_hard_error(self):
        artifacts = _matrix()
        target = next(
            run
            for run in artifacts[0]["runs"]
            if run["method"] == "causal_block_B25"
        )
        target["release_projection_fingerprint"] = "mismatched"
        with self.assertRaisesRegex(MODULE.CombinedValidationError, "unpaired"):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_safety_failure_forces_no_go_but_remains_reportable(self):
        artifacts = _matrix()
        target = artifacts[0]["runs"][0]
        target["safety"]["passed"] = False
        target["safety"]["collision_count"] = 1
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)
        self.assertFalse(report["audit"]["passed"])
        self.assertEqual(
            report["preregistered_go_no_go"]["recommendation"],
            "NO_GO_RETURN_TO_DEVELOPMENT",
        )

    def test_legacy_validation_is_marked_contaminated_and_cannot_pass(self):
        report = MODULE.analyze_artifacts(
            _matrix(split="validation"), bootstrap_samples=20
        )
        self.assertEqual(
            report["evidence"]["source_evidence_class"],
            "contaminated_pilot_validation",
        )
        self.assertFalse(
            report["preregistered_go_no_go"]["passed_any_candidate_path"]
        )

    def test_four_artifacts_must_be_exact_map_density_cross_product(self):
        artifacts = _matrix()
        artifacts[3] = copy.deepcopy(artifacts[2])
        with self.assertRaisesRegex(
            MODULE.CombinedValidationError, "duplicate map/density"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_formal_v2_rejects_any_seed_vector_substitution(self):
        artifacts = _matrix()
        artifacts[0]["seeds"][0] += 1
        with self.assertRaisesRegex(
            MODULE.CombinedValidationError, "frozen validation-v2 seed vector"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_formal_v2_rejects_development_only_method(self):
        artifacts = _matrix()
        artifacts[0]["methods"].append("random_memory_B25")
        with self.assertRaisesRegex(
            MODULE.CombinedValidationError, "frozen 13-method family"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_formal_v2_rejects_unfrozen_scenario_or_binary_hash(self):
        for mutation, pattern in (
            (
                lambda artifacts: artifacts[0].__setitem__("map_sha256", "wrong"),
                "not a frozen validation-v2 scenario",
            ),
            (
                lambda artifacts: artifacts[0].__setitem__(
                    "period_on_sim_sha256", "wrong"
                ),
                "simulator binary SHA-256 is not frozen",
            ),
            (
                lambda artifacts: artifacts[0]["generator"].__setitem__(
                    "params_sha256", "wrong"
                ),
                "frozen 10k checkpoint",
            ),
        ):
            with self.subTest(pattern=pattern):
                artifacts = _matrix()
                mutation(artifacts)
                with self.assertRaisesRegex(MODULE.CombinedValidationError, pattern):
                    MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_formal_v2_rejects_protocol_or_amendment_drift(self):
        artifacts = _matrix()
        artifacts[0]["protocol"]["context_memory_B25"]["recall_threshold"] = 0.10
        with self.assertRaisesRegex(
            MODULE.CombinedValidationError, "recall_threshold"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_formal_v2_rejects_changed_exact_budget_semantics(self):
        artifacts = _matrix()
        target = next(
            run
            for run in artifacts[0]["runs"]
            if run["method"] == "causal_block_B25"
        )
        target["post_bootstrap_publication_count"] = 24
        target["post_bootstrap_generation_count"] = 24
        target["generator_calls"] = 25
        target["budget"]["post_bootstrap_publication_count"] = 24
        target["budget"]["post_bootstrap_generation_count"] = 24
        target["budget"]["total_generator_calls"] = 25
        with self.assertRaisesRegex(
            MODULE.CombinedValidationError, "frozen causal_block_B25 budget semantics"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_frozen_causal_effect_and_random_noninferiority_boundaries(self):
        artifacts = _matrix()
        _set_method_tasks(artifacts, "causal_block_B25", 1019)
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=50)
        causal = report["preregistered_go_no_go"]["causal_quality_go"]
        self.assertFalse(causal["passed"])
        self.assertFalse(
            causal["checks"]["mean_relative_vs_exact_at_least_plus_2pct"]
        )

        artifacts = _matrix()
        _set_method_tasks(artifacts, "random_B25", 1031)
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=50)
        causal = report["preregistered_go_no_go"]["causal_quality_go"]
        self.assertFalse(causal["passed"])
        self.assertFalse(
            causal["checks"][
                "vs_random_cluster_bootstrap_95ci_lower_strictly_above_minus_1pct"
            ]
        )

    def test_frozen_context_signal_calls_and_near_exact_boundaries(self):
        artifacts = _matrix()
        _set_method_tasks(artifacts, "context_memory_B25", 968)
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=50)
        context = report["preregistered_go_no_go"]["context_validation_candidate"]
        self.assertFalse(context["passed"])
        self.assertFalse(
            context["checks"]["mean_relative_vs_bootstrap_at_least_plus_2pct"]
        )

        artifacts = _matrix()
        for artifact in artifacts:
            for run in artifact["runs"]:
                if run["method"] == "context_memory_B25":
                    run["post_bootstrap_generation_count"] = 5
                    run["post_bootstrap_reactivation_count"] = 0
                    run["generator_calls"] = 6
                    run["generator_seconds"] = 6.0
                    run["budget"]["post_bootstrap_generation_count"] = 5
                    run["budget"]["post_bootstrap_reactivation_count"] = 0
                    run["budget"]["total_generator_calls"] = 6
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=50)
        context = report["preregistered_go_no_go"]["context_validation_candidate"]
        self.assertFalse(context["passed"])
        self.assertFalse(
            context["checks"]["b25_generator_call_reduction_at_least_80pct"]
        )

        artifacts = _matrix()
        _set_method_tasks(artifacts, "context_memory_B25", 990)
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=50)
        near_exact = report["preregistered_go_no_go"]["context_near_exact_language"]
        self.assertFalse(near_exact["permitted"])
        self.assertFalse(
            near_exact["checks"][
                "cluster_bootstrap_95ci_lower_vs_exact_strictly_above_minus_1pct"
            ]
        )

    def test_frozen_integrity_gate_requires_zero_planner_timeouts(self):
        artifacts = _matrix()
        target = artifacts[0]["runs"][0]
        target["safety"]["planner_timeout_count"] = 1
        target["planner_timeouts"] = 1
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)
        self.assertFalse(report["audit"]["integrity_gate_passed"])
        self.assertFalse(
            report["preregistered_go_no_go"]["causal_quality_go"]["passed"]
        )

    def test_frozen_integrity_gate_rejects_unknown_route_attribution_reason(self):
        artifacts = _matrix()
        target = artifacts[0]["runs"][0]
        target["route_build_reason_counts"] = {"mystery": 1}
        target["cohort_attribution_audit"]["route_build_reason_counts"] = {
            "mystery": 1
        }
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)
        self.assertGreater(report["audit"]["route_attribution_error_count"], 0)
        self.assertFalse(report["audit"]["integrity_gate_passed"])

    def test_pure_throughput_gate_rejects_an_unseparated_tie(self):
        artifacts = _matrix()
        _set_method_tasks(artifacts, "random_B25", 1020)
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=50)
        pure = report["preregistered_go_no_go"][
            "pure_throughput_best_evaluated_controller"
        ]
        self.assertFalse(pure["passed"])
        self.assertEqual(pure["runner_up_multiplicity_adjusted_ci_lower"], 0.0)

    def test_separate_exclusive_timing_can_complete_efficiency_gate(self):
        artifacts = _matrix()
        for artifact in artifacts:
            artifact["protocol"]["jobs"] = 1
            artifact["protocol"]["exclusive_timing_declared"] = True
            artifact["protocol"]["timing_evidence_valid"] = True
            for run in artifact["runs"]:
                run["timing_evidence_valid"] = True
        report = MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)
        gate = report["preregistered_go_no_go"]
        self.assertTrue(gate["context_full_efficiency_claim_ready"])
        self.assertEqual(
            gate["context_full_efficiency_claim"]["status"],
            "full_efficiency_claim_ready",
        )

        artifacts = _matrix()
        artifacts[0]["split_protocol"][
            "seed_derivation_source_development_artifact_sha256"
        ] = "wrong"
        with self.assertRaisesRegex(
            MODULE.CombinedValidationError, "frozen amendment"
        ):
            MODULE.analyze_artifacts(artifacts, bootstrap_samples=20)

    def test_canonical_contaminated_label_is_supported_but_never_goes(self):
        report = MODULE.analyze_artifacts(
            _matrix(split="contaminated_pilot_validation"),
            bootstrap_samples=20,
        )
        self.assertFalse(report["evidence"]["fresh_validation_v2"])
        self.assertFalse(
            report["preregistered_go_no_go"]["passed_any_candidate_path"]
        )

    def test_markdown_names_gate_and_pseudoreplication_guard(self):
        report = MODULE.analyze_artifacts(_matrix(), bootstrap_samples=20)
        markdown = MODULE.render_markdown(report)
        self.assertIn("Inference uses **10**, not **120**", markdown)
        self.assertIn("Preregistered validation freeze gate", markdown)
        self.assertIn("causal_vs_random", markdown)


if __name__ == "__main__":
    unittest.main()
