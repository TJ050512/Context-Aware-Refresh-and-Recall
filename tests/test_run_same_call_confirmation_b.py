import copy
import hashlib
import importlib.util
from pathlib import Path
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_same_call_confirmation_b.py"
V1_PATH = ROOT / "scripts" / "run_same_call_confirmation_v1.py"
A1_ROOTS = {
    767369, 695428, 323681, 904171, 446020,
    434435, 488565, 514527, 544573, 838809,
}
A2_ROOTS = {
    691817, 376110, 263001, 293231, 296805,
    274330, 997942, 319782, 807287, 326454,
}


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_same_call_confirmation_b_test", WRAPPER
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _derive(source: str, domain: str, index: int) -> int:
    digest = hashlib.sha256(
        f"{source}|{domain}|{index}".encode("utf-8")
    ).hexdigest()
    return 100000 + (int(digest[:16], 16) % 900000)


class SameCallConfirmationBControlPlaneTests(unittest.TestCase):
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

    def test_b_roots_match_frozen_derivation_and_are_fresh(self):
        expected = tuple(
            _derive(
                self.module.B_DERIVATION_SOURCE_SHA256,
                self.module.B_DOMAIN,
                index,
            )
            for index in range(40)
        )
        self.assertEqual(self.module.B_ROOTS, expected)
        self.assertEqual(len(self.module.B_ROOTS), 40)
        self.assertEqual(len(set(self.module.B_ROOTS)), 40)
        self.assertFalse(set(self.module.B_ROOTS) & (A1_ROOTS | A2_ROOTS))

    def test_only_authorized_control_plane_bindings_change(self):
        before = dict(vars(self.module.V1))
        self.module._bind_b_root_registry()
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
            self.module.B_ROOTS,
        )
        self.assertEqual(
            self.module.V1.SPLIT_SEEDS[self.module.SPLIT],
            frozenset(self.module.B_ROOTS),
        )

    def test_same_call_split_emits_exact_b_derivation_provenance(self):
        self.module._bind_b_control_plane()
        metadata = self.module.V1._split_protocol_metadata(self.module.SPLIT)
        self.assertEqual(
            metadata["preregistered_seeds"], list(self.module.B_ROOTS)
        )
        self.assertEqual(
            metadata["seed_derivation_source_sha256"],
            self.module.B_DERIVATION_SOURCE_SHA256,
        )
        self.assertEqual(metadata["seed_derivation_domain"], self.module.B_DOMAIN)
        self.assertIn(
            self.module.B_DERIVATION_SOURCE_SHA256,
            metadata["seed_derivation"],
        )
        self.assertIn(self.module.B_DOMAIN, metadata["seed_derivation"])
        self.assertIn("i=0..39", metadata["seed_derivation"])

    def test_other_split_provenance_is_delegated_unchanged(self):
        expected = self.module.V1_SPLIT_PROTOCOL_METADATA("validation_v2")
        self.module._bind_b_control_plane()
        actual = self.module.V1._split_protocol_metadata("validation_v2")
        self.assertEqual(actual, expected)

    def test_b_roots_pass_and_other_vectors_fail(self):
        self.module._bind_b_root_registry()
        self.module.V1._validate_split(
            self.module.SPLIT, self.module.B_ROOTS, False
        )
        with self.assertRaises(ValueError):
            self.module.V1._validate_split(
                self.module.SPLIT, self.module.B_ROOTS[:-1], False
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
