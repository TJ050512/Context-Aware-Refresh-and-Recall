"""Selective stale-field repair diagnostic on the safe smoke executor.

This is intentionally *not* called GPIBT guide-path repair.  The smoke
executor follows per-agent distance potentials and chooses a safe move at every
step.  The diagnostic asks whether selectively rebinding stale potentials after
a global guidance change has useful headroom before implementing the analogous
operation in the official C++ backbone.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from .invariants import Position, assert_valid_joint_transition
from .protocol import ScenarioManifest
from .smoke_sim import (
    INF,
    GridMap,
    SmokeAgent,
    _phase_index,
    build_smoke_map,
    build_task_tape,
    safe_priority_step,
)


def _snapshot_hash(cell_cost: Mapping[Position, float]) -> str:
    payload = [
        [row, column, float(value)]
        for (row, column), value in sorted(cell_cost.items())
    ]
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


@dataclass(frozen=True)
class GuidanceSnapshot:
    version: int
    created_step: int
    cell_cost: Mapping[Position, float]
    snapshot_hash: str


@dataclass
class FieldBinding:
    goal: Position
    version: int
    built_step: int
    field: Mapping[Position, float]


@dataclass(frozen=True)
class RepairEvent:
    step: int
    old_version: int
    new_version: int
    old_snapshot_hash: str
    new_snapshot_hash: str
    eligible_count: int
    selected_count: int
    unique_field_builds: int
    exposure_mass: float
    selected_exposure_mass: float
    exposure_capture: float
    wasted_repair_ratio: float
    nominal_path_changed: int
    preferred_move_changed: int
    corridor_switched: int
    generation_seconds: float
    exposure_seconds: float
    field_build_seconds: float
    selected_agent_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["selected_agent_ids"] = list(self.selected_agent_ids)
        return payload


@dataclass(frozen=True)
class SelectiveRepairResult:
    run_id: str
    method: str
    map_id: str
    workload: str
    n_agents: int
    seed: int
    selector_seed: int
    event_delay: int
    guidance_scale: float
    horizon: int
    completed: int
    throughput: float
    post_shift_completed_100: int
    post_shift_throughput_100: float
    post_shift_wait_rate_100: float
    stale_fraction_auc: float
    version_lag_auc: float
    repair_event_count: int
    repair_rebind_count: int
    unique_field_build_count: int
    new_task_rebind_count: int
    new_task_unique_field_build_count: int
    guidance_generation_seconds: float
    exposure_seconds: float
    repair_field_build_seconds: float
    new_task_field_build_seconds: float
    executor_seconds: float
    wall_time_seconds: float
    collision_count: int
    deadlocked: bool
    trace_hash: str
    task_tape_hash: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class SnapshotStore:
    def __init__(self, world: GridMap, *, scale: float) -> None:
        self.world = world
        self.scale = scale
        self.snapshots: dict[int, GuidanceSnapshot] = {}
        self._fields: dict[tuple[int, Position], Mapping[Position, float]] = {}

    def install(
        self, *, step: int, cell_cost: Mapping[Position, float]
    ) -> GuidanceSnapshot:
        version = len(self.snapshots)
        normalized = {
            cell: max(0.0, float(cell_cost.get(cell, 0.0)))
            for cell in self.world.free_cells
        }
        snapshot = GuidanceSnapshot(
            version=version,
            created_step=step,
            cell_cost=normalized,
            snapshot_hash=_snapshot_hash(normalized),
        )
        self.snapshots[version] = snapshot
        return snapshot

    def field(self, version: int, goal: Position) -> tuple[Mapping[Position, float], bool, float]:
        key = (version, goal)
        cached = self._fields.get(key)
        if cached is not None:
            return cached, False, 0.0
        started = time.perf_counter_ns()
        snapshot = self.snapshots[version]
        computed = self.world.distance_field(
            goal, cell_cost=snapshot.cell_cost, scale=self.scale
        )
        seconds = (time.perf_counter_ns() - started) / 1e9
        self._fields[key] = computed
        return computed, True, seconds


def oracle_corridor_cost(world: GridMap, distribution: str) -> dict[Position, float]:
    """Deterministic shift intervention used only for causal mechanism tests."""

    corridor_rows = sorted({row for row, _ in world.bridge_cells})
    if not corridor_rows:
        # The open-map diagnostic uses a horizontal band instead of a bridge.
        corridor_rows = [world.height // 3, 2 * world.height // 3]
    if distribution.startswith("top_hotspot"):
        congested_row = corridor_rows[0]
    elif distribution.startswith("bottom_hotspot"):
        congested_row = corridor_rows[-1]
    else:
        raise ValueError(f"unsupported oracle distribution: {distribution}")
    costs: dict[Position, float] = {}
    for cell in world.free_cells:
        row, column = cell
        if world.bridge_cells:
            if cell in world.bridge_cells:
                costs[cell] = 1.0 / (1.0 + abs(row - congested_row))
            else:
                costs[cell] = 0.0
        else:
            center = world.width // 2
            in_middle = abs(column - center) <= 2
            costs[cell] = (
                1.0 / (1.0 + abs(row - congested_row)) if in_middle else 0.0
            )
    return costs


def nominal_path(
    world: GridMap,
    start: Position,
    goal: Position,
    potential: Mapping[Position, float],
) -> tuple[Position, ...]:
    """Roll out a deterministic strictly descending path for diagnostics."""

    if start == goal:
        return (start,)
    path = [start]
    current = start
    for _ in range(len(world.free_cells)):
        current_value = potential.get(current, INF)
        choices = sorted(
            world.neighbors[current],
            key=lambda cell: (potential.get(cell, INF), cell[0], cell[1]),
        )
        if not choices or potential.get(choices[0], INF) >= current_value - 1e-12:
            raise RuntimeError(
                f"potential does not strictly descend from {current} toward {goal}"
            )
        current = choices[0]
        path.append(current)
        if current == goal:
            return tuple(path)
    raise RuntimeError("nominal path exceeded the number of traversable cells")


def relative_positive_exposure(
    path: Sequence[Position],
    *,
    old_snapshot: GuidanceSnapshot,
    new_snapshot: GuidanceSnapshot,
    scale: float,
) -> float:
    if len(path) <= 1:
        return 0.0
    old_cost = 0.0
    positive_delta = 0.0
    for cell in path[:-1]:
        old_value = old_snapshot.cell_cost.get(cell, 0.0)
        new_value = new_snapshot.cell_cost.get(cell, 0.0)
        old_cost += 1.0 + scale * old_value
        positive_delta += scale * max(0.0, new_value - old_value)
    return positive_delta / max(1e-12, old_cost)


def _corridor_row(world: GridMap, path: Sequence[Position]) -> int | None:
    for row, column in path:
        if (row, column) in world.bridge_cells:
            return row
    return None


def _selection_fraction(method: str) -> float:
    if method.endswith("_10"):
        return 0.10
    if method.endswith("_25"):
        return 0.25
    raise ValueError(f"method has no registered selection fraction: {method}")


def _select_agents(
    method: str,
    eligible: Sequence[int],
    exposures: Mapping[int, float],
    rng: random.Random,
) -> list[int]:
    if method in {"no_update", "lazy_0", "static_no_event"}:
        return []
    if method in {"repair_all", "identity_all"}:
        return sorted(eligible)
    fraction = _selection_fraction(method)
    count = min(len(eligible), math.ceil(fraction * len(eligible)))
    if method.startswith("top_"):
        return sorted(eligible, key=lambda agent_id: (-exposures[agent_id], agent_id))[:count]
    if method.startswith("random_"):
        return sorted(rng.sample(list(eligible), count))
    raise ValueError(f"unknown selective repair method: {method}")


def run_selective_repair_episode(
    *,
    manifest: ScenarioManifest,
    workload: str,
    method: str,
    selector_seed: int = 0,
    guidance_scale: float = 8.0,
    post_shift_window: int = 100,
    event_delay: int = 0,
) -> tuple[SelectiveRepairResult, list[RepairEvent]]:
    """Run one paired stale-potential propagation diagnostic."""

    supported = {
        "no_update",
        "lazy_0",
        "random_10",
        "random_25",
        "top_10",
        "top_25",
        "repair_all",
        "static_no_event",
        "identity_all",
    }
    if method not in supported:
        raise ValueError(f"unknown method: {method}")
    if post_shift_window <= 0:
        raise ValueError("post_shift_window must be positive")
    if event_delay < 0:
        raise ValueError("event_delay must be non-negative")
    manifest.validate()
    world = build_smoke_map(manifest.map_id)
    tape = build_task_tape(world, manifest)
    agents: list[SmokeAgent] = []
    for agent_id, start in enumerate(tape.starts):
        goal = tape.goal_for(0, agent_id, 0)
        agents.append(SmokeAgent(agent_id=agent_id, position=start, goal=goal))
    initial = {agent.agent_id: agent.position for agent in agents}
    assert_valid_joint_transition(initial, initial, free_cells=world.free_cells)

    store = SnapshotStore(world, scale=guidance_scale)
    first_distribution = manifest.phases[0].goal_distribution
    snapshot = store.install(
        step=0, cell_cost=oracle_corridor_cost(world, first_distribution)
    )
    bindings: dict[int, FieldBinding] = {}
    for agent in agents:
        potential, _, _ = store.field(snapshot.version, agent.goal)
        bindings[agent.agent_id] = FieldBinding(
            goal=agent.goal,
            version=snapshot.version,
            built_step=0,
            field=potential,
        )

    execution_rng = random.Random(manifest.arrival_seed)
    selector_rng = random.Random(selector_seed)
    events: list[RepairEvent] = []
    first_shift = (
        manifest.phases[1].start_step if len(manifest.phases) > 1 else manifest.horizon_steps // 2
    )
    trace: list[tuple[Position, ...]] = []
    total_completed = total_wait = active_agent_steps = 0
    post_completed = post_wait = post_agent_steps = 0
    stale_values: list[float] = []
    lag_values: list[float] = []
    repair_rebind_count = 0
    repair_unique_build_count = 0
    new_task_rebind_count = 0
    new_task_unique_build_count = 0
    generation_seconds = exposure_seconds = repair_build_seconds = 0.0
    new_task_build_seconds = executor_seconds = 0.0
    last_completion_step = 0
    started_run = time.perf_counter_ns()

    for step in range(manifest.horizon_steps):
        phase_index = _phase_index(manifest.phases, step)
        phase = manifest.phases[phase_index]
        is_phase_event = (
            method != "no_update"
            and phase_index > 0
            and step == phase.start_step + event_delay
            and step < phase.end_step
        )
        is_identity_event = (
            method == "identity_all"
            and len(manifest.phases) == 1
            and step == first_shift
        )
        if is_phase_event or is_identity_event:
            old_snapshot = snapshot
            generation_started = time.perf_counter_ns()
            next_cost = (
                old_snapshot.cell_cost
                if is_identity_event
                else oracle_corridor_cost(world, phase.goal_distribution)
            )
            snapshot = store.install(step=step, cell_cost=next_cost)
            event_generation = (time.perf_counter_ns() - generation_started) / 1e9
            generation_seconds += event_generation

            eligible = [
                agent.agent_id
                for agent in agents
                if bindings[agent.agent_id].version < snapshot.version
                and bindings[agent.agent_id].goal == agent.goal
            ]
            scan_started = time.perf_counter_ns()
            exposures: dict[int, float] = {}
            old_paths: dict[int, tuple[Position, ...]] = {}
            for agent_id in eligible:
                agent = agents[agent_id]
                binding = bindings[agent_id]
                path = nominal_path(world, agent.position, agent.goal, binding.field)
                old_paths[agent_id] = path
                exposures[agent_id] = relative_positive_exposure(
                    path,
                    old_snapshot=store.snapshots[binding.version],
                    new_snapshot=snapshot,
                    scale=guidance_scale,
                )
            event_exposure_seconds = (time.perf_counter_ns() - scan_started) / 1e9
            exposure_seconds += event_exposure_seconds
            selected = _select_agents(method, eligible, exposures, selector_rng)
            selected_set = set(selected)
            path_changed = preferred_changed = corridor_changed = 0
            unique_builds = 0
            event_build_seconds = 0.0
            for agent_id in selected:
                agent = agents[agent_id]
                potential, built, seconds = store.field(snapshot.version, agent.goal)
                unique_builds += int(built)
                event_build_seconds += seconds
                new_path = nominal_path(world, agent.position, agent.goal, potential)
                old_path = old_paths[agent_id]
                path_changed += int(new_path != old_path)
                preferred_changed += int(
                    len(new_path) > 1
                    and len(old_path) > 1
                    and new_path[1] != old_path[1]
                )
                corridor_changed += int(
                    _corridor_row(world, new_path) != _corridor_row(world, old_path)
                )
                bindings[agent_id] = FieldBinding(
                    goal=agent.goal,
                    version=snapshot.version,
                    built_step=step,
                    field=potential,
                )
            repair_rebind_count += len(selected)
            repair_unique_build_count += unique_builds
            repair_build_seconds += event_build_seconds
            total_exposure = sum(exposures.values())
            selected_exposure = sum(exposures[agent_id] for agent_id in selected_set)
            events.append(
                RepairEvent(
                    step=step,
                    old_version=old_snapshot.version,
                    new_version=snapshot.version,
                    old_snapshot_hash=old_snapshot.snapshot_hash,
                    new_snapshot_hash=snapshot.snapshot_hash,
                    eligible_count=len(eligible),
                    selected_count=len(selected),
                    unique_field_builds=unique_builds,
                    exposure_mass=total_exposure,
                    selected_exposure_mass=selected_exposure,
                    exposure_capture=(
                        selected_exposure / total_exposure if total_exposure > 0 else 0.0
                    ),
                    wasted_repair_ratio=(
                        sum(exposures[agent_id] <= 0.0 for agent_id in selected)
                        / max(1, len(selected))
                    ),
                    nominal_path_changed=path_changed,
                    preferred_move_changed=preferred_changed,
                    corridor_switched=corridor_changed,
                    generation_seconds=event_generation,
                    exposure_seconds=event_exposure_seconds,
                    field_build_seconds=event_build_seconds,
                    selected_agent_ids=tuple(selected),
                )
            )

        # A newly assigned goal always uses the latest installed snapshot.  It
        # is normal planner work and is logged separately from selective repair.
        for agent in agents:
            binding = bindings[agent.agent_id]
            if binding.goal == agent.goal:
                continue
            potential, built, seconds = store.field(snapshot.version, agent.goal)
            bindings[agent.agent_id] = FieldBinding(
                goal=agent.goal,
                version=snapshot.version,
                built_step=step,
                field=potential,
            )
            new_task_rebind_count += 1
            new_task_unique_build_count += int(built)
            new_task_build_seconds += seconds

        if step >= first_shift:
            stale = [
                float(bindings[agent.agent_id].version < snapshot.version)
                for agent in agents
            ]
            stale_values.append(sum(stale) / len(stale))
            lag_values.append(
                sum(
                    snapshot.version - bindings[agent.agent_id].version
                    for agent in agents
                )
                / len(agents)
            )

        planning_started = time.perf_counter_ns()
        fields = {
            agent.agent_id: bindings[agent.agent_id].field for agent in agents
        }
        step_stats = safe_priority_step(world, agents, fields, execution_rng)
        executor_seconds += (time.perf_counter_ns() - planning_started) / 1e9
        trace.append(tuple(agent.position for agent in agents))
        total_wait += step_stats.waited
        active_agent_steps += len(agents)
        if first_shift <= step < first_shift + post_shift_window:
            post_wait += step_stats.waited
            post_agent_steps += len(agents)

        for agent in agents:
            if agent.position != agent.goal:
                continue
            agent.completed += 1
            total_completed += 1
            if first_shift <= step < first_shift + post_shift_window:
                post_completed += 1
            last_completion_step = step
            agent.task_index += 1
            next_goal = tape.goal_for(phase_index, agent.agent_id, agent.task_index)
            if next_goal == agent.position:
                raise ValueError("task tape produced a zero-distance task")
            agent.goal = next_goal

    trace_hash = hashlib.sha256(
        json.dumps(trace, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    run_payload = {
        "manifest": manifest.as_dict(),
        "method": method,
        "selector_seed": selector_seed,
        "guidance_scale": guidance_scale,
        "event_delay": event_delay,
    }
    run_id = hashlib.sha256(
        json.dumps(run_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    wall_seconds = (time.perf_counter_ns() - started_run) / 1e9
    post_duration = min(post_shift_window, manifest.horizon_steps - first_shift)
    result = SelectiveRepairResult(
        run_id=run_id,
        method=method,
        map_id=manifest.map_id,
        workload=workload,
        n_agents=len(agents),
        seed=manifest.layout_seed - 101,
        selector_seed=selector_seed,
        event_delay=event_delay,
        guidance_scale=guidance_scale,
        horizon=manifest.horizon_steps,
        completed=total_completed,
        throughput=total_completed / manifest.horizon_steps,
        post_shift_completed_100=post_completed,
        post_shift_throughput_100=post_completed / max(1, post_duration),
        post_shift_wait_rate_100=post_wait / max(1, post_agent_steps),
        stale_fraction_auc=(sum(stale_values) / len(stale_values) if stale_values else 0.0),
        version_lag_auc=(sum(lag_values) / len(lag_values) if lag_values else 0.0),
        repair_event_count=len(events),
        repair_rebind_count=repair_rebind_count,
        unique_field_build_count=repair_unique_build_count,
        new_task_rebind_count=new_task_rebind_count,
        new_task_unique_field_build_count=new_task_unique_build_count,
        guidance_generation_seconds=generation_seconds,
        exposure_seconds=exposure_seconds,
        repair_field_build_seconds=repair_build_seconds,
        new_task_field_build_seconds=new_task_build_seconds,
        executor_seconds=executor_seconds,
        wall_time_seconds=wall_seconds,
        collision_count=0,
        deadlocked=(
            manifest.horizon_steps - last_completion_step > max(50, world.width * 4)
        ),
        trace_hash=trace_hash,
        task_tape_hash=tape.tape_hash,
    )
    return result, events


__all__ = [
    "FieldBinding",
    "GuidanceSnapshot",
    "RepairEvent",
    "SelectiveRepairResult",
    "SnapshotStore",
    "nominal_path",
    "oracle_corridor_cost",
    "relative_positive_exposure",
    "run_selective_repair_episode",
]
