import unittest

from dai_lmapf.invariants import SafetyViolation, assert_valid_joint_transition


class JointTransitionTests(unittest.TestCase):
    def test_valid_wait_and_move(self) -> None:
        assert_valid_joint_transition(
            {0: (0, 0), 1: (2, 0)},
            {0: (1, 0), 1: (2, 0)},
        )

    def test_rejects_vertex_conflict(self) -> None:
        with self.assertRaisesRegex(SafetyViolation, "vertex conflict"):
            assert_valid_joint_transition(
                {0: (0, 0), 1: (2, 0)},
                {0: (1, 0), 1: (1, 0)},
            )

    def test_rejects_edge_swap(self) -> None:
        with self.assertRaisesRegex(SafetyViolation, "edge-swap conflict"):
            assert_valid_joint_transition(
                {0: (0, 0), 1: (1, 0)},
                {0: (1, 0), 1: (0, 0)},
            )

    def test_rejects_non_unit_move(self) -> None:
        with self.assertRaisesRegex(SafetyViolation, "non-unit move"):
            assert_valid_joint_transition({0: (0, 0)}, {0: (2, 0)})

    def test_rejects_duplicate_initial_state(self) -> None:
        positions = {0: (0, 0), 1: (0, 0)}
        with self.assertRaisesRegex(SafetyViolation, "vertex conflict"):
            assert_valid_joint_transition(positions, positions)


if __name__ == "__main__":
    unittest.main()
