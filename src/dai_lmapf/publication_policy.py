"""Exact-count causal publication policies for the fixed-tape benchmark.

The mandatory guidance bootstrap is outside this module.  ``total_epochs``
is the number of scored decision windows and ``budget`` is the exact number
of *additional* generator calls allowed across those windows.  Every policy
therefore exposes the same hard quota and returns a complete audit record for
each requested/accepted publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
import math
import random
from typing import Iterable


def evenly_spaced_indices(total_epochs: int, budget: int) -> tuple[int, ...]:
    """Place exactly ``budget`` calls as evenly as possible over the horizon.

    Calls are placed at the end of equal-sized prefix buckets.  For
    ``total_epochs=100`` and ``budget=25`` this is ``3, 7, ..., 99``: exactly
    one additional publication per four 20-step windows.
    """

    if total_epochs <= 0:
        raise ValueError("total_epochs must be positive")
    if budget < 0 or budget > total_epochs:
        raise ValueError("budget must lie in [0, total_epochs]")
    if budget == 0:
        return ()
    indices = tuple(
        ((rank * total_epochs + budget - 1) // budget) - 1
        for rank in range(1, budget + 1)
    )
    if len(set(indices)) != budget or indices[-1] >= total_epochs:
        raise RuntimeError("even schedule construction violated its quota")
    return indices


@dataclass(frozen=True)
class PublicationDecision:
    epoch: int
    requested: bool
    accepted: bool
    reason: str
    score: float | None
    threshold: float | None
    spent_before: int
    spent_after: int
    budget: int
    remaining_epochs_after: int


@dataclass(frozen=True)
class ContextMemoryDecision:
    """Auditable switch decision for the three-action memory controller."""

    epoch: int
    requested: bool
    accepted: bool
    reason: str
    score: float
    minimum_score: float
    threshold: float | None
    spent_before: int
    spent_after: int
    budget: int
    remaining_epochs_after: int
    triggered: bool
    action_available: bool
    route_mature: bool
    maintenance_due: bool
    persistence_count: int
    persistence_required: int


@dataclass(frozen=True)
class CausalBlockDecision:
    """Auditable decision for one-token-per-bucket causal publication."""

    epoch: int
    requested: bool
    accepted: bool
    reason: str
    score: float
    threshold: float | None
    spent_before: int
    spent_after: int
    budget: int
    remaining_epochs_after: int
    bucket_index: int
    bucket_start: int
    bucket_end: int
    earliest_event_epoch: int
    route_mature: bool
    max_advance: int
    min_gap: int


class CausalBlockPublicationPolicy:
    """Spend exactly one token in each even-quota bucket.

    The end of every bucket is the corresponding exact-even publication
    epoch.  A causal score may move that token earlier by at most
    ``max_advance`` epochs.  It can never move a token to a later bucket, so
    exact quota satisfaction does not rely on a burst of end-of-horizon
    feasibility publications.
    """

    def __init__(
        self,
        *,
        total_epochs: int,
        budget: int,
        score_quantile: float = 0.75,
        max_advance: int = 2,
        min_gap: int = 2,
        minimum_history: int = 4,
    ) -> None:
        if total_epochs <= 0:
            raise ValueError("total_epochs must be positive")
        if budget <= 0 or budget > total_epochs:
            raise ValueError("causal block budget must lie in [1, total_epochs]")
        if not 0.0 <= score_quantile <= 1.0:
            raise ValueError("score_quantile must lie in [0, 1]")
        if max_advance < 0 or min_gap < 0 or minimum_history < 0:
            raise ValueError(
                "max_advance, min_gap, and minimum_history must be non-negative"
            )

        self.total_epochs = int(total_epochs)
        self.budget = int(budget)
        self.score_quantile = float(score_quantile)
        self.max_advance = int(max_advance)
        self.min_gap = int(min_gap)
        self.minimum_history = int(minimum_history)
        self.bucket_ends = evenly_spaced_indices(total_epochs, budget)
        self.bucket_starts = (0,) + tuple(
            endpoint + 1 for endpoint in self.bucket_ends[:-1]
        )
        self.epoch = 0
        self.spent = 0
        self.score_history: list[float] = []
        self.decisions: list[CausalBlockDecision] = []
        self._bucket_spent = [False] * budget
        self._bucket_publication_epochs: list[int | None] = [None] * budget
        self._last_publication_epoch: int | None = None

    @staticmethod
    def _quantile(values: list[float], probability: float) -> float:
        if not values:
            return math.inf
        ordered = sorted(values)
        position = probability * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    @property
    def bucket_publication_epochs(self) -> tuple[int | None, ...]:
        return tuple(self._bucket_publication_epochs)

    def select(
        self, *, score: float, route_mature: bool
    ) -> CausalBlockDecision:
        if self.epoch >= self.total_epochs:
            raise RuntimeError("publication policy was queried past the horizon")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("causal block score must be numeric")
        if not math.isfinite(float(score)):
            raise ValueError("causal block score must be finite")
        if not isinstance(route_mature, bool):
            raise TypeError("route_mature must be boolean")

        epoch = self.epoch
        bucket_index = bisect_left(self.bucket_ends, epoch)
        if bucket_index >= self.budget:
            raise RuntimeError("causal block epoch lies outside its quota buckets")
        bucket_start = self.bucket_starts[bucket_index]
        bucket_end = self.bucket_ends[bucket_index]
        earliest_event_epoch = max(bucket_start, bucket_end - self.max_advance)
        spent_before = self.spent
        enough_history = len(self.score_history) >= self.minimum_history
        threshold = (
            self._quantile(self.score_history, self.score_quantile)
            if enough_history
            else None
        )
        gap_ok = (
            self._last_publication_epoch is None
            or epoch - self._last_publication_epoch >= self.min_gap
        )
        token_spent = self._bucket_spent[bucket_index]
        at_bucket_end = epoch == bucket_end
        in_event_window = earliest_event_epoch <= epoch < bucket_end
        event_request = bool(
            not token_spent
            and in_event_window
            and enough_history
            and route_mature
            and gap_ok
            and float(score) >= float(threshold)
        )
        forced_request = bool(not token_spent and at_bucket_end)
        requested = event_request or forced_request

        if event_request:
            reason = "causal_block_event"
        elif forced_request:
            reason = "causal_block_bucket_end"
        elif token_spent:
            reason = "causal_block_token_spent"
        elif epoch < earliest_event_epoch:
            reason = "causal_block_before_event_window"
        elif not enough_history:
            reason = "causal_block_history_warmup"
        elif not route_mature:
            reason = "causal_block_maturity_guard"
        elif not gap_ok:
            reason = "causal_block_min_gap"
        else:
            reason = "causal_block_below_threshold"

        accepted = requested
        if accepted:
            if self.spent >= self.budget or token_spent:
                raise RuntimeError("causal block hard-budget invariant failed")
            self._bucket_spent[bucket_index] = True
            self._bucket_publication_epochs[bucket_index] = epoch
            self._last_publication_epoch = epoch
            self.spent += 1
        self.score_history.append(float(score))
        self.epoch += 1

        decision = CausalBlockDecision(
            epoch=epoch,
            requested=requested,
            accepted=accepted,
            reason=reason,
            score=float(score),
            threshold=threshold,
            spent_before=spent_before,
            spent_after=self.spent,
            budget=self.budget,
            remaining_epochs_after=self.total_epochs - self.epoch,
            bucket_index=bucket_index,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            earliest_event_epoch=earliest_event_epoch,
            route_mature=route_mature,
            max_advance=self.max_advance,
            min_gap=self.min_gap,
        )
        self.decisions.append(decision)
        return decision

    def finalize(self) -> None:
        if self.epoch != self.total_epochs:
            raise RuntimeError(
                f"policy observed {self.epoch}/{self.total_epochs} epochs"
            )
        if self.spent != self.budget or not all(self._bucket_spent):
            raise RuntimeError(
                f"causal block policy spent {self.spent}/{self.budget} publications"
            )
        if any(epoch is None for epoch in self._bucket_publication_epochs):
            raise RuntimeError("a causal block bucket lacks a publication")


class CappedScorePublicationPolicy:
    """Causal score trigger with an upper budget and permission to abstain.

    Unlike the exact-count policy, this deployment-oriented controller never
    catches up and never spends a quota merely to make the final count equal
    the cap.  A publication therefore requires a strictly exceptional score,
    a minimum inter-publication gap, and enough remaining windows to observe
    its effect.
    """

    def __init__(
        self,
        *,
        total_epochs: int,
        budget: int,
        score_quantile: float = 0.75,
        minimum_history: int = 4,
        min_gap: int = 2,
        minimum_effect_epochs: int = 3,
    ) -> None:
        if total_epochs <= 0:
            raise ValueError("total_epochs must be positive")
        if budget < 0 or budget > total_epochs:
            raise ValueError("budget must lie in [0, total_epochs]")
        if not 0.0 <= score_quantile <= 1.0:
            raise ValueError("score_quantile must lie in [0, 1]")
        if min(minimum_history, min_gap, minimum_effect_epochs) < 0:
            raise ValueError("capped-score guard parameters must be non-negative")
        if minimum_effect_epochs > total_epochs:
            raise ValueError("minimum effect horizon exceeds total epochs")
        self.total_epochs = int(total_epochs)
        self.budget = int(budget)
        self.score_quantile = float(score_quantile)
        self.minimum_history = int(minimum_history)
        self.min_gap = int(min_gap)
        self.minimum_effect_epochs = int(minimum_effect_epochs)
        self.epoch = 0
        self.spent = 0
        self.score_history: list[float] = []
        self.decisions: list[PublicationDecision] = []
        self._last_publication_epoch: int | None = None

    @staticmethod
    def _quantile(values: list[float], probability: float) -> float:
        ordered = sorted(values)
        position = probability * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    def select(self, *, score: float) -> PublicationDecision:
        if self.epoch >= self.total_epochs:
            raise RuntimeError("publication policy was queried past the horizon")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("capped publication score must be numeric")
        if not math.isfinite(float(score)):
            raise ValueError("capped publication score must be finite")

        epoch = self.epoch
        spent_before = self.spent
        enough_history = len(self.score_history) >= self.minimum_history
        threshold = (
            self._quantile(self.score_history, self.score_quantile)
            if enough_history
            else None
        )
        gap_ok = (
            self._last_publication_epoch is None
            or epoch - self._last_publication_epoch >= self.min_gap
        )
        effect_ok = self.total_epochs - epoch >= self.minimum_effect_epochs
        under_cap = self.spent < self.budget
        requested = bool(
            enough_history
            and gap_ok
            and effect_ok
            and under_cap
            and float(score) > float(threshold)
        )
        if requested:
            reason = "capped_causal_score"
        elif not enough_history:
            reason = "capped_history_warmup"
        elif not gap_ok:
            reason = "capped_min_gap"
        elif not effect_ok:
            reason = "capped_effect_horizon"
        elif not under_cap:
            reason = "capped_budget_exhausted"
        else:
            reason = "capped_below_threshold"

        if requested:
            self.spent += 1
            self._last_publication_epoch = epoch
        self.score_history.append(float(score))
        self.epoch += 1
        decision = PublicationDecision(
            epoch=epoch,
            requested=requested,
            accepted=requested,
            reason=reason,
            score=float(score),
            threshold=threshold,
            spent_before=spent_before,
            spent_after=self.spent,
            budget=self.budget,
            remaining_epochs_after=self.total_epochs - self.epoch,
        )
        self.decisions.append(decision)
        return decision

    def finalize(self) -> None:
        if self.epoch != self.total_epochs:
            raise RuntimeError(
                f"policy observed {self.epoch}/{self.total_epochs} epochs"
            )
        if not 0 <= self.spent <= self.budget:
            raise RuntimeError("capped publication policy exceeded its budget")
        if sum(decision.accepted for decision in self.decisions) != self.spent:
            raise RuntimeError("decision log and capped publication count disagree")


class ContextMemoryPublicationPolicy:
    """Causal at-most switch policy used by context guidance memory.

    The policy owns only the *switch* cap.  The caller determines whether the
    current context calls for a new generation or a recall and reports whether
    an effective action is available.  No quota is spent for a hold, a guard,
    or an end-of-horizon catch-up.
    """

    def __init__(
        self,
        *,
        total_epochs: int,
        budget: int,
        score_quantile: float = 0.75,
        minimum_history: int = 4,
        min_gap: int = 2,
        minimum_effect_epochs: int = 3,
        persistence: int = 1,
        minimum_score: float = 0.10,
    ) -> None:
        if total_epochs <= 0:
            raise ValueError("total_epochs must be positive")
        if budget < 0 or budget > total_epochs:
            raise ValueError("budget must lie in [0, total_epochs]")
        if not 0.0 <= score_quantile <= 1.0:
            raise ValueError("score_quantile must lie in [0, 1]")
        if min(
            minimum_history,
            min_gap,
            minimum_effect_epochs,
            persistence,
        ) < 0:
            raise ValueError("context-memory guard parameters must be non-negative")
        if persistence < 1:
            raise ValueError("persistence must be at least one")
        if not math.isfinite(float(minimum_score)) or minimum_score < 0.0:
            raise ValueError("minimum_score must be finite and non-negative")
        if minimum_effect_epochs > total_epochs:
            raise ValueError("minimum effect horizon exceeds total epochs")
        self.total_epochs = int(total_epochs)
        self.budget = int(budget)
        self.score_quantile = float(score_quantile)
        self.minimum_history = int(minimum_history)
        self.min_gap = int(min_gap)
        self.minimum_effect_epochs = int(minimum_effect_epochs)
        self.persistence = int(persistence)
        self.minimum_score = float(minimum_score)
        self.epoch = 0
        self.spent = 0
        self.score_history: list[float] = []
        self.decisions: list[ContextMemoryDecision] = []
        self._last_switch_epoch: int | None = None
        self._persistence_count = 0

    @staticmethod
    def _quantile(values: list[float], probability: float) -> float:
        ordered = sorted(values)
        position = probability * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    def select(
        self,
        *,
        score: float,
        action_available: bool,
        route_mature: bool,
        maintenance_due: bool = False,
    ) -> ContextMemoryDecision:
        if self.epoch >= self.total_epochs:
            raise RuntimeError("publication policy was queried past the horizon")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("context-memory score must be numeric")
        if not math.isfinite(float(score)):
            raise ValueError("context-memory score must be finite")
        if not isinstance(action_available, bool):
            raise TypeError("action_available must be boolean")
        if not isinstance(route_mature, bool):
            raise TypeError("route_mature must be boolean")
        if not isinstance(maintenance_due, bool):
            raise TypeError("maintenance_due must be boolean")

        epoch = self.epoch
        spent_before = self.spent
        enough_history = len(self.score_history) >= self.minimum_history
        threshold = (
            self._quantile(self.score_history, self.score_quantile)
            if enough_history
            else None
        )
        above_absolute_gate = float(score) >= self.minimum_score
        exceptional = bool(
            enough_history
            and above_absolute_gate
            and float(score) > float(threshold)
        )
        self._persistence_count = self._persistence_count + 1 if exceptional else 0
        persistence_count = self._persistence_count
        persistent = self._persistence_count >= self.persistence
        event_ready = exceptional and persistent
        triggered = maintenance_due or event_ready
        gap_ok = (
            self._last_switch_epoch is None
            or epoch - self._last_switch_epoch >= self.min_gap
        )
        effect_ok = self.total_epochs - epoch >= self.minimum_effect_epochs
        under_cap = self.spent < self.budget
        accepted = bool(
            triggered
            and action_available
            and route_mature
            and gap_ok
            and effect_ok
            and under_cap
        )
        if accepted and maintenance_due:
            reason = "context_memory_maintenance"
        elif accepted:
            reason = "context_memory_switch"
        elif maintenance_due and not route_mature:
            reason = "context_memory_maturity_guard"
        elif maintenance_due and not gap_ok:
            reason = "context_memory_min_gap"
        elif maintenance_due and not effect_ok:
            reason = "context_memory_effect_horizon"
        elif maintenance_due and not under_cap:
            reason = "context_memory_budget_exhausted"
        elif maintenance_due and not action_available:
            reason = "context_memory_active_context_match"
        elif not enough_history:
            reason = "context_memory_history_warmup"
        elif not above_absolute_gate:
            reason = "context_memory_below_absolute_gate"
        elif not exceptional:
            reason = "context_memory_below_threshold"
        elif not persistent:
            reason = "context_memory_persistence"
        elif not action_available:
            reason = "context_memory_active_context_match"
        elif not route_mature:
            reason = "context_memory_maturity_guard"
        elif not gap_ok:
            reason = "context_memory_min_gap"
        elif not effect_ok:
            reason = "context_memory_effect_horizon"
        elif not under_cap:
            reason = "context_memory_budget_exhausted"
        else:  # pragma: no cover - defensive completeness
            raise RuntimeError("context-memory decision has no reason")

        if accepted:
            self.spent += 1
            self._last_switch_epoch = epoch
            self._persistence_count = 0
        self.score_history.append(float(score))
        self.epoch += 1
        decision = ContextMemoryDecision(
            epoch=epoch,
            requested=accepted,
            accepted=accepted,
            reason=reason,
            score=float(score),
            minimum_score=self.minimum_score,
            threshold=threshold,
            spent_before=spent_before,
            spent_after=self.spent,
            budget=self.budget,
            remaining_epochs_after=self.total_epochs - self.epoch,
            triggered=triggered,
            action_available=action_available,
            route_mature=route_mature,
            maintenance_due=maintenance_due,
            persistence_count=persistence_count,
            persistence_required=self.persistence,
        )
        self.decisions.append(decision)
        return decision

    def finalize(self) -> None:
        if self.epoch != self.total_epochs:
            raise RuntimeError(
                f"policy observed {self.epoch}/{self.total_epochs} epochs"
            )
        if not 0 <= self.spent <= self.budget:
            raise RuntimeError("context-memory policy exceeded its switch cap")
        if sum(decision.accepted for decision in self.decisions) != self.spent:
            raise RuntimeError("context-memory decision log disagrees with switch count")


class ExactBudgetPublicationPolicy:
    """Hard-quota schedule or online score policy with deterministic pacing."""

    SCHEDULE_METHODS = {"bootstrap_only", "always", "even", "random"}
    SCORE_METHODS = {"js", "throughput_drop", "proposed", "proposed_no_cohort"}

    def __init__(
        self,
        *,
        method: str,
        total_epochs: int,
        budget: int,
        policy_seed: int,
        pacing_slack: int = 2,
        minimum_history: int = 4,
    ) -> None:
        if method not in self.SCHEDULE_METHODS | self.SCORE_METHODS:
            raise ValueError(f"unknown publication policy {method!r}")
        if total_epochs <= 0:
            raise ValueError("total_epochs must be positive")
        if budget < 0 or budget > total_epochs:
            raise ValueError("budget must lie in [0, total_epochs]")
        if pacing_slack < 0 or minimum_history < 0:
            raise ValueError("pacing_slack and minimum_history must be non-negative")
        if method == "bootstrap_only" and budget != 0:
            raise ValueError("bootstrap_only requires zero post-bootstrap budget")
        if method == "always" and budget != total_epochs:
            raise ValueError("always requires one call per epoch")

        self.method = method
        self.total_epochs = int(total_epochs)
        self.budget = int(budget)
        self.policy_seed = int(policy_seed)
        self.pacing_slack = int(pacing_slack)
        self.minimum_history = int(minimum_history)
        self.epoch = 0
        self.spent = 0
        self.score_history: list[float] = []
        self.decisions: list[PublicationDecision] = []

        if method == "even":
            schedule: Iterable[int] = evenly_spaced_indices(total_epochs, budget)
        elif method == "random":
            rng = random.Random(policy_seed)
            schedule = sorted(rng.sample(range(total_epochs), budget))
        elif method == "always":
            schedule = range(total_epochs)
        else:
            schedule = ()
        self._schedule = frozenset(schedule)

    @staticmethod
    def _quantile(values: list[float], probability: float) -> float:
        if not values:
            return math.inf
        ordered = sorted(values)
        position = probability * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    def select(self, *, score: float | None = None) -> PublicationDecision:
        if self.epoch >= self.total_epochs:
            raise RuntimeError("publication policy was queried past the horizon")
        if score is not None and (not isinstance(score, (int, float)) or not math.isfinite(score)):
            raise ValueError("publication score must be finite")
        if self.method in self.SCORE_METHODS and score is None:
            raise ValueError(f"score policy {self.method!r} requires a score")

        epoch = self.epoch
        spent_before = self.spent
        remaining_including_current = self.total_epochs - epoch
        quota_remaining = self.budget - self.spent
        if quota_remaining < 0 or quota_remaining > remaining_including_current:
            raise RuntimeError("publication quota is no longer feasible")

        threshold: float | None = None
        reason = "reuse"
        if self.method in self.SCHEDULE_METHODS:
            requested = epoch in self._schedule
            reason = "registered_schedule" if requested else "registered_reuse"
        else:
            # The lower/upper prefix envelope permits event-driven movement by
            # ``pacing_slack`` calls while preventing both early exhaustion
            # and a pathological all-at-the-end policy.  The final feasibility
            # rule makes the exact quota unavoidable.
            target_floor = ((epoch + 1) * self.budget) // self.total_epochs
            target_ceil = math.ceil(
                ((epoch + 1) * self.budget) / self.total_epochs
            )
            lower = max(0, target_floor - self.pacing_slack)
            upper = min(self.budget, target_ceil + self.pacing_slack)
            must_publish = quota_remaining == remaining_including_current
            catch_up = self.spent < lower
            enough_history = len(self.score_history) >= self.minimum_history
            threshold = self._quantile(
                self.score_history, 1.0 - self.budget / self.total_epochs
            )
            event_request = (
                quota_remaining > 0
                and self.spent < upper
                and enough_history
                and float(score) >= threshold
            )
            requested = bool(must_publish or catch_up or event_request)
            if must_publish:
                reason = "quota_feasibility"
            elif catch_up:
                reason = "pacing_catch_up"
            elif event_request:
                reason = "causal_score"
            elif self.spent >= upper:
                reason = "pacing_upper_guard"
            elif not enough_history:
                reason = "history_warmup"
            else:
                reason = "below_causal_threshold"

        accepted = bool(requested and self.spent < self.budget)
        if accepted:
            self.spent += 1
        elif requested:
            reason = "hard_budget_guard"
        if score is not None:
            self.score_history.append(float(score))
        self.epoch += 1

        decision = PublicationDecision(
            epoch=epoch,
            requested=bool(requested),
            accepted=accepted,
            reason=reason,
            score=None if score is None else float(score),
            threshold=threshold,
            spent_before=spent_before,
            spent_after=self.spent,
            budget=self.budget,
            remaining_epochs_after=self.total_epochs - self.epoch,
        )
        self.decisions.append(decision)
        return decision

    def finalize(self) -> None:
        if self.epoch != self.total_epochs:
            raise RuntimeError(
                f"policy observed {self.epoch}/{self.total_epochs} epochs"
            )
        if self.spent != self.budget:
            raise RuntimeError(
                f"policy spent {self.spent}/{self.budget} publications"
            )
        if sum(decision.accepted for decision in self.decisions) != self.budget:
            raise RuntimeError("decision log and publication budget disagree")


__all__ = [
    "CappedScorePublicationPolicy",
    "CausalBlockDecision",
    "CausalBlockPublicationPolicy",
    "ExactBudgetPublicationPolicy",
    "PublicationDecision",
    "evenly_spaced_indices",
]
