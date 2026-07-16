import json
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dai_lmapf.claim_runner import (
    AVAILABLE_METHODS,
    CONTEXT_DUALCAP_METHOD,
    CONTEXT_DUALCAP_POST_GENERATION_CAP,
    CONTEXT_DUALCAP_SWITCH_CAP,
    CONTEXT_EVENTRESERVE_METHOD,
    CONTEXT_EVENTRESERVE_POST_GENERATION_CAP,
    CONTEXT_EVENTRESERVE_SWITCH_CAP,
    CausalFeatureSnapshot,
    CausalFeatureTracker,
    DEVELOPMENT_ONLY_METHODS,
    EXACT_BUDGET_METHODS,
    REGISTERED_METHODS,
    SCORE_METHODS,
    audit_joint_paths,
    b25_budget,
    decision_to_dict,
    make_exact_policy,
    method_budget,
    method_generation_cap,
    period_80_refresh,
    score_for_method,
)


WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT_PATH = WORKSPACE / "scripts" / "run_claim_aware_budgeted_validation.py"
SPEC = importlib.util.spec_from_file_location("claim_validation_runner", SCRIPT_PATH)
SCRIPT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SCRIPT)


def _trace(
    *,
    tasks,
    active,
    paths,
    events,
    builds,
):
    return {
        "curr_tasks": tasks,
        "curr_task_active": active,
        "actual_paths": paths,
        "recent_events": events,
        "recent_route_builds": builds,
    }


