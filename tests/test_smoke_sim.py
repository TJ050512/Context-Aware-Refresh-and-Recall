import unittest

from dai_lmapf.controller import GuidanceAction, FixedController, PeriodicRefreshController
from dai_lmapf.smoke_sim import (
    build_smoke_manifest,
    build_smoke_map,
    build_task_tape,
    run_smoke_episode,
)


class SmokeTaskTapeTests(unittest.TestCase):
    def test_tape_is_deterministic_and_alternates_rooms(self) -> None:
        manifest = build_smoke_manifest(
            map_id="two_corridor",
            workload="recurring",
            n_agents=12,
            horizon_steps=80,
            seed=4,
        )
        world = build_smoke_map("two_corridor")
        first = build_task_tape(world, manifest)
        second = build_task_tape(world, manifest)
        self.assertEqual(first.tape_hash, second.tape_hash)
        for phase_index in range(len(manifest.phases)):
            for agent_id, start in enumerate(first.starts):
                previous = start
                for task_index in range(12):
                    goal = first.goal_for(phase_index, agent_id, task_index)
                    self.assertNotEqual(goal, previous)
                    self.assertNotEqual(world.side(goal), world.side(previous))
                    previous = goal


class SmokeEpisodeTests(unittest.TestCase):
    def test_replay_is_deterministic_and_collision_free(self) -> None:
        manifest = build_smoke_manifest(
            map_id="two_corridor",
            workload="abrupt",
            n_agents=16,
            horizon_steps=100,
            seed=8,
        )

        def run():
            return run_smoke_episode(
                manifest=manifest,
                workload="abrupt",
                method="periodic_20",
                controller=PeriodicRefreshController(20),
                decision_interval=5,
                controller_seed=91,
            )

        first, first_records = run()
        second, second_records = run()
        self.assertEqual(first.completed, second.completed)
        self.assertEqual(first.total_wait, second.total_wait)
        self.assertEqual(first.refresh_count, second.refresh_count)
        self.assertEqual(first.task_tape_hash, second.task_tape_hash)
        self.assertEqual(first.collision_count, 0)
        self.assertEqual(
            [record.selected_action for record in first_records],
            [record.selected_action for record in second_records],
        )

    def test_registered_controllers_produce_different_action_traces(self) -> None:
        manifest = build_smoke_manifest(
            map_id="two_corridor",
            workload="static",
            n_agents=8,
            horizon_steps=60,
            seed=1,
        )
        reuse_result, reuse_records = run_smoke_episode(
            manifest=manifest,
            workload="static",
            method="always_reuse",
            controller=FixedController(GuidanceAction(False)),
            decision_interval=5,
        )
        periodic_result, periodic_records = run_smoke_episode(
            manifest=manifest,
            workload="static",
            method="periodic_20",
            controller=PeriodicRefreshController(20),
            decision_interval=5,
        )
        self.assertEqual(reuse_result.task_tape_hash, periodic_result.task_tape_hash)
        self.assertNotEqual(
            [record.selected_action for record in reuse_records],
            [record.selected_action for record in periodic_records],
        )
        self.assertEqual(reuse_records[0].selected_action, "refresh")
        self.assertTrue(reuse_records[0].bootstrap)

    def test_multiple_seeds_pass_safety_gate(self) -> None:
        for seed in range(5):
            manifest = build_smoke_manifest(
                map_id="three_corridor",
                workload="recurring",
                n_agents=20,
                horizon_steps=80,
                seed=seed,
            )
            result, _ = run_smoke_episode(
                manifest=manifest,
                workload="recurring",
                method="always_refresh",
                controller=FixedController(GuidanceAction(True)),
                decision_interval=5,
            )
            self.assertEqual(result.collision_count, 0)


if __name__ == "__main__":
    unittest.main()
