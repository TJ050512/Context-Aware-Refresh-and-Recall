"""Controllers for periodic and budgeted event-triggered guidance refresh.

The implementations in this module are planner independent.  They receive a
compact traffic context once per decision epoch and decide whether the runner
should reuse the current guidance artifact or refresh it.  The experimental
runner remains responsible for the mandatory cold-start refresh and for
measuring actual wall-clock costs.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TrafficContext:
    active_agent_density: float
    recent_throughput: float
    wait_ratio: float
    conflict_rate: float
    maximum_to_mean_edge_load: float
    edge_load_entropy: float
    opposite_direction_flow: float
    goal_hotspot_entropy: float
    cross_region_demand_ratio: float
    guidance_age: int
    goal_distribution_js_divergence_since_refresh: float
    edge_usage_distribution_drift_since_refresh: float
    throughput_ewma_drop: float
    last_refresh_wall_clock_cost: float
    recent_planning_time: float
    previous_refresh: bool = False


@dataclass(frozen=True)
class GuidanceAction:
    refresh: bool
    generator_id: str = "online_ggo"


@dataclass(frozen=True)
class WindowFeedback:
    start_step: int
    end_step: int
    completed_tasks: int
    agent_timesteps: int
    wait_agent_timesteps: int
    path_length: int
    shortest_path_length: int
    planning_seconds: float
    refresh_seconds: float
    budget_violations: int

    @property
    def throughput(self) -> float:
        duration = self.end_step - self.start_step
        if duration <= 0:
            raise ValueError("feedback window must have positive duration")
        return self.completed_tasks / duration

    def validate(self) -> None:
        if self.end_step <= self.start_step:
            raise ValueError("feedback window must have positive duration")
        nonnegative = {
            "completed_tasks": self.completed_tasks,
            "agent_timesteps": self.agent_timesteps,
            "wait_agent_timesteps": self.wait_agent_timesteps,
            "path_length": self.path_length,
            "shortest_path_length": self.shortest_path_length,
            "planning_seconds": self.planning_seconds,
            "refresh_seconds": self.refresh_seconds,
            "budget_violations": self.budget_violations,
        }
        for name, value in nonnegative.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.wait_agent_timesteps > self.agent_timesteps:
            raise ValueError("wait_agent_timesteps cannot exceed agent_timesteps")


class GuidanceController(Protocol):
    def reset(self, *, policy_seed: int) -> None: ...

    def select(self, context: TrafficContext, *, step: int) -> GuidanceAction: ...

    def observe(
        self,
        context: TrafficContext,
        action: GuidanceAction,
        feedback: WindowFeedback,
        next_context: TrafficContext,
    ) -> None: ...


def post_bootstrap_publication_budget(
    num_scored_windows: int, fraction: float
) -> int:
    """Return the exact publication quota after the mandatory bootstrap.

    A run with ``N`` scored windows has decision indices ``0..N-1``.  Index 0
    installs the common bootstrap graph and is excluded from the budget, so
    exactly ``K=N-1`` decisions are budget eligible.
    """

    if isinstance(num_scored_windows, bool) or not isinstance(
        num_scored_windows, int
    ) or num_scored_windows < 1:
        raise ValueError("num_scored_windows must be a positive integer")
    if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError("publication fraction must be in [0, 1]")
    return math.ceil(fraction * (num_scored_windows - 1))


def exact_even_post_bootstrap_indices(
    num_scored_windows: int, publication_budget: int
) -> tuple[int, ...]:
    """Spread an exact integer quota over eligible decision indices.

    The integer accumulator publishes at eligible index ``d`` iff
    ``floor(d*B/K) > floor((d-1)*B/K)``.  It is deterministic, has no floating
    boundary ambiguity, never spends at bootstrap index 0, and returns exactly
    ``B`` indices.  The last eligible window is included whenever ``B>0``.
    """

    if isinstance(num_scored_windows, bool) or not isinstance(
        num_scored_windows, int
    ) or num_scored_windows < 1:
        raise ValueError("num_scored_windows must be a positive integer")
    if isinstance(publication_budget, bool) or not isinstance(
        publication_budget, int
    ):
        raise TypeError("publication_budget must be an integer")
    eligible = num_scored_windows - 1
    if not 0 <= publication_budget <= eligible:
        raise ValueError("publication_budget must lie in [0, N-1]")
    if publication_budget == 0:
        return ()
    return tuple(
        decision_index
        for decision_index in range(1, num_scored_windows)
        if (decision_index * publication_budget) // eligible
        > ((decision_index - 1) * publication_budget) // eligible
    )


class FixedController:
    """Registered fixed-action control used in every experiment."""

    def __init__(self, action: GuidanceAction) -> None:
        self._action = action

    def reset(self, *, policy_seed: int) -> None:
        del policy_seed

    def select(self, context: TrafficContext, *, step: int) -> GuidanceAction:
        del context, step
        return self._action

    def observe(
        self,
        context: TrafficContext,
        action: GuidanceAction,
        feedback: WindowFeedback,
        next_context: TrafficContext,
    ) -> None:
        del context, action, feedback, next_context


class PeriodicRefreshController:
    """Fixed-period Online GGO control used as the primary baseline family."""

    def __init__(self, period: int, *, generator_id: str = "online_ggo") -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self.generator_id = generator_id
        self._last_period_bucket = -1

    def reset(self, *, policy_seed: int) -> None:
        del policy_seed
        self._last_period_bucket = -1

    def select(self, context: TrafficContext, *, step: int) -> GuidanceAction:
        del context
        if step < 0:
            raise ValueError("step must be non-negative")
        bucket = step // self.period
        refresh = bucket > self._last_period_bucket
        if refresh:
            # Anchor the cadence to episode time.  If a runner skips an exact
            # boundary, the next call refreshes without permanently drifting
            # all later refreshes.
            self._last_period_bucket = bucket
        return GuidanceAction(refresh=refresh, generator_id=self.generator_id)

    def observe(
        self,
        context: TrafficContext,
        action: GuidanceAction,
        feedback: WindowFeedback,
        next_context: TrafficContext,
    ) -> None:
        del context, action, feedback, next_context


class _RefreshTokenBucket:
    """Hard count-rate guard used alongside the wall-clock dual constraint."""

    def __init__(self, fraction: float | None, *, capacity: float = 2.0) -> None:
        if fraction is not None and not (0.0 < fraction <= 1.0):
            raise ValueError("max_refresh_fraction must be in (0, 1]")
        if capacity < 1.0:
            raise ValueError("refresh token capacity must be at least one")
        self.fraction = fraction
        self.capacity = capacity
        self.tokens = 1.0 if fraction is None else 1.0 - fraction

    def reset(self) -> None:
        self.tokens = 1.0 if self.fraction is None else 1.0 - self.fraction

    def begin_epoch(self) -> None:
        if self.fraction is not None:
            self.tokens = min(self.capacity, self.tokens + self.fraction)

    @property
    def allowed(self) -> bool:
        return self.fraction is None or self.tokens >= 1.0 - 1e-12

    def consume(self) -> None:
        if self.fraction is not None:
            if not self.allowed:
                raise RuntimeError("refresh token consumed without available budget")
            self.tokens -= 1.0


class DriftThresholdController:
    """Simple event-trigger baseline using workload/traffic distribution drift."""

    def __init__(
        self,
        threshold: float,
        *,
        max_refresh_fraction: float | None = None,
        refresh_burst_capacity: float = 2.0,
        minimum_gap_steps: int = 0,
        use_edge_drift: bool = False,
        generator_id: str = "smoke_cached_heat",
    ) -> None:
        if threshold < 0:
            raise ValueError("threshold must be non-negative")
        if minimum_gap_steps < 0:
            raise ValueError("minimum_gap_steps must be non-negative")
        self.threshold = threshold
        self.minimum_gap_steps = minimum_gap_steps
        self.use_edge_drift = use_edge_drift
        self.generator_id = generator_id
        self._bucket = _RefreshTokenBucket(
            max_refresh_fraction, capacity=refresh_burst_capacity
        )
        self._last_refresh_step: int | None = None

    def reset(self, *, policy_seed: int) -> None:
        del policy_seed
        self._bucket.reset()
        self._last_refresh_step = None

    def select(self, context: TrafficContext, *, step: int) -> GuidanceAction:
        if step < 0:
            raise ValueError("step must be non-negative")
        self._bucket.begin_epoch()
        cold_start = self._last_refresh_step is None
        gap_ok = cold_start or step - self._last_refresh_step >= self.minimum_gap_steps
        drift = context.goal_distribution_js_divergence_since_refresh
        if self.use_edge_drift:
            drift = max(
                drift, context.edge_usage_distribution_drift_since_refresh
            )
        refresh = self._bucket.allowed and gap_ok and (cold_start or drift >= self.threshold)
        if refresh:
            self._bucket.consume()
            self._last_refresh_step = step
        return GuidanceAction(refresh=refresh, generator_id=self.generator_id)

    def observe(
        self,
        context: TrafficContext,
        action: GuidanceAction,
        feedback: WindowFeedback,
        next_context: TrafficContext,
    ) -> None:
        del context, action, next_context
        feedback.validate()


def _feature_vector(context: TrafficContext) -> tuple[float, ...]:
    """Stable, bounded feature order for the smoke and public-backbone adapters."""

    def unit(value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("traffic context contains a non-finite value")
        return max(0.0, min(1.0, value))

    return (
        1.0,
        unit(context.active_agent_density),
        math.tanh(max(0.0, context.recent_throughput)),
        unit(context.wait_ratio),
        unit(context.conflict_rate),
        unit(context.goal_distribution_js_divergence_since_refresh),
        unit(context.edge_usage_distribution_drift_since_refresh),
        math.tanh(max(0.0, context.guidance_age) / 25.0),
        math.tanh(max(0.0, context.throughput_ewma_drop)),
        unit(context.cross_region_demand_ratio),
    )


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small dense linear system with pivoted Gauss-Jordan elimination."""

    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular contextual-bandit covariance matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            augmented[row] = [
                current - factor * base
                for current, base in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


@dataclass(frozen=True)
class _BanditObservation:
    refresh: bool
    features: tuple[float, ...]
    reward: float


class BudgetedEventTriggeredController:
    """Sliding-window LinUCB refresh controller with online budget control.

    Throughput is modelled separately for refresh and reuse.  The selection
    rule compares optimistic reward estimates and subtracts the dual-weighted
    predicted refresh cost.  A token bucket is an optional hard guard for the
    small pilot; the primal-dual term uses measured wall-clock seconds.
    """

    def __init__(
        self,
        *,
        sliding_window: int = 30,
        exploration_alpha: float = 0.35,
        ridge: float = 1.0,
        budget_seconds_per_window: float | None = None,
        dual_step_size: float = 0.05,
        hysteresis_margin: float = 0.01,
        max_refresh_fraction: float | None = None,
        refresh_burst_capacity: float = 2.0,
        minimum_gap_steps: int = 0,
        safety_goal_js_threshold: float | None = 0.12,
        safety_wait_threshold: float | None = 0.30,
        generator_id: str = "smoke_cached_heat",
    ) -> None:
        if sliding_window <= 1:
            raise ValueError("sliding_window must exceed one")
        if exploration_alpha < 0 or ridge <= 0 or dual_step_size < 0:
            raise ValueError("invalid LinUCB or dual hyperparameter")
        if budget_seconds_per_window is not None and budget_seconds_per_window <= 0:
            raise ValueError("budget_seconds_per_window must be positive")
        if minimum_gap_steps < 0:
            raise ValueError("minimum_gap_steps must be non-negative")
        if safety_goal_js_threshold is not None and safety_goal_js_threshold < 0:
            raise ValueError("safety_goal_js_threshold must be non-negative")
        if safety_wait_threshold is not None and safety_wait_threshold < 0:
            raise ValueError("safety_wait_threshold must be non-negative")
        self.sliding_window = sliding_window
        self.exploration_alpha = exploration_alpha
        self.ridge = ridge
        self.budget_seconds_per_window = budget_seconds_per_window
        self.dual_step_size = dual_step_size
        self.hysteresis_margin = hysteresis_margin
        self.minimum_gap_steps = minimum_gap_steps
        self.safety_goal_js_threshold = safety_goal_js_threshold
        self.safety_wait_threshold = safety_wait_threshold
        self.generator_id = generator_id
        self._history: deque[_BanditObservation] = deque()
        self._bucket = _RefreshTokenBucket(
            max_refresh_fraction, capacity=refresh_burst_capacity
        )
        self._rng = random.Random(0)
        self._last_refresh_step: int | None = None
        self._cost_ewma: float | None = None
        self.dual_lambda = 0.0
        self.last_scores: dict[str, float] = {"reuse": 0.0, "refresh": 0.0}
        self._inverse_covariance: list[list[float]] | None = None
        self._target: list[float] | None = None

    def reset(self, *, policy_seed: int) -> None:
        self._history.clear()
        self._bucket.reset()
        self._rng.seed(policy_seed)
        self._last_refresh_step = None
        self._cost_ewma = None
        self.dual_lambda = 0.0
        self.last_scores = {"reuse": 0.0, "refresh": 0.0}
        self._inverse_covariance = None
        self._target = None

    @staticmethod
    def _action_features(
        refresh: bool, features: tuple[float, ...]
    ) -> tuple[float, ...]:
        return features + tuple(value if refresh else 0.0 for value in features)

    def _scores(self, features: tuple[float, ...]) -> tuple[float, float]:
        # Shared baseline + refresh-treatment interactions.  A separate model
        # per action badly underuses sparse refresh data; this joint form lets
        # the abundant reuse windows identify the traffic baseline while the
        # interaction block estimates marginal refresh value.
        self._ensure_model(features)
        inverse = self._inverse_covariance
        target = self._target
        assert inverse is not None and target is not None
        dimension = len(target)
        theta = [
            sum(inverse[row][column] * target[column] for column in range(dimension))
            for row in range(dimension)
        ]

        def score(refresh: bool) -> float:
            action_features = self._action_features(refresh, features)
            projected = [
                sum(
                    inverse[row][column] * action_features[column]
                    for column in range(dimension)
                )
                for row in range(dimension)
            ]
            mean = sum(
                weight * value for weight, value in zip(theta, action_features)
            )
            variance = sum(
                value * projection
                for value, projection in zip(action_features, projected)
            )
            return mean + self.exploration_alpha * math.sqrt(max(0.0, variance))

        return score(False), score(True)

    def _ensure_model(self, features: tuple[float, ...]) -> None:
        if self._inverse_covariance is not None:
            return
        dimension = len(self._action_features(False, features))
        self._inverse_covariance = [
            [1.0 / self.ridge if row == column else 0.0 for column in range(dimension)]
            for row in range(dimension)
        ]
        self._target = [0.0] * dimension

    def _apply_observation(
        self, observation: _BanditObservation, *, sign: float
    ) -> bool:
        """Apply a rank-one add/remove via Sherman-Morrison."""

        self._ensure_model(observation.features)
        inverse = self._inverse_covariance
        target = self._target
        assert inverse is not None and target is not None
        vector = self._action_features(observation.refresh, observation.features)
        dimension = len(vector)
        projected = [
            sum(inverse[row][column] * vector[column] for column in range(dimension))
            for row in range(dimension)
        ]
        quadratic = sum(value * projection for value, projection in zip(vector, projected))
        denominator = 1.0 + sign * quadratic
        if denominator <= 1e-9:
            return False
        for row in range(dimension):
            for column in range(dimension):
                inverse[row][column] -= (
                    sign * projected[row] * projected[column] / denominator
                )
            target[row] += sign * observation.reward * vector[row]
        return True

    def _rebuild_model(self) -> None:
        observations = list(self._history)
        self._inverse_covariance = None
        self._target = None
        if not observations:
            return
        self._ensure_model(observations[0].features)
        for observation in observations:
            if not self._apply_observation(observation, sign=1.0):
                raise RuntimeError("failed to rebuild sliding-window LinUCB state")

    def select(self, context: TrafficContext, *, step: int) -> GuidanceAction:
        if step < 0:
            raise ValueError("step must be non-negative")
        features = _feature_vector(context)
        self._bucket.begin_epoch()
        reuse_score, refresh_score = self._scores(features)

        predicted_cost = self._cost_ewma
        if predicted_cost is None:
            predicted_cost = context.last_refresh_wall_clock_cost
        if self.budget_seconds_per_window is not None:
            if predicted_cost <= 0:
                predicted_cost = self.budget_seconds_per_window
            refresh_score -= self.dual_lambda * (
                predicted_cost / self.budget_seconds_per_window
            )

        self.last_scores = {"reuse": reuse_score, "refresh": refresh_score}
        cold_start = self._last_refresh_step is None
        gap_ok = cold_start or step - self._last_refresh_step >= self.minimum_gap_steps
        safety_trigger = False
        if self.safety_goal_js_threshold is not None:
            safety_trigger = (
                context.goal_distribution_js_divergence_since_refresh
                >= self.safety_goal_js_threshold
            )
        if self.safety_wait_threshold is not None:
            safety_trigger = safety_trigger or context.wait_ratio >= self.safety_wait_threshold
        refresh = (
            cold_start
            or safety_trigger
            or refresh_score > reuse_score + self.hysteresis_margin
        )
        refresh = refresh and gap_ok and self._bucket.allowed

        # Exact ties after both actions have observations are broken by the
        # policy RNG, not by execution randomness, preserving paired scenarios.
        if (
            not cold_start
            and gap_ok
            and self._bucket.allowed
            and abs(refresh_score - reuse_score - self.hysteresis_margin) < 1e-12
        ):
            refresh = bool(self._rng.getrandbits(1))

        if refresh:
            self._bucket.consume()
            self._last_refresh_step = step
        return GuidanceAction(refresh=refresh, generator_id=self.generator_id)

    def observe(
        self,
        context: TrafficContext,
        action: GuidanceAction,
        feedback: WindowFeedback,
        next_context: TrafficContext,
    ) -> None:
        del next_context
        feedback.validate()
        # The first window starts from a mandatory common bootstrap artifact;
        # its low warm-up throughput is not evidence about refresh value.
        is_bootstrap_window = feedback.start_step == 0 and not self._history
        if not is_bootstrap_window:
            observation = _BanditObservation(
                refresh=action.refresh,
                features=_feature_vector(context),
                reward=feedback.throughput,
            )
            if len(self._history) >= self.sliding_window:
                removed = self._history.popleft()
                if not self._apply_observation(removed, sign=-1.0):
                    self._rebuild_model()
            self._history.append(observation)
            if not self._apply_observation(observation, sign=1.0):
                raise RuntimeError("failed to update sliding-window LinUCB state")
        if action.refresh and feedback.refresh_seconds > 0:
            if self._cost_ewma is None:
                self._cost_ewma = feedback.refresh_seconds
            else:
                self._cost_ewma = 0.8 * self._cost_ewma + 0.2 * feedback.refresh_seconds
        if self.budget_seconds_per_window is not None:
            normalized_spend = feedback.refresh_seconds / self.budget_seconds_per_window
            self.dual_lambda = max(
                0.0,
                self.dual_lambda + self.dual_step_size * (normalized_spend - 1.0),
            )
