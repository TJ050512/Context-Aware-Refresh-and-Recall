"""Safety checks that must run at every simulator step.

These checks are intentionally independent of any planner. A planner result that
violates one of them is invalid evidence, even if the aggregate throughput looks
good.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
Position = tuple[int, int]


class SafetyViolation(AssertionError):
    """Raised when a joint transition violates the MAPF motion model."""


def _agents_by_position(positions: Mapping[int, Position]) -> dict[Position, list[int]]:
    agents: dict[Position, list[int]] = defaultdict(list)
    for agent_id, position in positions.items():
        agents[position].append(agent_id)
    return agents


def assert_valid_joint_transition(
    previous: Mapping[int, Position],
    current: Mapping[int, Position],
    *,
    free_cells: Collection[Position] | None = None,
    allow_agent_birth_or_death: bool = False,
) -> None:
    """Validate one synchronous MAPF transition.

    Checks agent identity consistency, legal unit moves, obstacle occupancy,
    vertex conflicts, and pairwise edge-swap conflicts.
    """

    previous_ids = set(previous)
    current_ids = set(current)
    if not allow_agent_birth_or_death and previous_ids != current_ids:
        missing = sorted(previous_ids - current_ids)
        added = sorted(current_ids - previous_ids)
        raise SafetyViolation(f"agent set changed: missing={missing}, added={added}")

    for agent_id, position in current.items():
        if free_cells is not None and position not in free_cells:
            raise SafetyViolation(f"agent {agent_id} occupies blocked cell {position}")

        if agent_id not in previous:
            continue
        old = previous[agent_id]
        manhattan_distance = abs(old[0] - position[0]) + abs(old[1] - position[1])
        if manhattan_distance > 1:
            raise SafetyViolation(
                f"agent {agent_id} made non-unit move {old}->{position}"
            )

    duplicates = {
        position: sorted(agent_ids)
        for position, agent_ids in _agents_by_position(current).items()
        if len(agent_ids) > 1
    }
    if duplicates:
        raise SafetyViolation(f"vertex conflict(s): {duplicates}")

    # Hash directed transitions so swap detection stays O(number of agents).
    # The earlier quadratic implementation was fine for unit tests but became
    # a material part of runtime once every simulator step was validated.
    directed_moves: dict[tuple[Position, Position], int] = {}
    for agent_id in previous_ids & current_ids:
        old, new = previous[agent_id], current[agent_id]
        if old != new:
            reverse_agent = directed_moves.get((new, old))
            if reverse_agent is not None:
                raise SafetyViolation(
                    "edge-swap conflict: "
                    f"agents {reverse_agent}/{agent_id} swap {new}<->{old}"
                )
            directed_moves[(old, new)] = agent_id
