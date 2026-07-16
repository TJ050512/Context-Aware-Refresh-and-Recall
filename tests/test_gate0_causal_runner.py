import importlib.util
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

from dai_lmapf.online_ggo_adapter import action_digest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "gate0_publication_mvp.py"
)
SPEC = importlib.util.spec_from_file_location("gate0_publication_mvp", SCRIPT_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNNER)


class MethodSemanticsTests(unittest.TestCase):
    def test_uniform_never_publishes_but_never_bootstraps_once(self) -> None:
        kwargs = {
            "current_timestep": 0,
            "warmup_time": 0,
            "shift_interval": 160,
            "decision_window": 20,
            "task_js": 0.0,
            "event_threshold": 0.02,
            "last_refresh_timestep": 0,
            "event_minimum_gap": 20,
            "cohort_ready": False,
            "observed_shift": False,
            "observed_shift_index": None,
            "bootstrap_timestep": 0,
        }
        self.assertFalse(RUNNER._method_refresh(
            "uniform", decision_index=0, **kwargs
        ))
        self.assertFalse(RUNNER._method_refresh(
            "uniform", decision_index=7, **kwargs
        ))
        self.assertTrue(RUNNER._method_refresh(
            "never", decision_index=0, **kwargs
        ))
        self.assertFalse(RUNNER._method_refresh(
            "never", decision_index=1, **kwargs
        ))


@unittest.skipUnless(np is not None, "candidate preview requires NumPy")
class CandidatePreviewTests(unittest.TestCase):
    def test_candidate_hash_matches_adapter_flattened_contract(self) -> None:
        action = np.arange(24, dtype=np.float64).reshape(4, 2, 3)
        self.assertEqual(
            RUNNER._raw_guidance_hash(action),
            action_digest(action, height=2, width=3),
        )

    def test_next_route_preview_is_pure_and_does_not_count_publication(self) -> None:
        generator = RUNNER.NextRouteFlowGuidanceGenerator(
            graph=np.zeros((2, 3), dtype=np.int8),
            home_locs=[(0, 0)],
            endpoint_locs=[(1, 2)],
            flow_bias=0.1,
            decision_window=20,
        )
        update_trace = {
            "recent_distribution_updates": [{
                "source": "kiva",
                "timestep": 20,
                "primary_weights": [1.0],
                "secondary_weights": [1.0],
            }],
        }
        generator.observe_trace(update_trace)
        trace = {
            "recent_distribution_updates": [],
            "recent_events": [],
            "window_end_timestep": 40,
            "curr_pos": [[0, 0], [1, 2]],
            "curr_tasks": [[1, 2], [0, 0]],
        }
        generator.state_provider = lambda: trace
        state_before = (
            generator.calls,
            generator.last_distribution_timestep,
            generator.last_distribution_change_js,
            generator.home_weights.copy(),
            generator.endpoint_weights.copy(),
        )
        first = generator.preview(None)
        second = generator.preview(None)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(generator.calls, state_before[0])
        self.assertEqual(generator.last_distribution_timestep, state_before[1])
        self.assertEqual(generator.last_distribution_change_js, state_before[2])
        self.assertTrue(np.array_equal(generator.home_weights, state_before[3]))
        self.assertTrue(np.array_equal(generator.endpoint_weights, state_before[4]))

    def test_route_flow_skips_inactive_holding_targets(self) -> None:
        generator = RUNNER.RouteFlowGuidanceGenerator(
            graph=np.asarray([[0, 0], [0, 1]], dtype=np.int8),
            flow_bias=0.1,
        )
        generator.state_provider = lambda: {
            "curr_pos": [[0, 0], [1, 0]],
            "curr_tasks": [[0, 1], [1, 1]],
            "curr_task_active": [True, False],
        }
        action = generator(None)
        self.assertEqual(action.shape, (4, 2, 2))
        # Guidance values are edge costs: the active agent's rightward route
        # must be cheaper, while the inactive agent contributes no flow.
        self.assertLess(float(action[0, 0, 0]), 1.0)
        self.assertGreater(float(action[2, 0, 1]), 1.0)
        np.testing.assert_allclose(action[:, 1, 0], 1.0)

    def test_next_route_skips_inactive_holding_targets(self) -> None:
        generator = RUNNER.NextRouteFlowGuidanceGenerator(
            graph=np.asarray([[0, 0], [0, 1]], dtype=np.int8),
            home_locs=[(0, 0)],
            endpoint_locs=[(0, 1)],
            flow_bias=0.1,
            decision_window=5,
        )
        trace = {
            "recent_distribution_updates": [],
            "recent_events": [{
                "event_type": "assigned",
                "agent_id": 0,
                "timestep": 0,
            }],
            "window_end_timestep": 0,
            "curr_pos": [[0, 0], [1, 0]],
            "curr_tasks": [[0, 1], [1, 1]],
            "curr_task_active": [True, False],
        }
        action = generator._generate_action_from_trace(trace)
        self.assertEqual(action.shape, (4, 2, 2))
        # Guidance values are edge costs: the active agent's rightward route
        # must be cheaper, while the inactive agent contributes no flow.
        self.assertLess(float(action[0, 0, 0]), 1.0)
        self.assertGreater(float(action[2, 0, 1]), 1.0)
        np.testing.assert_allclose(action[:, 1, 0], 1.0)


if __name__ == "__main__":
    unittest.main()
