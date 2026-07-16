"""Task records and validity rules shared by all evaluated methods."""

from __future__ import annotations

from dataclasses import dataclass

from .invariants import Position


class InvalidTask(ValueError):
    """Raised when a generated task violates the registered protocol."""


@dataclass(frozen=True)
class ReleasedTask:
    task_id: int
    release_step: int
    goal: Position
    pickup: Position | None = None


def validate_released_task(
    task: ReleasedTask,
    *,
    current_position: Position,
    free_cells: set[Position],
    horizon_steps: int,
    allow_zero_distance: bool = False,
) -> None:
    """Validate a task before it enters the shared task stream."""

    if task.task_id < 0:
        raise InvalidTask(f"task_id must be non-negative: {task.task_id}")
    if task.release_step < 0 or task.release_step >= horizon_steps:
        raise InvalidTask(
            f"release_step {task.release_step} outside [0, {horizon_steps})"
        )
    if task.goal not in free_cells:
        raise InvalidTask(f"goal {task.goal} is not traversable")
    if not allow_zero_distance and task.goal == current_position:
        raise InvalidTask(
            f"zero-distance task {task.task_id}: current position equals goal {task.goal}"
        )
    if task.pickup is not None and task.pickup not in free_cells:
        raise InvalidTask(f"pickup {task.pickup} is not traversable")
