"""Claim-bearing primitives for exact-budget absolute-tape experiments.

This module deliberately contains no OnlineGGO imports.  It defines the
registered method contracts, causal feature construction, and independent
trajectory audits used by the Linux experiment entry point.  Keeping these
pieces backend-free makes the budget and safety rules unit-testable before an
expensive simulator run.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from numbers import Integral, Real
from typing import Any, Mapping, Sequence

from .publication_policy import (
    CappedScorePublicationPolicy,
    CausalBlockDecision,
    CausalBlockPublicationPolicy,
    ContextMemoryDecision,
    ContextMemoryPublicationPolicy,
    ExactBudgetPublicationPolicy,
    PublicationDecision,
)


CLAIM_RUNNER_SCHEMA = "dai.claim-aware-absolute-budget/v1"
CONTEXT_DUALCAP_METHOD = "context_dualcap_G4S5"
CONTEXT_DUALCAP_POST_GENERATION_CAP = 4
CONTEXT_DUALCAP_SWITCH_CAP = 5
CONTEXT_EVENTRESERVE_METHOD = "context_eventreserve_G5S6"
CONTEXT_EVENTRESERVE_POST_GENERATION_CAP = 5
CONTEXT_EVENTRESERVE_SWITCH_CAP = 6
EXACT_EVEN_G4_METHOD = "exact_even_G4"
EXACT_EVEN_G5_METHOD = "exact_even_G5"
RANDOM_G5_METHOD = "random_G5"
JS_CAP_G5_METHOD = "js_cap_G5"
CONTEXT_NO_REACTIVATION_METHOD = "context_no_reactivation_B25"
G4_POST_BOOTSTRAP_CAP = 4
G5_POST_BOOTSTRAP_CAP = 5
REGISTERED_METHODS = (
    "uniform",
    "bootstrap_only",
    "always",
    "exact_even_B25",
    "period_80",
    "random_B25",
    "js_B25",
    "js_cap_B25",
    "context_memory_B25",
    "throughput_drop_B25",
    "causal_block_B25",
    "proposed_cohort_B25",
    "proposed_no_cohort_B25",
)
DEVELOPMENT_ONLY_METHODS = (
    "random_memory_B25",
    CONTEXT_DUALCAP_METHOD,
    CONTEXT_EVENTRESERVE_METHOD,
    EXACT_EVEN_G4_METHOD,
    EXACT_EVEN_G5_METHOD,
    RANDOM_G5_METHOD,
    JS_CAP_G5_METHOD,
    CONTEXT_NO_REACTIVATION_METHOD,
)
AVAILABLE_METHODS = REGISTERED_METHODS + DEVELOPMENT_ONLY_METHODS
EXACT_BUDGET_METHODS = frozenset(
    {
        "bootstrap_only",
        "always",
        "exact_even_B25",
        "random_B25",
        "js_B25",
        "throughput_drop_B25",
        "causal_block_B25",
        "proposed_cohort_B25",
        "proposed_no_cohort_B25",
        EXACT_EVEN_G4_METHOD,
        EXACT_EVEN_G5_METHOD,
        RANDOM_G5_METHOD,
    }
)
SCORE_METHODS = frozenset(
    {
        "js_B25",
        "js_cap_B25",
        "context_memory_B25",
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
        JS_CAP_G5_METHOD,
        CONTEXT_NO_REACTIVATION_METHOD,
        "throughput_drop_B25",
        "causal_block_B25",
        "proposed_cohort_B25",
        "proposed_no_cohort_B25",
    }
)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def b25_budget(num_scored_windows: int) -> int:
    """Return ``ceil(.25 * (N - 1))`` after excluding decision zero."""

    if isinstance(num_scored_windows, bool) or not isinstance(
        num_scored_windows, int
    ):
        raise TypeError("num_scored_windows must be an integer")
    if num_scored_windows < 1:
        raise ValueError("num_scored_windows must be positive")
    return math.ceil(0.25 * (num_scored_windows - 1))


def method_budget(method: str, num_scored_windows: int) -> int | None:
    """Return an available method's post-bootstrap quota, or ``None`` for m80."""

    if method not in AVAILABLE_METHODS:
        raise ValueError(f"unknown available method {method!r}")
    eligible = num_scored_windows - 1
    if method in {"uniform", "bootstrap_only"}:
        return 0
    if method == "always":
        return eligible
    if method == "period_80":
        return None
    if method == CONTEXT_DUALCAP_METHOD:
        return min(CONTEXT_DUALCAP_SWITCH_CAP, eligible)
    if method == CONTEXT_EVENTRESERVE_METHOD:
        return min(CONTEXT_EVENTRESERVE_SWITCH_CAP, eligible)
    if method == EXACT_EVEN_G4_METHOD:
        return min(G4_POST_BOOTSTRAP_CAP, eligible)
    if method in {EXACT_EVEN_G5_METHOD, RANDOM_G5_METHOD, JS_CAP_G5_METHOD}:
        return min(G5_POST_BOOTSTRAP_CAP, eligible)
    return b25_budget(num_scored_windows)


