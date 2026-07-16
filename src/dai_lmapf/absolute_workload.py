"""Versioned, exogenous Kiva workloads with absolute release times.

The simulator-facing representation is intentionally small and language
neutral.  ``tape[agent_id][tape_index]`` is ``[goal_location,
release_timestep]`` where locations are flattened map IDs.  Task IDs are not
stored redundantly: they are the agent-major contiguous offset plus the
per-agent tape index.

This module contains *offline* construction and fingerprinting only.  A run
must copy the complete tape into the simulator before timestep zero; no task
content or release time is sampled online.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Sequence


ABSOLUTE_TASK_TAPE_SCHEMA_VERSION = "dai.kiva-absolute-release-tape/v1"
ABSOLUTE_TASK_TAPE_ID_SEMANTICS = (
    "agent-major contiguous offset plus per-agent tape index"
)
ABSOLUTE_TASK_TAPE_FINGERPRINT_SEMANTICS = (
    "fnv1a64(schema,agent_count,agent_id,start_loc,length,"
    "flat_goal_loc,release_timestep),little-endian-u64"
)
ABSOLUTE_TASK_TAPE_RELEASE_SEMANTICS = (
    "r=0 before first plan; r=t>0 after the move ending at t and before "
    "the decision at t; released tasks enter a per-agent FIFO backlog"
)

_UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True)
class KivaMap:
    """Minimal Kiva map view needed by the offline workload generator."""

    rows: int
    cols: int
    grid_types: tuple[str, ...]
    free_locations: tuple[int, ...]
    home_locations: tuple[int, ...]
    endpoint_locations: tuple[int, ...]


def read_kiva_map(path: str | Path) -> KivaMap:
    """Read the octile ``.map`` format used by OnlineGGO's Kiva simulator."""

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if len(lines) < 5 or lines[0].strip() != "type octile":
        raise ValueError("expected an octile Kiva map")
    try:
        rows = int(lines[1].split()[1])
        cols = int(lines[2].split()[1])
    except (IndexError, ValueError) as exc:
        raise ValueError("invalid octile map dimensions") from exc
    if lines[3].strip() != "map" or len(lines[4:]) != rows:
        raise ValueError("invalid octile map body")
    body = lines[4:]
    if any(len(row) != cols for row in body):
        raise ValueError("map row width does not match the header")

    grid_types = tuple(character for row in body for character in row)
    free = tuple(
        location
        for location, character in enumerate(grid_types)
        if character not in {"@", "T"}
    )
    homes = tuple(
        location
        for location, character in enumerate(grid_types)
        if character == "W"
    )
    endpoints = tuple(
        location
        for location, character in enumerate(grid_types)
        if character == "E"
    )
    if not homes or not endpoints:
        raise ValueError("Kiva absolute workloads require W and E locations")
    return KivaMap(rows, cols, grid_types, free, homes, endpoints)


