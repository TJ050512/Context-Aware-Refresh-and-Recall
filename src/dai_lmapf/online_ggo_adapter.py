"""Thin, testable control layer for the official OnlineGGO environment.

The official ``TrafficFlowOnlineEnv`` advances the simulator only through
``env.step(action)``.  Reusing guidance therefore means passing the *same raw
action* again; skipping ``step`` would also skip tasks, motion, and reward.

This module deliberately does not import NumPy, Gymnasium, or OnlineGGO.  The
real environment can be injected on a compatible Linux machine, while unit
tests use a small fake backend on any Python >= 3.10 installation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import Any, Callable, Mapping, Protocol


RDLU = ("R", "D", "L", "U")


class OnlineGGOEnv(Protocol):
    """Gymnasium subset implemented by ``TrafficFlowOnlineEnv``."""

    def reset(
        self, *, seed: int | None = None, options: Mapping[str, Any] | None = None
    ) -> tuple[Any, Mapping[str, Any]]: ...

    def step(
        self, action: Any
    ) -> tuple[Any, Real, bool, bool, Mapping[str, Any]]: ...


class GuidanceGenerator(Protocol):
    """Frozen OnlineGGO-style generator mapping an observation to edge weights."""

    def __call__(self, observation: Any) -> Any: ...


class GuidanceOperation(str, Enum):
    """One action in the three-way guidance-memory interface."""

    HOLD = "hold"
    REACTIVATE = "reactivate"
    GENERATE = "generate"


@dataclass(frozen=True)
class GuidanceCommand:
    """Request a hold, a fresh generation, or a historical reactivation."""

    operation: GuidanceOperation
    target_generation_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, GuidanceOperation):
            raise TypeError("guidance command operation must be a GuidanceOperation")
        if self.operation is GuidanceOperation.REACTIVATE:
            if (
                isinstance(self.target_generation_id, bool)
                or not isinstance(self.target_generation_id, int)
                or self.target_generation_id <= 0
            ):
                raise ValueError(
                    "reactivation requires a positive target_generation_id"
                )
        elif self.target_generation_id is not None:
            raise ValueError(
                "only a reactivation command may specify target_generation_id"
            )

    @classmethod
    def hold(cls) -> "GuidanceCommand":
        return cls(GuidanceOperation.HOLD)

    @classmethod
    def generate(cls) -> "GuidanceCommand":
        return cls(GuidanceOperation.GENERATE)

    @classmethod
    def reactivate(cls, generation_id: int) -> "GuidanceCommand":
        return cls(
            GuidanceOperation.REACTIVATE,
            target_generation_id=generation_id,
        )


@dataclass(frozen=True)
class GuidanceRecord:
    """Immutable public metadata for one cached generated guidance tensor."""

    generation_id: int
    source: str
    raw_guidance_digest: str
    applied_guidance_digest: str | None


@dataclass
class _StoredGuidance:
    generation_id: int
    source: str
    action: Any
    raw_guidance_digest: str
    applied_guidance_digest: str | None = None


def uniform_action(height: int, width: int, value: float = 1.0) -> list[list[list[float]]]:
    """Return an official Python action with shape ``[4, H, W]``."""

    if height <= 0 or width <= 0:
        raise ValueError("height and width must be positive")
    if not math.isfinite(value):
        raise ValueError("uniform action value must be finite")
    return [
        [[float(value) for _ in range(width)] for _ in range(height)]
        for _ in range(4)
    ]


def _as_nested_action(action: Any) -> Any:
    # NumPy arrays expose ``tolist``; ordinary nested lists do not.  Keeping the
    # conversion local avoids a NumPy dependency in the research foundation.
    tolist = getattr(action, "tolist", None)
    return tolist() if callable(tolist) else action


def validate_official_action(action: Any, *, height: int, width: int) -> None:
    """Validate the raw action expected by ``TrafficFlowOnlineEnv.step``.

    The official Python tensor is channel-first ``[4, H, W]``.  Its current
    source labels those channels ``R,U,L,D`` when constructing traffic
    observations, while the C++ consumer indexes flattened weights ``R,D,L,U``.
    We preserve the official interface here and require the direction audit in
    the integration protocol instead of silently permuting channels.
    """

    nested = _as_nested_action(action)
    if isinstance(nested, (str, bytes)):
        raise TypeError("guidance action must be a numeric [4, H, W] tensor")
    try:
        channels = list(nested)
    except TypeError as exc:
        raise TypeError("guidance action must be iterable") from exc
    if len(channels) != 4:
        raise ValueError(f"guidance action needs 4 channels, received {len(channels)}")
    for channel_index, channel in enumerate(channels):
        try:
            rows = list(channel)
        except TypeError as exc:
            raise TypeError(f"channel {channel_index} must be iterable") from exc
        if len(rows) != height:
            raise ValueError(
                f"channel {channel_index} needs {height} rows, received {len(rows)}"
            )
        for row_index, row in enumerate(rows):
            try:
                values = list(row)
            except TypeError as exc:
                raise TypeError(
                    f"channel {channel_index}, row {row_index} must be iterable"
                ) from exc
            if len(values) != width:
                raise ValueError(
                    f"channel {channel_index}, row {row_index} needs {width} "
                    f"values, received {len(values)}"
                )
            for column_index, value in enumerate(values):
                if not isinstance(value, Real) or isinstance(value, bool):
                    raise TypeError(
                        "guidance action contains a non-numeric value at "
                        f"[{channel_index}, {row_index}, {column_index}]"
                    )
                if not math.isfinite(float(value)):
                    raise ValueError(
                        "guidance action contains a non-finite value at "
                        f"[{channel_index}, {row_index}, {column_index}]"
                    )


def action_digest(action: Any, *, height: int, width: int) -> str:
    """Return a stable digest of a validated channel-first action."""

    validate_official_action(action, height=height, width=width)
    nested = _as_nested_action(action)
    values = [
        float(value)
        for channel in nested
        for row in channel
        for value in row
    ]
    canonical = json.dumps(values, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OnlineGGOWindow:
    decision_index: int
    refreshed: bool
    guidance_version: int
    guidance_digest: str
    applied_guidance_digest: str | None
    reward: float
    terminated: bool
    truncated: bool
    generator_seconds: float
    simulator_seconds: float
    observation: Any
    info: Mapping[str, Any]
    requested_operation: GuidanceOperation = GuidanceOperation.HOLD
    operation: GuidanceOperation = GuidanceOperation.HOLD
    generation_id: int | None = None
    installation_version: int = 0
    reactivated: bool = False


class OnlineGGOAdapter:
    """Cache raw guidance actions while always advancing the official backend.

    ``refresh=True`` invokes the frozen generator once and installs its raw
    action.  ``refresh=False`` sends a defensive copy of the cached raw action.
    In both cases ``env.step`` is called exactly once.
    """

    def __init__(
        self,
        env: OnlineGGOEnv,
        generator: GuidanceGenerator,
        *,
        height: int,
        width: int,
        direction_order: tuple[str, ...] = RDLU,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        if height <= 0 or width <= 0:
            raise ValueError("height and width must be positive")
        if tuple(direction_order) != RDLU:
            raise ValueError(
                "period_on_sim consumes weights in R,D,L,U order; convert the "
                "generator output explicitly before constructing the adapter"
            )
        self.env = env
        self.generator = generator
        self.height = height
        self.width = width
        self.direction_order = RDLU
        self._clock_ns = clock_ns
        self.observation: Any = None
        self.info: Mapping[str, Any] = {}
        self.cached_action: Any = None
        self.decision_index = 0
        self.bootstrap_count = 0
        self.refresh_count = 0
        self.reuse_count = 0
        self.reactivation_count = 0
        self.installation_version = 0
        self.guidance_digest = ""
        self.active_generation_id: int | None = None
        self._next_generation_id = 1
        self._guidance_memory: dict[int, _StoredGuidance] = {}
        self._active_applied_guidance_digest: str | None = None
        self.done = False
        self.faulted = False

    @property
    def guidance_version(self) -> int:
        """Backward-compatible alias for the installed guidance version."""

        return self.installation_version

    @property
    def guidance_catalog(self) -> tuple[GuidanceRecord, ...]:
        """Return immutable metadata without exposing mutable cached actions."""

        return tuple(
            GuidanceRecord(
                generation_id=entry.generation_id,
                source=entry.source,
                raw_guidance_digest=entry.raw_guidance_digest,
                applied_guidance_digest=entry.applied_guidance_digest,
            )
            for _, entry in sorted(self._guidance_memory.items())
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None,
        initial_action: Any | None = None,
    ) -> tuple[Any, Mapping[str, Any]]:
        observation, info = self.env.reset(seed=seed, options=options)
        action = (
            uniform_action(self.height, self.width)
            if initial_action is None
            else initial_action
        )
        validate_official_action(action, height=self.height, width=self.width)
        self.cached_action = copy.deepcopy(action)
        self.guidance_digest = action_digest(
            self.cached_action, height=self.height, width=self.width
        )
        self.observation = observation
        self.info = info
        self.decision_index = 0
        self.bootstrap_count = 0
        self.refresh_count = 0
        self.reuse_count = 0
        self.reactivation_count = 0
        self.installation_version = 0
        self.active_generation_id = None
        self._next_generation_id = 1
        self._guidance_memory = {}
        self._active_applied_guidance_digest = None
        self.done = False
        self.faulted = False
        return observation, info

    def bootstrap_guidance(self) -> float:
        """Generate and cache one mandatory pre-horizon guidance version.

        ``TrafficFlowOnlineEnv.reset`` finishes the warm-up and exposes the
        first scored observation without accepting a guidance action.  This
        method lets an experiment generate the mandatory bootstrap graph from
        that observation without advancing a scored simulator window.  The
        next :meth:`advance` call sends the cached graph to C++ as publication
        version one.  Bootstrap calls are tracked separately from subsequent
        budgeted refreshes.
        """

        if self.cached_action is None:
            raise RuntimeError("adapter must be reset before bootstrap")
        if self.faulted:
            raise RuntimeError("adapter is faulted; reset before continuing")
        if self.done or self.decision_index != 0:
            raise RuntimeError("bootstrap must precede the first scored window")
        if self.bootstrap_count or self.refresh_count or self.reuse_count:
            raise RuntimeError("bootstrap guidance was already installed")

        started = self._clock_ns()
        action = self.generator(self.observation)
        generator_seconds = max(0.0, (self._clock_ns() - started) / 1e9)
        validate_official_action(action, height=self.height, width=self.width)
        candidate_action = copy.deepcopy(action)
        candidate_digest = action_digest(
            candidate_action, height=self.height, width=self.width
        )

        self.cached_action = candidate_action
        self.guidance_digest = candidate_digest
        generation_id = self._next_generation_id
        self._next_generation_id += 1
        self._guidance_memory[generation_id] = _StoredGuidance(
            generation_id=generation_id,
            source="bootstrap",
            action=copy.deepcopy(candidate_action),
            raw_guidance_digest=candidate_digest,
        )
        self.active_generation_id = generation_id
        self.installation_version = 1
        self.bootstrap_count = 1
        return generator_seconds

    def advance(
        self,
        *,
        refresh: bool | None = None,
        command: GuidanceCommand | None = None,
    ) -> OnlineGGOWindow:
        """Advance one window under a legacy or three-way guidance command.

        ``refresh=True`` remains exactly the legacy fresh-generation request,
        while ``refresh=False`` remains a hold.  New callers can instead pass
        ``command=GuidanceCommand.reactivate(id)`` to install a previously
        generated raw action without invoking the generator.
        """

        if self.cached_action is None:
            raise RuntimeError("adapter must be reset before advance")
        if self.faulted:
            raise RuntimeError("adapter is faulted; reset before continuing")
        if self.done:
            raise RuntimeError("cannot advance a terminated or truncated episode")
        if refresh is not None and command is not None:
            raise ValueError("specify either refresh or command, not both")
        if command is None:
            if not isinstance(refresh, bool):
                raise TypeError("legacy advance requires a boolean refresh value")
            command = (
                GuidanceCommand.generate() if refresh else GuidanceCommand.hold()
            )
        elif not isinstance(command, GuidanceCommand):
            raise TypeError("command must be a GuidanceCommand")

        generator_seconds = 0.0
        candidate_action = self.cached_action
        candidate_digest = self.guidance_digest
        requested_operation = command.operation
        operation = requested_operation
        candidate_generation_id = self.active_generation_id
        candidate_entry: _StoredGuidance | None = None
        if operation is GuidanceOperation.GENERATE:
            started = self._clock_ns()
            action = self.generator(self.observation)
            generator_seconds = max(0.0, (self._clock_ns() - started) / 1e9)
            validate_official_action(action, height=self.height, width=self.width)
            candidate_action = copy.deepcopy(action)
            candidate_digest = action_digest(
                candidate_action, height=self.height, width=self.width
            )
            candidate_generation_id = self._next_generation_id
        elif operation is GuidanceOperation.REACTIVATE:
            target = command.target_generation_id
            if target not in self._guidance_memory:
                raise ValueError(f"unknown historical guidance generation {target}")
            candidate_entry = self._guidance_memory[target]
            same_active = target == self.active_generation_id
            same_raw = candidate_entry.raw_guidance_digest == self.guidance_digest
            same_applied = bool(
                candidate_entry.applied_guidance_digest is not None
                and self._active_applied_guidance_digest is not None
                and candidate_entry.applied_guidance_digest
                == self._active_applied_guidance_digest
            )
            if same_active or same_raw or same_applied:
                # Reinstalling the currently effective vector would not create
                # a C++ map revision.  Treat it as HOLD instead of inventing a
                # logical installation version with no physical treatment.
                operation = GuidanceOperation.HOLD
                candidate_entry = self._guidance_memory.get(
                    self.active_generation_id
                )
            else:
                candidate_action = candidate_entry.action
                candidate_digest = candidate_entry.raw_guidance_digest
                candidate_generation_id = candidate_entry.generation_id

        installs_guidance = operation in {
            GuidanceOperation.GENERATE,
            GuidanceOperation.REACTIVATE,
        }
        candidate_installation_version = (
            self.installation_version + int(installs_guidance)
        )

        # Re-send the cached *raw* action.  Do not cache normalized weights from
        # OnlineGGO's private _run_sim method: step() normalizes raw actions.
        # The instrumented environment optionally accepts this external policy
        # identity and returns it alongside a separate digest of the normalized
        # weights actually sent to C++.  Publication version and treatment hash
        # must not be inferred from task timestamps.
        metadata_setter = getattr(self.env, "set_dai_guidance_metadata", None)
        if callable(metadata_setter):
            metadata_setter(
                version=candidate_installation_version,
                sha256=candidate_digest,
            )
        env_action = copy.deepcopy(candidate_action)
        started = self._clock_ns()
        try:
            observation, reward, terminated, truncated, info = self.env.step(env_action)
        except Exception:
            # The C++ simulator may already have advanced before propagating an
            # exception, so continuing could splice together an invalid run.
            self.faulted = True
            raise
        simulator_seconds = max(0.0, (self._clock_ns() - started) / 1e9)
        if not isinstance(reward, Real) or not math.isfinite(float(reward)):
            self.faulted = True
            raise ValueError("OnlineGGO backend returned a non-finite reward")
        if not isinstance(terminated, bool) or not isinstance(truncated, bool):
            self.faulted = True
            raise TypeError("OnlineGGO backend termination flags must be booleans")
        if not isinstance(info, Mapping):
            self.faulted = True
            raise TypeError("OnlineGGO backend info must be a mapping")

        applied_guidance_digest: str | None = None
        trace = info.get("dai_trace")
        if trace is not None:
            if not isinstance(trace, Mapping):
                self.faulted = True
                raise TypeError("OnlineGGO dai_trace must be a mapping")
            expected_version = candidate_installation_version
            if trace.get("guidance_version") != expected_version:
                self.faulted = True
                raise ValueError("OnlineGGO trace guidance version disagrees with adapter")
            if trace.get("guidance_sha256") != candidate_digest:
                self.faulted = True
                raise ValueError("OnlineGGO trace raw guidance digest disagrees with adapter")
            installed = trace.get("applied_guidance_sha256")
            if (
                not isinstance(installed, str)
                or len(installed) != 64
                or any(character not in "0123456789abcdef" for character in installed)
            ):
                self.faulted = True
                raise ValueError("OnlineGGO trace has an invalid applied guidance digest")
            applied_guidance_digest = installed
            if (
                candidate_entry is not None
                and candidate_entry.applied_guidance_digest is not None
                and candidate_entry.applied_guidance_digest != installed
            ):
                self.faulted = True
                raise ValueError(
                    "historical raw guidance replay changed its applied digest"
                )

        if operation is GuidanceOperation.GENERATE:
            new_entry = _StoredGuidance(
                generation_id=int(candidate_generation_id),
                source="generated",
                action=copy.deepcopy(candidate_action),
                raw_guidance_digest=candidate_digest,
                applied_guidance_digest=applied_guidance_digest,
            )
            self._guidance_memory[new_entry.generation_id] = new_entry
            self._next_generation_id += 1
            self.cached_action = candidate_action
            self.guidance_digest = candidate_digest
            self.active_generation_id = new_entry.generation_id
            self.installation_version = candidate_installation_version
            self.refresh_count += 1
        elif operation is GuidanceOperation.REACTIVATE:
            if candidate_entry is None:
                raise RuntimeError("reactivation lost its historical guidance")
            if candidate_entry.applied_guidance_digest is None:
                candidate_entry.applied_guidance_digest = applied_guidance_digest
            self.cached_action = copy.deepcopy(candidate_entry.action)
            self.guidance_digest = candidate_entry.raw_guidance_digest
            self.active_generation_id = candidate_entry.generation_id
            self.installation_version = candidate_installation_version
            self.reactivation_count += 1
        else:
            self.reuse_count += 1

        if applied_guidance_digest is not None:
            self._active_applied_guidance_digest = applied_guidance_digest
            active_entry = self._guidance_memory.get(self.active_generation_id)
            if active_entry is not None:
                if active_entry.applied_guidance_digest is None:
                    active_entry.applied_guidance_digest = applied_guidance_digest
                elif active_entry.applied_guidance_digest != applied_guidance_digest:
                    self.faulted = True
                    raise ValueError(
                        "cached guidance changed its applied digest during replay"
                    )

        window = OnlineGGOWindow(
            decision_index=self.decision_index,
            refreshed=operation is GuidanceOperation.GENERATE,
            guidance_version=self.installation_version,
            guidance_digest=self.guidance_digest,
            applied_guidance_digest=applied_guidance_digest,
            reward=float(reward),
            terminated=terminated,
            truncated=truncated,
            generator_seconds=generator_seconds,
            simulator_seconds=simulator_seconds,
            observation=observation,
            info=info,
            requested_operation=requested_operation,
            operation=operation,
            generation_id=self.active_generation_id,
            installation_version=self.installation_version,
            reactivated=operation is GuidanceOperation.REACTIVATE,
        )
        self.observation = observation
        self.info = info
        self.done = terminated or truncated
        self.decision_index += 1
        return window


__all__ = [
    "GuidanceCommand",
    "GuidanceGenerator",
    "GuidanceOperation",
    "GuidanceRecord",
    "OnlineGGOAdapter",
    "OnlineGGOEnv",
    "OnlineGGOWindow",
    "RDLU",
    "action_digest",
    "uniform_action",
    "validate_official_action",
]
