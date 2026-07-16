"""Task-cohort attribution for versioned OnlineGGO guidance."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from numbers import Integral
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CohortAssignment:
    agent_id: int
    task_id: int
    assigned_step: int
    guidance_version: int


@dataclass(frozen=True)
class CohortCompletion:
    agent_id: int
    task_id: int
    assigned_step: int
    completed_step: int
    guidance_version: int

    @property
    def service_steps(self) -> int:
        return self.completed_step - self.assigned_step


class GuidanceCohortTracker:
    """Attribute task service outcomes to the version active at assignment.

    The instrumented C++ backend returns per-agent ``recent_events`` with
    entries ``[task_id, timestep, assigned|finished]``.  All assignments in one
    simulator window use the version installed before that window advanced.
    """

    def __init__(self, *, n_agents: int) -> None:
        if n_agents <= 0:
            raise ValueError("n_agents must be positive")
        self.n_agents = n_agents
        self.active: dict[int, CohortAssignment] = {}
        self.completions: list[CohortCompletion] = []
        self._seen: set[tuple[int, int, int, str]] = set()
        self.last_timestep = -1

    def reset(self) -> None:
        self.active.clear()
        self.completions.clear()
        self._seen.clear()
        self.last_timestep = -1

    def process_trace(
        self, trace: Mapping[str, Any], *, guidance_version: int
    ) -> list[CohortCompletion]:
        if guidance_version < 0:
            raise ValueError("guidance_version must be non-negative")
        timestep = trace.get("timestep")
        if not isinstance(timestep, Integral) or isinstance(timestep, bool):
            raise TypeError("trace timestep must be an integer")
        timestep = int(timestep)
        if timestep < self.last_timestep:
            raise ValueError("trace timestep moved backwards")
        events = trace.get("recent_events")
        if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
            raise TypeError("recent_events must be a per-agent sequence")
        if len(events) != self.n_agents:
            raise ValueError(
                f"recent_events needs {self.n_agents} agent lists, received {len(events)}"
            )

        produced: list[CohortCompletion] = []
        for agent_id, agent_events in enumerate(events):
            if not isinstance(agent_events, Sequence) or isinstance(
                agent_events, (str, bytes)
            ):
                raise TypeError(f"events for agent {agent_id} must be a sequence")
            for raw_event in agent_events:
                if not isinstance(raw_event, Sequence) or len(raw_event) != 3:
                    raise ValueError("each task event must be [task_id, timestep, type]")
                task_id, event_step, event_type = raw_event
                if (
                    not isinstance(task_id, Integral)
                    or isinstance(task_id, bool)
                    or not isinstance(event_step, Integral)
                    or isinstance(event_step, bool)
                ):
                    raise TypeError("task id and event timestep must be integers")
                task_id = int(task_id)
                event_step = int(event_step)
                if event_type not in {"released", "assigned", "finished"}:
                    raise ValueError(f"unknown task event type: {event_type!r}")
                if event_step < 0 or event_step > timestep:
                    raise ValueError("task event lies outside observed simulator time")
                identity = (agent_id, task_id, event_step, event_type)
                if identity in self._seen:
                    continue
                self._seen.add(identity)

                # Absolute workload lifecycle event. Cohort exposure starts at
                # assignment/route construction, not at exogenous release.
                if event_type == "released":
                    continue

                if event_type == "assigned":
                    if task_id in self.active:
                        raise ValueError(f"task {task_id} was assigned twice")
                    self.active[task_id] = CohortAssignment(
                        agent_id=agent_id,
                        task_id=task_id,
                        assigned_step=event_step,
                        guidance_version=guidance_version,
                    )
                    continue

                assignment = self.active.pop(task_id, None)
                if assignment is None:
                    raise ValueError(
                        f"task {task_id} finished without a recorded assignment"
                    )
                if assignment.agent_id != agent_id:
                    raise ValueError("task finished by a different agent than assigned")
                if event_step < assignment.assigned_step:
                    raise ValueError("task finished before it was assigned")
                completion = CohortCompletion(
                    agent_id=agent_id,
                    task_id=task_id,
                    assigned_step=assignment.assigned_step,
                    completed_step=event_step,
                    guidance_version=assignment.guidance_version,
                )
                self.completions.append(completion)
                produced.append(completion)
        self.last_timestep = timestep
        return produced

    def version_summary(self) -> dict[int, dict[str, float | int]]:
        grouped: dict[int, list[CohortCompletion]] = {}
        for completion in self.completions:
            grouped.setdefault(completion.guidance_version, []).append(completion)
        summary: dict[int, dict[str, float | int]] = {}
        for version, completions in sorted(grouped.items()):
            service = [item.service_steps for item in completions]
            ordered = sorted(service)
            p95_index = min(len(ordered) - 1, int(0.95 * len(ordered)))
            summary[version] = {
                "completed": len(completions),
                "mean_service_steps": statistics.fmean(service),
                "median_service_steps": statistics.median(service),
                "p95_service_steps": ordered[p95_index],
            }
        return summary


@dataclass(frozen=True)
class RouteTaskAssignment:
    agent_id: int
    task_id: int
    goal_loc: tuple[int, int]
    assigned_step: int


@dataclass(frozen=True)
class RouteBuildExposure:
    event_id: int
    agent_id: int
    task_id: int
    goal_loc: tuple[int, int]
    execution_step: int
    map_weights_revision: int
    publication_version: int
    raw_guidance_sha256: str
    applied_guidance_sha256: str
    reason: str


@dataclass(frozen=True)
class RouteCohortOutcome:
    assignment: RouteTaskAssignment
    completed_step: int
    builds: tuple[RouteBuildExposure, ...]

    @property
    def service_steps(self) -> int:
        return self.completed_step - self.assignment.assigned_step

    @property
    def first_publication_version(self) -> int:
        return self.builds[0].publication_version


class RouteCohortTracker:
    """Join task outcomes to actual guide-path construction versions.

    The official instrumented environment returns flat task events and route
    construction events.  A task's reveal/assignment version is deliberately
    ignored: only a direct route-build event defines its guidance exposure.
    Summaries from this tracker are diagnostic delayed feedback; paired episode
    outcomes remain the causal experimental unit.
    """

    _TASK_EVENT_KEYS = {
        "event_id",
        "agent_id",
        "task_id",
        "event_type",
        "timestep",
        "goal_loc",
    }
    _ROUTE_EVENT_KEYS = {
        "event_id",
        "agent_id",
        "task_id",
        "goal_loc",
        "execution_timestep",
        "map_weights_revision",
        "reason",
        "publication_version",
        "raw_guidance_sha256",
        "applied_normalized_guidance_sha256",
    }

    def __init__(self, *, n_agents: int) -> None:
        if n_agents <= 0:
            raise ValueError("n_agents must be positive")
        self.n_agents = n_agents
        self.assignments: dict[int, RouteTaskAssignment] = {}
        self.builds: dict[int, list[RouteBuildExposure]] = {}
        self.outcomes: list[RouteCohortOutcome] = []
        self._next_task_event_id = 0
        self._next_route_event_id = 0
        self.last_timestep = -1

    def reset(self) -> None:
        self.assignments.clear()
        self.builds.clear()
        self.outcomes.clear()
        self._next_task_event_id = 0
        self._next_route_event_id = 0
        self.last_timestep = -1

    @staticmethod
    def _integer(value: Any, field: str) -> int:
        if not isinstance(value, Integral) or isinstance(value, bool):
            raise TypeError(f"{field} must be an integer")
        value = int(value)
        if value < 0:
            raise ValueError(f"{field} must be non-negative")
        return value

    @classmethod
    def _location(cls, value: Any, field: str) -> tuple[int, int]:
        if (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or len(value) != 2
        ):
            raise ValueError(f"{field} must be [row, col]")
        return (
            cls._integer(value[0], f"{field}[0]"),
            cls._integer(value[1], f"{field}[1]"),
        )

    @staticmethod
    def _digest(value: Any, field: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        return value

    def process_trace(self, trace: Mapping[str, Any]) -> list[RouteCohortOutcome]:
        timestep = self._integer(trace.get("timestep"), "timestep")
        if timestep < self.last_timestep:
            raise ValueError("trace timestep moved backwards")
        task_events = trace.get("recent_events")
        route_events = trace.get("recent_route_builds")
        if not isinstance(task_events, list):
            raise TypeError("recent_events must be a flat list")
        if not isinstance(route_events, list):
            raise TypeError("recent_route_builds must be a flat list")

        pending_finishes: list[tuple[int, int, int, tuple[int, int]]] = []
        for raw in task_events:
            if not isinstance(raw, Mapping) or set(raw) != self._TASK_EVENT_KEYS:
                raise ValueError("task event has an invalid schema")
            event_id = self._integer(raw["event_id"], "task event_id")
            if event_id != self._next_task_event_id:
                raise ValueError("task event IDs are missing, duplicated, or reordered")
            self._next_task_event_id += 1
            agent_id = self._integer(raw["agent_id"], "task agent_id")
            if agent_id >= self.n_agents:
                raise ValueError("task agent_id is outside the team")
            task_id = self._integer(raw["task_id"], "task_id")
            event_step = self._integer(raw["timestep"], "task timestep")
            if event_step > timestep:
                raise ValueError("task event lies after the trace window")
            goal_loc = self._location(raw["goal_loc"], "task goal_loc")
            event_type = raw["event_type"]
            if event_type == "released":
                # Release establishes workload availability only; it is not a
                # guidance exposure and creates no route cohort.
                continue
            if event_type == "assigned":
                if task_id in self.assignments:
                    raise ValueError(f"task {task_id} was assigned twice")
                self.assignments[task_id] = RouteTaskAssignment(
                    agent_id=agent_id,
                    task_id=task_id,
                    goal_loc=goal_loc,
                    assigned_step=event_step,
                )
                self.builds[task_id] = []
            elif event_type == "finished":
                pending_finishes.append((task_id, agent_id, event_step, goal_loc))
            else:
                raise ValueError(f"unknown task event type: {event_type!r}")

        for raw in route_events:
            if not isinstance(raw, Mapping) or set(raw) != self._ROUTE_EVENT_KEYS:
                raise ValueError("route-build event has an invalid schema")
            event_id = self._integer(raw["event_id"], "route event_id")
            if event_id != self._next_route_event_id:
                raise ValueError("route event IDs are missing, duplicated, or reordered")
            self._next_route_event_id += 1
            agent_id = self._integer(raw["agent_id"], "route agent_id")
            if agent_id >= self.n_agents:
                raise ValueError("route agent_id is outside the team")
            task_id = self._integer(raw["task_id"], "route task_id")
            assignment = self.assignments.get(task_id)
            if assignment is None:
                raise ValueError(f"route built for unknown task {task_id}")
            goal_loc = self._location(raw["goal_loc"], "route goal_loc")
            if agent_id != assignment.agent_id or goal_loc != assignment.goal_loc:
                raise ValueError("route-build identity disagrees with task assignment")
            execution_step = self._integer(
                raw["execution_timestep"], "route execution_timestep"
            )
            if execution_step <= assignment.assigned_step or execution_step > timestep:
                raise ValueError("route build lies outside the task/trace lifetime")
            reason = raw["reason"]
            if reason not in {"init_pp", "task_change"}:
                raise ValueError("route-build reason is invalid")
            exposure = RouteBuildExposure(
                event_id=event_id,
                agent_id=agent_id,
                task_id=task_id,
                goal_loc=goal_loc,
                execution_step=execution_step,
                map_weights_revision=self._integer(
                    raw["map_weights_revision"], "map_weights_revision"
                ),
                publication_version=self._integer(
                    raw["publication_version"], "publication_version"
                ),
                raw_guidance_sha256=self._digest(
                    raw["raw_guidance_sha256"], "raw_guidance_sha256"
                ),
                applied_guidance_sha256=self._digest(
                    raw["applied_normalized_guidance_sha256"],
                    "applied_normalized_guidance_sha256",
                ),
                reason=reason,
            )
            task_builds = self.builds[task_id]
            if task_builds and execution_step <= task_builds[-1].execution_step:
                raise ValueError("route builds for a task are not strictly ordered")
            task_builds.append(exposure)

        produced: list[RouteCohortOutcome] = []
        for task_id, agent_id, completed_step, goal_loc in pending_finishes:
            assignment = self.assignments.get(task_id)
            if assignment is None:
                raise ValueError(f"task {task_id} finished without assignment")
            if agent_id != assignment.agent_id or goal_loc != assignment.goal_loc:
                raise ValueError("task completion identity disagrees with assignment")
            if completed_step < assignment.assigned_step:
                raise ValueError("task finished before assignment")
            task_builds = tuple(self.builds.get(task_id, ()))
            if not task_builds:
                raise ValueError(f"task {task_id} finished without a route-build event")
            if task_builds[-1].execution_step > completed_step:
                raise ValueError("route was built after task completion")
            outcome = RouteCohortOutcome(
                assignment=assignment,
                completed_step=completed_step,
                builds=task_builds,
            )
            self.outcomes.append(outcome)
            produced.append(outcome)
            del self.assignments[task_id]
            del self.builds[task_id]

        self.last_timestep = timestep
        return produced

    def version_summary(self) -> dict[int, dict[str, float | int]]:
        grouped: dict[int, list[RouteCohortOutcome]] = {}
        for outcome in self.outcomes:
            grouped.setdefault(outcome.first_publication_version, []).append(outcome)
        summary: dict[int, dict[str, float | int]] = {}
        for version, outcomes in sorted(grouped.items()):
            service = [outcome.service_steps for outcome in outcomes]
            summary[version] = {
                "completed": len(outcomes),
                "mean_service_steps": statistics.fmean(service),
                "median_service_steps": statistics.median(service),
            }
        return summary


__all__ = [
    "CohortAssignment",
    "CohortCompletion",
    "GuidanceCohortTracker",
    "RouteBuildExposure",
    "RouteCohortOutcome",
    "RouteCohortTracker",
    "RouteTaskAssignment",
]