def method_generation_cap(method: str, num_scored_windows: int) -> int | None:
    """Return the hard post-bootstrap fresh-generation cap for a method.

    Most methods share their publication and generation cap.  The two
    development-only context controllers are deliberately different: G4/S5
    allows at most four fresh generations within five switches, while G5/S6
    allows at most five within six.  Reactivating cached guidance spends only
    the switch cap.  The mandatory bootstrap is outside all post-bootstrap
    caps.
    """

    switch_cap = method_budget(method, num_scored_windows)
    if method == CONTEXT_DUALCAP_METHOD:
        return min(CONTEXT_DUALCAP_POST_GENERATION_CAP, num_scored_windows - 1)
    if method == CONTEXT_EVENTRESERVE_METHOD:
        return min(
            CONTEXT_EVENTRESERVE_POST_GENERATION_CAP,
            num_scored_windows - 1,
        )
    return switch_cap


def make_exact_policy(
    method: str,
    *,
    num_scored_windows: int,
    policy_seed: int,
    pacing_slack: int = 2,
    minimum_history: int = 4,
    context_min_score: float = 0.10,
    context_min_gap: int = 6,
) -> (
    ExactBudgetPublicationPolicy
    | CausalBlockPublicationPolicy
    | CappedScorePublicationPolicy
    | ContextMemoryPublicationPolicy
    | None
):
    """Create a policy over decision indices ``1..N-1``.

    Policy epoch zero corresponds to global decision index one.  Bootstrap is
    therefore structurally impossible to charge to the quota.
    """

    budget = method_budget(method, num_scored_windows)
    if budget is None or method == "uniform":
        return None
    eligible = num_scored_windows - 1
    if method == "causal_block_B25":
        return CausalBlockPublicationPolicy(
            total_epochs=eligible,
            budget=budget,
            score_quantile=0.75,
            max_advance=2,
            min_gap=2,
            minimum_history=minimum_history,
        )
    if method in {"js_cap_B25", JS_CAP_G5_METHOD}:
        return CappedScorePublicationPolicy(
            total_epochs=eligible,
            budget=budget,
            score_quantile=0.75,
            minimum_history=minimum_history,
            min_gap=2,
            minimum_effect_epochs=3,
        )
    if method in {
        "context_memory_B25",
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
        CONTEXT_NO_REACTIVATION_METHOD,
    }:
        return ContextMemoryPublicationPolicy(
            total_epochs=eligible,
            budget=budget,
            score_quantile=0.75,
            minimum_history=minimum_history,
            min_gap=context_min_gap,
            minimum_effect_epochs=3,
            persistence=1,
            minimum_score=context_min_score,
        )
    policy_method = {
        "bootstrap_only": "bootstrap_only",
        "always": "always",
        "exact_even_B25": "even",
        EXACT_EVEN_G4_METHOD: "even",
        EXACT_EVEN_G5_METHOD: "even",
        "random_B25": "random",
        RANDOM_G5_METHOD: "random",
        "random_memory_B25": "random",
        "js_B25": "js",
        "throughput_drop_B25": "throughput_drop",
        "proposed_cohort_B25": "proposed",
        "proposed_no_cohort_B25": "proposed_no_cohort",
    }[method]
    return ExactBudgetPublicationPolicy(
        method=policy_method,
        total_epochs=eligible,
        budget=budget,
        policy_seed=policy_seed,
        pacing_slack=pacing_slack,
        minimum_history=minimum_history,
    )


