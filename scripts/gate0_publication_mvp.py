"""Mechanism-feasibility MVP for event-triggered guidance publication.

This runner uses the official compiled GPIBT simulator. It supports both the
mechanism-only heuristic generators and a hash-locked, frozen copy of the
official period-online 3,084-parameter CNN. Its sole question is whether a
dynamic workload contains publication-schedule headroom worth pursuing.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import platform
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _probabilities(values: Any) -> Any:
    import numpy as np

    array = np.asarray(values, dtype=np.float64).reshape(-1)
    array = np.maximum(array, 0.0)
    total = float(array.sum())
    if total <= 0.0:
        return np.full(array.shape, 1.0 / array.size, dtype=np.float64)
    return array / total


def _js_divergence(left: Any, right: Any) -> float:
    import numpy as np

    p = _probabilities(left)
    q = _probabilities(right)
    midpoint = 0.5 * (p + q)

    def kl(first: Any, second: Any) -> float:
        mask = first > 0
        return float(np.sum(first[mask] * np.log(first[mask] / second[mask])))

    return 0.5 * kl(p, midpoint) + 0.5 * kl(q, midpoint)


class TrafficGoalHeuristicGenerator:
    """Frozen R,D,L,U edge-cost generator for a mechanism-only MVP."""

    def __init__(
        self,
        *,
        graph: Any,
        traffic_alpha: float,
        wait_alpha: float,
        goal_alpha: float,
    ) -> None:
        import numpy as np

        self.graph = np.asarray(graph, dtype=np.float64)
        self.height, self.width = self.graph.shape
        self.traffic_alpha = float(traffic_alpha)
        self.wait_alpha = float(wait_alpha)
        self.goal_alpha = float(goal_alpha)
        self.calls = 0

    def __call__(self, observation: Any) -> Any:
        import numpy as np

        obs = np.asarray(observation, dtype=np.float64)
        if obs.shape != (6, self.height, self.width):
            raise ValueError(
                "MVP expects traffic(5)+task(1) observation channels, got "
                f"{obs.shape!r}"
            )
        # Official traffic observations are R,U,L,D.  The compiled weight
        # consumer is R,D,L,U, so convert explicitly here.
        traffic_rdlu = obs[[0, 3, 2, 1], :, :]
        wait = obs[4]
        task = _probabilities(obs[5]).reshape(self.height, self.width)

        traffic_scale = max(float(traffic_rdlu.max()), 1e-12)
        wait_scale = max(float(wait.max()), 1e-12)
        traffic = traffic_rdlu / traffic_scale
        wait_penalty = wait / wait_scale

        rows = np.arange(self.height, dtype=np.float64)
        cols = np.arange(self.width, dtype=np.float64)
        row_mass = task.sum(axis=1)
        col_mass = task.sum(axis=0)
        row_potential = np.abs(rows[:, None] - rows[None, :]) @ row_mass
        col_potential = np.abs(cols[:, None] - cols[None, :]) @ col_mass
        potential = row_potential[:, None] + col_potential[None, :]
        potential_scale = max(float(potential.max()), 1e-12)
        potential = potential / potential_scale

        action = np.ones(
            (4, self.height, self.width), dtype=np.float64
        )
        action += self.traffic_alpha * traffic
        action += self.wait_alpha * wait_penalty[None, :, :]

        # Edge potential difference: moving toward the current goal mass has
        # a lower cost.  Boundary values are neutral and invalid edges are
        # ignored by the simulator's map mask.
        deltas = np.zeros_like(action)
        deltas[0, :, :-1] = potential[:, 1:] - potential[:, :-1]  # R
        deltas[1, :-1, :] = potential[1:, :] - potential[:-1, :]  # D
        deltas[2, :, 1:] = potential[:, :-1] - potential[:, 1:]  # L
        deltas[3, 1:, :] = potential[:-1, :] - potential[1:, :]  # U
        action += self.goal_alpha * deltas
        action = np.clip(action, 0.05, None)
        self.calls += 1
        return action


class RouteFlowGuidanceGenerator:
    """Aggregate obstacle-aware current routes into a mild directed flow map."""

    def __init__(self, *, graph: Any, flow_bias: float) -> None:
        import numpy as np

        if not (0.0 < flow_bias < 1.0):
            raise ValueError("flow_bias must be in (0, 1)")
        self.graph = np.asarray(graph, dtype=np.int8)
        self.height, self.width = self.graph.shape
        self.flow_bias = float(flow_bias)
        self.calls = 0
        self.state_provider: Optional[Callable[[], dict[str, Any]]] = None
        self._directions = ((0, 1), (1, 0), (0, -1), (-1, 0))
        self._opposite = (2, 3, 0, 1)

    def _distance_map(self, goal: tuple[int, int]) -> Any:
        import numpy as np

        distances = np.full(
            (self.height, self.width), -1, dtype=np.int32
        )
        goal_row, goal_col = goal
        if self.graph[goal_row, goal_col] != 0:
            raise ValueError("route-flow goal lies on an obstacle")
        distances[goal_row, goal_col] = 0
        queue = deque([(goal_row, goal_col)])
        while queue:
            row, col = queue.popleft()
            next_distance = int(distances[row, col]) + 1
            for delta_row, delta_col in self._directions:
                next_row = row + delta_row
                next_col = col + delta_col
                if (
                    0 <= next_row < self.height
                    and 0 <= next_col < self.width
                    and self.graph[next_row, next_col] == 0
                    and distances[next_row, next_col] < 0
                ):
                    distances[next_row, next_col] = next_distance
                    queue.append((next_row, next_col))
        return distances

    def __call__(self, observation: Any) -> Any:
        del observation
        import numpy as np

        if self.state_provider is None:
            raise RuntimeError("route-flow generator has no state provider")
        trace = self.state_provider()
        positions = trace["curr_pos"]
        goals = trace["curr_tasks"]
        active_tasks = trace.get(
            "curr_task_active", [True] * len(positions)
        )
        if not (len(positions) == len(goals) == len(active_tasks)):
            raise ValueError("route-flow position/task/active lengths differ")

        distance_cache = {}
        directed_flow = np.zeros(
            (4, self.height, self.width), dtype=np.float64
        )
        for agent_id, (position, goal_value, task_active) in enumerate(
            zip(positions, goals, active_tasks)
        ):
            if not bool(task_active):
                continue
            goal = (int(goal_value[0]), int(goal_value[1]))
            if goal not in distance_cache:
                distance_cache[goal] = self._distance_map(goal)
            distances = distance_cache[goal]
            row, col = int(position[0]), int(position[1])
            steps = 0
            while (row, col) != goal:
                current_distance = int(distances[row, col])
                if current_distance <= 0:
                    raise RuntimeError("route-flow goal is unreachable")
                candidates = []
                for direction, (delta_row, delta_col) in enumerate(
                    self._directions
                ):
                    next_row = row + delta_row
                    next_col = col + delta_col
                    if (
                        0 <= next_row < self.height
                        and 0 <= next_col < self.width
                        and distances[next_row, next_col]
                        == current_distance - 1
                    ):
                        candidates.append((
                            directed_flow[direction, row, col],
                            (next_row * self.width + next_col + agent_id)
                            % (self.height * self.width),
                            direction,
                            next_row,
                            next_col,
                        ))
                if not candidates:
                    raise RuntimeError("route-flow shortest-path trace failed")
                _, _, direction, next_row, next_col = min(candidates)
                directed_flow[direction, row, col] += 1.0
                row, col = next_row, next_col
                steps += 1
                if steps > self.height * self.width:
                    raise RuntimeError("route-flow path exceeded map size")

        net_flow = np.zeros_like(directed_flow)
        for row in range(self.height):
            for col in range(self.width):
                if self.graph[row, col] != 0:
                    continue
                for direction, (delta_row, delta_col) in enumerate(
                    self._directions
                ):
                    next_row = row + delta_row
                    next_col = col + delta_col
                    if (
                        0 <= next_row < self.height
                        and 0 <= next_col < self.width
                        and self.graph[next_row, next_col] == 0
                    ):
                        reverse = self._opposite[direction]
                        net_flow[direction, row, col] = (
                            directed_flow[direction, row, col]
                            - directed_flow[reverse, next_row, next_col]
                        )
        nonzero = np.abs(net_flow[np.nonzero(net_flow)])
        scale = (
            float(np.percentile(nonzero, 90.0))
            if nonzero.size
            else 1.0
        )
        signed_flow = np.clip(net_flow / max(scale, 1.0), -1.0, 1.0)
        action = 1.0 - self.flow_bias * signed_flow
        self.calls += 1
        return action


class NextRouteFlowGuidanceGenerator(RouteFlowGuidanceGenerator):
    """Predict the guide paths that can be built after the next task change."""

    def __init__(
        self,
        *,
        graph: Any,
        home_locs: Any,
        endpoint_locs: Any,
        flow_bias: float,
        decision_window: int,
    ) -> None:
        import numpy as np

        super().__init__(graph=graph, flow_bias=flow_bias)
        self.home_locs = [tuple(map(int, loc)) for loc in home_locs]
        self.endpoint_locs = [tuple(map(int, loc)) for loc in endpoint_locs]
        if not self.home_locs or not self.endpoint_locs:
            raise ValueError("next-route generator needs W and E map locations")
        self.home_set = set(self.home_locs)
        self.endpoint_set = set(self.endpoint_locs)
        self.home_weights = np.ones(len(self.home_locs), dtype=np.float64)
        self.endpoint_weights = np.ones(
            len(self.endpoint_locs), dtype=np.float64
        )
        self.last_distribution_timestep: Optional[int] = None
        self.last_distribution_change_js = 0.0
        self.decision_window = int(decision_window)
        if self.decision_window <= 0:
            raise ValueError("decision_window must be positive")

    def observe_trace(self, trace: dict[str, Any]) -> None:
        """Consume exogenous workload updates even when we do not publish.

        Publication policies intentionally call the generator at different
        times.  Updating the cached workload only inside ``__call__`` would
        therefore make delayed policies build guidance from stale task
        distributions, confounding state observation with publication timing.
        """
        import numpy as np

        for update in trace["recent_distribution_updates"]:
            if update["source"] != "kiva":
                continue
            timestep = int(update["timestep"])
            if (
                self.last_distribution_timestep is not None
                and timestep <= self.last_distribution_timestep
            ):
                continue
            primary = np.asarray(update["primary_weights"], dtype=np.float64)
            secondary = np.asarray(
                update["secondary_weights"], dtype=np.float64
            )
            if primary.size != len(self.home_locs):
                raise ValueError(
                    "Kiva primary weight count does not match W cells"
                )
            if secondary.size != len(self.endpoint_locs):
                raise ValueError(
                    "Kiva secondary weight count does not match E cells"
                )
            self.last_distribution_change_js = _js_divergence(
                secondary, self.endpoint_weights
            )
            self.home_weights = primary
            self.endpoint_weights = secondary
            self.last_distribution_timestep = timestep

    @staticmethod
    def _weighted_location(
        locations: list[tuple[int, int]], weights: Any, agent_id: int
    ) -> tuple[int, int]:
        import numpy as np

        normalized = _probabilities(weights)
        # A fixed low-discrepancy per-agent quantile approximates the expected
        # OD mixture without consuming policy-dependent RNG state.
        value = ((agent_id + 1) * 2654435761) & 0xFFFFFFFF
        quantile = (value + 0.5) / float(1 << 32)
        index = int(np.searchsorted(np.cumsum(normalized), quantile, side="right"))
        return locations[min(index, len(locations) - 1)]

    def _add_shortest_route(
        self,
        directed_flow: Any,
        distance_cache: dict[tuple[int, int], Any],
        *,
        origin: tuple[int, int],
        destination: tuple[int, int],
        weight: float,
        agent_id: int,
    ) -> None:
        if weight <= 0.0 or origin == destination:
            return
        if destination not in distance_cache:
            distance_cache[destination] = self._distance_map(destination)
        distances = distance_cache[destination]
        row, col = origin
        steps = 0
        while (row, col) != destination:
            current_distance = int(distances[row, col])
            if current_distance <= 0:
                raise RuntimeError("next-route OD pair is unreachable")
            candidates = []
            for direction, (delta_row, delta_col) in enumerate(
                self._directions
            ):
                next_row = row + delta_row
                next_col = col + delta_col
                if (
                    0 <= next_row < self.height
                    and 0 <= next_col < self.width
                    and distances[next_row, next_col] == current_distance - 1
                ):
                    candidates.append((
                        directed_flow[direction, row, col],
                        (next_row * self.width + next_col + agent_id)
                        % (self.height * self.width),
                        direction,
                        next_row,
                        next_col,
                    ))
            if not candidates:
                raise RuntimeError("next-route shortest-path trace failed")
            _, _, direction, next_row, next_col = min(candidates)
            directed_flow[direction, row, col] += weight
            row, col = next_row, next_col
            steps += 1
            if steps > self.height * self.width:
                raise RuntimeError("next-route path exceeded map size")

    def _generate_action_from_trace(self, trace: dict[str, Any]) -> Any:
        import numpy as np

        pending_agents = {
            int(event["agent_id"])
            for event in trace["recent_events"]
            if event["event_type"] == "assigned"
            and event["timestep"] == trace["window_end_timestep"]
        }
        directed_flow = np.zeros(
            (4, self.height, self.width), dtype=np.float64
        )
        distance_cache: dict[tuple[int, int], Any] = {}
        positions = trace["curr_pos"]
        goals = trace["curr_tasks"]
        active_tasks = trace.get(
            "curr_task_active", [True] * len(positions)
        )
        if not (len(positions) == len(goals) == len(active_tasks)):
            raise ValueError("next-route position/task/active lengths differ")
        for agent_id, (position_value, goal_value, task_active) in enumerate(
            zip(positions, goals, active_tasks)
        ):
            if not bool(task_active):
                continue
            position = tuple(map(int, position_value))
            current_goal = tuple(map(int, goal_value))
            if agent_id in pending_agents:
                self._add_shortest_route(
                    directed_flow,
                    distance_cache,
                    origin=position,
                    destination=current_goal,
                    weight=1.0,
                    agent_id=agent_id,
                )
                continue

            if current_goal not in distance_cache:
                distance_cache[current_goal] = self._distance_map(current_goal)
            eta_distance = int(distance_cache[current_goal][position])
            eta_weight = math.exp(
                -max(0, eta_distance) / float(self.decision_window)
            )
            if current_goal in self.home_set:
                next_goal = self._weighted_location(
                    self.endpoint_locs, self.endpoint_weights, agent_id
                )
            elif current_goal in self.endpoint_set:
                next_goal = self._weighted_location(
                    self.home_locs, self.home_weights, agent_id
                )
            else:
                # Defensive fallback for non-Kiva tasks.
                next_goal = current_goal
            self._add_shortest_route(
                directed_flow,
                distance_cache,
                origin=current_goal,
                destination=next_goal,
                weight=eta_weight,
                agent_id=agent_id,
            )

        net_flow = np.zeros_like(directed_flow)
        for row in range(self.height):
            for col in range(self.width):
                if self.graph[row, col] != 0:
                    continue
                for direction, (delta_row, delta_col) in enumerate(
                    self._directions
                ):
                    next_row = row + delta_row
                    next_col = col + delta_col
                    if (
                        0 <= next_row < self.height
                        and 0 <= next_col < self.width
                        and self.graph[next_row, next_col] == 0
                    ):
                        reverse = self._opposite[direction]
                        net_flow[direction, row, col] = (
                            directed_flow[direction, row, col]
                            - directed_flow[reverse, next_row, next_col]
                        )
        nonzero = np.abs(net_flow[np.nonzero(net_flow)])
        scale = float(np.percentile(nonzero, 90.0)) if nonzero.size else 1.0
        action = 1.0 - self.flow_bias * np.clip(
            net_flow / max(scale, 1e-12), -1.0, 1.0
        )
        return action

    def preview(self, observation: Any) -> Any:
        """Return the candidate graph without changing generator state/calls."""

        del observation
        if self.state_provider is None:
            raise RuntimeError("next-route generator has no state provider")
        trace = self.state_provider()
        return self._generate_action_from_trace(trace)

    def __call__(self, observation: Any) -> Any:
        del observation
        if self.state_provider is None:
            raise RuntimeError("next-route generator has no state provider")
        trace = self.state_provider()
        self.observe_trace(trace)
        action = self._generate_action_from_trace(trace)
        self.calls += 1
        return action


def _normalized_entropy(values: Any) -> float:
    import numpy as np

    probabilities = _probabilities(values)
    positive = probabilities[probabilities > 0.0]
    if probabilities.size <= 1:
        return 0.0
    entropy = -float(np.sum(positive * np.log(positive)))
    return entropy / math.log(probabilities.size)


def _wait_ratio_from_paths(paths: Any) -> float:
    wait_count = 0
    move_count = 0
    for path in paths:
        for move in path:
            if move == ",":
                continue
            move_count += 1
            wait_count += int(move == "W")
    return wait_count / move_count if move_count else 0.0


def _valid_edge_mask(graph: Any) -> Any:
    import numpy as np

    graph_array = np.asarray(graph)
    height, width = graph_array.shape
    free = graph_array == 0
    mask = np.zeros((4, height, width), dtype=bool)
    mask[0, :, :-1] = free[:, :-1] & free[:, 1:]
    mask[1, :-1, :] = free[:-1, :] & free[1:, :]
    mask[2, :, 1:] = free[:, 1:] & free[:, :-1]
    mask[3, 1:, :] = free[1:, :] & free[:-1, :]
    return mask


def _candidate_guidance_drift(
    current_action: Any, candidate_action: Any, graph: Any
) -> dict[str, float]:
    import numpy as np

    current = np.asarray(current_action, dtype=np.float64)
    candidate = np.asarray(candidate_action, dtype=np.float64)
    if current.shape != candidate.shape or current.shape[0] != 4:
        raise ValueError("candidate/current guidance shapes differ")
    valid = _valid_edge_mask(graph)
    current_values = current[valid]
    candidate_values = candidate[valid]
    difference = candidate_values - current_values
    mean_scale = max(float(np.mean(np.abs(current_values))), 1e-12)
    max_scale = max(float(np.max(np.abs(current_values))), 1e-12)
    denominator = max(
        float(np.linalg.norm(current_values))
        * float(np.linalg.norm(candidate_values)),
        1e-12,
    )
    cosine = float(current_values @ candidate_values) / denominator
    return {
        "candidate_l1_relative": float(np.mean(np.abs(difference)))
        / mean_scale,
        "candidate_rms_relative": math.sqrt(float(np.mean(difference ** 2)))
        / mean_scale,
        "candidate_max_relative": float(np.max(np.abs(difference)))
        / max_scale,
        "candidate_changed_fraction": float(
            np.mean(np.abs(difference) > 1e-12)
        ),
        "candidate_cosine_distance": max(0.0, min(2.0, 1.0 - cosine)),
    }


def _raw_guidance_hash(action: Any) -> str:
    import numpy as np

    values = np.asarray(action, dtype=np.float64).reshape(-1).tolist()
    payload = json.dumps(
        values, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _causal_feature_snapshot(
    *,
    observation: Any,
    previous_trace: dict[str, Any],
    generator: NextRouteFlowGuidanceGenerator,
    current_action: Any,
    candidate_action: Any,
    current_guidance_sha256: str,
    current_timestep: int,
    warmup_time: int,
    horizon: int,
    decision_window: int,
    last_refresh_timestep: int,
    task_js_since_refresh: float,
    recent_rewards: list[float],
    num_agents: int,
    shift_index: int,
) -> tuple[dict[str, Any], str, str]:
    """Build a deterministic pre-action feature/state snapshot."""

    import numpy as np

    obs = np.asarray(observation, dtype=np.float64)
    if obs.shape != (6, generator.height, generator.width):
        raise ValueError("causal feature extractor expects six observation channels")
    task = _probabilities(obs[5])
    traffic = np.maximum(obs[:4], 0.0)
    traffic_probability = _probabilities(traffic)
    traffic_total = max(float(traffic.sum()), 1e-12)
    opposite_mass = float(
        np.minimum(traffic[0, :, :-1], traffic[2, :, 1:]).sum()
        + np.minimum(traffic[3, :-1, :], traffic[1, 1:, :]).sum()
    )
    rows = np.arange(generator.height, dtype=np.float64)
    cols = np.arange(generator.width, dtype=np.float64)
    task_matrix = task.reshape(generator.height, generator.width)
    recent_reward = float(recent_rewards[-1]) if recent_rewards else 0.0
    recent_mean = (
        float(np.mean(recent_rewards[-3:])) if recent_rewards else 0.0
    )
    earlier_mean = (
        float(np.mean(recent_rewards[-4:-1]))
        if len(recent_rewards) >= 2
        else recent_mean
    )
    endpoint_probability = _probabilities(generator.endpoint_weights)
    drift = _candidate_guidance_drift(
        current_action, candidate_action, generator.graph
    )
    features = {
        "guidance_age_windows": (current_timestep - last_refresh_timestep)
        / float(decision_window),
        "task_js_since_refresh": float(task_js_since_refresh),
        "task_entropy": _normalized_entropy(task),
        "task_hotspot": float(task.max()),
        "task_centroid_row": float(
            task_matrix.sum(axis=1) @ rows
        ) / max(generator.height - 1, 1),
        "task_centroid_col": float(
            task_matrix.sum(axis=0) @ cols
        ) / max(generator.width - 1, 1),
        "traffic_entropy": _normalized_entropy(traffic_probability),
        "traffic_hotspot": float(traffic_probability.max()),
        "opposite_flow_ratio": opposite_mass / traffic_total,
        "recent_completed_per_agent": recent_reward / num_agents,
        "recent_completed_mean3_per_agent": recent_mean / num_agents,
        "recent_throughput_drop_per_agent": (
            earlier_mean - recent_reward
        ) / num_agents,
        "recent_route_builds_per_agent": len(
            previous_trace["recent_route_builds"]
        ) / num_agents,
        "recent_wait_ratio": _wait_ratio_from_paths(
            previous_trace["actual_paths"]
        ),
        **drift,
    }
    candidate_guidance_sha256 = _raw_guidance_hash(candidate_action)
    snapshot = {
        "schema": "dai.gate0.predecision-features/v1",
        "decision_timestep": int(current_timestep),
        "shift_index": int(shift_index),
        "current_guidance_sha256": current_guidance_sha256,
        "candidate_guidance_sha256": candidate_guidance_sha256,
        "features": features,
        # Pairing-only oracle context.  These fields must never enter the
        # frozen trigger feature list; the current heuristic generator itself
        # remains a diagnostic upper-bound component because it consumes the
        # simulator's true distribution weights.
        "audit_context": {
            "episode_progress": (current_timestep - warmup_time)
            / max(float(horizon), 1.0),
            "distribution_js": float(generator.last_distribution_change_js),
            "distribution_entropy": _normalized_entropy(
                endpoint_probability
            ),
            "distribution_hotspot": float(endpoint_probability.max()),
            "generator_distribution_timestep": (
                generator.last_distribution_timestep
            ),
        },
    }
    feature_fingerprint = _canonical_hash(snapshot)
    state_fingerprint = _canonical_hash({
        "decision_timestep": int(current_timestep),
        "guidance_version": previous_trace["guidance_version"],
        "guidance_sha256": previous_trace["guidance_sha256"],
        "applied_guidance_sha256": previous_trace[
            "applied_guidance_sha256"
        ],
        "map_weights_revision": previous_trace["map_weights_revision"],
        "num_task_finished": previous_trace["num_task_finished"],
        "curr_pos": previous_trace["curr_pos"],
        "curr_tasks": previous_trace["curr_tasks"],
        "curr_task_active": previous_trace.get(
            "curr_task_active",
            [True] * len(previous_trace["curr_pos"]),
        ),
        "actual_paths": previous_trace["actual_paths"],
        "recent_events": previous_trace["recent_events"],
        "recent_route_builds": previous_trace["recent_route_builds"],
        "recent_distribution_updates": previous_trace[
            "recent_distribution_updates"
        ],
        "feature_fingerprint": feature_fingerprint,
    })
    return snapshot, feature_fingerprint, state_fingerprint


def _method_refresh(
    method: str,
    *,
    decision_index: int,
    current_timestep: int,
    warmup_time: int,
    shift_interval: int,
    decision_window: int,
    task_js: float,
    event_threshold: float,
    last_refresh_timestep: int,
    event_minimum_gap: int,
    cohort_ready: bool,
    observed_shift: bool,
    observed_shift_index: Optional[int],
    bootstrap_timestep: int,
) -> bool:
    if method == "uniform":
        # ``OnlineGGOAdapter.reset`` installs an all-ones action. Never
        # publishing therefore gives a true no-learned-guidance baseline.
        return False
    if decision_index == 0:
        return True
    if method == "never":
        return False
    if method == "always":
        return True
    if method.startswith("period_"):
        period = int(method.split("_", 1)[1])
        if period <= 0:
            raise ValueError("publication period must be positive")
        # Anchor the fixed schedule to the first decision instead of starting
        # a fresh timer after each rounded publication.  This makes a nominal
        # period 50 on a 20-step decision grid alternate 60/40 rather than
        # silently becoming period 60 forever.
        current_bucket = (
            current_timestep - bootstrap_timestep
        ) // period
        previous_bucket = (
            last_refresh_timestep - bootstrap_timestep
        ) // period
        return current_bucket > previous_bucket
    if method == "oracle_shift":
        del shift_interval
        return observed_shift
    if method.startswith("shiftmask_"):
        mask = method.split("_", 1)[1]
        if not mask or any(value not in "01" for value in mask):
            raise ValueError(
                "shiftmask method must end in a non-empty binary mask"
            )
        if not observed_shift:
            return False
        if observed_shift_index is None:
            raise RuntimeError("observed shift has no shift index")
        return (
            observed_shift_index < len(mask)
            and mask[observed_shift_index] == "1"
        )
    if method == "task_js_event":
        return (
            current_timestep - last_refresh_timestep >= event_minimum_gap
            and task_js >= event_threshold
        )
    if method == "cohort_event":
        return cohort_ready
    raise ValueError(f"unknown method {method!r}")


def _run_condition(
    *,
    method: str,
    seed: int,
    config_factory: Callable[[], Any],
    env_class: Any,
    adapter_class: Any,
    generator_mode: str,
    generator_kwargs: dict[str, Any],
    decision_window: int,
    warmup_time: int,
    shift_interval: int,
    event_threshold: float,
    event_minimum_gap: int,
    cohort_delay: int,
    cohort_min_route_builds: int,
    horizon: int,
    trigger_model: Any = None,
) -> dict[str, Any]:
    import numpy as np

    env = env_class(config=config_factory(), seed=seed)
    if trigger_model is not None:
        trigger_model.validate_evaluation_seed(seed)
    if generator_mode == "potential":
        generator = TrafficGoalHeuristicGenerator(
            graph=env.comp_map.graph,
            **generator_kwargs,
        )
    elif generator_mode == "route_flow":
        generator = RouteFlowGuidanceGenerator(
            graph=env.comp_map.graph,
            flow_bias=generator_kwargs["flow_bias"],
        )
    elif generator_mode == "next_route_flow":
        generator = NextRouteFlowGuidanceGenerator(
            graph=env.comp_map.graph,
            home_locs=env.comp_map.home_loc_ids,
            endpoint_locs=env.comp_map.end_points_ids,
            flow_bias=generator_kwargs["flow_bias"],
            decision_window=decision_window,
        )
    elif generator_mode == "frozen_cnn":
        from dai_lmapf.frozen_cnn_generator import (
            FrozenCNNGuidanceGenerator,
        )

        generator = FrozenCNNGuidanceGenerator.from_path(
            generator_kwargs["checkpoint_path"],
            expected_file_sha256=generator_kwargs.get(
                "expected_file_sha256"
            ),
            expected_params_sha256=generator_kwargs.get(
                "expected_params_sha256"
            ),
        )
    else:
        raise ValueError(f"unknown generator mode {generator_mode!r}")
    adapter = adapter_class(
        env,
        generator,
        height=env.comp_map.height,
        width=env.comp_map.width,
    )
    if isinstance(generator, RouteFlowGuidanceGenerator):
        generator.state_provider = lambda: dict(adapter.info["dai_trace"])
    observation, reset_info = adapter.reset(seed=seed)
    reset_trace = dict(reset_info["dai_trace"])
    reference_task = _probabilities(observation[-1])
    current_timestep = int(
        reset_info["dai_trace"]["window_end_timestep"]
    )
    last_refresh_timestep = current_timestep
    bootstrap_timestep = current_timestep
    pending_shift_timestep = None
    pending_route_builds = 0
    observed_shift_count = 0
    distribution_update_tape = list(
        reset_trace["recent_distribution_updates"]
    )
    windows = []
    recent_rewards: list[float] = []
    started = time.perf_counter()

    while not adapter.done:
        previous_trace = adapter.info["dai_trace"]
        if isinstance(generator, NextRouteFlowGuidanceGenerator):
            generator.observe_trace(previous_trace)
        distribution_updates = previous_trace["recent_distribution_updates"]
        observed_shift_index = None
        if distribution_updates:
            observed_shift_index = (
                observed_shift_count + len(distribution_updates) - 1
            )
            observed_shift_count += len(distribution_updates)
            pending_shift_timestep = max(
                int(update["timestep"]) for update in distribution_updates
            )
            pending_route_builds = 0
        if pending_shift_timestep is not None:
            pending_route_builds += sum(
                1
                for route_build in previous_trace["recent_route_builds"]
                if int(route_build["execution_timestep"])
                > pending_shift_timestep
            )
        cohort_ready = (
            pending_shift_timestep is not None
            and current_timestep - pending_shift_timestep >= cohort_delay
            and pending_route_builds >= cohort_min_route_builds
        )
        decision_pending_shift = pending_shift_timestep
        decision_pending_route_builds = pending_route_builds
        current_task = _probabilities(adapter.observation[-1])
        task_js = _js_divergence(current_task, reference_task)
        feature_snapshot = None
        feature_fingerprint = None
        state_fingerprint = None
        candidate_guidance_sha256 = None
        preview_seconds = 0.0
        trigger_scores = None
        if distribution_updates and isinstance(
            generator, NextRouteFlowGuidanceGenerator
        ):
            preview_started = time.perf_counter()
            generator_state_before = (
                generator.calls,
                generator.last_distribution_timestep,
                generator.last_distribution_change_js,
                generator.home_weights.copy(),
                generator.endpoint_weights.copy(),
            )
            candidate_action = generator.preview(adapter.observation)
            preview_seconds = time.perf_counter() - preview_started
            if (
                generator.calls != generator_state_before[0]
                or generator.last_distribution_timestep
                != generator_state_before[1]
                or generator.last_distribution_change_js
                != generator_state_before[2]
                or not np.array_equal(
                    generator.home_weights, generator_state_before[3]
                )
                or not np.array_equal(
                    generator.endpoint_weights, generator_state_before[4]
                )
            ):
                raise RuntimeError("candidate preview mutated generator state")
            feature_snapshot, feature_fingerprint, state_fingerprint = (
                _causal_feature_snapshot(
                    observation=adapter.observation,
                    previous_trace=dict(previous_trace),
                    generator=generator,
                    current_action=adapter.cached_action,
                    candidate_action=candidate_action,
                    current_guidance_sha256=adapter.guidance_digest,
                    current_timestep=current_timestep,
                    warmup_time=warmup_time,
                    horizon=horizon,
                    decision_window=decision_window,
                    last_refresh_timestep=last_refresh_timestep,
                    task_js_since_refresh=task_js,
                    recent_rewards=recent_rewards,
                    num_agents=env.config.num_agents,
                    shift_index=int(observed_shift_index),
                )
            )
            candidate_guidance_sha256 = feature_snapshot[
                "candidate_guidance_sha256"
            ]

        if method in {"oracle_boundary_ridge", "oracle_boundary_lcb"}:
            if trigger_model is None:
                raise ValueError(f"method {method!r} requires --trigger-model")
            if adapter.decision_index == 0:
                refresh = True
            elif distribution_updates:
                trigger_scores = trigger_model.score(
                    feature_snapshot["features"]
                )
                refresh = bool(trigger_scores[
                    "ridge_refresh" if method == "oracle_boundary_ridge"
                    else "lcb_refresh"
                ])
            else:
                refresh = False
        else:
            refresh = _method_refresh(
                method,
                decision_index=adapter.decision_index,
                current_timestep=current_timestep,
                warmup_time=warmup_time,
                shift_interval=shift_interval,
                decision_window=decision_window,
                task_js=task_js,
                event_threshold=event_threshold,
                last_refresh_timestep=last_refresh_timestep,
                event_minimum_gap=event_minimum_gap,
                cohort_ready=cohort_ready,
                observed_shift=bool(distribution_updates),
                observed_shift_index=observed_shift_index,
                bootstrap_timestep=bootstrap_timestep,
            )
        if (
            refresh
            and decision_pending_shift is not None
            and isinstance(generator, NextRouteFlowGuidanceGenerator)
            and (
                generator.last_distribution_timestep is None
                or generator.last_distribution_timestep
                < decision_pending_shift
            )
        ):
            raise RuntimeError(
                "publication attempted with stale task-distribution state"
            )
        window = adapter.advance(refresh=refresh)
        if (
            refresh
            and candidate_guidance_sha256 is not None
            and window.guidance_digest != candidate_guidance_sha256
        ):
            raise RuntimeError(
                "published guidance differs from the pre-action candidate"
            )
        trace = window.info["dai_trace"]
        distribution_update_tape.extend(
            trace["recent_distribution_updates"]
        )
        if any(
            record["timed_out"] for record in trace["recent_planner_times"]
        ):
            raise RuntimeError("planner timeout invalidates MVP condition")
        if refresh:
            reference_task = current_task.copy()
            last_refresh_timestep = current_timestep
            if method == "cohort_event":
                pending_shift_timestep = None
                pending_route_builds = 0
        windows.append({
            "decision_index": window.decision_index,
            "window_start_timestep": trace["window_start_timestep"],
            "window_end_timestep": trace["window_end_timestep"],
            "reward": window.reward,
            "refreshed": refresh,
            "task_js_since_refresh": task_js,
            "pending_shift_timestep": decision_pending_shift,
            "pending_route_builds": decision_pending_route_builds,
            "cohort_ready": cohort_ready,
            "guidance_version": trace["guidance_version"],
            "num_task_finished": trace["num_task_finished"],
            "route_build_count": len(trace["recent_route_builds"]),
            "distribution_update_count": len(
                trace["recent_distribution_updates"]
            ),
            "observed_shift_index": observed_shift_index,
            "planner_seconds": sum(
                record["seconds"]
                for record in trace["recent_planner_times"]
            ),
            "generator_seconds": window.generator_seconds,
            "simulator_seconds": window.simulator_seconds,
            "applied_guidance_sha256": trace["applied_guidance_sha256"],
            "generator_distribution_timestep": (
                generator.last_distribution_timestep
                if isinstance(generator, NextRouteFlowGuidanceGenerator)
                else None
            ),
            "decision_feature_snapshot": feature_snapshot,
            "decision_feature_fingerprint": feature_fingerprint,
            "decision_state_fingerprint": state_fingerprint,
            "candidate_preview_seconds": preview_seconds,
            "trigger_scores": trigger_scores,
        })
        recent_rewards.append(float(window.reward))
        current_timestep = int(trace["window_end_timestep"])

    elapsed = time.perf_counter() - started
    final_finished = int(windows[-1]["num_task_finished"])
    reward_sum = float(sum(row["reward"] for row in windows))
    if not math.isclose(reward_sum, float(final_finished), abs_tol=1e-9):
        raise RuntimeError(
            "window reward sum does not equal final completed-task count"
        )
    post_shift_rewards = [
        row["reward"]
        for row in windows
        if row["window_start_timestep"] >= shift_interval
    ]
    result = {
        "method": method,
        "seed": seed,
        "num_task_finished": final_finished,
        "throughput_per_timestep": final_finished
        / config_factory().simu_time,
        "post_shift_mean_window_reward": (
            float(np.mean(post_shift_rewards)) if post_shift_rewards else 0.0
        ),
        "publication_count": adapter.refresh_count,
        "generator_calls": generator.calls,
        "generator_metadata": getattr(generator, "metadata", None),
        "generator_seconds": sum(row["generator_seconds"] for row in windows),
        "simulator_seconds": sum(row["simulator_seconds"] for row in windows),
        "elapsed_seconds": elapsed,
        "window_count": len(windows),
        "reward_sum": reward_sum,
        "reset_causal_fingerprint": _canonical_hash({
            "seed_bundle": reset_trace["seed_bundle"],
            "start": reset_trace["start"],
            "planner_initial_priority_order": reset_trace[
                "planner_initial_priority_order"
            ],
            "curr_pos": reset_trace["curr_pos"],
            "curr_tasks": reset_trace["curr_tasks"],
            "curr_task_active": reset_trace.get(
                "curr_task_active",
                [True] * len(reset_trace["curr_pos"]),
            ),
            "actual_paths": reset_trace["actual_paths"],
        }),
        "distribution_update_fingerprint": _canonical_hash(
            distribution_update_tape
        ),
        "task_tape_identity": (
            {
                field: reset_trace["task_tape"][field]
                for field in (
                    "mode",
                    "manifest_sha256",
                    "content_fnv1a64",
                    "start_locations",
                    "per_agent_lengths",
                    "total_tasks",
                )
            }
            if reset_trace.get("task_tape", {}).get("enabled") is True
            else None
        ),
        "final_task_tape_prefixes": (
            {
                field: trace["task_tape"][field]
                for field in (
                    "released_prefix_lengths",
                    "assigned_prefix_lengths",
                    "completed_prefix_lengths",
                    "all_released",
                    "all_completed",
                    "exhausted",
                )
                if field in trace["task_tape"]
            }
            if trace.get("task_tape", {}).get("enabled") is True
            else None
        ),
        "windows": windows,
    }
    del adapter, generator, env
    gc.collect()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[17, 18, 19])
    parser.add_argument(
        "--methods",
        nargs="+",
        default=[
            "uniform",
            "never",
            "always",
            "period_50",
            "period_100",
            "task_js_event",
            "cohort_event",
            "oracle_shift",
        ],
    )
    parser.add_argument("--agents", type=int, default=400)
    parser.add_argument("--warmup-time", type=int, default=100)
    parser.add_argument("--horizon", type=int, default=600)
    parser.add_argument("--decision-window", type=int, default=20)
    parser.add_argument("--shift-interval", type=int, default=200)
    parser.add_argument("--event-threshold", type=float, default=0.02)
    parser.add_argument("--event-minimum-gap", type=int, default=40)
    parser.add_argument("--cohort-delay", type=int, default=40)
    parser.add_argument("--cohort-min-route-builds", type=int, default=40)
    parser.add_argument("--traffic-alpha", type=float, default=1.0)
    parser.add_argument("--wait-alpha", type=float, default=0.25)
    parser.add_argument("--goal-alpha", type=float, default=4.0)
    parser.add_argument(
        "--generator-mode",
        choices=(
            "potential", "route_flow", "next_route_flow", "frozen_cnn"
        ),
        default="next_route_flow",
    )
    parser.add_argument("--flow-bias", type=float, default=0.10)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help=(
            "optimal_update_model.json required by --generator-mode "
            "frozen_cnn"
        ),
    )
    parser.add_argument(
        "--checkpoint-sha256",
        default=None,
        help="optional expected SHA-256 of the exact checkpoint file",
    )
    parser.add_argument(
        "--checkpoint-params-sha256",
        default=None,
        help=(
            "optional expected SHA-256 of the effective float32 parameter "
            "vector"
        ),
    )
    parser.add_argument(
        "--trigger-model",
        type=Path,
        default=None,
        help=(
            "frozen ridge trigger JSON for oracle_boundary_ridge/"
            "oracle_boundary_lcb"
        ),
    )
    args = parser.parse_args()

    if len(set(args.seeds)) != len(args.seeds):
        raise ValueError("seeds must be unique")
    if len(set(args.methods)) != len(args.methods):
        raise ValueError("methods must be unique")
    if "never" not in args.methods:
        raise ValueError(
            "methods must include never as the paired bootstrap-only baseline"
        )

    if args.horizon % args.decision_window != 0:
        raise ValueError("horizon must be divisible by decision window")
    workspace = args.workspace.resolve()
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    sys.path.insert(0, str(workspace / "src"))
    sys.path.insert(0, str(cmaes))

    from dai_lmapf.online_ggo_adapter import OnlineGGOAdapter
    from dai_lmapf.causal_trigger import FrozenRidgeTrigger
    from env_search.iterative_update.envs.trafficflow_online_env import (
        TrafficFlowOnlineEnv,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig

    causal_methods = {
        "oracle_boundary_ridge", "oracle_boundary_lcb"
    } & set(args.methods)
    if causal_methods and args.trigger_model is None:
        raise ValueError(
            f"methods {sorted(causal_methods)!r} require --trigger-model"
        )
    if causal_methods and args.generator_mode != "next_route_flow":
        raise ValueError(
            "oracle_boundary trigger diagnostics currently require "
            "next_route_flow predecision features"
        )
    trigger_model = (
        FrozenRidgeTrigger.from_path(args.trigger_model.resolve())
        if args.trigger_model is not None
        else None
    )

    map_path = (
        onlineggo
        / "Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
        / "warehouse_small_narrow_kiva.map"
    ).resolve()

    def config_factory() -> Any:
        return TrafficMAPFConfig(
            map_path=str(map_path),
            simu_time=args.horizon,
            num_agents=args.agents,
            num_tasks=1_000_000,
            gen_tasks=True,
            task_assignment_strategy="roundrobin",
            update_gg_interval=args.decision_window,
            warmup_time=args.warmup_time,
            past_traffic_interval=args.decision_window,
            task_dist_change_interval=args.shift_interval,
            task_random_type="Gaussian",
            dist_sigma=0.5,
            dist_K=3,
            has_traffic_obs=True,
            has_gg_obs=False,
            has_task_obs=True,
            has_map_obs=False,
        )

    checkpoint_metadata = None
    if args.generator_mode == "potential":
        generator_kwargs = {
            "traffic_alpha": args.traffic_alpha,
            "wait_alpha": args.wait_alpha,
            "goal_alpha": args.goal_alpha,
        }
    elif args.generator_mode in {"route_flow", "next_route_flow"}:
        generator_kwargs = {"flow_bias": args.flow_bias}
    else:
        if args.checkpoint is None:
            raise ValueError(
                "--generator-mode frozen_cnn requires --checkpoint"
            )
        from dai_lmapf.frozen_cnn_generator import (
            load_frozen_cnn_checkpoint,
        )

        checkpoint_path = args.checkpoint.resolve()
        checkpoint = load_frozen_cnn_checkpoint(
            checkpoint_path,
            expected_file_sha256=args.checkpoint_sha256,
            expected_params_sha256=args.checkpoint_params_sha256,
        )
        checkpoint_metadata = checkpoint.metadata()
        generator_kwargs = {
            "checkpoint_path": str(checkpoint_path),
            "expected_file_sha256": checkpoint.file_sha256,
            "expected_params_sha256": checkpoint.params_sha256,
        }
    module_paths = sorted(
        (cmaes / "simulators" / "trafficMAPF_on").glob("period_on_sim*.so")
    )
    if len(module_paths) != 1:
        raise RuntimeError("expected exactly one compiled period_on_sim module")

    runs = []
    for seed in args.seeds:
        for method in args.methods:
            print(f"MVP start method={method} seed={seed}", flush=True)
            run = _run_condition(
                method=method,
                seed=seed,
                config_factory=config_factory,
                env_class=TrafficFlowOnlineEnv,
                adapter_class=OnlineGGOAdapter,
                generator_mode=args.generator_mode,
                generator_kwargs=generator_kwargs,
                decision_window=args.decision_window,
                warmup_time=args.warmup_time,
                shift_interval=args.shift_interval,
                event_threshold=args.event_threshold,
                event_minimum_gap=args.event_minimum_gap,
                cohort_delay=args.cohort_delay,
                cohort_min_route_builds=args.cohort_min_route_builds,
                horizon=args.horizon,
                trigger_model=trigger_model,
            )
            runs.append(run)
            print(
                "MVP done "
                f"method={method} seed={seed} "
                f"tasks={run['num_task_finished']} "
                f"pubs={run['publication_count']}",
                flush=True,
            )

    for seed in args.seeds:
        seed_runs = [run for run in runs if run["seed"] == seed]
        reset_fingerprints = {
            run["reset_causal_fingerprint"] for run in seed_runs
        }
        distribution_fingerprints = {
            run["distribution_update_fingerprint"] for run in seed_runs
        }
        if len(reset_fingerprints) != 1:
            raise RuntimeError(
                f"seed {seed} has unpaired reset causal state across methods"
            )
        if len(distribution_fingerprints) != 1:
            raise RuntimeError(
                f"seed {seed} has different exogenous distribution updates"
            )

    summaries = {}
    for method in args.methods:
        method_runs = [run for run in runs if run["method"] == method]
        task_counts = [run["num_task_finished"] for run in method_runs]
        publication_counts = [run["publication_count"] for run in method_runs]
        summaries[method] = {
            "mean_num_task_finished": sum(task_counts) / len(task_counts),
            "mean_publication_count": sum(publication_counts)
            / len(publication_counts),
            "task_counts_by_seed": {
                str(run["seed"]): run["num_task_finished"]
                for run in method_runs
            },
        }
    never_by_seed = {
        run["seed"]: run["num_task_finished"]
        for run in runs
        if run["method"] == "never"
    }
    uniform_by_seed = {
        run["seed"]: run["num_task_finished"]
        for run in runs
        if run["method"] == "uniform"
    }
    for method, summary in summaries.items():
        if method == "never":
            summary["mean_paired_delta_vs_never"] = 0.0
            continue
        deltas = [
            run["num_task_finished"] - never_by_seed[run["seed"]]
            for run in runs
            if run["method"] == method
        ]
        summary["mean_paired_delta_vs_never"] = sum(deltas) / len(deltas)
    if uniform_by_seed:
        for method, summary in summaries.items():
            deltas = [
                run["num_task_finished"] - uniform_by_seed[run["seed"]]
                for run in runs
                if run["method"] == method
            ]
            summary["mean_paired_delta_vs_uniform"] = (
                sum(deltas) / len(deltas)
            )

    artifact = {
        "schema": "dai.gate0.publication-mvp/v1",
        "status": "complete",
        "claim_scope": (
            "publication-schedule feasibility with a hash-locked official "
            "OnlineGGO CNN; not a deployable-trigger or SOTA claim"
            if args.generator_mode == "frozen_cnn"
            else
            "mechanism feasibility only; frozen heuristic generator, not a "
            "trained OnlineGGO/SOTA claim; next_route_flow consumes true "
            "distribution weights and is an oracle-generator diagnostic"
        ),
        "method_semantics": {
            "uniform": (
                "never invoke the generator; reuse the all-ones guidance "
                "installed by adapter reset for the entire episode"
            ),
            "never": (
                "publish once at the first post-warmup decision, then reuse; "
                "this is a bootstrap-only baseline, not zero guidance"
            ),
            "oracle_shift": (
                "publish when an actual task-distribution update is observed "
                "in the preceding simulator window"
            ),
            "oracle_boundary_ridge": (
                "diagnostic only: at a true observed workload-update "
                "boundary, publish iff the frozen ridge mean predicts "
                "positive local net value"
            ),
            "oracle_boundary_lcb": (
                "diagnostic only: at a true observed workload-update "
                "boundary, publish iff the frozen ridge lower confidence "
                "bound predicts positive local net value"
            ),
        },
        "platform": platform.platform(),
        "python": platform.python_version(),
        "map_path": str(map_path),
        "map_sha256": _sha256(map_path),
        "period_on_sim_sha256": _sha256(module_paths[0]),
        "seeds": args.seeds,
        "methods": args.methods,
        "agents": args.agents,
        "warmup_time": args.warmup_time,
        "horizon": args.horizon,
        "decision_window": args.decision_window,
        "shift_interval": args.shift_interval,
        "workload": {
            "task_random_type": "Gaussian",
            "dist_sigma": 0.5,
            "dist_K": 3,
            "task_assignment_strategy": "roundrobin",
            "kiva_task_generator": True,
        },
        "event_threshold": args.event_threshold,
        "event_minimum_gap": args.event_minimum_gap,
        "cohort_delay": args.cohort_delay,
        "cohort_min_route_builds": args.cohort_min_route_builds,
        "generator": {
            "mode": args.generator_mode,
            **(
                checkpoint_metadata
                if checkpoint_metadata is not None
                else generator_kwargs
            ),
        },
        "trigger_model": (
            {
                "path": str(args.trigger_model.resolve()),
                "model_id": trigger_model.model_id,
            }
            if trigger_model is not None
            else None
        ),
        "summaries": summaries,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "method",
                "seed",
                "num_task_finished",
                "throughput_per_timestep",
                "post_shift_mean_window_reward",
                "publication_count",
                "generator_seconds",
                "simulator_seconds",
                "elapsed_seconds",
            ],
        )
        writer.writeheader()
        for run in runs:
            writer.writerow({field: run[field] for field in writer.fieldnames})
    print(json.dumps(summaries, indent=2, sort_keys=True))
    print(f"artifact={args.output}")
    print(f"csv={csv_path}")


if __name__ == "__main__":
    main()
