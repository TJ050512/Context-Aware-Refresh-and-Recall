import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

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
            load_frozen_cnn_checkpoint(path, expected_file_sha256="0" * 64)
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

    def test_synthetic_output_matches_pinned_onlineggo(self) -> None:
        sys.path.insert(0, str(CMAES))
        try:
            from env_search.traffic_mapf.update_model.update_model import (
                CNNUpdateModel,
            )
        except ImportError as exc:
            self.skipTest(f"pinned OnlineGGO imports unavailable: {exc}")
        finally:
            if sys.path[0] == str(CMAES):
                sys.path.pop(0)

        candidate = FrozenCNNGuidanceGenerator.from_path(
            self._write_checkpoint()
        )
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


if __name__ == "__main__":
    unittest.main()
