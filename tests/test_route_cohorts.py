import unittest

from dai_lmapf.cohorts import RouteCohortTracker


RAW = "a" * 64
APPLIED = "b" * 64


def assigned(event_id, task_id, timestep, goal=(1, 2), agent_id=0):
    return {
        "event_id": event_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "event_type": "assigned",
        "timestep": timestep,
        "goal_loc": list(goal),
    }


def released(event_id, task_id, timestep, goal=(1, 2), agent_id=0):
    event = assigned(event_id, task_id, timestep, goal, agent_id)
    event["event_type"] = "released"
    return event


def finished(event_id, task_id, timestep, goal=(1, 2), agent_id=0):
    event = assigned(event_id, task_id, timestep, goal, agent_id)
    event["event_type"] = "finished"
    return event


def route(event_id, task_id, timestep, version, goal=(1, 2), agent_id=0):
    return {
        "event_id": event_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "goal_loc": list(goal),
        "execution_timestep": timestep,
        "map_weights_revision": version,
        "reason": "init_pp" if version == 0 else "task_change",
        "publication_version": version,
        "raw_guidance_sha256": RAW,
        "applied_normalized_guidance_sha256": APPLIED,
    }


class RouteCohortTrackerTests(unittest.TestCase):
    def test_attributes_completion_to_actual_route_build_version(self):
        tracker = RouteCohortTracker(n_agents=1)
        tracker.process_trace(
            {
                "timestep": 3,
                "recent_events": [assigned(0, 7, 0)],
                "recent_route_builds": [route(0, 7, 2, version=3)],
            }
        )
        produced = tracker.process_trace(
            {
                "timestep": 8,
                "recent_events": [finished(1, 7, 8)],
                "recent_route_builds": [],
            }
        )

        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].first_publication_version, 3)
        self.assertEqual(produced[0].service_steps, 8)
        self.assertEqual(tracker.version_summary()[3]["completed"], 1)

    def test_ignores_assignment_window_as_treatment(self):
        tracker = RouteCohortTracker(n_agents=1)
        tracker.process_trace(
            {
                "timestep": 1,
                "recent_events": [assigned(0, 9, 0)],
                "recent_route_builds": [],
            }
        )
        tracker.process_trace(
            {
                "timestep": 5,
                "recent_events": [],
                "recent_route_builds": [route(0, 9, 5, version=4)],
            }
        )
        outcome = tracker.process_trace(
            {
                "timestep": 10,
                "recent_events": [finished(1, 9, 10)],
                "recent_route_builds": [],
            }
        )[0]
        self.assertEqual(outcome.first_publication_version, 4)

    def test_rejects_completion_without_route_build(self):
        tracker = RouteCohortTracker(n_agents=1)
        tracker.process_trace(
            {
                "timestep": 1,
                "recent_events": [assigned(0, 2, 0)],
                "recent_route_builds": [],
            }
        )
        with self.assertRaisesRegex(ValueError, "without a route-build"):
            tracker.process_trace(
                {
                    "timestep": 2,
                    "recent_events": [finished(1, 2, 2)],
                    "recent_route_builds": [],
                }
            )

    def test_release_does_not_create_route_cohort(self):
        tracker = RouteCohortTracker(n_agents=1)
        self.assertEqual(
            tracker.process_trace({
                "timestep": 4,
                "recent_events": [released(0, 7, 4)],
                "recent_route_builds": [],
            }),
            [],
        )
        self.assertEqual(tracker.assignments, {})
        self.assertEqual(tracker.builds, {})


if __name__ == "__main__":
    unittest.main()
