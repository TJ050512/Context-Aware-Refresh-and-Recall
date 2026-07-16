import unittest

from dai_lmapf.tasks import InvalidTask, ReleasedTask, validate_released_task


class ReleasedTaskTests(unittest.TestCase):
    def test_accepts_released_nonzero_task(self) -> None:
        validate_released_task(
            ReleasedTask(task_id=1, release_step=3, goal=(1, 0)),
            current_position=(0, 0),
            free_cells={(0, 0), (1, 0)},
            horizon_steps=10,
        )

    def test_rejects_zero_distance_task(self) -> None:
        with self.assertRaisesRegex(InvalidTask, "zero-distance"):
            validate_released_task(
                ReleasedTask(task_id=1, release_step=3, goal=(0, 0)),
                current_position=(0, 0),
                free_cells={(0, 0), (1, 0)},
                horizon_steps=10,
            )


if __name__ == "__main__":
    unittest.main()
