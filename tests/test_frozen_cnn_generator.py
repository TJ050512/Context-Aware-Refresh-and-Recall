import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import numpy as np
    import torch
except ImportError:
    np = None
    torch = None

from dai_lmapf.frozen_cnn_generator import (
    CheckpointValidationError,
    EXPECTED_NUM_PARAMS,
    FrozenCNNGuidanceGenerator,
    PARAMETER_LAYOUT,
    load_frozen_cnn_checkpoint,
)


WORKSPACE = Path(__file__).resolve().parents[1]
CMAES = WORKSPACE / "external" / "OnlineGGO" / "CMAES"
RUNNER_PATH = WORKSPACE / "scripts" / "gate0_publication_mvp.py"


class ArchitectureContractTests(unittest.TestCase):
    def test_pinned_layout_has_exactly_3084_values(self) -> None:
        count = sum(math.prod(shape) for _, shape in PARAMETER_LAYOUT)
        self.assertEqual(count, 3084)
        self.assertEqual(count, EXPECTED_NUM_PARAMS)
        self.assertEqual(len(PARAMETER_LAYOUT), 12)


@unittest.skipUnless(
    np is not None and torch is not None,
    "frozen CNN validation requires NumPy and PyTorch",
)
class FrozenCNNTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.params = np.linspace(
            -0.35, 0.45, EXPECTED_NUM_PARAMS, dtype=np.float64
        )

    def _write_checkpoint(self, params=None, model_type="cnn") -> Path:
        path = Path(self.temp_dir.name) / "optimal_update_model.json"
        values = self.params if params is None else params
        serialized = values.tolist() if hasattr(values, "tolist") else list(values)
        payload = {"type": model_type, "params": serialized}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _observation(self):
        values = np.linspace(-1.25, 2.0, 6 * 5 * 7, dtype=np.float64)
        return (values + 0.1 * np.sin(values * 3.0)).reshape(6, 5, 7)

    def test_checkpoint_length_and_both_hashes_are_validated(self) -> None:
        path = self._write_checkpoint()
        raw_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        checkpoint = load_frozen_cnn_checkpoint(
            path, expected_file_sha256=raw_sha256
        )
        self.assertEqual(checkpoint.num_params, 3084)
        self.assertEqual(checkpoint.file_sha256, raw_sha256)
        self.assertEqual(checkpoint.params.shape, (3084,))
        self.assertEqual(checkpoint.params.dtype, np.float32)
        reloaded = load_frozen_cnn_checkpoint(
            path,
            expected_file_sha256=checkpoint.file_sha256,
            expected_params_sha256=checkpoint.params_sha256,
        )
        self.assertEqual(reloaded.params_sha256, checkpoint.params_sha256)
        with self.assertRaisesRegex(
            CheckpointValidationError, "file SHA-256 mismatch"
        ):
            load_frozen_cnn_checkpoint(
                path, expected_file_sha256="0" * 64
            )
        with self.assertRaisesRegex(
            CheckpointValidationError, "parameter SHA-256 mismatch"
        ):
            load_frozen_cnn_checkpoint(
                path, expected_params_sha256="f" * 64
            )

    def test_malformed_parameter_vectors_are_rejected(self) -> None:
        short_path = self._write_checkpoint(self.params[:-1])
        with self.assertRaisesRegex(
            CheckpointValidationError, "parameter count mismatch"
        ):
            load_frozen_cnn_checkpoint(short_path)

        bad_values = self.params.tolist()
        bad_values[31] = True
        bad_path = self._write_checkpoint(bad_values)
        with self.assertRaisesRegex(
            CheckpointValidationError, "parameter 31 is not a JSON number"
        ):
            load_frozen_cnn_checkpoint(bad_path)

    def test_output_shape_and_preview_purity(self) -> None:
        generator = FrozenCNNGuidanceGenerator.from_path(
            self._write_checkpoint()
        )
        observation = self._observation()
        buffers_before = {
            name: value.detach().clone()
            for name, value in generator.model.named_buffers()
        }
        preview = generator.preview(observation)
        self.assertEqual(preview.shape, (4, 5, 7))
        self.assertEqual(generator.calls, 0)
        for name, value in generator.model.named_buffers():
            self.assertTrue(torch.equal(value, buffers_before[name]))
        output = generator(observation)
        self.assertEqual(output.shape, (4, 5, 7))
        self.assertEqual(generator.calls, 1)
        np.testing.assert_array_equal(output, preview)
        with self.assertRaisesRegex(ValueError, r"shape \[6,H,W\]"):
            generator(np.zeros((5, 5, 7), dtype=np.float32))

    def test_synthetic_output_is_exactly_official_cnn_update_model(self) -> None:
        sys.path.insert(0, str(CMAES))
        try:
            from env_search.traffic_mapf.update_model.update_model import (
                CNNUpdateModel,
            )
        except ImportError as exc:
            self.skipTest(f"pinned official OnlineGGO imports unavailable: {exc}")
        finally:
            if sys.path[0] == str(CMAES):
                sys.path.pop(0)

        path = self._write_checkpoint()
        candidate = FrozenCNNGuidanceGenerator.from_path(path)
        official = CNNUpdateModel(
            self.params,
            nc=6,
            kernel_size=3,
            n_hid_chan=32,
        )
        observation = self._observation()
        expected = official.get_update_values_from_obs(observation)
        actual = candidate(observation)
        self.assertEqual(expected.shape, (4, 5, 7))
        self.assertEqual(actual.shape, expected.shape)
        np.testing.assert_array_equal(actual, expected)

    def test_runner_accepts_frozen_cnn_across_distribution_update(self) -> None:
        from dai_lmapf.online_ggo_adapter import OnlineGGOAdapter

        spec = importlib.util.spec_from_file_location(
            "frozen_cnn_runner_test", RUNNER_PATH
        )
        runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(runner)

        class FakeEnv:
            def __init__(self, *, config, seed):
                self.config = config
                self.seed = seed
                self.comp_map = SimpleNamespace(
                    graph=np.zeros((2, 2), dtype=np.int8),
                    height=2,
                    width=2,
                )
                self.version = 0
                self.guidance_sha256 = ""

            def set_dai_guidance_metadata(self, *, version, sha256):
                self.version = version
                self.guidance_sha256 = sha256

            def reset(self, *, seed=None, options=None):
                del seed, options
                observation = np.arange(24, dtype=np.float32).reshape(6, 2, 2)
                trace = {
                    "window_start_timestep": 0,
                    "window_end_timestep": 0,
                    "seed_bundle": {"root": self.seed},
                    "start": [[0, 0]],
                    "planner_initial_priority_order": [0],
                    "curr_pos": [[0, 0]],
                    "curr_tasks": [[1, 1]],
                    "actual_paths": ["R,D"],
                    "recent_events": [],
                    "recent_route_builds": [],
                    "recent_planner_times": [],
                    "recent_distribution_updates": [{
                        "source": "kiva",
                        "timestep": 0,
                        "primary_weights": [1.0],
                        "secondary_weights": [1.0],
                    }],
                    "guidance_version": 0,
                    "guidance_sha256": "0" * 64,
                    "applied_guidance_sha256": "0" * 64,
                    "map_weights_revision": 0,
                    "num_task_finished": 0,
                }
                return observation, {"dai_trace": trace}

            def step(self, action):
                del action
                observation = np.arange(24, dtype=np.float32).reshape(6, 2, 2)
                trace = {
                    "window_start_timestep": 0,
                    "window_end_timestep": 20,
                    "seed_bundle": {"root": self.seed},
                    "start": [[0, 0]],
                    "planner_initial_priority_order": [0],
                    "curr_pos": [[1, 1]],
                    "curr_tasks": [[0, 0]],
                    "actual_paths": ["D,R"],
                    "recent_events": [],
                    "recent_route_builds": [],
                    "recent_planner_times": [{
                        "seconds": 0.0,
                        "timed_out": False,
                    }],
                    "recent_distribution_updates": [],
                    "guidance_version": self.version,
                    "guidance_sha256": self.guidance_sha256,
                    "applied_guidance_sha256": self.guidance_sha256,
                    "map_weights_revision": self.version,
                    "num_task_finished": 2,
                }
                return observation, 2.0, True, False, {"dai_trace": trace}

        config_factory = lambda: SimpleNamespace(
            num_agents=1, simu_time=20
        )
        checkpoint_path = self._write_checkpoint()
        checkpoint = load_frozen_cnn_checkpoint(checkpoint_path)
        result = runner._run_condition(
            method="never",
            seed=20,
            config_factory=config_factory,
            env_class=FakeEnv,
            adapter_class=OnlineGGOAdapter,
            generator_mode="frozen_cnn",
            generator_kwargs={
                "checkpoint_path": str(checkpoint_path),
                "expected_file_sha256": checkpoint.file_sha256,
                "expected_params_sha256": checkpoint.params_sha256,
            },
            decision_window=20,
            warmup_time=0,
            shift_interval=20,
            event_threshold=0.02,
            event_minimum_gap=20,
            cohort_delay=20,
            cohort_min_route_builds=1,
            horizon=20,
        )
        self.assertEqual(result["num_task_finished"], 2)
        self.assertEqual(result["generator_calls"], 1)
        self.assertEqual(
            result["generator_metadata"]["file_sha256"],
            checkpoint.file_sha256,
        )


if __name__ == "__main__":
    unittest.main()
