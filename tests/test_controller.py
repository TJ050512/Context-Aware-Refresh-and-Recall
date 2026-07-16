import math
import unittest

from dai_lmapf.controller import (
    BudgetedEventTriggeredController,
    PeriodicRefreshController,
    TrafficContext,
    WindowFeedback,
    exact_even_post_bootstrap_indices,
    post_bootstrap_publication_budget,
)


def empty_context() -> TrafficContext:
    return TrafficContext(
        active_agent_density=0.1,
        recent_throughput=1.0,
        wait_ratio=0.0,
        conflict_rate=0.0,
        maximum_to_mean_edge_load=1.0,
        edge_load_entropy=1.0,
        opposite_direction_flow=0.0,
        goal_hotspot_entropy=1.0,
        cross_region_demand_ratio=0.0,
        guidance_age=0,
        goal_distribution_js_divergence_since_refresh=0.0,
        edge_usage_distribution_drift_since_refresh=0.0,
        throughput_ewma_drop=0.0,
        last_refresh_wall_clock_cost=0.0,
        recent_planning_time=0.0,
    )


class PeriodicRefreshControllerTests(unittest.TestCase):
    def test_refreshes_at_registered_period(self) -> None:
        controller = PeriodicRefreshController(period=20)
        controller.reset(policy_seed=7)
        context = empty_context()
        decisions = {
            step: controller.select(context, step=step).refresh
            for step in (0, 1, 19, 20, 39, 40)
        }
        self.assertEqual(
            decisions,
            {0: True, 1: False, 19: False, 20: True, 39: False, 40: True},
        )

    def test_rejects_nonpositive_period(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            PeriodicRefreshController(period=0)

    def test_exact_even_b25_excludes_bootstrap_and_spends_25(self) -> None:
        budget = post_bootstrap_publication_budget(100, 0.25)
        self.assertEqual(budget, 25)
        self.assertEqual(
            exact_even_post_bootstrap_indices(100, budget),
            (
                4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52,
                56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 96, 99,
            ),
        )

    def test_exact_even_endpoints(self) -> None:
        self.assertEqual(exact_even_post_bootstrap_indices(100, 0), ())
        self.assertEqual(
            exact_even_post_bootstrap_indices(100, 99), tuple(range(1, 100))
        )

    def test_period_remains_anchored_after_skipped_boundary(self) -> None:
        controller = PeriodicRefreshController(period=20)
        controller.reset(policy_seed=0)
        context = empty_context()
        self.assertTrue(controller.select(context, step=0).refresh)
        self.assertTrue(controller.select(context, step=25).refresh)
        self.assertTrue(controller.select(context, step=40).refresh)


class BudgetedControllerTests(unittest.TestCase):
    def test_hard_rate_guard_includes_initial_refresh(self) -> None:
        controller = BudgetedEventTriggeredController(
            max_refresh_fraction=0.25,
            refresh_burst_capacity=2.0,
            safety_goal_js_threshold=0.0,
            safety_wait_threshold=None,
            budget_seconds_per_window=None,
            minimum_gap_steps=0,
        )
        controller.reset(policy_seed=3)
        context = empty_context()
        refreshes = 0
        for decision in range(20):
            action = controller.select(context, step=decision * 5)
            refreshes += int(action.refresh)
            controller.observe(
                context,
                action,
                WindowFeedback(
                    start_step=decision * 5,
                    end_step=(decision + 1) * 5,
                    completed_tasks=1,
                    agent_timesteps=5,
                    wait_agent_timesteps=0,
                    path_length=4,
                    shortest_path_length=4,
                    planning_seconds=0.0,
                    refresh_seconds=0.001 if action.refresh else 0.0,
                    budget_violations=0,
                ),
                context,
            )
        self.assertLessEqual(refreshes, math.ceil(20 * 0.25))

    def test_feedback_rejects_invalid_wait_count(self) -> None:
        feedback = WindowFeedback(
            start_step=0,
            end_step=5,
            completed_tasks=0,
            agent_timesteps=4,
            wait_agent_timesteps=5,
            path_length=0,
            shortest_path_length=0,
            planning_seconds=0.0,
            refresh_seconds=0.0,
            budget_violations=0,
        )
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            feedback.validate()


if __name__ == "__main__":
    unittest.main()