class RegisteredBudgetTests(unittest.TestCase):
    def test_b25_excludes_bootstrap_at_both_formal_and_smoke_horizons(self) -> None:
        self.assertEqual(b25_budget(100), 25)
        self.assertEqual(b25_budget(30), 8)
        self.assertEqual(method_budget("always", 100), 99)
        self.assertEqual(method_budget("bootstrap_only", 100), 0)
        self.assertIsNone(method_budget("period_80", 100))

    def test_exact_methods_only_select_global_indices_one_through_n_minus_one(self) -> None:
        for method in (
            "bootstrap_only",
            "always",
            "exact_even_B25",
            "random_B25",
            "js_B25",
            "throughput_drop_B25",
            "causal_block_B25",
            "proposed_cohort_B25",
            "proposed_no_cohort_B25",
        ):
            policy = make_exact_policy(
                method, num_scored_windows=30, policy_seed=17
            )
            assert policy is not None
            accepted = []
            for global_index in range(1, 30):
                score = 0.5 if method.endswith("B25") and method not in {
                    "exact_even_B25", "random_B25"
                } else None
                if method == "causal_block_B25":
                    decision = policy.select(score=score, route_mature=True)
                else:
                    decision = policy.select(score=score)
                if decision.accepted:
                    accepted.append(global_index)
            policy.finalize()
            self.assertNotIn(0, accepted)
            self.assertEqual(len(accepted), method_budget(method, 30))

    def test_formal_exact_even_global_schedule_matches_protocol(self) -> None:
        policy = make_exact_policy(
            "exact_even_B25", num_scored_windows=100, policy_seed=0
        )
        assert policy is not None
        selected = [
            decision_index
            for decision_index in range(1, 100)
            if policy.select().accepted
        ]
        policy.finalize()
        self.assertEqual(
            selected,
            [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52,
             56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 96, 99],
        )

    def test_nominal_period_80_is_not_falsely_called_b25(self) -> None:
        selected = [
            index for index in range(100) if period_80_refresh(index, 20)
        ]
        self.assertEqual(selected, list(range(4, 97, 4)))
        self.assertEqual(len(selected), 24)

    def test_all_requested_method_names_are_stable(self) -> None:
        self.assertEqual(len(REGISTERED_METHODS), 13)
        self.assertIn("causal_block_B25", REGISTERED_METHODS)
        self.assertIn("js_cap_B25", REGISTERED_METHODS)
        self.assertIn("context_memory_B25", REGISTERED_METHODS)
        self.assertNotIn("random_memory_B25", REGISTERED_METHODS)
        self.assertNotIn(CONTEXT_DUALCAP_METHOD, REGISTERED_METHODS)
        self.assertNotIn(CONTEXT_EVENTRESERVE_METHOD, REGISTERED_METHODS)
        self.assertEqual(
            DEVELOPMENT_ONLY_METHODS,
            (
                "random_memory_B25",
                CONTEXT_DUALCAP_METHOD,
                CONTEXT_EVENTRESERVE_METHOD,
            ),
        )
        self.assertEqual(len(AVAILABLE_METHODS), 16)
        self.assertIn("random_memory_B25", AVAILABLE_METHODS)
        self.assertIn(CONTEXT_DUALCAP_METHOD, AVAILABLE_METHODS)
        self.assertIn(CONTEXT_EVENTRESERVE_METHOD, AVAILABLE_METHODS)
        self.assertIn("proposed_cohort_B25", REGISTERED_METHODS)
        self.assertIn("uniform", REGISTERED_METHODS)

    def test_random_memory_shares_random_opportunities_but_is_at_most(self) -> None:
        self.assertNotIn("random_memory_B25", EXACT_BUDGET_METHODS)
        self.assertEqual(
            SCRIPT._publication_policy_seed(17, "random_memory_B25"),
            SCRIPT._publication_policy_seed(17, "random_B25"),
        )
        policy_seed = SCRIPT._publication_policy_seed(17, "random_B25")
        schedules = []
        for method in ("random_B25", "random_memory_B25"):
            policy = make_exact_policy(
                method, num_scored_windows=100, policy_seed=policy_seed
            )
            assert policy is not None
            schedules.append([
                index
                for index in range(1, 100)
                if policy.select().accepted
            ])
            policy.finalize()
        self.assertEqual(schedules[0], schedules[1])
        self.assertEqual(len(schedules[0]), 25)

    def test_context_dualcap_restores_g4_s5_comparator_contract(self) -> None:
        self.assertEqual(CONTEXT_DUALCAP_POST_GENERATION_CAP, 4)
        self.assertEqual(CONTEXT_DUALCAP_SWITCH_CAP, 5)
        self.assertNotIn(CONTEXT_DUALCAP_METHOD, EXACT_BUDGET_METHODS)
        self.assertIn(CONTEXT_DUALCAP_METHOD, SCORE_METHODS)
        self.assertEqual(method_budget(CONTEXT_DUALCAP_METHOD, 100), 5)
        self.assertEqual(method_generation_cap(CONTEXT_DUALCAP_METHOD, 100), 4)
        policy = make_exact_policy(
            CONTEXT_DUALCAP_METHOD,
            num_scored_windows=100,
            policy_seed=17,
        )
        assert policy is not None
        self.assertEqual(policy.budget, 5)
        accepted = [
            policy.select(
                score=1.0,
                action_available=True,
                route_mature=True,
                maintenance_due=True,
            ).accepted
            for _ in range(99)
        ]
        policy.finalize()
        self.assertEqual(sum(accepted), 5)
        self.assertEqual(1 + method_generation_cap(CONTEXT_DUALCAP_METHOD, 100), 5)

    def test_context_dualcap_generation_cap_is_fresh_only_and_off_by_one(self) -> None:
        self.assertEqual(
            SCRIPT._apply_hard_generation_cap(
                "generate", post_generations=3, generation_cap=4
            ),
            ("generate", False),
        )
        self.assertEqual(
            SCRIPT._apply_hard_generation_cap(
                "generate", post_generations=4, generation_cap=4
            ),
            ("hold", True),
        )
        self.assertEqual(
            SCRIPT._apply_hard_generation_cap(
                "reactivate", post_generations=4, generation_cap=4
            ),
            ("reactivate", False),
        )

    def test_context_dualcap_binding_preview_is_causal_and_nonmutating(self) -> None:
        policy = make_exact_policy(
            CONTEXT_DUALCAP_METHOD,
            num_scored_windows=100,
            policy_seed=17,
            minimum_history=1,
            context_min_gap=0,
            context_min_score=0.0,
        )
        assert policy is not None
        policy.select(
            score=0.0,
            action_available=False,
            route_mature=True,
            maintenance_due=False,
        )
        for rank in range(1, 5):
            self.assertTrue(policy.select(
                score=float(rank),
                action_available=True,
                route_mature=True,
                maintenance_due=False,
            ).accepted)
        state_before = (
            policy.epoch,
            policy.spent,
            tuple(policy.score_history),
        )
        operation, candidate, binding = SCRIPT._resolve_context_generation_cap(
            policy,
            proposed_operation="generate",
            post_generations=4,
            generation_cap=4,
            score=5.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertEqual((operation, candidate, binding), ("hold", True, True))
        self.assertEqual(
            state_before,
            (policy.epoch, policy.spent, tuple(policy.score_history)),
        )
        actual = policy.select(
            score=5.0,
            action_available=False,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertFalse(actual.accepted)
        self.assertEqual(policy.spent, 4)

    def test_context_eventreserve_has_g5_s6_and_bootstrap_is_outside_caps(self) -> None:
        self.assertEqual(CONTEXT_EVENTRESERVE_POST_GENERATION_CAP, 5)
        self.assertEqual(CONTEXT_EVENTRESERVE_SWITCH_CAP, 6)
        self.assertNotIn(CONTEXT_EVENTRESERVE_METHOD, EXACT_BUDGET_METHODS)
        self.assertIn(CONTEXT_EVENTRESERVE_METHOD, SCORE_METHODS)
        self.assertEqual(method_budget(CONTEXT_EVENTRESERVE_METHOD, 100), 6)
        self.assertEqual(
            method_generation_cap(CONTEXT_EVENTRESERVE_METHOD, 100), 5
        )
        self.assertEqual(method_generation_cap("exact_even_B25", 100), 25)

        policy = make_exact_policy(
            CONTEXT_EVENTRESERVE_METHOD,
            num_scored_windows=100,
            policy_seed=17,
        )
        assert policy is not None
        self.assertEqual(policy.budget, 6)
        accepted = [
            policy.select(
                score=1.0,
                action_available=True,
                route_mature=True,
                maintenance_due=True,
            ).accepted
            for _ in range(99)
        ]
        policy.finalize()
        self.assertEqual(sum(accepted), 6)

        # Bootstrap is mandatory but is charged to neither post cap.  Hence
        # G5 implies a hard total of six generator calls, while S6 remains a
        # separate cap over generate + reactivate.
        post_generation_cap = method_generation_cap(
            CONTEXT_EVENTRESERVE_METHOD, 100
        )
        self.assertEqual(1 + post_generation_cap, 6)

    @staticmethod
    def _eventreserve_policy_with_switches(count: int):
        policy = make_exact_policy(
            CONTEXT_EVENTRESERVE_METHOD,
            num_scored_windows=100,
            policy_seed=17,
            minimum_history=1,
            context_min_gap=0,
            context_min_score=0.0,
        )
        assert policy is not None
        warmup = policy.select(
            score=0.0,
            action_available=False,
            route_mature=True,
            maintenance_due=False,
        )
        assert not warmup.accepted
        for rank in range(1, count + 1):
            decision = policy.select(
                score=float(rank),
                action_available=True,
                route_mature=True,
                maintenance_due=False,
            )
            assert decision.accepted
            assert decision.triggered
        assert policy.spent == count
        return policy

    def test_context_eventreserve_reuses_context_score(self) -> None:
        snapshot = CausalFeatureSnapshot(
            goal_js_since_publication=0.0,
            released_goal_js_recent_vs_history=0.0,
            edge_flow_js_since_publication=0.0,
            recent_throughput_drop_per_agent=0.0,
            recent_wait_ratio=0.0,
            guidance_age_windows=0,
            guidance_age_fraction=0.0,
            recent_route_builds_per_agent=0.0,
            current_version_route_fraction=0.0,
            current_version_maturity=0.0,
            current_cohort_service_degradation=0.0,
            js_score=0.0,
            throughput_drop_score=0.0,
            proposed_no_cohort_score=0.0,
            proposed_cohort_score=0.0,
            causal_block_score=0.42,
        )
        self.assertEqual(
            score_for_method(CONTEXT_EVENTRESERVE_METHOD, snapshot),
            score_for_method("context_memory_B25", snapshot),
        )
        self.assertEqual(
            score_for_method(CONTEXT_DUALCAP_METHOD, snapshot),
            score_for_method("context_memory_B25", snapshot),
        )

    def test_eventreserve_g5_off_by_one_and_preview_is_nonmutating(self) -> None:
        policy = self._eventreserve_policy_with_switches(4)
        state_before = (
            policy.epoch,
            policy.spent,
            tuple(policy.score_history),
        )
        fifth = SCRIPT._resolve_context_eventreserve(
            policy,
            proposed_operation="generate",
            post_generations=4,
            post_switches=4,
            generation_cap=5,
            switch_cap=6,
            score=5.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertEqual(fifth["effective_operation"], "generate")
        self.assertFalse(fifth["generation_cap_candidate"])
        self.assertFalse(fifth["constraint_binding"])
        self.assertEqual(
            state_before,
            (policy.epoch, policy.spent, tuple(policy.score_history)),
        )
        self.assertTrue(policy.select(
            score=5.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        ).accepted)

        sixth_fresh = SCRIPT._resolve_context_eventreserve(
            policy,
            proposed_operation="generate",
            post_generations=5,
            post_switches=5,
            generation_cap=5,
            switch_cap=6,
            score=6.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertTrue(sixth_fresh["generation_cap_candidate"])
        self.assertTrue(sixth_fresh["generation_cap_binding"])
        self.assertEqual(sixth_fresh["effective_operation"], "hold")

    def test_eventreserve_sixth_switch_allows_fresh_event_generation(self) -> None:
        policy = self._eventreserve_policy_with_switches(5)
        resolution = SCRIPT._resolve_context_eventreserve(
            policy,
            proposed_operation="generate",
            post_generations=4,
            post_switches=5,
            generation_cap=5,
            switch_cap=6,
            score=6.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertTrue(resolution["reserve_active"])
        self.assertTrue(resolution["reserve_candidate"])
        self.assertTrue(resolution["reserve_preview_accepted"])
        self.assertTrue(resolution["reserve_preview_triggered"])
        self.assertTrue(resolution["reserve_event_preview_accepted"])
        self.assertTrue(resolution["reserve_event_preview_triggered"])
        self.assertTrue(resolution["reserve_qualified"])
        self.assertFalse(resolution["reserve_binding"])
        self.assertEqual(resolution["effective_operation"], "generate")
        actual = policy.select(
            score=6.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertTrue(actual.accepted)
        self.assertEqual(policy.spent, 6)

    def test_eventreserve_sixth_rejects_reactivation_and_maintenance_only(self) -> None:
        recall_policy = self._eventreserve_policy_with_switches(5)
        recall = SCRIPT._resolve_context_eventreserve(
            recall_policy,
            proposed_operation="reactivate",
            post_generations=3,
            post_switches=5,
            generation_cap=5,
            switch_cap=6,
            score=6.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertTrue(recall["reserve_preview_accepted"])
        self.assertFalse(recall["reserve_qualified"])
        self.assertTrue(recall["reserve_binding"])
        self.assertEqual(recall["effective_operation"], "hold")

        maintenance_policy = self._eventreserve_policy_with_switches(5)
        maintenance = SCRIPT._resolve_context_eventreserve(
            maintenance_policy,
            proposed_operation="generate",
            post_generations=4,
            post_switches=5,
            generation_cap=5,
            switch_cap=6,
            score=0.0,
            action_available=True,
            route_mature=True,
            maintenance_due=True,
        )
        self.assertTrue(maintenance["reserve_preview_accepted"])
        self.assertTrue(maintenance["reserve_preview_triggered"])
        self.assertFalse(maintenance["reserve_event_preview_accepted"])
        self.assertFalse(maintenance["reserve_event_preview_triggered"])
        self.assertFalse(maintenance["reserve_qualified"])
        self.assertTrue(maintenance["reserve_binding"])
        self.assertEqual(maintenance["effective_operation"], "hold")

    def test_eventreserve_reactivation_does_not_spend_generation_cap(self) -> None:
        policy = self._eventreserve_policy_with_switches(4)
        resolution = SCRIPT._resolve_context_eventreserve(
            policy,
            proposed_operation="reactivate",
            post_generations=5,
            post_switches=4,
            generation_cap=5,
            switch_cap=6,
            score=5.0,
            action_available=True,
            route_mature=True,
            maintenance_due=False,
        )
        self.assertFalse(resolution["generation_cap_candidate"])
        self.assertFalse(resolution["constraint_binding"])
        self.assertEqual(resolution["effective_operation"], "reactivate")

    def test_score_history_warmup_decision_is_strict_json(self) -> None:
        policy = make_exact_policy(
            "js_B25", num_scored_windows=30, policy_seed=17
        )
        assert policy is not None
        payload = decision_to_dict(policy.select(score=0.0))
        self.assertEqual(payload["reason"], "history_warmup")
        self.assertIsNone(payload["threshold"])
        json.dumps(payload, allow_nan=False)

    def test_causal_block_decision_audit_is_strict_json(self) -> None:
        policy = make_exact_policy(
            "causal_block_B25", num_scored_windows=30, policy_seed=17
        )
        assert policy is not None
        payloads = []
        for epoch in range(29):
            decision = policy.select(score=float(epoch), route_mature=True)
            payload = decision_to_dict(decision)
            json.dumps(payload, allow_nan=False)
            payloads.append(payload)
        policy.finalize()
        accepted = [payload for payload in payloads if payload["accepted"]]
        self.assertEqual(len(accepted), 8)
        self.assertEqual({payload["bucket_index"] for payload in accepted}, set(range(8)))
        self.assertTrue(
            all(
                0 <= payload["bucket_end"] - payload["epoch"] <= 2
                for payload in accepted
            )
        )

    def test_js_cap_is_at_most_b25_and_strict_json(self) -> None:
        policy = make_exact_policy(
            "js_cap_B25", num_scored_windows=30, policy_seed=17
        )
        assert policy is not None
        payloads = [
            decision_to_dict(policy.select(score=0.0)) for _ in range(29)
        ]
        policy.finalize()
        self.assertEqual(sum(item["accepted"] for item in payloads), 0)
        json.dumps(payloads, allow_nan=False)

    def test_context_memory_is_at_most_b25_and_requires_an_effective_action(self) -> None:
        policy = make_exact_policy(
            "context_memory_B25", num_scored_windows=30, policy_seed=17
        )
        assert policy is not None
        payloads = [
            decision_to_dict(policy.select(
                score=1.0,
                action_available=False,
                route_mature=True,
            ))
            for _ in range(29)
        ]
        policy.finalize()
        self.assertEqual(sum(item["accepted"] for item in payloads), 0)
        json.dumps(payloads, allow_nan=False)


class CausalFeatureTrackerTests(unittest.TestCase):
    def test_consecutive_tasks_on_one_agent_each_require_first_exposure(self) -> None:
        tracker = CausalFeatureTracker(
            n_agents=1, rows=1, cols=2, total_windows=4
        )
        tracker.ingest_trace(_trace(
            tasks=[[0, 1]], active=[True], paths=["W"],
            events=[
                {"event_id": 0, "agent_id": 0, "task_id": 10,
                 "event_type": "assigned", "timestep": 0,
                 "goal_loc": [0, 1]},
                {"event_id": 1, "agent_id": 0, "task_id": 10,
                 "event_type": "finished", "timestep": 2,
                 "goal_loc": [0, 1]},
                {"event_id": 2, "agent_id": 0, "task_id": 11,
                 "event_type": "assigned", "timestep": 2,
                 "goal_loc": [0, 1]},
            ],
            builds=[
                {"event_id": 0, "agent_id": 0, "task_id": 10,
                 "publication_version": 0},
                {"event_id": 1, "agent_id": 0, "task_id": 11,
                 "publication_version": 0},
            ],
        ))
        tracker.ingest_trace(_trace(
            tasks=[[0, 1]], active=[False], paths=["W"],
            events=[
                {"event_id": 3, "agent_id": 0, "task_id": 11,
                 "event_type": "finished", "timestep": 4,
                 "goal_loc": [0, 1]},
            ],
            builds=[],
        ))
        self.assertEqual(tracker.route_exposed_completion_count, 2)

    def test_tracker_uses_route_build_version_and_drops_idle_agents(self) -> None:
        tracker = CausalFeatureTracker(
            n_agents=2, rows=2, cols=2, total_windows=10
        )
        tracker.ingest_trace(_trace(
            tasks=[[0, 1], [1, 0]],
            active=[True, True],
            paths=["W", "W"],
            events=[
                {"event_id": 0, "agent_id": 0, "task_id": 0,
                 "event_type": "assigned", "timestep": 0, "goal_loc": [0, 1]},
                {"event_id": 1, "agent_id": 1, "task_id": 1,
                 "event_type": "assigned", "timestep": 0, "goal_loc": [1, 0]},
            ],
            builds=[
                {"event_id": 0, "agent_id": 0, "task_id": 0,
                 "publication_version": 0},
                {"event_id": 1, "agent_id": 1, "task_id": 1,
                 "publication_version": 0},
            ],
        ))
        tracker.mark_publication(version=1, decision_index=0)
        first = tracker.snapshot(decision_index=1)
        self.assertEqual(first.current_version_route_fraction, 0.0)

        tracker.ingest_trace(_trace(
            tasks=[[0, 0], [1, 0]],
            active=[False, True],
            paths=["W", "W"],
            events=[
                {"event_id": 2, "agent_id": 0, "task_id": 0,
                 "event_type": "finished", "timestep": 1, "goal_loc": [0, 1]},
            ],
            builds=[],
        ))
        self.assertNotIn(0, tracker.latest_route_version)
        self.assertEqual(tracker.latest_route_version, {1: 0})

    def test_score_snapshots_are_finite_and_causal(self) -> None:
        tracker = CausalFeatureTracker(
            n_agents=1, rows=1, cols=2, total_windows=5
        )
        tracker.ingest_trace(_trace(
            tasks=[[0, 0]], active=[True], paths=["W"],
            events=[
                {"event_id": 0, "agent_id": 0, "task_id": 0,
                 "event_type": "assigned", "timestep": 0, "goal_loc": [0, 0]},
            ],
            builds=[
                {"event_id": 0, "agent_id": 0, "task_id": 0,
                 "publication_version": 0},
            ],
        ))
        tracker.mark_publication(version=1, decision_index=0)
        tracker.observe_reward(2)
        tracker.ingest_trace(_trace(
            tasks=[[0, 1]], active=[True], paths=["R"], events=[], builds=[]
        ))
        tracker.observe_reward(0)
        snapshot = tracker.snapshot(decision_index=2)
        for method in (
            "js_B25",
            "throughput_drop_B25",
            "causal_block_B25",
            "proposed_cohort_B25",
            "proposed_no_cohort_B25",
        ):
            self.assertGreaterEqual(score_for_method(method, snapshot), 0.0)
        self.assertGreater(snapshot.goal_js_since_publication, 0.0)
        self.assertGreater(snapshot.recent_throughput_drop_per_agent, 0.0)

    def test_released_goal_score_uses_only_observed_release_events(self) -> None:
        tracker = CausalFeatureTracker(
            n_agents=1, rows=4, cols=4, total_windows=8
        )
        for event_id, goal in enumerate(([0, 0], [0, 0], [3, 3])):
            tracker.ingest_trace(_trace(
                tasks=[[0, 0]],
                active=[True],
                paths=["W"],
                events=[
                    {"event_id": event_id, "agent_id": 0,
                     "task_id": 100 + event_id, "event_type": "released",
                     "timestep": event_id, "goal_loc": goal},
                ],
                builds=[],
            ))
        snapshot = tracker.snapshot(decision_index=3)
        self.assertGreater(snapshot.released_goal_js_recent_vs_history, 0.0)
        self.assertEqual(
            snapshot.causal_block_score,
            snapshot.released_goal_js_recent_vs_history,
        )
        self.assertEqual(
            score_for_method("causal_block_B25", snapshot),
            snapshot.released_goal_js_recent_vs_history,
        )

    def test_new_assignment_clears_stale_route_until_its_own_build(self) -> None:
        tracker = CausalFeatureTracker(
            n_agents=1, rows=1, cols=2, total_windows=4
        )
        tracker.mark_publication(version=1, decision_index=0)
        tracker.ingest_trace(_trace(
            tasks=[[0, 1]], active=[True], paths=["W"],
            events=[
                {"event_id": 0, "agent_id": 0, "task_id": 10,
                 "event_type": "assigned", "timestep": 0,
                 "goal_loc": [0, 1]},
            ],
            builds=[
                {"event_id": 0, "agent_id": 0, "task_id": 10,
                 "publication_version": 1, "reason": "first_task_exposure"},
            ],
        ))
        self.assertEqual(tracker.latest_route_version, {0: 1})
        self.assertEqual(
            dict(tracker.route_build_reason_counts), {"first_task_exposure": 1}
        )

        tracker.ingest_trace(_trace(
            tasks=[[0, 0]], active=[True], paths=["W"],
            events=[
                {"event_id": 1, "agent_id": 0, "task_id": 10,
                 "event_type": "finished", "timestep": 2,
                 "goal_loc": [0, 1]},
                {"event_id": 2, "agent_id": 0, "task_id": 11,
                 "event_type": "assigned", "timestep": 2,
                 "goal_loc": [0, 0]},
            ],
            builds=[],
        ))
        self.assertEqual(tracker.active_task_by_agent, {0: 11})
        self.assertNotIn(0, tracker.latest_route_version)
        self.assertEqual(
            tracker.snapshot(decision_index=1).current_version_route_fraction,
            0.0,
        )

    def test_zero_route_minimum_latency_completion_is_counted_not_attributed(self) -> None:
        tracker = CausalFeatureTracker(
            n_agents=1, rows=1, cols=1, total_windows=2
        )
        trace = _trace(
            tasks=[[0, 0]], active=[False], paths=["W"],
            events=[
                {"event_id": 0, "agent_id": 0, "task_id": 7,
                 "event_type": "assigned", "timestep": 10, "goal_loc": [0, 0]},
                {"event_id": 1, "agent_id": 0, "task_id": 7,
                 "event_type": "finished", "timestep": 11, "goal_loc": [0, 0]},
            ],
            builds=[],
        )
        trace["route_build_trace_valid"] = True
        tracker.ingest_trace(trace)
        self.assertEqual(tracker.unexposed_zero_route_completion_count, 1)
        self.assertEqual(tracker.route_exposed_completion_count, 0)
        self.assertFalse(tracker.service_by_version)

    def test_missing_assignment_or_nonminimum_unexposed_completion_is_fatal(self) -> None:
        missing = CausalFeatureTracker(n_agents=1, rows=1, cols=1, total_windows=2)
        trace = _trace(
            tasks=[[0, 0]], active=[False], paths=["W"],
            events=[{"event_id": 0, "agent_id": 0, "task_id": 7,
                     "event_type": "finished", "timestep": 1, "goal_loc": [0, 0]}],
            builds=[],
        )
        trace["route_build_trace_valid"] = True
        with self.assertRaisesRegex(ValueError, "lacks assignment"):
            missing.ingest_trace(trace)

        delayed = CausalFeatureTracker(n_agents=1, rows=1, cols=1, total_windows=2)
        trace = _trace(
            tasks=[[0, 0]], active=[False], paths=["W"],
            events=[
                {"event_id": 0, "agent_id": 0, "task_id": 8,
                 "event_type": "assigned", "timestep": 1, "goal_loc": [0, 0]},
                {"event_id": 1, "agent_id": 0, "task_id": 8,
                 "event_type": "finished", "timestep": 3, "goal_loc": [0, 0]},
            ], builds=[],
        )
        trace["route_build_trace_valid"] = True
        with self.assertRaisesRegex(ValueError, "lacks route exposure"):
            delayed.ingest_trace(trace)


class SafetyAuditTests(unittest.TestCase):
    def test_clean_joint_move_passes(self) -> None:
        audit = audit_joint_paths(
            start_positions=[[0, 0], [1, 0]],
            actual_paths=["R", "R"],
            end_positions=[[0, 1], [1, 1]],
            graph=[[0, 0], [0, 0]],
        )
        self.assertTrue(audit.passed)

    def test_vertex_collision_and_swap_are_detected(self) -> None:
        collision = audit_joint_paths(
            start_positions=[[0, 0], [0, 2]],
            actual_paths=["R", "L"],
            end_positions=[[0, 1], [0, 1]],
            graph=[[0, 0, 0]],
        )
        self.assertEqual(collision.collision_count, 1)
        swap = audit_joint_paths(
            start_positions=[[0, 0], [0, 1]],
            actual_paths=["R", "L"],
            end_positions=[[0, 1], [0, 0]],
            graph=[[0, 0]],
        )
        self.assertEqual(swap.edge_swap_count, 1)
        self.assertFalse(swap.passed)

    def test_endpoint_mismatch_is_a_failure(self) -> None:
        audit = audit_joint_paths(
            start_positions=[[0, 0]], actual_paths=["R"],
            end_positions=[[0, 0]], graph=[[0, 0]],
        )
        self.assertEqual(audit.endpoint_mismatch_count, 1)
        self.assertFalse(audit.passed)


class WorkloadClockTests(unittest.TestCase):
    @staticmethod
    def _map():
        return SimpleNamespace(
            rows=1, cols=101, endpoint_locations=(0, 25, 50, 75, 100)
        )

    def test_dynamic_phase_clock_includes_warmup(self) -> None:
        starts, scored, centres, adjacent_js = SCRIPT._phase_plan(
            workload="abrupt",
            warmup_time=200,
            horizon=2000,
            kiva_map=self._map(),
            sigma=0.75,
            seed=17,
        )
        self.assertEqual(scored, [500, 1000, 1500])
        self.assertEqual(starts, [0, 700, 1200, 1700])
        self.assertEqual(len(set(centres)), 4)
        self.assertTrue(all(value >= 0.30 for value in adjacent_js))

    def test_recurrent_centres_return_to_a(self) -> None:
        _, _, centres, adjacent_js = SCRIPT._phase_plan(
            workload="recurrent",
            warmup_time=200,
            horizon=2000,
            kiva_map=self._map(),
            sigma=0.75,
            seed=17,
        )
        self.assertEqual(centres[0], centres[2])
        self.assertEqual(centres[1], centres[3])
        self.assertTrue(all(value >= 0.30 for value in adjacent_js))

    def test_release_schedule_is_staggered_and_has_guard_suffix(self) -> None:
        schedules, metadata = SCRIPT._staggered_release_schedules(
            n_agents=400, total_steps=2200, interval=110, guard_suffix=4
        )
        self.assertEqual(len(schedules), 400)
        self.assertLessEqual(metadata["maximum_regular_arrivals_in_one_timestep"], 4)
        self.assertAlmostEqual(
            metadata["nominal_arrival_rate_tasks_per_timestep"], 400 / 110
        )
        self.assertEqual(metadata["guard_suffix_tasks_per_agent"], 4)
        self.assertTrue(
            all(schedule[-4:] == [2199, 2199, 2199, 2199] for schedule in schedules)
        )

    def test_release_guard_rejects_less_than_four_tasks(self) -> None:
        for guard_suffix in (0, 1, 2, 3):
            with self.assertRaises(ValueError):
                SCRIPT._staggered_release_schedules(
                    n_agents=4,
                    total_steps=20,
                    interval=5,
                    guard_suffix=guard_suffix,
                )

    def test_absolute_v1_guard_does_not_expect_nonexistent_exhausted_field(self) -> None:
        tape = {
            "per_agent_lengths": [10, 11],
            "assigned_prefix_lengths": [9, 9],
            "all_released": True,
            "all_completed": False,
        }
        self.assertTrue(SCRIPT._absolute_tape_has_unassigned_guard(tape))
        tape["assigned_prefix_lengths"] = [10, 9]
        self.assertFalse(SCRIPT._absolute_tape_has_unassigned_guard(tape))

    def test_release_projection_ignores_treatment_dependent_global_event_ids(self) -> None:
        first = {"recent_events": [
            {"event_id": 4, "agent_id": 1, "task_id": 11,
             "event_type": "released", "timestep": 7, "goal_loc": [0, 2]},
            {"event_id": 5, "agent_id": 0, "task_id": 3,
             "event_type": "assigned", "timestep": 7, "goal_loc": [0, 1]},
        ]}
        second = {"recent_events": [
            {"event_id": 99, "agent_id": 1, "task_id": 11,
             "event_type": "released", "timestep": 7, "goal_loc": [0, 2]},
        ]}
        self.assertEqual(
            SCRIPT._release_records(first), SCRIPT._release_records(second)
        )

    def test_protected_seed_sets_cannot_be_peeked_in_subsets(self) -> None:
        with self.assertRaises(ValueError):
            SCRIPT._validate_split("validation", [101, 102], False)
        SCRIPT._validate_split("validation", list(range(101, 111)), False)
        self.assertEqual(
            SCRIPT._canonical_split("validation"),
            "contaminated_pilot_validation",
        )
        expected_v2 = [
            320019, 241771, 827130, 693142, 741084,
            12102, 133633, 876480, 50620, 131545,
        ]
        self.assertEqual(list(SCRIPT.VALIDATION_V2_SEEDS), expected_v2)
        with self.assertRaises(ValueError):
            SCRIPT._validate_split("validation_v2", expected_v2[:-1], False)
        SCRIPT._validate_split("validation_v2", expected_v2, False)
        with self.assertRaises(ValueError):
            SCRIPT._validate_split("locked_test", list(range(1001, 1031)), False)
        SCRIPT._validate_split("locked_test", list(range(1001, 1031)), True)

    def test_validation_v2_requires_formal_family_and_all_workloads(self) -> None:
        SCRIPT._validate_protocol_matrix(
            "validation_v2", REGISTERED_METHODS, SCRIPT.WORKLOADS,
            REGISTERED_METHODS,
        )
        with self.assertRaisesRegex(ValueError, "registered method family"):
            SCRIPT._validate_protocol_matrix(
                "validation_v2", AVAILABLE_METHODS, SCRIPT.WORKLOADS,
                REGISTERED_METHODS,
            )
        with self.assertRaisesRegex(ValueError, "registered method family"):
            SCRIPT._validate_protocol_matrix(
                "validation_v2",
                REGISTERED_METHODS + (CONTEXT_DUALCAP_METHOD,),
                SCRIPT.WORKLOADS,
                REGISTERED_METHODS,
            )
        with self.assertRaisesRegex(ValueError, "registered method family"):
            SCRIPT._validate_protocol_matrix(
                "validation_v2",
                REGISTERED_METHODS + (CONTEXT_EVENTRESERVE_METHOD,),
                SCRIPT.WORKLOADS,
                REGISTERED_METHODS,
            )
        with self.assertRaisesRegex(ValueError, "registered method family"):
            SCRIPT._validate_protocol_matrix(
                "locked_test",
                REGISTERED_METHODS + (CONTEXT_DUALCAP_METHOD,),
                SCRIPT.WORKLOADS,
                REGISTERED_METHODS,
            )
        with self.assertRaisesRegex(ValueError, "registered method family"):
            SCRIPT._validate_protocol_matrix(
                "locked_test",
                REGISTERED_METHODS + (CONTEXT_EVENTRESERVE_METHOD,),
                SCRIPT.WORKLOADS,
                REGISTERED_METHODS,
            )
        with self.assertRaisesRegex(ValueError, "stationary, abrupt, and recurrent"):
            SCRIPT._validate_protocol_matrix(
                "validation_v2", REGISTERED_METHODS,
                ("stationary", "abrupt"), REGISTERED_METHODS,
            )
        # The screened method remains reproducible on development only.
        SCRIPT._validate_protocol_matrix(
            "development", ("exact_even_B25", "random_memory_B25"),
            SCRIPT.WORKLOADS, REGISTERED_METHODS,
        )
        SCRIPT._validate_protocol_matrix(
            "development", ("exact_even_B25", CONTEXT_DUALCAP_METHOD),
            SCRIPT.WORKLOADS, REGISTERED_METHODS,
        )
        SCRIPT._validate_protocol_matrix(
            "development", ("exact_even_B25", CONTEXT_EVENTRESERVE_METHOD),
            SCRIPT.WORKLOADS, REGISTERED_METHODS,
        )

    def test_validation_v2_output_and_sortation_are_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "artifact.json"
            existing.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "validation_v2"):
                SCRIPT._ensure_output_is_writable("validation_v2", existing)
            SCRIPT._ensure_output_is_writable("development", existing)
            existing.unlink()
            existing.with_suffix(".csv").write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "validation_v2"):
                SCRIPT._ensure_output_is_writable("validation_v2", existing)
        with self.assertRaisesRegex(ValueError, "sortation"):
            SCRIPT._validate_map_reservation(
                "validation_v2", Path("sortation_small.map")
            )
        SCRIPT._validate_map_reservation(
            "locked_test", Path("sortation_small.map")
        )

    def test_validation_v2_metadata_binds_frozen_development_sha(self) -> None:
        metadata = SCRIPT._split_protocol_metadata("validation_v2")
        self.assertEqual(metadata["canonical_name"], "validation_v2")
        self.assertEqual(
            metadata["preregistered_seeds"], list(SCRIPT.VALIDATION_V2_SEEDS)
        )
        self.assertEqual(
            metadata["seed_derivation_source_development_artifact_sha256"],
            "d971c23983bb9e2b1bc517cea0db19fd5da5bc97a16b6a2aa3a777c06b7ff9f7",
        )
        contaminated = SCRIPT._split_protocol_metadata("validation")
        self.assertEqual(
            contaminated["classification"],
            "contaminated_pilot_evidence_only",
        )


if __name__ == "__main__":
    unittest.main()