def normalize_absolute_task_tape(
    tape: Sequence[Sequence[Sequence[int]]],
    *,
    start_locations: Sequence[int],
    map_size: int,
    horizon_steps: int | None = None,
) -> list[list[list[int]]]:
    """Validate and defensively copy an absolute release tape.

    Release times must be nondecreasing within each agent's sequence.  Equal
    times are allowed and represent a burst.  The Kiva W/E alternation itself
    is map-specific and is checked independently by the C++ simulator.
    """

    if isinstance(tape, (str, bytes)):
        raise TypeError("absolute_task_tape must be a nested sequence")
    if len(tape) != len(start_locations):
        raise ValueError(
            "absolute_task_tape must contain exactly one sequence per agent"
        )
    if map_size <= 0:
        raise ValueError("map_size must be positive")
    if horizon_steps is not None and horizon_steps <= 0:
        raise ValueError("horizon_steps must be positive when provided")

    normalized: list[list[list[int]]] = []
    for agent_id, sequence in enumerate(tape):
        if isinstance(sequence, (str, bytes)):
            raise TypeError(
                f"absolute_task_tape[{agent_id}] must be a task sequence"
            )
        tasks = list(sequence)
        if not tasks:
            raise ValueError("absolute task-tape sequences must be non-empty")
        previous_release = -1
        normalized_tasks: list[list[int]] = []
        for tape_index, entry in enumerate(tasks):
            if isinstance(entry, (str, bytes)):
                raise TypeError("absolute task entries must be [goal, release]")
            try:
                values = list(entry)
            except TypeError as exc:
                raise TypeError(
                    "absolute task entries must be [goal, release]"
                ) from exc
            if len(values) != 2:
                raise ValueError("absolute task entries must be [goal, release]")
            goal, release = values
            if isinstance(goal, bool) or not isinstance(goal, int):
                raise TypeError(
                    f"goal for agent {agent_id}, index {tape_index} must be int"
                )
            if isinstance(release, bool) or not isinstance(release, int):
                raise TypeError(
                    "release_timestep for agent "
                    f"{agent_id}, index {tape_index} must be int"
                )
            if goal < 0 or goal >= map_size:
                raise ValueError(f"goal location {goal} is outside the map")
            if release < 0:
                raise ValueError("release_timestep must be non-negative")
            if release < previous_release:
                raise ValueError(
                    "release_timestep must be nondecreasing within each agent"
                )
            if horizon_steps is not None and release >= horizon_steps:
                raise ValueError(
                    f"release_timestep {release} is outside [0, {horizon_steps})"
                )
            normalized_tasks.append([goal, release])
            previous_release = release
        normalized.append(normalized_tasks)
    return normalized


def absolute_task_tape_payload(
    start_locations: Sequence[int],
    tape: Sequence[Sequence[Sequence[int]]],
) -> dict[str, object]:
    """Return the only content covered by the cross-method SHA-256 identity."""

    return {
        "schema_version": ABSOLUTE_TASK_TAPE_SCHEMA_VERSION,
        "start_locations": [int(location) for location in start_locations],
        "absolute_task_tape": [
            [[int(goal), int(release)] for goal, release in sequence]
            for sequence in tape
        ],
    }


