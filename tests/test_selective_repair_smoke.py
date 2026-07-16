import unittest

from dai_lmapf.selective_repair_smoke import (
    GuidanceSnapshot,
    nominal_path,
    oracle_corridor_cost,
    relative_positive_exposure,
    run_selective_repair_episode,
)
from dai_lmapf.smoke_sim import build_smoke_manifest, build_smoke_map


class SelectiveRepairPrimitiveTests(unittest.TestCase):
    def test_nominal_path_reaches_goal(self) -> None:
        world = build_smoke_map("two_corridor")
        start = world.left_cells[0]
        goal = world.right_cells[-1]
        field = world.distance_field(goal)
        path = nominal_path(world, start, goal, field)
        self.assertEqual(path[0], start)
        self.assertEqual(path[-1], goal)
        self.assertEqual(len(path) - 1, world.shortest_distance(start, goal))

    def test_positive_exposure_detects_new_penalty_on_old_route(self) -> None:
        world = build_smoke_map("two_corridor")
        start = min(world.left_cells)
        goal = min(world.right_cells)
        old_cost = oracle_corridor_cost(world, "bottom_hotspot")
        new_cost = oracle_corridor_cost(world, "top_hotspot")
        old_field = world.distance_field(goal, cell_cost=old_cost, scale=8.0)
        path = nominal_path(world, start, goal, old_field)
        old = GuidanceSnapshot(0, 0, old_cost, "old")
        new = GuidanceSnapshot(1, 1, new_cost, "new")
        self.assertGreater(
            relative_positive_exposure(path, old_snapshot=old, new_snapshot=new, scale=8.0),
            0.0,
        )


class SelectiveRepairEpisodeTests(unittest.TestCase):
    def test_unselected_agents_remain_stale_and_new_tasks_upgrade(self) -> None:
        manifest = build_smoke_manifest(
            map_id="two_corridor",
            workload="abrupt",
            n_agents=16,
            horizon_steps=100,
            seed=7,
        )
        result, events = run_selective_repair_episode(
            manifest=manifest,
            workload="abrupt",
            method="lazy_0",
            selector_seed=99,
        )
        self.assertEqual(result.collision_count, 0)
        self.assertEqual(events[0].selected_count, 0)
        self.assertGreater(result.stale_fraction_auc, 0.0)
        self.assertGreater(result.new_task_rebind_count, 0)

    def test_top_budget_is_cost_matched_and_captures_exposure(self) -> None:
        manifest = build_smoke_manifest(
            map_id="two_corridor",
            workload="abrupt",
            n_agents=16,
            horizon_steps=100,
            seed=8,
        )
        result, events = run_selective_repair_episode(
            manifest=manifest,
            workload="abrupt",
            method="top_25",
            selector_seed=99,
        )
        event = events[0]
        self.assertEqual(event.selected_count, 4)
        self.assertGreater(event.exposure_capture, 0.0)
        self.assertEqual(result.repair_rebind_count, event.selected_count)

    def test_identity_repair_preserves_complete_trace(self) -> None:
        manifest = build_smoke_manifest(
            map_id="two_corridor",
            workload="static",
            n_agents=12,
            horizon_steps=80,
            seed=4,
        )
        baseline, _ = run_selective_repair_episode(
            manifest=manifest,
            workload="static",
            method="static_no_event",
        )
        identity, events = run_selective_repair_episode(
            manifest=manifest,
            workload="static",
            method="identity_all",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].old_snapshot_hash, events[0].new_snapshot_hash)
        self.assertEqual(baseline.trace_hash, identity.trace_hash)
        self.assertEqual(baseline.completed, identity.completed)

    def test_episode_replay_is_deterministic(self) -> None:
        manifest = build_smoke_manifest(
            map_id="three_corridor",
            workload="abrupt",
            n_agents=16,
            horizon_steps=100,
            seed=12,
        )
        first, first_events = run_selective_repair_episode(
            manifest=manifest,
            workload="abrupt",
            method="random_25",
            selector_seed=77,
            guidance_scale=2.0,
        )
        second, second_events = run_selective_repair_episode(
            manifest=manifest,
            workload="abrupt",
            method="random_25",
            selector_seed=77,
            guidance_scale=2.0,
        )
        self.assertEqual(first.trace_hash, second.trace_hash)
        self.assertEqual(first.completed, second.completed)
        self.assertEqual(
            [event.selected_agent_ids for event in first_events],
            [event.selected_agent_ids for event in second_events],
        )


if __name__ == "__main__":
    unittest.main()
