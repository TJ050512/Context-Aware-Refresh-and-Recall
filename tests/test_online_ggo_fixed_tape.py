import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _stub_module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


def _load_trafficflow_module():
    """Load only the adapter module while replacing its heavy dependencies."""
    source = (
        Path(__file__).resolve().parents[1]
        / "external"
        / "OnlineGGO"
        / "CMAES"
        / "env_search"
        / "iterative_update"
        / "envs"
        / "trafficflow_online_env.py"
    )
    dummy = lambda *args, **kwargs: None
    stubs = {
        "env_search": _stub_module("env_search"),
        "env_search.competition": _stub_module("env_search.competition"),
        "env_search.competition.config": _stub_module(
            "env_search.competition.config", CompetitionConfig=object
        ),
        "env_search.competition.update_model": _stub_module(
            "env_search.competition.update_model"
        ),
        "env_search.competition.update_model.utils": _stub_module(
            "env_search.competition.update_model.utils",
            Map=object,
            comp_uncompress_vertex_matrix=dummy,
            comp_uncompress_edge_matrix=dummy,
        ),
        "env_search.utils": _stub_module(
            "env_search.utils",
            min_max_normalize=dummy,
            load_pibt_default_config=dummy,
            load_w_pibt_default_config=dummy,
            load_wppl_default_config=dummy,
            get_project_dir=dummy,
        ),
        "env_search.utils.logging": _stub_module(
            "env_search.utils.logging",
            get_current_time_str=dummy,
            get_hash_file_name=dummy,
        ),
        "env_search.utils.task_generator": _stub_module(
            "env_search.utils.task_generator", generate_task_and_agent=dummy
        ),
        "env_search.iterative_update": _stub_module(
            "env_search.iterative_update"
        ),
        "env_search.iterative_update.envs": _stub_module(
            "env_search.iterative_update.envs"
        ),
        "env_search.iterative_update.envs.utils": _stub_module(
            "env_search.iterative_update.envs.utils",
            visualize_simulation=dummy,
        ),
        "env_search.iterative_update.envs.env": _stub_module(
            "env_search.iterative_update.envs.env",
            REDUNDANT_COMPETITION_KEYS=set(),
        ),
        "env_search.traffic_mapf": _stub_module("env_search.traffic_mapf"),
        "env_search.traffic_mapf.config": _stub_module(
            "env_search.traffic_mapf.config", TrafficMAPFConfig=object
        ),
        "gymnasium": _stub_module(
            "gymnasium", spaces=SimpleNamespace(Box=dummy)
        ),
        "numpy": _stub_module(
            "numpy", bool_=bool, integer=int, inf=float("inf")
        ),
        "simulators": _stub_module("simulators"),
        "simulators.trafficMAPF_on": _stub_module(
            "simulators.trafficMAPF_on"
        ),
        "simulators.trafficMAPF_on.period_on_sim": _stub_module(
            "simulators.trafficMAPF_on.period_on_sim",
            generate_kiva_saturated_goal_tape=dummy,
            period_on_sim=object,
        ),
    }
    spec = importlib.util.spec_from_file_location(
        "_dai_trafficflow_online_env_for_test", source
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class FixedGoalTapeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_trafficflow_module()

    def test_canonical_fingerprints_are_stable_and_order_sensitive(self):
        starts = [4, 5]
        tape = [[1, 2], [3]]
        self.assertEqual(
            self.module._dai_fixed_goal_tape_sha256(starts, tape),
            "e10e181905b124ec297723b03df1fe1e83f8b06bf3f0ed92da8028478fc63a9e",
        )
        self.assertEqual(
            self.module._dai_fixed_goal_tape_fnv1a64(starts, tape),
            "a788f32d8b8b30fc",
        )
        self.assertNotEqual(
            self.module._dai_fixed_goal_tape_fnv1a64(starts, tape),
            self.module._dai_fixed_goal_tape_fnv1a64(
                starts, [[2, 1], [3]]
            ),
        )
        self.assertNotEqual(
            self.module._dai_fixed_goal_tape_fnv1a64(starts, tape),
            self.module._dai_fixed_goal_tape_fnv1a64([5, 4], tape),
        )

    def test_normalization_rejects_ambiguous_or_out_of_range_goals(self):
        with self.assertRaises(ValueError):
            self.module._normalize_dai_fixed_goal_tape(
                [[1, 2]], num_agents=2, map_size=8
            )
        with self.assertRaises(TypeError):
            self.module._normalize_dai_fixed_goal_tape(
                [[True], [2]], num_agents=2, map_size=8
            )
        with self.assertRaises(ValueError):
            self.module._normalize_dai_fixed_goal_tape(
                [[8], [2]], num_agents=2, map_size=8
            )

    def test_trace_prefixes_reconstruct_deterministic_task_ids(self):
        module = self.module
        env = module.TrafficFlowOnlineEnv.__new__(module.TrafficFlowOnlineEnv)
        env.config = SimpleNamespace(num_agents=2)
        env.comp_map = SimpleNamespace(height=2, width=4)
        env._dai_expected_goal_tape = [[1, 2], [3]]
        env._dai_expected_goal_tape_start_locations = [4, 5]
        env._dai_expected_goal_tape_sha256 = (
            module._dai_fixed_goal_tape_sha256(
                env._dai_expected_goal_tape_start_locations,
                env._dai_expected_goal_tape,
            )
        )
        env._dai_expected_goal_tape_fnv1a64 = (
            module._dai_fixed_goal_tape_fnv1a64(
                env._dai_expected_goal_tape_start_locations,
                env._dai_expected_goal_tape,
            )
        )
        env._dai_last_tape_assigned_prefix = None
        env._dai_last_tape_completed_prefix = None

        metadata = {
            "schema_version": module.DAI_TASK_TAPE_SCHEMA_VERSION,
            "enabled": True,
            "mode": "saturated_backlog_per_agent",
            "manifest_sha256": env._dai_expected_goal_tape_sha256,
            "content_fnv1a64": env._dai_expected_goal_tape_fnv1a64,
            "start_locations": [4, 5],
            "per_agent_lengths": [2, 1],
            "assigned_prefix_lengths": [1, 1],
            "completed_prefix_lengths": [0, 0],
            "total_tasks": 3,
            "exhausted": False,
            "task_id_semantics": module.DAI_TASK_TAPE_ID_SEMANTICS,
            "fingerprint_semantics": (
                module.DAI_TASK_TAPE_FINGERPRINT_SEMANTICS
            ),
        }
        assignments = [
            {
                "event_type": "assigned",
                "agent_id": 0,
                "task_id": 0,
                "goal_loc": [0, 1],
            },
            {
                "event_type": "assigned",
                "agent_id": 1,
                "task_id": 2,
                "goal_loc": [0, 3],
            },
        ]
        env._dai_validate_task_tape(metadata, assignments)

        next_metadata = dict(metadata)
        next_metadata["assigned_prefix_lengths"] = [2, 1]
        next_metadata["completed_prefix_lengths"] = [1, 0]
        next_events = [
            {
                "event_type": "finished",
                "agent_id": 0,
                "task_id": 0,
                "goal_loc": [0, 1],
            },
            {
                "event_type": "assigned",
                "agent_id": 0,
                "task_id": 1,
                "goal_loc": [0, 2],
            },
        ]
        env._dai_validate_task_tape(next_metadata, next_events)

        bad_env = module.TrafficFlowOnlineEnv.__new__(
            module.TrafficFlowOnlineEnv
        )
        bad_env.config = env.config
        bad_env.comp_map = env.comp_map
        bad_env._dai_expected_goal_tape = env._dai_expected_goal_tape
        bad_env._dai_expected_goal_tape_start_locations = (
            env._dai_expected_goal_tape_start_locations
        )
        bad_env._dai_expected_goal_tape_sha256 = (
            env._dai_expected_goal_tape_sha256
        )
        bad_env._dai_expected_goal_tape_fnv1a64 = (
            env._dai_expected_goal_tape_fnv1a64
        )
        bad_env._dai_last_tape_assigned_prefix = None
        bad_env._dai_last_tape_completed_prefix = None
        bad_assignments = [dict(assignments[0]), dict(assignments[1])]
        bad_assignments[1]["task_id"] = 1
        with self.assertRaisesRegex(ValueError, "task_id"):
            bad_env._dai_validate_task_tape(metadata, bad_assignments)

    def test_sim_kwargs_copy_and_bind_the_manifest_before_cpp(self):
        module = self.module
        env = module.TrafficFlowOnlineEnv.__new__(module.TrafficFlowOnlineEnv)
        env.comp_map = SimpleNamespace(height=2, width=4)
        env.config = SimpleNamespace(
            fixed_goal_tape=((1, 2), (3,)),
            fixed_goal_tape_start_locations=(4, 5),
            num_agents=2,
            simu_time=20,
            map_path="map.map",
            gen_tasks=True,
            num_tasks=100,
            hidden_size=8,
            task_assignment_strategy="roundrobin",
            num_tasks_reveal=1,
            task_dist_change_interval=-1,
            task_random_type="Gaussian",
            dist_sigma=0.5,
            dist_K=3,
            initial_task_distribution_phase=0,
            warmup_time=5,
            update_gg_interval=5,
        )
        env._effective_episode_seed = 17
        kwargs = env.gen_sim_kwargs()

        self.assertEqual(kwargs["fixed_goal_tape"], [[1, 2], [3]])
        self.assertIsNot(kwargs["fixed_goal_tape"], env.config.fixed_goal_tape)
        self.assertEqual(
            kwargs["fixed_goal_tape_manifest_sha256"],
            "e10e181905b124ec297723b03df1fe1e83f8b06bf3f0ed92da8028478fc63a9e",
        )
        self.assertEqual(
            kwargs["fixed_goal_tape_start_locations"], [4, 5]
        )
        self.assertEqual(
            env._dai_expected_goal_tape_fnv1a64, "a788f32d8b8b30fc"
        )

        env.config.task_dist_change_interval = 5
        with self.assertRaisesRegex(ValueError, "encode changes in the tape"):
            env.gen_sim_kwargs()

        env.config.task_dist_change_interval = -1
        env.config.fixed_goal_tape_start_locations = None
        with self.assertRaisesRegex(ValueError, "must be set together"):
            env.gen_sim_kwargs()

    def test_absolute_tape_fingerprints_bind_release_times(self):
        starts = [4, 5]
        tape = [[[1, 0], [2, 3]], [[3, 0]]]
        self.assertEqual(
            self.module._dai_absolute_task_tape_sha256(starts, tape),
            "50efc6040ee8ecfcc7e09975877574845ec80301b8901685e8e2648bf3004054",
        )
        self.assertEqual(
            self.module._dai_absolute_task_tape_fnv1a64(starts, tape),
            "fde122a89c5810d5",
        )
        shifted = [[[1, 0], [2, 4]], [[3, 0]]]
        self.assertNotEqual(
            self.module._dai_absolute_task_tape_sha256(starts, tape),
            self.module._dai_absolute_task_tape_sha256(starts, shifted),
        )
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            self.module._normalize_dai_absolute_task_tape(
                [[[1, 3], [2, 2]], [[3, 0]]],
                num_agents=2,
                map_size=8,
                horizon_steps=10,
            )

    def test_absolute_release_events_reconstruct_all_three_prefixes(self):
        module = self.module
        env = module.TrafficFlowOnlineEnv.__new__(module.TrafficFlowOnlineEnv)
        env.config = SimpleNamespace(num_agents=2)
        env.comp_map = SimpleNamespace(height=2, width=4)
        env._dai_expected_goal_tape = None
        env._dai_expected_absolute_task_tape = [
            [[1, 0], [2, 3]],
            [[3, 0]],
        ]
        env._dai_expected_absolute_task_tape_start_locations = [4, 5]
        env._dai_expected_absolute_task_tape_sha256 = (
            module._dai_absolute_task_tape_sha256(
                env._dai_expected_absolute_task_tape_start_locations,
                env._dai_expected_absolute_task_tape,
            )
        )
        env._dai_expected_absolute_task_tape_fnv1a64 = (
            module._dai_absolute_task_tape_fnv1a64(
                env._dai_expected_absolute_task_tape_start_locations,
                env._dai_expected_absolute_task_tape,
            )
        )
        env._dai_last_tape_released_prefix = None
        env._dai_last_tape_assigned_prefix = None
        env._dai_last_tape_completed_prefix = None

        def metadata(released, assigned, completed):
            return {
                "schema_version": module.DAI_ABSOLUTE_TASK_TAPE_SCHEMA_VERSION,
                "enabled": True,
                "mode": module.DAI_ABSOLUTE_TASK_TAPE_MODE,
                "manifest_sha256": env._dai_expected_absolute_task_tape_sha256,
                "content_fnv1a64": env._dai_expected_absolute_task_tape_fnv1a64,
                "start_locations": [4, 5],
                "per_agent_lengths": [2, 1],
                "released_prefix_lengths": released,
                "assigned_prefix_lengths": assigned,
                "completed_prefix_lengths": completed,
                "total_tasks": 3,
                "all_released": released == [2, 1],
                "all_completed": completed == [2, 1],
                "online_workload_rng_draws": 0,
                "task_id_semantics": module.DAI_TASK_TAPE_ID_SEMANTICS,
                "fingerprint_semantics": (
                    module.DAI_ABSOLUTE_TASK_TAPE_FINGERPRINT_SEMANTICS
                ),
                "release_timestep_semantics": (
                    module.DAI_ABSOLUTE_TASK_TAPE_RELEASE_SEMANTICS
                ),
            }

        initial_events = [
            {"event_type": "released", "agent_id": 0, "task_id": 0,
             "timestep": 0, "goal_loc": [0, 1]},
            {"event_type": "assigned", "agent_id": 0, "task_id": 0,
             "timestep": 0, "goal_loc": [0, 1]},
            {"event_type": "released", "agent_id": 1, "task_id": 2,
             "timestep": 0, "goal_loc": [0, 3]},
            {"event_type": "assigned", "agent_id": 1, "task_id": 2,
             "timestep": 0, "goal_loc": [0, 3]},
        ]
        env._dai_validate_task_tape(
            metadata([1, 1], [1, 1], [0, 0]), initial_events, 0
        )
        next_events = [
            {"event_type": "finished", "agent_id": 0, "task_id": 0,
             "timestep": 2, "goal_loc": [0, 1]},
            {"event_type": "released", "agent_id": 0, "task_id": 1,
             "timestep": 3, "goal_loc": [0, 2]},
            {"event_type": "assigned", "agent_id": 0, "task_id": 1,
             "timestep": 3, "goal_loc": [0, 2]},
        ]
        env._dai_validate_task_tape(
            metadata([2, 1], [2, 1], [1, 0]), next_events, 3
        )

        bad = metadata([1, 1], [2, 1], [1, 0])
        with self.assertRaisesRegex((ValueError, RuntimeError), "released|prefix"):
            env._dai_validate_task_tape(bad, [], 3)

    def test_absolute_manifest_is_copied_and_bound_before_cpp(self):
        module = self.module
        env = module.TrafficFlowOnlineEnv.__new__(module.TrafficFlowOnlineEnv)
        env.comp_map = SimpleNamespace(height=2, width=4)
        env.config = SimpleNamespace(
            fixed_goal_tape=None,
            fixed_goal_tape_start_locations=None,
            absolute_task_tape=(((1, 0), (2, 3)), ((3, 0),)),
            absolute_task_tape_start_locations=(4, 5),
            num_agents=2,
            simu_time=8,
            map_path="map.map",
            gen_tasks=True,
            num_tasks=3,
            hidden_size=8,
            task_assignment_strategy="roundrobin",
            num_tasks_reveal=1,
            task_dist_change_interval=-1,
            task_random_type="Gaussian",
            dist_sigma=0.5,
            dist_K=3,
            initial_task_distribution_phase=0,
            warmup_time=2,
            update_gg_interval=5,
        )
        env._effective_episode_seed = 17
        kwargs = env.gen_sim_kwargs()
        self.assertEqual(
            kwargs["absolute_task_tape"],
            [[[1, 0], [2, 3]], [[3, 0]]],
        )
        self.assertEqual(
            kwargs["absolute_task_tape_manifest_sha256"],
            "50efc6040ee8ecfcc7e09975877574845ec80301b8901685e8e2648bf3004054",
        )
        self.assertEqual(
            env._dai_expected_absolute_task_tape_fnv1a64,
            "fde122a89c5810d5",
        )
        env.config.fixed_goal_tape = ((1,), (3,))
        env.config.fixed_goal_tape_start_locations = (4, 5)
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            env.gen_sim_kwargs()


if __name__ == "__main__":
    unittest.main()
