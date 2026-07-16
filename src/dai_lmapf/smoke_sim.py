"""Correctness-first smoke simulator for guidance-refresh experiments.

This module is intentionally modest: it is a transactional grid executor and a
cached congestion-guidance backend for testing the *refresh-control mechanism*
before the official Online GGO/GPIBT backend is available.  Results from this
simulator are diagnostics, not public-benchmark SOTA evidence.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Hashable, Mapping, Sequence

from .controller import (
    GuidanceAction,
    GuidanceController,
    TrafficContext,
    WindowFeedback,
)
from .invariants import Position, assert_valid_joint_transition
from .protocol import ScenarioManifest, WorkloadPhase

INF = 10**12


def _canonical_hash(payload: object, *, length: int = 16) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


@dataclass
class GridMap:
    map_id: str
    grid: tuple[str, ...]
    free_cells: frozenset[Position]
    neighbors: dict[Position, tuple[Position, ...]]
    left_cells: tuple[Position, ...]
    right_cells: tuple[Position, ...]
    bridge_cells: frozenset[Position]
    _plain_cache: dict[Position, dict[Position, float]] = field(default_factory=dict)

    @classmethod
    def from_grid(
        cls,
        map_id: str,
        grid: Sequence[str],
        *,
        left_columns: range,
        right_columns: range,
        bridge_columns: range | None = None,
    ) -> "GridMap":
        if not grid or len({len(row) for row in grid}) != 1:
            raise ValueError("grid must be a non-empty rectangle")
        free = {
            (row, column)
            for row, line in enumerate(grid)
            for column, value in enumerate(line)
            if value != "#"
        }
        neighbors: dict[Position, tuple[Position, ...]] = {}
        for row, column in free:
            adjacent = []
            for delta_row, delta_column in ((-1, 0), (0, 1), (1, 0), (0, -1)):
                candidate = (row + delta_row, column + delta_column)
                if candidate in free:
                    adjacent.append(candidate)
            neighbors[(row, column)] = tuple(adjacent)
        left = tuple(sorted(cell for cell in free if cell[1] in left_columns))
        right = tuple(sorted(cell for cell in free if cell[1] in right_columns))
        bridge = frozenset(
            cell
            for cell in free
            if bridge_columns is not None and cell[1] in bridge_columns
        )
        if not left or not right:
            raise ValueError("map must define non-empty left and right task regions")
        return cls(
            map_id=map_id,
            grid=tuple(grid),
            free_cells=frozenset(free),
            neighbors=neighbors,
            left_cells=left,
            right_cells=right,
            bridge_cells=bridge,
        )

    @property
    def height(self) -> int:
        return len(self.grid)

    @property
    def width(self) -> int:
        return len(self.grid[0])

    def side(self, cell: Position) -> str:
        if cell in self.left_cells:
            return "left"
        if cell in self.right_cells:
            return "right"
        return "bridge"

    def distance_field(
        self,
        goal: Position,
        *,
        cell_cost: Mapping[Position, float] | None = None,
        scale: float = 0.0,
    ) -> dict[Position, float]:
        if goal not in self.free_cells:
            raise ValueError(f"goal {goal} is not traversable")
        if not cell_cost or scale == 0.0:
            cached = self._plain_cache.get(goal)
            if cached is not None:
                return cached
        distances: dict[Position, float] = {goal: 0.0}
        queue: list[tuple[float, Position]] = [(0.0, goal)]
        while queue:
            distance, cell = heapq.heappop(queue)
            if distance != distances.get(cell):
                continue
            for neighbor in self.neighbors[cell]:
                edge_cost = 1.0
                if cell_cost:
                    edge_cost += scale * max(0.0, cell_cost.get(neighbor, 0.0))
                candidate = distance + edge_cost
                if candidate < distances.get(neighbor, INF):
                    distances[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))
        if not cell_cost or scale == 0.0:
            self._plain_cache[goal] = distances
        return distances

    def shortest_distance(self, start: Position, goal: Position) -> int:
        distance = self.distance_field(goal).get(start, INF)
        return int(distance) if distance < INF else int(INF)


def make_corridor_map(n_corridors: int = 2) -> GridMap:
    if n_corridors not in {2, 3}:
        raise ValueError("smoke map supports two or three corridors")
    room_width, room_height, bridge_length = 8, 11, 6
    total_width = room_width * 2 + bridge_length
    grid = [["#"] * (total_width + 2) for _ in range(room_height + 2)]
    for row in range(1, room_height + 1):
        for column in range(1, room_width + 1):
            grid[row][column] = "."
        for column in range(room_width + bridge_length + 1, total_width + 1):
            grid[row][column] = "."
    rows = (3, 9) if n_corridors == 2 else (2, 6, 10)
    bridge_columns = range(room_width + 1, room_width + bridge_length + 1)
    for row in rows:
        for column in bridge_columns:
            grid[row][column] = "."
    return GridMap.from_grid(
        f"{n_corridors}_corridor",
        ["".join(row) for row in grid],
        left_columns=range(1, room_width + 1),
        right_columns=range(room_width + bridge_length + 1, total_width + 1),
        bridge_columns=bridge_columns,
    )


def make_open_map(width: int = 24, height: int = 12) -> GridMap:
    grid = ["#" * (width + 2)]
    grid.extend("#" + "." * width + "#" for _ in range(height))
    grid.append("#" * (width + 2))
    midpoint = 1 + width // 2
    return GridMap.from_grid(
        "open",
        grid,
        left_columns=range(1, midpoint),
        right_columns=range(midpoint, width + 1),
    )


def build_smoke_map(map_id: str) -> GridMap:
    if map_id == "two_corridor":
        return make_corridor_map(2)
    if map_id == "three_corridor":
        return make_corridor_map(3)
    if map_id == "open":
        return make_open_map()
    raise ValueError(f"unknown smoke map: {map_id}")


def build_workload_phases(
    workload: str,
    *,
    horizon_steps: int,
    active_agents: int,
    seed: int,
) -> tuple[WorkloadPhase, ...]:
    if horizon_steps < 30:
        raise ValueError("smoke horizon must be at least 30 steps")
    rng = random.Random(seed)
    first = "top_hotspot" if rng.randrange(2) == 0 else "bottom_hotspot"
    second = "bottom_hotspot" if first == "top_hotspot" else "top_hotspot"
    if workload == "static":
        phases = (WorkloadPhase(first, 0, horizon_steps, active_agents, first),)
    elif workload == "abrupt":
        center = int(horizon_steps * 0.45)
        jitter = max(1, horizon_steps // 12)
        shift = rng.randint(center - jitter, center + jitter)
        phases = (
            WorkloadPhase(first, 0, shift, active_agents, first),
            WorkloadPhase(second, shift, horizon_steps, active_agents, second),
        )
    elif workload == "recurring":
        first_shift = rng.randint(int(horizon_steps * 0.28), int(horizon_steps * 0.36))
        second_shift = rng.randint(int(horizon_steps * 0.62), int(horizon_steps * 0.72))
        phases = (
            WorkloadPhase(first, 0, first_shift, active_agents, first),
            WorkloadPhase(second, first_shift, second_shift, active_agents, second),
            WorkloadPhase(first + "_return", second_shift, horizon_steps, active_agents, first),
        )
    else:
        raise ValueError(f"unknown workload: {workload}")
    return phases


def build_smoke_manifest(
    *,
    map_id: str,
    workload: str,
    n_agents: int,
    horizon_steps: int,
    seed: int,
) -> ScenarioManifest:
    phases = build_workload_phases(
        workload,
        horizon_steps=horizon_steps,
        active_agents=n_agents,
        seed=seed + 41,
    )
    manifest = ScenarioManifest(
        schema_version="1",
        map_id=map_id,
        map_family="smoke",
        horizon_steps=horizon_steps,
        layout_seed=seed + 101,
        start_seed=seed + 10_101,
        task_seed=seed + 20_101,
        arrival_seed=seed + 30_101,
        policy_seed=0,
        phases=phases,
    )
    manifest.validate()
    return manifest


def _phase_index(phases: Sequence[WorkloadPhase], step: int) -> int:
    for index, phase in enumerate(phases):
        if phase.start_step <= step < phase.end_step:
            return index
    raise ValueError(f"step {step} is outside the workload phases")


def _pool_for_distribution(
    cells: Sequence[Position], distribution: str, *, height: int
) -> list[Position]:
    if distribution.startswith("top_hotspot"):
        pool = [cell for cell in cells if cell[0] <= height // 2]
    elif distribution.startswith("bottom_hotspot"):
        pool = [cell for cell in cells if cell[0] > height // 2]
    elif distribution == "uniform":
        pool = list(cells)
    else:
        raise ValueError(f"unsupported goal distribution: {distribution}")
    return pool or list(cells)


@dataclass(frozen=True)
class TaskTape:
    starts: tuple[Position, ...]
    goals_by_phase: tuple[tuple[tuple[Position, ...], ...], ...]
    tape_hash: str

    def goal_for(self, phase_index: int, agent_id: int, task_index: int) -> Position:
        return self.goals_by_phase[phase_index][agent_id][task_index]


def build_task_tape(world: GridMap, manifest: ScenarioManifest) -> TaskTape:
    n_agents = manifest.phases[0].active_agents
    if any(phase.active_agents != n_agents for phase in manifest.phases):
        raise ValueError("smoke pilot keeps active-agent count fixed within an episode")
    rng_starts = random.Random(manifest.start_seed)
    left = list(world.left_cells)
    right = list(world.right_cells)
    rng_starts.shuffle(left)
    rng_starts.shuffle(right)
    requested_left = (n_agents + 1) // 2
    requested_right = n_agents // 2
    if requested_left > len(left) or requested_right > len(right):
        raise ValueError("not enough distinct start cells for requested agent count")
    starts: list[Position] = []
    left_index = right_index = 0
    for agent_id in range(n_agents):
        if agent_id % 2 == 0:
            starts.append(left[left_index])
            left_index += 1
        else:
            starts.append(right[right_index])
            right_index += 1

    max_tasks = manifest.horizon_steps + 1
    rng_tasks = random.Random(manifest.task_seed)
    goals_by_phase: list[tuple[tuple[Position, ...], ...]] = []
    for phase in manifest.phases:
        left_pool = _pool_for_distribution(
            world.left_cells, phase.goal_distribution, height=world.height
        )
        right_pool = _pool_for_distribution(
            world.right_cells, phase.goal_distribution, height=world.height
        )
        phase_agents: list[tuple[Position, ...]] = []
        for agent_id, start in enumerate(starts):
            start_side = world.side(start)
            agent_goals: list[Position] = []
            for task_index in range(max_tasks):
                target_start_side = task_index % 2 == 1
                if (start_side == "left") == target_start_side:
                    pool = left_pool
                else:
                    pool = right_pool
                agent_goals.append(rng_tasks.choice(pool))
            phase_agents.append(tuple(agent_goals))
        goals_by_phase.append(tuple(phase_agents))

    payload = {
        "starts": starts,
        "goals_by_phase": goals_by_phase,
        "task_seed": manifest.task_seed,
    }
    return TaskTape(
        starts=tuple(starts),
        goals_by_phase=tuple(goals_by_phase),
        tape_hash=_canonical_hash(payload),
    )


@dataclass
class SmokeAgent:
    agent_id: int
    position: Position
    goal: Position
    task_index: int = 0
    completed: int = 0
    move_steps: int = 0
    wait_steps: int = 0
    priority: int = 0


@dataclass(frozen=True)
class StepStats:
    moved: int
    waited: int
    directed_edges: tuple[tuple[Position, Position], ...]


def safe_priority_step(
    world: GridMap,
    agents: Sequence[SmokeAgent],
    fields: Mapping[int, Mapping[Position, float]],
    rng: random.Random,
) -> StepStats:
    """Plan one collision-free transactional step with priority inheritance.

    Cyclic rotations are conservatively rejected.  This is slower and weaker
    than reference PIBT/GPIBT, but every returned transition is validated and
    therefore suitable for mechanism smoke tests.
    """

    current = {agent.agent_id: agent.position for agent in agents}
    occupied = {position: agent_id for agent_id, position in current.items()}
    if len(occupied) != len(current):
        raise ValueError("initial smoke state contains duplicate positions")
    assigned: dict[int, Position] = {}
    reserved: dict[Position, int] = {}
    visiting: set[int] = set()
    by_id = {agent.agent_id: agent for agent in agents}

    def candidates(agent_id: int) -> list[Position]:
        agent = by_id[agent_id]
        field = fields[agent_id]
        choices = list(world.neighbors[agent.position]) + [agent.position]
        tie_break = {cell: rng.random() for cell in choices}
        choices.sort(
            key=lambda cell: (
                field.get(cell, INF),
                cell == agent.position,
                tie_break[cell],
            )
        )
        return choices

    def plan(agent_id: int, *, must_vacate: bool = False) -> bool:
        if agent_id in assigned:
            return not must_vacate or assigned[agent_id] != current[agent_id]
        if agent_id in visiting:
            return False
        visiting.add(agent_id)
        origin = current[agent_id]
        for destination in candidates(agent_id):
            if must_vacate and destination == origin:
                continue
            holder = reserved.get(destination)
            if holder is not None and holder != agent_id:
                continue
            occupant = occupied.get(destination)
            if (
                occupant is not None
                and occupant in assigned
                and assigned[occupant] == origin
                and destination != origin
            ):
                continue

            reserved[destination] = agent_id
            success = True
            if occupant is not None and occupant != agent_id:
                success = plan(occupant, must_vacate=True)
            if success:
                assigned[agent_id] = destination
                visiting.remove(agent_id)
                return True
            if reserved.get(destination) == agent_id:
                reserved.pop(destination)
        visiting.remove(agent_id)
        return False

    order = sorted(agents, key=lambda agent: (-agent.priority, agent.agent_id))
    for agent in order:
        if agent.agent_id in assigned:
            continue
        if not plan(agent.agent_id):
            if agent.position in reserved:
                raise RuntimeError("transactional planner could not reserve fallback wait")
            reserved[agent.position] = agent.agent_id
            assigned[agent.agent_id] = agent.position

    assert_valid_joint_transition(current, assigned, free_cells=world.free_cells)
    edges: list[tuple[Position, Position]] = []
    moved = waited = 0
    for agent in agents:
        destination = assigned[agent.agent_id]
        if destination == agent.position:
            agent.wait_steps += 1
            agent.priority += 1
            waited += 1
        else:
            edges.append((agent.position, destination))
            agent.position = destination
            agent.move_steps += 1
            agent.priority = 0
            moved += 1
    return StepStats(moved=moved, waited=waited, directed_edges=tuple(edges))


def _distribution(values: Sequence[Hashable]) -> dict[Hashable, float]:
    counts: dict[Hashable, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    total = sum(counts.values())
    if total == 0:
        return {}
    return {key: count / total for key, count in counts.items()}


def _normalized_entropy(distribution: Mapping[Hashable, float]) -> float:
    if len(distribution) <= 1:
        return 0.0
    entropy = -sum(value * math.log(value) for value in distribution.values() if value > 0)
    return entropy / math.log(len(distribution))


def _js_divergence(
    first: Mapping[Hashable, float], second: Mapping[Hashable, float]
) -> float:
    keys = set(first) | set(second)
    if not keys:
        return 0.0
    midpoint = {key: 0.5 * (first.get(key, 0.0) + second.get(key, 0.0)) for key in keys}

    def kl(source: Mapping[Hashable, float]) -> float:
        value = 0.0
        for key, probability in source.items():
            if probability > 0 and midpoint[key] > 0:
                value += probability * math.log(probability / midpoint[key])
        return value

    return min(1.0, (0.5 * kl(first) + 0.5 * kl(second)) / math.log(2.0))


def _goal_distribution(world: GridMap, agents: Sequence[SmokeAgent]) -> dict[str, float]:
    buckets = []
    for agent in agents:
        side = world.side(agent.goal)
        vertical = "top" if agent.goal[0] <= world.height // 2 else "bottom"
        buckets.append(f"{side}_{vertical}")
    return _distribution(buckets)


def _edge_distribution(
    edges: Mapping[tuple[Position, Position], int]
) -> dict[tuple[Position, Position], float]:
    total = sum(edges.values())
    if total == 0:
        return {}
    return {edge: count / total for edge, count in edges.items()}


@dataclass
class CachedHeatGuidance:
    world: GridMap
    scale: float = 5.0
    version: int = -1
    last_refresh_step: int = 0
    last_refresh_seconds: float = 0.0
    cell_cost: dict[Position, float] = field(default_factory=dict)
    goal_distribution_at_refresh: dict[str, float] = field(default_factory=dict)
    edge_distribution_at_refresh: dict[tuple[Position, Position], float] = field(
        default_factory=dict
    )
    _fields: dict[Position, dict[Position, float]] = field(default_factory=dict)

    def refresh(
        self,
        *,
        step: int,
        route_heat: Mapping[Position, float],
        active_goals: Sequence[Position],
        goal_distribution: Mapping[str, float],
        edge_distribution: Mapping[tuple[Position, Position], float],
    ) -> float:
        started = time.perf_counter_ns()
        maximum = max(route_heat.values(), default=0.0)
        base = {
            cell: (route_heat.get(cell, 0.0) / maximum if maximum > 0 else 0.0)
            for cell in self.world.free_cells
        }
        # Two cheap diffusion passes make the artifact a global traffic
        # guidance graph rather than a raw occupancy lookup.
        smoothed = base
        for _ in range(2):
            next_cost: dict[Position, float] = {}
            for cell in self.world.free_cells:
                neighbors = self.world.neighbors[cell]
                neighbor_mean = (
                    sum(smoothed[neighbor] for neighbor in neighbors) / len(neighbors)
                    if neighbors
                    else 0.0
                )
                next_cost[cell] = 0.65 * base[cell] + 0.35 * neighbor_mean
            smoothed = next_cost
        self.cell_cost = smoothed
        self.goal_distribution_at_refresh = dict(goal_distribution)
        self.edge_distribution_at_refresh = dict(edge_distribution)
        self.version += 1
        self.last_refresh_step = step
        self._fields.clear()
        for goal in set(active_goals):
            self._fields[goal] = self.world.distance_field(
                goal, cell_cost=self.cell_cost, scale=self.scale
            )
        self.last_refresh_seconds = (time.perf_counter_ns() - started) / 1e9
        return self.last_refresh_seconds

    def field(self, goal: Position) -> tuple[dict[Position, float], float]:
        cached = self._fields.get(goal)
        if cached is not None:
            return cached, 0.0
        started = time.perf_counter_ns()
        computed = self.world.distance_field(goal, cell_cost=self.cell_cost, scale=self.scale)
        self._fields[goal] = computed
        return computed, (time.perf_counter_ns() - started) / 1e9


@dataclass
class _WindowCounters:
    start_step: int
    completed: int = 0
    waited: int = 0
    active_agent_steps: int = 0
    path_length: int = 0
    shortest_path_length: int = 0
    planning_seconds: float = 0.0
    refresh_seconds: float = 0.0
    edges: dict[tuple[Position, Position], int] = field(default_factory=dict)


@dataclass
class DecisionRecord:
    run_id: str
    decision_id: int
    sim_step: int
    phase_id: str
    is_shift_step: bool
    guidance_version: int
    guidance_age: int
    selected_action: str
    bootstrap: bool
    active_agents: int
    recent_throughput: float
    recent_wait_rate: float
    goal_js: float
    flow_js: float
    throughput_ewma_drop: float
    refresh_seconds: float
    controller_seconds: float
    ucb_reuse: float | None
    ucb_refresh: float | None
    dual_lambda: float | None
    reward: float | None = None
    completed_delta: int | None = None
    waited_delta: int | None = None
    active_agent_steps: int | None = None
    planning_seconds: float | None = None
    budget_violation: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SmokeRunResult:
    run_id: str
    scenario_id: str
    method: str
    map_id: str
    workload: str
    n_agents: int
    horizon: int
    decision_interval: int
    shift_steps: tuple[int, ...]
    task_tape_hash: str
    layout_seed: int
    start_seed: int
    task_seed: int
    execution_seed: int
    controller_seed: int
    completed: int
    throughput: float
    total_wait: int
    active_agent_steps: int
    wait_rate: float
    path_length: int
    shortest_path_length: int
    refresh_count: int
    bootstrap_refresh_count: int
    refresh_rate: float
    budget_violation: int
    wall_time_seconds: float
    controller_seconds: float
    refresh_seconds: float
    bootstrap_refresh_seconds: float
    route_plan_seconds: float
    collision_count: int
    deadlocked: bool

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["shift_steps"] = list(self.shift_steps)
        return payload


def _context_from_window(
    *,
    world: GridMap,
    agents: Sequence[SmokeAgent],
    step: int,
    window: _WindowCounters,
    guidance: CachedHeatGuidance,
    route_heat: Mapping[Position, float],
    throughput_ewma: float,
    previous_refresh: bool,
) -> TrafficContext:
    duration = max(1, step - window.start_step)
    recent_throughput = window.completed / duration
    wait_ratio = window.waited / max(1, window.active_agent_steps)
    current_goals = _goal_distribution(world, agents)
    recent_edges = _edge_distribution(window.edges)
    edge_loads = list(window.edges.values())
    maximum_to_mean = 0.0
    if edge_loads:
        maximum_to_mean = max(edge_loads) / max(1e-12, sum(edge_loads) / len(edge_loads))
    opposite = 0
    for (source, target), count in window.edges.items():
        opposite += min(count, window.edges.get((target, source), 0))
    total_edges = sum(window.edges.values())
    opposite_ratio = opposite / max(1, total_edges)
    cross_region = sum(
        1 for agent in agents if world.side(agent.position) != world.side(agent.goal)
    ) / max(1, len(agents))
    return TrafficContext(
        active_agent_density=len(agents) / len(world.free_cells),
        recent_throughput=recent_throughput,
        wait_ratio=wait_ratio,
        conflict_rate=wait_ratio,
        maximum_to_mean_edge_load=min(10.0, maximum_to_mean),
        edge_load_entropy=_normalized_entropy(recent_edges),
        opposite_direction_flow=min(1.0, opposite_ratio),
        goal_hotspot_entropy=_normalized_entropy(current_goals),
        cross_region_demand_ratio=cross_region,
        guidance_age=max(0, step - guidance.last_refresh_step),
        goal_distribution_js_divergence_since_refresh=_js_divergence(
            current_goals, guidance.goal_distribution_at_refresh
        ),
        edge_usage_distribution_drift_since_refresh=_js_divergence(
            recent_edges, guidance.edge_distribution_at_refresh
        ),
        throughput_ewma_drop=max(0.0, throughput_ewma - recent_throughput),
        last_refresh_wall_clock_cost=guidance.last_refresh_seconds,
        recent_planning_time=window.planning_seconds / duration,
        previous_refresh=previous_refresh,
    )


def run_smoke_episode(
    *,
    manifest: ScenarioManifest,
    workload: str,
    method: str,
    controller: GuidanceController | None,
    decision_interval: int = 5,
    controller_seed: int = 0,
    guidance_scale: float = 5.0,
) -> tuple[SmokeRunResult, list[DecisionRecord]]:
    if decision_interval <= 0:
        raise ValueError("decision_interval must be positive")
    manifest.validate()
    world = build_smoke_map(manifest.map_id)
    tape = build_task_tape(world, manifest)
    agents = []
    for agent_id, start in enumerate(tape.starts):
        goal = tape.goal_for(0, agent_id, 0)
        if goal == start:
            raise ValueError("task tape produced a zero-distance initial task")
        agents.append(SmokeAgent(agent_id=agent_id, position=start, goal=goal))
    initial = {agent.agent_id: agent.position for agent in agents}
    assert_valid_joint_transition(initial, initial, free_cells=world.free_cells)

    scenario_id = _canonical_hash(
        {
            "manifest": manifest.as_dict(),
            "workload": workload,
            "task_tape_hash": tape.tape_hash,
        }
    )
    run_id = _canonical_hash(
        {
            "scenario_id": scenario_id,
            "method": method,
            "controller_seed": controller_seed,
            "decision_interval": decision_interval,
            "guidance_scale": guidance_scale,
        }
    )
    execution_rng = random.Random(manifest.arrival_seed)
    guidance = CachedHeatGuidance(world=world, scale=guidance_scale)
    route_heat: dict[Position, float] = {}
    bootstrap_seconds = 0.0
    if controller is not None:
        controller.reset(policy_seed=controller_seed)

    window = _WindowCounters(start_step=0)
    previous_context: TrafficContext | None = None
    previous_action: GuidanceAction | None = None
    previous_record: DecisionRecord | None = None
    decision_records: list[DecisionRecord] = []
    throughput_ewma = 0.0
    policy_refresh_count = 0
    policy_refresh_seconds = 0.0
    controller_seconds = 0.0
    route_plan_seconds = 0.0
    total_completed = total_wait = total_moves = total_shortest = 0
    active_agent_steps = 0
    last_completion_step = 0
    started_run = time.perf_counter_ns()
    decision_id = 0

    def finish_previous_window(step: int, next_context: TrafficContext) -> None:
        nonlocal previous_context, previous_action, previous_record
        if previous_context is None or previous_action is None or previous_record is None:
            return
        budget = getattr(controller, "budget_seconds_per_window", None)
        feedback_violation = int(
            budget is not None and window.refresh_seconds > budget
        )
        feedback = WindowFeedback(
            start_step=window.start_step,
            end_step=step,
            completed_tasks=window.completed,
            agent_timesteps=window.active_agent_steps,
            wait_agent_timesteps=window.waited,
            path_length=window.path_length,
            shortest_path_length=window.shortest_path_length,
            planning_seconds=window.planning_seconds,
            refresh_seconds=window.refresh_seconds,
            budget_violations=feedback_violation,
        )
        controller.observe(previous_context, previous_action, feedback, next_context)
        previous_record.reward = feedback.throughput
        previous_record.completed_delta = feedback.completed_tasks
        previous_record.waited_delta = feedback.wait_agent_timesteps
        previous_record.active_agent_steps = feedback.agent_timesteps
        previous_record.planning_seconds = feedback.planning_seconds
        previous_record.budget_violation = feedback_violation

    for step in range(manifest.horizon_steps):
        if controller is not None and step % decision_interval == 0:
            edge_snapshot = _edge_distribution(window.edges)
            context = _context_from_window(
                world=world,
                agents=agents,
                step=step,
                window=window,
                guidance=guidance,
                route_heat=route_heat,
                throughput_ewma=throughput_ewma,
                previous_refresh=bool(previous_action and previous_action.refresh),
            )
            if step > 0:
                finish_previous_window(step, context)
                recent = window.completed / max(1, step - window.start_step)
                throughput_ewma = 0.8 * throughput_ewma + 0.2 * recent
                window = _WindowCounters(start_step=step)

            selected_started = time.perf_counter_ns()
            selected_action = controller.select(context, step=step)
            selected_seconds = (time.perf_counter_ns() - selected_started) / 1e9
            controller_seconds += selected_seconds
            refresh_seconds = 0.0
            bootstrap = guidance.version < 0
            effective_refresh = selected_action.refresh or bootstrap
            action = GuidanceAction(
                refresh=effective_refresh,
                generator_id=selected_action.generator_id,
            )
            if effective_refresh:
                refresh_seconds = guidance.refresh(
                    step=step,
                    route_heat=route_heat,
                    active_goals=[agent.goal for agent in agents],
                    goal_distribution=_goal_distribution(world, agents),
                    edge_distribution=edge_snapshot,
                )
                policy_refresh_count += 1
                policy_refresh_seconds += refresh_seconds
                window.refresh_seconds += refresh_seconds
                if bootstrap:
                    bootstrap_seconds = refresh_seconds
            phase_index = _phase_index(manifest.phases, step)
            phase = manifest.phases[phase_index]
            scores = getattr(controller, "last_scores", {})
            record = DecisionRecord(
                run_id=run_id,
                decision_id=decision_id,
                sim_step=step,
                phase_id=phase.phase_id,
                is_shift_step=any(
                    max(0, step - decision_interval) < item.start_step <= step
                    for item in manifest.phases[1:]
                ),
                guidance_version=guidance.version,
                guidance_age=max(0, step - guidance.last_refresh_step),
                selected_action="refresh" if action.refresh else "reuse",
                bootstrap=bootstrap,
                active_agents=len(agents),
                recent_throughput=context.recent_throughput,
                recent_wait_rate=context.wait_ratio,
                goal_js=context.goal_distribution_js_divergence_since_refresh,
                flow_js=context.edge_usage_distribution_drift_since_refresh,
                throughput_ewma_drop=context.throughput_ewma_drop,
                refresh_seconds=refresh_seconds,
                controller_seconds=selected_seconds,
                ucb_reuse=scores.get("reuse"),
                ucb_refresh=scores.get("refresh"),
                dual_lambda=getattr(controller, "dual_lambda", None),
            )
            decision_records.append(record)
            previous_context = context
            previous_action = action
            previous_record = record
            decision_id += 1

        phase_index = _phase_index(manifest.phases, step)
        fields: dict[int, Mapping[Position, float]] = {}
        planning_started = time.perf_counter_ns()
        for agent in agents:
            if controller is None:
                fields[agent.agent_id] = world.distance_field(agent.goal)
            else:
                field_value, field_seconds = guidance.field(agent.goal)
                fields[agent.agent_id] = field_value
                del field_seconds
        # Executor ordering/tie-breaking is included in planning time but kept
        # separate from refresh cost.
        step_stats = safe_priority_step(world, agents, fields, execution_rng)
        executor_seconds = (time.perf_counter_ns() - planning_started) / 1e9
        window.planning_seconds += max(0.0, executor_seconds)
        route_plan_seconds += max(0.0, executor_seconds)

        for cell in list(route_heat):
            route_heat[cell] *= 0.82
            if route_heat[cell] < 0.01:
                del route_heat[cell]
        for agent in agents:
            route_heat[agent.position] = route_heat.get(agent.position, 0.0) + 1.0
        for edge in step_stats.directed_edges:
            window.edges[edge] = window.edges.get(edge, 0) + 1

        window.waited += step_stats.waited
        window.active_agent_steps += len(agents)
        window.path_length += step_stats.moved
        total_wait += step_stats.waited
        total_moves += step_stats.moved
        active_agent_steps += len(agents)

        for agent in agents:
            if agent.position != agent.goal:
                continue
            agent.completed += 1
            total_completed += 1
            window.completed += 1
            last_completion_step = step
            agent.task_index += 1
            next_goal = tape.goal_for(phase_index, agent.agent_id, agent.task_index)
            if next_goal == agent.position:
                raise ValueError(
                    f"task tape produced zero-distance task for agent {agent.agent_id}"
                )
            shortest = world.shortest_distance(agent.position, next_goal)
            if shortest >= INF:
                raise ValueError("task tape produced an unreachable task")
            total_shortest += shortest
            window.shortest_path_length += shortest
            agent.goal = next_goal

    if controller is not None and previous_context is not None:
        final_context = _context_from_window(
            world=world,
            agents=agents,
            step=manifest.horizon_steps,
            window=window,
            guidance=guidance,
            route_heat=route_heat,
            throughput_ewma=throughput_ewma,
            previous_refresh=bool(previous_action and previous_action.refresh),
        )
        finish_previous_window(manifest.horizon_steps, final_context)

    wall_seconds = (time.perf_counter_ns() - started_run) / 1e9
    decisions = max(1, len(decision_records))
    budget = getattr(controller, "budget_seconds_per_window", None)
    budget_violation = int(
        budget is not None
        and policy_refresh_seconds > budget * decisions * 1.05
    )
    deadlocked = manifest.horizon_steps - last_completion_step > max(50, world.width * 4)
    result = SmokeRunResult(
        run_id=run_id,
        scenario_id=scenario_id,
        method=method,
        map_id=manifest.map_id,
        workload=workload,
        n_agents=len(agents),
        horizon=manifest.horizon_steps,
        decision_interval=decision_interval,
        shift_steps=tuple(phase.start_step for phase in manifest.phases[1:]),
        task_tape_hash=tape.tape_hash,
        layout_seed=manifest.layout_seed,
        start_seed=manifest.start_seed,
        task_seed=manifest.task_seed,
        execution_seed=manifest.arrival_seed,
        controller_seed=controller_seed,
        completed=total_completed,
        throughput=total_completed / manifest.horizon_steps,
        total_wait=total_wait,
        active_agent_steps=active_agent_steps,
        wait_rate=total_wait / max(1, active_agent_steps),
        path_length=total_moves,
        shortest_path_length=total_shortest,
        refresh_count=policy_refresh_count,
        bootstrap_refresh_count=1 if controller is not None else 0,
        refresh_rate=policy_refresh_count / decisions if controller is not None else 0.0,
        budget_violation=budget_violation,
        wall_time_seconds=wall_seconds,
        controller_seconds=controller_seconds,
        refresh_seconds=policy_refresh_seconds,
        bootstrap_refresh_seconds=bootstrap_seconds,
        route_plan_seconds=route_plan_seconds,
        collision_count=0,
        deadlocked=deadlocked,
    )
    return result, decision_records


__all__ = [
    "CachedHeatGuidance",
    "DecisionRecord",
    "GridMap",
    "SmokeRunResult",
    "TaskTape",
    "build_smoke_manifest",
    "build_smoke_map",
    "build_task_tape",
    "build_workload_phases",
    "run_smoke_episode",
    "safe_priority_step",
]
