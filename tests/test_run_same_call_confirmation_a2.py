import copy
import hashlib
import importlib.util
from pathlib import Path
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_same_call_confirmation_a2.py"
V1_PATH = ROOT / "scripts" / "run_same_call_confirmation_v1.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_same_call_confirmation_a2_test", WRAPPER
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SameCallConfirmationA2ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.module = _load()
        self.original = {
            "SAME_CALL_CONFIRMATION_V1_SEEDS": (
                self.module.V1.SAME_CALL_CONFIRMATION_V1_SEEDS
            ),
            "SPLIT_SEED_ORDER": copy.deepcopy(self.module.V1.SPLIT_SEED_ORDER),
            "SPLIT_SEEDS": copy.deepcopy(self.module.V1.SPLIT_SEEDS),
            "_split_protocol_metadata": self.module.V1._split_protocol_metadata,
        }

    def tearDown(self):
        for name, value in self.original.items():
            setattr(self.module.V1, name, value)

    def test_frozen_v1_bytes_are_verified(self):
        digest = hashlib.sha256(V1_PATH.read_bytes()).hexdigest()
        self.assertEqual(digest, self.module.V1_SHA256)
        self.assertEqual(Path(self.module.V1.__file__).resolve(), V1_PATH.resolve())

    def test_only_authorized_control_plane_bindings_change(self):
        before = dict(vars(self.module.V1))
        self.module._bind_a2_root_registry()
        allowed = {
            "SAME_CALL_CONFIRMATION_V1_SEEDS",
            "SPLIT_SEED_ORDER",
            "SPLIT_SEEDS",
            "_split_protocol_metadata",
        }
        changed = {
            name
            for name, value in vars(self.module.V1).items()
            if name in before and value is not before[name]
        }
        self.assertEqual(changed, allowed)
        self.assertEqual(
            self.module.V1.SPLIT_SEED_ORDER[self.module.SPLIT],
            self.module.A2_ROOTS,
        )
        self.assertEqual(
            self.module.V1.SPLIT_SEEDS[self.module.SPLIT],
            frozenset(self.module.A2_ROOTS),
        )

    def test_same_call_split_emits_exact_a2_derivation_provenance(self):
        self.module._bind_a2_control_plane()
        metadata = self.module.V1._split_protocol_metadata(self.module.SPLIT)
        self.assertEqual(
            metadata["preregistered_seeds"], list(self.module.A2_ROOTS)
        )
        self.assertEqual(
            metadata["seed_derivation_source_sha256"],
            self.module.A2_DERIVATION_SOURCE_SHA256,
        )
        self.assertEqual(
            metadata["seed_derivation_domain"],
            self.module.A2_DERIVATION_DOMAIN,
        )
        self.assertIn(
            self.module.A2_DERIVATION_SOURCE_SHA256,
            metadata["seed_derivation"],
        )
        self.assertIn(
            self.module.A2_DERIVATION_DOMAIN,
            metadata["seed_derivation"],
        )

    def test_other_split_provenance_is_delegated_unchanged(self):
        expected = self.module.V1_SPLIT_PROTOCOL_METADATA("validation_v2")
        self.module._bind_a2_control_plane()
        actual = self.module.V1._split_protocol_metadata("validation_v2")
        self.assertEqual(actual, expected)

    def test_a2_roots_pass_and_other_vectors_fail(self):
        self.module._bind_a2_root_registry()
        self.module.V1._validate_split(
            self.module.SPLIT, self.module.A2_ROOTS, False
        )
        with self.assertRaises(ValueError):
            self.module.V1._validate_split(
                self.module.SPLIT, self.module.A2_ROOTS[:-1], False
            )
        retired = self.original["SAME_CALL_CONFIRMATION_V1_SEEDS"]
        with self.assertRaises(ValueError):
            self.module.V1._validate_split(self.module.SPLIT, retired, False)

    def test_main_delegates_to_frozen_v1_main(self):
        with mock.patch.object(self.module.V1, "main") as delegated:
            self.module.main()
        delegated.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