def period_80_refresh(decision_index: int, decision_window: int) -> bool:
    """Nominal m80 schedule anchored at the mandatory bootstrap decision."""

    if decision_index <= 0:
        return False
    if decision_window <= 0:
        raise ValueError("decision_window must be positive")
    return (decision_index * decision_window) // 80 > (
        (decision_index - 1) * decision_window
    ) // 80


def probabilities(values: Sequence[Real]) -> tuple[float, ...]:
    numeric = [max(0.0, float(value)) for value in values]
    if not numeric:
        raise ValueError("probability vector must be non-empty")
    if any(not math.isfinite(value) for value in numeric):
        raise ValueError("probability values must be finite")
    total = math.fsum(numeric)
    if total <= 0:
        return tuple(1.0 / len(numeric) for _ in numeric)
    return tuple(value / total for value in numeric)


def js_divergence(left: Sequence[Real], right: Sequence[Real]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("JS inputs must be non-empty and aligned")
    p = probabilities(left)
    q = probabilities(right)
    midpoint = tuple((a + b) / 2.0 for a, b in zip(p, q))

    def kl(first: tuple[float, ...], second: tuple[float, ...]) -> float:
        return math.fsum(
            value * math.log(value / target)
            for value, target in zip(first, second)
            if value > 0
        )

    return 0.5 * kl(p, midpoint) + 0.5 * kl(q, midpoint)


def empirical_active_goal_distribution(
    trace: Mapping[str, Any], *, rows: int, cols: int
) -> tuple[float, ...]:
    tasks = trace.get("curr_tasks")
    active = trace.get("curr_task_active")
    if not isinstance(tasks, list) or not isinstance(active, list):
        raise TypeError("trace must expose curr_tasks and curr_task_active lists")
    if len(tasks) != len(active):
        raise ValueError("current task and activity arrays differ in length")
    counts = [0.0] * (rows * cols)
    for goal, is_active in zip(tasks, active):
        if not isinstance(is_active, bool):
            raise TypeError("curr_task_active values must be boolean")
        if not is_active:
            continue
        if not isinstance(goal, list) or len(goal) != 2:
            raise ValueError("current goals must be [row, col]")
        row, col = goal
        if any(isinstance(value, bool) or not isinstance(value, Integral) for value in goal):
            raise TypeError("goal coordinates must be integers")
        row, col = int(row), int(col)
        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError("active goal lies outside the map")
        counts[row * cols + col] += 1.0
    return probabilities(counts)


def flow_wait_distribution(trace: Mapping[str, Any]) -> tuple[tuple[float, ...], float]:
    """Return observable R,D,L,U flow proportions and wait ratio."""

    paths = trace.get("actual_paths")
    if not isinstance(paths, list):
        raise TypeError("actual_paths must be a list")
    counts = [0.0] * 4
    waits = 0
    total = 0
    action_index = {"R": 0, "D": 1, "L": 2, "U": 3}
    for raw_path in paths:
        if not isinstance(raw_path, str):
            raise TypeError("actual path must be a string")
        for action in ([] if raw_path == "" else raw_path.split(",")):
            total += 1
            if action == "W":
                waits += 1
            elif action in action_index:
                counts[action_index[action]] += 1.0
            else:
                raise ValueError(f"unknown path action {action!r}")
    return probabilities(counts), waits / max(total, 1)


@dataclass(frozen=True)
class CausalFeatureSnapshot:
    goal_js_since_publication: float
    released_goal_js_recent_vs_history: float
    edge_flow_js_since_publication: float
    recent_throughput_drop_per_agent: float
    recent_wait_ratio: float
    guidance_age_windows: int
    guidance_age_fraction: float
    recent_route_builds_per_agent: float
    current_version_route_fraction: float
    current_version_maturity: float
    current_cohort_service_degradation: float
    js_score: float
    throughput_drop_score: float
    proposed_no_cohort_score: float
    proposed_cohort_score: float
    causal_block_score: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


class CausalFeatureTracker:
    """Causal, tape-blind feature state updated only from emitted traces.

    The tracker never reads ``recent_distribution_updates`` or the unreleased
    task tape.  Cohorts are keyed by the version on the first actual route
    construction, not by release or assignment time.
    """

    def __init__(self, *, n_agents: int, rows: int, cols: int, total_windows: int):
        if min(n_agents, rows, cols, total_windows) <= 0:
            raise ValueError("tracker dimensions must be positive")
        self.n_agents = n_agents
        self.rows = rows
        self.cols = cols
        self.total_windows = total_windows
        self.latest_goal = probabilities([0.0] * (rows * cols))
        self.latest_flow = probabilities([0.0] * 4)
        self.latest_wait = 0.0
        # One normalized 4x4 histogram per observed trace window.  ``None``
        # means that the window contained no released task and therefore
        # cannot provide a workload-change observation.
        self.released_goal_history: deque[tuple[float, ...] | None] = deque(
            maxlen=8
        )
        self.goal_reference = self.latest_goal
        self.flow_reference = self.latest_flow
        self.rewards: deque[float] = deque(maxlen=8)
        self.latest_route_version: dict[int, int] = {}
        self.active_task_by_agent: dict[int, int] = {}
        self.current_active_agent_count = 0
        self.route_build_counts: defaultdict[int, int] = defaultdict(int)
        self.route_build_reason_counts: defaultdict[str, int] = defaultdict(int)
        # task_id -> (agent_id, assignment_timestep, goal)
        self.assignments: dict[int, tuple[int, int, tuple[int, int]]] = {}
        self.first_build_version: dict[int, int] = {}
        self.service_by_version: defaultdict[int, deque[int]] = defaultdict(
            lambda: deque(maxlen=256)
        )
        self.current_version = 0
        self.last_publication_decision = 0
        self.last_recent_route_build_count = 0
        self._last_task_event_id = -1
        self._last_route_event_id = -1
        self.route_exposed_completion_count = 0
        self.unexposed_zero_route_completion_count = 0

    @staticmethod
    def _event_integer(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise TypeError(f"{field} must be an integer")
        return int(value)

    def ingest_trace(self, trace: Mapping[str, Any]) -> None:
        self.latest_goal = empirical_active_goal_distribution(
            trace, rows=self.rows, cols=self.cols
        )
        self.latest_flow, self.latest_wait = flow_wait_distribution(trace)
        events = trace.get("recent_events")
        builds = trace.get("recent_route_builds")
        if not isinstance(events, list) or not isinstance(builds, list):
            raise TypeError("trace event streams must be lists")

        pending_finishes: list[tuple[int, int, int, tuple[int, int]]] = []
        released_goal_counts = [0.0] * 16
        released_goal_count = 0
        for event in events:
            event_id = self._event_integer(event.get("event_id"), "task event_id")
            if event_id <= self._last_task_event_id:
                raise ValueError("task event IDs must strictly increase")
            self._last_task_event_id = event_id
            event_type = event.get("event_type")
            task_id = self._event_integer(event.get("task_id"), "task_id")
            timestep = self._event_integer(event.get("timestep"), "task timestep")
            agent_id = self._event_integer(event.get("agent_id"), "task agent_id")
            goal_raw = event.get("goal_loc")
            if (
                not isinstance(goal_raw, list)
                or len(goal_raw) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, Integral)
                    for value in goal_raw
                )
            ):
                raise ValueError("task goal_loc must be an integer [row, col]")
            goal = (int(goal_raw[0]), int(goal_raw[1]))
            if not (0 <= goal[0] < self.rows and 0 <= goal[1] < self.cols):
                raise ValueError("task goal_loc lies outside the map")
            if event_type == "assigned":
                if task_id in self.assignments:
                    raise ValueError("task was assigned twice")
                self.assignments[task_id] = (agent_id, timestep, goal)
                # Assignment changes invalidate any route version left by the
                # preceding task.  The new task becomes cohort-visible only
                # after its own route-build event arrives.
                self.active_task_by_agent[agent_id] = task_id
                self.latest_route_version.pop(agent_id, None)
            elif event_type == "finished":
                pending_finishes.append((task_id, agent_id, timestep, goal))
                if self.active_task_by_agent.get(agent_id) == task_id:
                    self.active_task_by_agent.pop(agent_id, None)
                    self.latest_route_version.pop(agent_id, None)
            elif event_type == "released":
                row_bin = min(3, (goal[0] * 4) // self.rows)
                col_bin = min(3, (goal[1] * 4) // self.cols)
                released_goal_counts[row_bin * 4 + col_bin] += 1.0
                released_goal_count += 1
            else:
                raise ValueError(f"unknown task event type {event_type!r}")

        self.released_goal_history.append(
            probabilities([value + 0.5 for value in released_goal_counts])
            if released_goal_count
            else None
        )

        for build in builds:
            event_id = self._event_integer(build.get("event_id"), "route event_id")
            if event_id <= self._last_route_event_id:
                raise ValueError("route-build event IDs must strictly increase")
            self._last_route_event_id = event_id
            agent_id = self._event_integer(build.get("agent_id"), "route agent_id")
            task_id = self._event_integer(build.get("task_id"), "route task_id")
            version = self._event_integer(
                build.get("publication_version"), "publication_version"
            )
            reason = build.get("reason")
            if reason is not None:
                if not isinstance(reason, str) or not reason:
                    raise ValueError("route-build reason must be a non-empty string")
                self.route_build_reason_counts[reason] += 1
            if self.active_task_by_agent.get(agent_id) == task_id:
                self.latest_route_version[agent_id] = version
            self.route_build_counts[version] += 1
            self.first_build_version.setdefault(task_id, version)
        self.last_recent_route_build_count = len(builds)

        trace_valid = trace.get("route_build_trace_valid") is True
        for task_id, completed_agent, completed_step, completed_goal in pending_finishes:
            assignment = self.assignments.pop(task_id, None)
            version = self.first_build_version.pop(task_id, None)
            if assignment is None:
                raise ValueError("finished task lacks assignment")
            assigned_agent, assigned_step, assigned_goal = assignment
            if (completed_agent, completed_goal) != (assigned_agent, assigned_goal):
                raise ValueError("finished task identity disagrees with assignment")
            if completed_step < assigned_step:
                raise ValueError("task finished before assignment")
            if version is None:
                # The planner deliberately leaves its trajectory empty when a
                # newly assigned goal is already satisfied.  Such a task is
                # popped on the next simulator move without a route build.  We
                # admit only that exact minimum-latency case, and only while
                # the simulator certifies the route trace as complete.  It is
                # observable but has no guidance exposure/cohort attribution.
                if not trace_valid or completed_step - assigned_step != 1:
                    raise ValueError(
                        "finished task lacks route exposure: "
                        f"task_id={task_id}, agent_id={completed_agent}, "
                        f"assigned_step={assigned_step}, "
                        f"completed_step={completed_step}, goal={completed_goal}, "
                        f"route_build_trace_valid={trace_valid}"
                    )
                self.unexposed_zero_route_completion_count += 1
                continue
            self.route_exposed_completion_count += 1
            self.service_by_version[version].append(completed_step - assigned_step)

        # A finished task leaves no active route cohort.  Do not let an idle
        # agent's last historical route inflate the current-version fraction.
        active_flags = trace.get("curr_task_active")
        if not isinstance(active_flags, list) or len(active_flags) != self.n_agents:
            raise ValueError("curr_task_active must align with the agent team")
        self.current_active_agent_count = sum(active_flags)
        self.latest_route_version = {
            agent_id: version
            for agent_id, version in self.latest_route_version.items()
            if active_flags[agent_id]
        }
        self.active_task_by_agent = {
            agent_id: task_id
            for agent_id, task_id in self.active_task_by_agent.items()
            if active_flags[agent_id]
        }

    def released_goal_change_score(self) -> float:
        """Return causal JS change from released goals in fixed 4x4 bins.

        The fast side averages the latest two trace-window histograms; the
        reference side averages up to six preceding windows.  It never uses
        active-task composition, workload metadata, phase clocks, or an
        unreleased task-tape suffix.
        """

        history = list(self.released_goal_history)
        if len(history) < 3 or history[-1] is None:
            return 0.0
        fast = [value for value in history[-2:] if value is not None]
        slow = [value for value in history[:-2][-6:] if value is not None]
        if not fast or not slow:
            return 0.0

        def mean_distribution(
            values: list[tuple[float, ...]],
        ) -> tuple[float, ...]:
            return tuple(
                math.fsum(value[index] for value in values) / len(values)
                for index in range(16)
            )

        score = js_divergence(mean_distribution(fast), mean_distribution(slow))
        return min(1.0, max(0.0, score / math.log(2.0)))

    def active_goal_context_4x4(self) -> tuple[float, ...]:
        """Return a causal coarse context from currently active task goals."""

        counts = [0.0] * 16
        for flat_index, mass in enumerate(self.latest_goal):
            row, col = divmod(flat_index, self.cols)
            row_bin = min(3, (row * 4) // self.rows)
            col_bin = min(3, (col * 4) // self.cols)
            counts[row_bin * 4 + col_bin] += float(mass)
        return probabilities(counts)

    def observe_reward(self, reward: float) -> None:
        if not math.isfinite(float(reward)):
            raise ValueError("reward must be finite")
        self.rewards.append(float(reward))

    def mark_publication(self, *, version: int, decision_index: int) -> None:
        if version <= self.current_version:
            raise ValueError("publication version must increase")
        if decision_index < self.last_publication_decision:
            raise ValueError("publication decision index moved backwards")
        self.current_version = version
        self.last_publication_decision = decision_index
        self.goal_reference = self.latest_goal
        self.flow_reference = self.latest_flow

    def snapshot(self, *, decision_index: int) -> CausalFeatureSnapshot:
        if decision_index < self.last_publication_decision:
            raise ValueError("decision index predates the active publication")
        goal_js = js_divergence(self.latest_goal, self.goal_reference)
        released_goal_js = self.released_goal_change_score()
        flow_js = js_divergence(self.latest_flow, self.flow_reference)
        latest = self.rewards[-1] if self.rewards else 0.0
        previous = (
            math.fsum(list(self.rewards)[:-1]) / (len(self.rewards) - 1)
            if len(self.rewards) >= 2
            else latest
        )
        throughput_drop = max(0.0, previous - latest) / self.n_agents
        known_versions = list(self.latest_route_version.values())
        current_fraction = (
            sum(version == self.current_version for version in known_versions)
            / self.current_active_agent_count
            if self.current_active_agent_count
            else 0.0
        )
        minimum_builds = max(8, math.ceil(0.25 * self.n_agents))
        build_maturity = min(
            1.0, self.route_build_counts[self.current_version] / minimum_builds
        )
        maturity = max(current_fraction, build_maturity)

        current_service = list(self.service_by_version[self.current_version])
        previous_service = [
            value
            for version, samples in self.service_by_version.items()
            if version != self.current_version
            for value in samples
        ]
        service_degradation = 0.0
        if len(current_service) >= 8 and len(previous_service) >= 8:
            current_mean = math.fsum(current_service[-64:]) / len(current_service[-64:])
            previous_mean = math.fsum(previous_service[-128:]) / len(previous_service[-128:])
            service_degradation = max(
                0.0, (current_mean - previous_mean) / max(previous_mean, 1.0)
            )

        age = decision_index - self.last_publication_decision
        age_fraction = age / max(self.total_windows - 1, 1)
        route_rate = self.last_recent_route_build_count / self.n_agents
        throughput_score = throughput_drop + 0.25 * self.latest_wait
        no_cohort = (
            4.0 * goal_js
            + 2.0 * flow_js
            + 2.0 * throughput_drop
            + self.latest_wait
            + 0.25 * age_fraction
        )
        cohort = (
            no_cohort * (0.25 + 0.75 * maturity)
            + 1.5 * service_degradation
            + 0.10 * route_rate
        )
        values = CausalFeatureSnapshot(
            goal_js_since_publication=goal_js,
            released_goal_js_recent_vs_history=released_goal_js,
            edge_flow_js_since_publication=flow_js,
            recent_throughput_drop_per_agent=throughput_drop,
            recent_wait_ratio=self.latest_wait,
            guidance_age_windows=age,
            guidance_age_fraction=age_fraction,
            recent_route_builds_per_agent=route_rate,
            current_version_route_fraction=current_fraction,
            current_version_maturity=maturity,
            current_cohort_service_degradation=service_degradation,
            js_score=goal_js,
            throughput_drop_score=throughput_score,
            proposed_no_cohort_score=no_cohort,
            proposed_cohort_score=cohort,
            causal_block_score=released_goal_js,
        )
        if any(
            not math.isfinite(float(value))
            for value in values.as_dict().values()
        ):
            raise RuntimeError("causal feature construction produced non-finite data")
        return values


def score_for_method(method: str, snapshot: CausalFeatureSnapshot) -> float | None:
    return {
        "js_B25": snapshot.js_score,
        "js_cap_B25": snapshot.js_score,
        JS_CAP_G5_METHOD: snapshot.js_score,
        "context_memory_B25": snapshot.causal_block_score,
        CONTEXT_NO_REACTIVATION_METHOD: snapshot.causal_block_score,
        CONTEXT_DUALCAP_METHOD: snapshot.causal_block_score,
        CONTEXT_EVENTRESERVE_METHOD: snapshot.causal_block_score,
        "throughput_drop_B25": snapshot.throughput_drop_score,
        "causal_block_B25": snapshot.causal_block_score,
        "proposed_cohort_B25": snapshot.proposed_cohort_score,
        "proposed_no_cohort_B25": snapshot.proposed_no_cohort_score,
    }.get(method)


@dataclass(frozen=True)
class SafetyAudit:
    collision_count: int = 0
    edge_swap_count: int = 0
    invalid_move_count: int = 0
    endpoint_mismatch_count: int = 0

    @property
    def passed(self) -> bool:
        return not any(asdict(self).values())


def audit_joint_paths(
    *,
    start_positions: Sequence[Sequence[int]],
    actual_paths: Sequence[str],
    end_positions: Sequence[Sequence[int]],
    graph: Sequence[Sequence[int]],
) -> SafetyAudit:
    """Independently replay a simulator window and count MAPF violations."""

    if len(start_positions) != len(actual_paths) or len(actual_paths) != len(end_positions):
        raise ValueError("one start/path/end triple is required per agent")
    rows = len(graph)
    cols = len(graph[0]) if rows else 0
    if rows <= 0 or cols <= 0 or any(len(row) != cols for row in graph):
        raise ValueError("graph must be a non-empty rectangle")
    parsed = [([] if path == "" else path.split(",")) for path in actual_paths]
    lengths = {len(path) for path in parsed}
    if len(lengths) != 1:
        raise ValueError("all agents must expose the same executed path length")
    positions = [tuple(map(int, position)) for position in start_positions]
    deltas = {"R": (0, 1), "D": (1, 0), "L": (0, -1), "U": (-1, 0), "W": (0, 0)}
    collision_count = edge_swap_count = invalid_move_count = 0
    for offset in range(next(iter(lengths), 0)):
        old = list(positions)
        proposed: list[tuple[int, int]] = []
        for position, path in zip(old, parsed):
            action = path[offset]
            if action not in deltas:
                raise ValueError(f"unknown action {action!r}")
            delta = deltas[action]
            target = (position[0] + delta[0], position[1] + delta[1])
            if not (
                0 <= target[0] < rows
                and 0 <= target[1] < cols
                and int(graph[target[0]][target[1]]) == 0
            ):
                invalid_move_count += 1
                target = position
            proposed.append(target)
        collision_count += len(proposed) - len(set(proposed))
        directed = {(origin, target) for origin, target in zip(old, proposed) if origin != target}
        edge_swap_count += sum((target, origin) in directed for origin, target in directed) // 2
        positions = proposed
    expected = [tuple(map(int, position)) for position in end_positions]
    endpoint_mismatch_count = sum(a != b for a, b in zip(positions, expected))
    return SafetyAudit(
        collision_count=collision_count,
        edge_swap_count=edge_swap_count,
        invalid_move_count=invalid_move_count,
        endpoint_mismatch_count=endpoint_mismatch_count,
    )


def decision_to_dict(
    decision: PublicationDecision | CausalBlockDecision | ContextMemoryDecision,
) -> dict[str, Any]:
    payload = asdict(decision)
    threshold = payload["threshold"]
    if threshold is not None and not math.isfinite(float(threshold)):
        # Score policies intentionally use +inf before their causal history is
        # mature, which makes an event-driven request impossible during
        # warm-up.  That is internal control state, not a JSON number.  Emit a
        # standards-compliant null while preserving the decision/reason.
        payload["threshold"] = None
    return payload


__all__ = [
    "CLAIM_RUNNER_SCHEMA",
    "CONTEXT_DUALCAP_METHOD",
    "CONTEXT_DUALCAP_POST_GENERATION_CAP",
    "CONTEXT_DUALCAP_SWITCH_CAP",
    "CONTEXT_EVENTRESERVE_METHOD",
    "CONTEXT_EVENTRESERVE_POST_GENERATION_CAP",
    "CONTEXT_EVENTRESERVE_SWITCH_CAP",
    "EXACT_EVEN_G4_METHOD",
    "EXACT_EVEN_G5_METHOD",
    "RANDOM_G5_METHOD",
    "JS_CAP_G5_METHOD",
    "CONTEXT_NO_REACTIVATION_METHOD",
    "G4_POST_BOOTSTRAP_CAP",
    "G5_POST_BOOTSTRAP_CAP",
    "REGISTERED_METHODS",
    "DEVELOPMENT_ONLY_METHODS",
    "AVAILABLE_METHODS",
    "EXACT_BUDGET_METHODS",
    "SCORE_METHODS",
    "CausalFeatureSnapshot",
    "CausalFeatureTracker",
    "SafetyAudit",
    "audit_joint_paths",
    "b25_budget",
    "canonical_sha256",
    "decision_to_dict",
    "empirical_active_goal_distribution",
    "flow_wait_distribution",
    "js_divergence",
    "make_exact_policy",
    "method_budget",
    "method_generation_cap",
    "period_80_refresh",
    "probabilities",
    "score_for_method",
]
