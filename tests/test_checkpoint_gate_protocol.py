import importlib.util
from pathlib import Path
import unittest

from dai_lmapf.absolute_workload import read_kiva_map


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_absolute_tape_checkpoint_gate.py"
)
SPEC = importlib.util.spec_from_file_location("checkpoint_gate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CheckpointGateProtocolTests(unittest.TestCase):
    def test_fresh_validation_v2_seeds_are_forbidden_to_development_gate(self) -> None:
        expected = {
            320019, 241771, 827130, 693142, 741084,
            12102, 133633, 876480, 50620, 131545,
        }
        self.assertEqual(MODULE.FRESH_VALIDATION_V2_SEEDS, expected)
        self.assertTrue(expected.issubset(MODULE.FORBIDDEN_SEEDS))
        self.assertTrue(set(MODULE.DEV_SEEDS).isdisjoint(expected))

    def test_release_schedule_is_staggered_and_guarded(self) -> None:
        schedules, metadata = MODULE._staggered_release_schedules(
            n_agents=400,
            total_steps=2200,
            interval=110,
            guard_suffix=4,
        )
        self.assertEqual(len(schedules), 400)
        self.assertLessEqual(
            metadata["maximum_regular_arrivals_in_one_timestep"], 4
        )
        self.assertAlmostEqual(
            metadata["nominal_arrival_rate_tasks_per_timestep"], 400 / 110
        )
        self.assertEqual(metadata["guard_suffix_tasks_per_agent"], 4)
        self.assertEqual(metadata["guard_suffix_release_timestep"], 2199)
        self.assertEqual(
            metadata["total_task_tape_entries"], sum(map(len, schedules))
        )
        regular_counts = {}
        for schedule in schedules:
            self.assertEqual(schedule[-4:], [2199, 2199, 2199, 2199])
            for release in schedule[:-4]:
                regular_counts[release] = regular_counts.get(release, 0) + 1
        self.assertTrue(regular_counts)
        self.assertLessEqual(max(regular_counts.values()), 4)
        self.assertNotIn(400, regular_counts.values())

    def test_phase_boundaries_use_union_of_regular_release_epochs(self) -> None:
        schedules, _ = MODULE._staggered_release_schedules(
            n_agents=400,
            total_steps=2200,
            interval=110,
            guard_suffix=4,
        )
        regular_union = MODULE._regular_release_union(
            schedules, guard_suffix=4
        )
        absolute, scored = MODULE._snap_phase_starts(
            release_times=regular_union,
            warmup_time=200,
            requested_scored_starts=[500, 1000, 1500],
        )
        self.assertEqual(absolute, [0, 700, 1200, 1700])
        self.assertEqual(scored, [500, 1000, 1500])
        self.assertTrue(all(start in regular_union for start in absolute))

    def test_guard_requires_at_least_four_tasks_per_agent(self) -> None:
        for guard_suffix in range(4):
            with self.assertRaises(ValueError):
                MODULE._staggered_release_schedules(
                    n_agents=4,
                    total_steps=20,
                    interval=5,
                    guard_suffix=guard_suffix,
                )

    def test_registered_schedule_call_counts(self) -> None:
        self.assertEqual(
            MODULE._expected_schedule_calls(
                "never", horizon=2000, decision_window=20
            ),
            1,
        )
        self.assertEqual(
            MODULE._expected_schedule_calls(
                "period_80", horizon=2000, decision_window=20
            ),
            25,
        )

    def test_development_phase_centers_have_registered_js_separation(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        kiva_map = read_kiva_map(
            workspace
            / "external/OnlineGGO/Guided-PIBT/guided-pibt/"
            "benchmark-lifelong/maps/warehouse_small_narrow_kiva.map"
        )
        for seed in range(17, 27):
            centers, divergences = MODULE._separated_phase_centers(
                kiva_map=kiva_map,
                seed=seed,
                phase_count=4,
                sigma=0.75,
                minimum_js=0.30,
            )
            self.assertEqual(len(set(centers)), 4)
            self.assertEqual(len(divergences), 3)
            self.assertTrue(all(value >= 0.30 for value in divergences))


if __name__ == "__main__":
    unittest.main()
