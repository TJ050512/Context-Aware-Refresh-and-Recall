import unittest

from dai_lmapf.cohorts import GuidanceCohortTracker


class GuidanceCohortTrackerTests(unittest.TestCase):
    def test_attributes_assignment_to_window_version(self) -> None:
        tracker = GuidanceCohortTracker(n_agents=2)
        tracker.process_trace(
            {
                "timestep": 20,
                "recent_events": [
                    [[10, 2, "assigned"]],
                    [[11, 3, "assigned"]],
                ],
            },
            guidance_version=0,
        )
        produced = tracker.process_trace(
            {
                "timestep": 40,
                "recent_events": [
                    [[10, 25, "finished"], [12, 25, "assigned"]],
                    [[11, 30, "finished"]],
                ],
            },
            guidance_version=1,
        )
        self.assertEqual([item.guidance_version for item in produced], [0, 0])
        self.assertEqual(tracker.active[12].guidance_version, 1)
        self.assertEqual(tracker.version_summary()[0]["completed"], 2)

    def test_deduplicates_overlapping_event_windows(self) -> None:
        tracker = GuidanceCohortTracker(n_agents=1)
        trace = {"timestep": 10, "recent_events": [[[5, 1, "assigned"]]]}
        tracker.process_trace(trace, guidance_version=0)
        tracker.process_trace(trace, guidance_version=0)
        self.assertEqual(len(tracker.active), 1)

    def test_rejects_finish_without_assignment(self) -> None:
        tracker = GuidanceCohortTracker(n_agents=1)
        with self.assertRaisesRegex(ValueError, "without a recorded assignment"):
            tracker.process_trace(
                {"timestep": 10, "recent_events": [[[5, 4, "finished"]]]},
                guidance_version=0,
            )

    def test_release_does_not_create_guidance_exposure(self) -> None:
        tracker = GuidanceCohortTracker(n_agents=1)
        produced = tracker.process_trace(
            {
                "timestep": 4,
                "recent_events": [[[7, 4, "released"]]],
            },
            guidance_version=3,
        )
        self.assertEqual(produced, [])
        self.assertEqual(tracker.active, {})


if __name__ == "__main__":
    unittest.main()