def absolute_task_tape_sha256(
    start_locations: Sequence[int],
    tape: Sequence[Sequence[Sequence[int]]],
) -> str:
    canonical = json.dumps(
        absolute_task_tape_payload(start_locations, tape),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def absolute_task_tape_fnv1a64(
    start_locations: Sequence[int],
    tape: Sequence[Sequence[Sequence[int]]],
) -> str:
    """Mirror the independent, cheap C++ content fingerprint."""

    if len(start_locations) != len(tape):
        raise ValueError("one start location is required per agent")
    digest = 14695981039346656037

    def add_byte(value: int) -> None:
        nonlocal digest
        digest ^= value
        digest = (digest * 1099511628211) & _UINT64_MASK

    def add_uint64(value: int) -> None:
        for byte_index in range(8):
            add_byte((int(value) >> (8 * byte_index)) & 0xFF)

    for byte in ABSOLUTE_TASK_TAPE_SCHEMA_VERSION.encode("ascii"):
        add_byte(byte)
    add_uint64(len(tape))
    for agent_id, sequence in enumerate(tape):
        add_uint64(agent_id)
        add_uint64(start_locations[agent_id])
        add_uint64(len(sequence))
        for goal_location, release_timestep in sequence:
            add_uint64(goal_location)
            add_uint64(release_timestep)
    return f"{digest:016x}"


def build_absolute_task_tape_manifest(
    start_locations: Sequence[int],
    tape: Sequence[Sequence[Sequence[int]]],
    *,
    generator: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a self-identifying JSON-serializable artifact."""

    payload = absolute_task_tape_payload(start_locations, tape)
    return {
        **payload,
        "manifest_sha256": absolute_task_tape_sha256(start_locations, tape),
        "content_fnv1a64": absolute_task_tape_fnv1a64(start_locations, tape),
        "generator": {} if generator is None else dict(generator),
    }


def _keyed_unit_interval(*parts: object) -> float:
    encoded = "\x1f".join(str(part) for part in parts).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")
    return (value + 0.5) / float(1 << 64)


def _weighted_choice(
    locations: Sequence[int], weights: Sequence[float], quantile: float
) -> int:
    if len(locations) != len(weights) or not locations:
        raise ValueError("locations and weights must be non-empty and aligned")
    total = math.fsum(weights)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("weights must have a finite positive sum")
    threshold = quantile * total
    cumulative = 0.0
    for location, weight in zip(locations, weights):
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("weights must be finite and non-negative")
        cumulative += weight
        if threshold < cumulative:
            return int(location)
    return int(locations[-1])


def _phase_index(release: int, phase_starts: Sequence[int]) -> int:
    phase = 0
    for candidate, start in enumerate(phase_starts):
        if start > release:
            break
        phase = candidate
    return phase


def generate_phase_shifted_kiva_tape(
    *,
    kiva_map: KivaMap,
    start_locations: Sequence[int],
    release_timesteps: Sequence[int],
    phase_starts: Sequence[int],
    endpoint_phase_centers: Sequence[int],
    task_seed: int,
    sigma: float = 0.75,
) -> list[list[list[int]]]:
    """Generate a deterministic, phase-shifted tape entirely offline.

    Each agent receives the same absolute release schedule.  Goals alternate
    between Kiva homes and endpoints.  Endpoint goals follow a Gaussian hotspot
    selected solely by the task's release phase; home goals are uniform.  A
    SHA-256 keyed quantile is used instead of mutable RNG state, so generation
    order cannot couple one agent to another.
    """

    if len(start_locations) <= 0:
        raise ValueError("at least one start location is required")
    if not release_timesteps:
        raise ValueError("release_timesteps must be non-empty")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in release_timesteps
    ):
        raise ValueError("release_timesteps must be non-negative integers")
    if any(
        release_timesteps[index] > release_timesteps[index + 1]
        for index in range(len(release_timesteps) - 1)
    ):
        raise ValueError("release_timesteps must be nondecreasing")
    if (
        not phase_starts
        or phase_starts[0] != 0
        or len(phase_starts) != len(endpoint_phase_centers)
        or any(
            phase_starts[index] >= phase_starts[index + 1]
            for index in range(len(phase_starts) - 1)
        )
    ):
        raise ValueError(
            "phase_starts must begin at zero, increase, and align with centers"
        )
    endpoint_set = set(kiva_map.endpoint_locations)
    if any(center not in endpoint_set for center in endpoint_phase_centers):
        raise ValueError("every phase center must be a Kiva endpoint")
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError("sigma must be finite and positive")
    if any(location not in set(kiva_map.free_locations) for location in start_locations):
        raise ValueError("every start location must be traversable")

    endpoint_weights: list[list[float]] = []
    for center in endpoint_phase_centers:
        center_row, center_col = divmod(center, kiva_map.cols)
        weights: list[float] = []
        for endpoint in kiva_map.endpoint_locations:
            row, col = divmod(endpoint, kiva_map.cols)
            x_scale = 10.0 / max(1, kiva_map.cols - 1)
            y_scale = 10.0 / max(1, kiva_map.rows - 1)
            squared = ((col - center_col) * x_scale) ** 2 + (
                (row - center_row) * y_scale
            ) ** 2
            weights.append(math.exp(-squared / (2.0 * sigma * sigma)))
        endpoint_weights.append(weights)

    tape: list[list[list[int]]] = []
    for agent_id, start in enumerate(start_locations):
        previous = int(start)
        agent_tasks: list[list[int]] = []
        for tape_index, release in enumerate(release_timesteps):
            previous_type = kiva_map.grid_types[previous]
            quantile = _keyed_unit_interval(
                ABSOLUTE_TASK_TAPE_SCHEMA_VERSION,
                task_seed,
                agent_id,
                tape_index,
                release,
            )
            if previous_type in {".", "E"}:
                goal = _weighted_choice(
                    kiva_map.home_locations,
                    [1.0] * len(kiva_map.home_locations),
                    quantile,
                )
            elif previous_type == "W":
                phase = _phase_index(release, phase_starts)
                goal = _weighted_choice(
                    kiva_map.endpoint_locations,
                    endpoint_weights[phase],
                    quantile,
                )
            else:
                raise ValueError(
                    f"unsupported Kiva start/goal type {previous_type!r}"
                )
            agent_tasks.append([goal, int(release)])
            previous = goal
        tape.append(agent_tasks)
    return tape

