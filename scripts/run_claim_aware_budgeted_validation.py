#!/usr/bin/env python3
"""Run exact-budget OnlineGGO publication experiments on absolute task tapes.

The runner is intentionally claim-aware: it separates development, contaminated
pilot-validation, fresh validation-v2, and locked-test seeds; makes decision
zero a mandatory bootstrap for every
learned-guidance method; spends quotas only at decisions 1..N-1; records a
planner timeout when the backend still returns a valid trace; rejects MAPF or
trace-integrity failures; and hard-fails if paired methods do not receive the
same reset state and absolute release projection.  The pinned wrapper rejects
a timeout that invalidates its route trace before this runner can continue, so
such an arm aborts the artifact instead of being silently omitted or spliced.

``uniform`` is the registered zero-CNN control and is the sole exception to
the mandatory learned-guidance bootstrap.  It makes zero generator calls.
"""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gc
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import random
import statistics
import sys
import time
from typing import Any, Iterable, Mapping


DEVELOPMENT_SEEDS = tuple(range(17, 27))
CONTAMINATED_PILOT_VALIDATION_SEEDS = tuple(range(101, 111))
VALIDATION_V2_SEEDS = (
    320019,
    241771,
    827130,
    693142,
    741084,
    12102,
    133633,
    876480,
    50620,
    131545,
)
LOCKED_TEST_SEEDS = tuple(range(1001, 1031))
VALIDATION_V2_SOURCE_DEVELOPMENT_SHA256 = (
    "d971c23983bb9e2b1bc517cea0db19fd5da5bc97a16b6a2aa3a777c06b7ff9f7"
)

SPLIT_SEED_ORDER = {
    "development": DEVELOPMENT_SEEDS,
    "contaminated_pilot_validation": CONTAMINATED_PILOT_VALIDATION_SEEDS,
    "validation_v2": VALIDATION_V2_SEEDS,
    "locked_test": LOCKED_TEST_SEEDS,
}
SPLIT_SEEDS = {
    name: frozenset(seeds) for name, seeds in SPLIT_SEED_ORDER.items()
}
# Compatibility is intentionally one-way: an old CLI invocation can still be
# parsed, but every newly written artifact receives the unambiguous canonical
# contaminated label.  Existing artifacts with split="validation" and seeds
# 101--110 must be interpreted as contaminated pilot evidence.
LEGACY_SPLIT_ALIASES = {"validation": "contaminated_pilot_validation"}
COMPLETE_MATRIX_SPLITS = frozenset(
    {"contaminated_pilot_validation", "validation_v2", "locked_test"}
)
OVERWRITE_PROTECTED_SPLITS = COMPLETE_MATRIX_SPLITS
WORKLOADS = ("stationary", "abrupt", "recurrent")
_MANIFEST_CACHE: dict[tuple[Any, ...], tuple[dict[str, Any], Any, Path]] = {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _keyed_uint32(*parts: object) -> int:
    encoded = "\x1f".join(map(str, parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:4], "big")


def _publication_policy_seed(seed: int, method: str) -> int:
    """Return the causal policy seed, sharing random-memory opportunities."""

    schedule_method = "random_B25" if method == "random_memory_B25" else method
    return _keyed_uint32("publication-policy", seed, schedule_method)


def _apply_hard_generation_cap(
    proposed_operation: str,
    *,
    post_generations: int,
    generation_cap: int,
) -> tuple[str, bool]:
    """Causally block a fresh generation after its post-bootstrap cap."""

    if proposed_operation not in {"hold", "reactivate", "generate"}:
        raise ValueError("unknown context-memory operation")
    for name, value in (
        ("post_generations", post_generations),
        ("generation_cap", generation_cap),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    blocked = bool(
        proposed_operation == "generate" and post_generations >= generation_cap
    )
    return ("hold" if blocked else proposed_operation), blocked


def _resolve_context_generation_cap(
    policy: Any,
    *,
    proposed_operation: str,
    post_generations: int,
    generation_cap: int,
    score: float,
    action_available: bool,
    route_mature: bool,
    maintenance_due: bool,
) -> tuple[str, bool, bool]:
    """Return effective operation, over-G4 candidate, and causal binding.

    The deep-copy preview answers whether the unchanged context policy would
    accept the fresh generation.  Only an otherwise accepted call is changed
    to hold, and the live policy is still advanced exactly once by the caller.
    Reactivation never enters this generation-cap path.
    """

    capped_operation, candidate_suppressed = _apply_hard_generation_cap(
        proposed_operation,
        post_generations=post_generations,
        generation_cap=generation_cap,
    )
    if not candidate_suppressed:
        return proposed_operation, False, False
    preview = copy.deepcopy(policy).select(
        score=score,
        action_available=action_available,
        route_mature=route_mature,
        maintenance_due=maintenance_due,
    )
    cap_binding = bool(preview.accepted)
    return (
        capped_operation if cap_binding else proposed_operation,
        True,
        cap_binding,
    )


def _resolve_context_eventreserve(
    policy: Any,
    *,
    proposed_operation: str,
    post_generations: int,
    post_switches: int,
    generation_cap: int,
    switch_cap: int,
    score: float,
    action_available: bool,
    route_mature: bool,
    maintenance_due: bool,
) -> dict[str, Any]:
    """Resolve the development-only G5/S6 event-reserve constraints.

    The mandatory bootstrap is absent from both counters.  Fresh generation
    is allowed while ``post_generations < G5``; this strict inequality makes
    the fifth post-bootstrap call legal and the sixth illegal.  Reactivation
    never spends G5.

    S6 has one additional causal restriction.  Once five *executed* switches
    have occurred, the sixth slot is reserved for a fresh generation whose
    unconstrained context-policy preview would be accepted and event-triggered.
    A second preview with maintenance disabled proves that acceptance is not
    maintenance-only.  A recall can therefore use an earlier S6 slot, but can
    never consume the reserved sixth slot.

    Both previews operate on deep copies.  The live policy is advanced exactly
    once by the caller, preserving score history, persistence, gap state, and
    switch-budget accounting.  Candidate and binding fields are returned
    separately so an underlying policy rejection is never misattributed to a
    hard constraint.
    """

    if proposed_operation not in {"hold", "reactivate", "generate"}:
        raise ValueError("unknown context-memory operation")
    for name, value in (
        ("post_generations", post_generations),
        ("post_switches", post_switches),
        ("generation_cap", generation_cap),
        ("switch_cap", switch_cap),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    for name, value in (
        ("action_available", action_available),
        ("route_mature", route_mature),
        ("maintenance_due", maintenance_due),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name} must be boolean")

    generation_cap_candidate = bool(
        proposed_operation == "generate" and post_generations >= generation_cap
    )
    # The reserve is semantically the literal sixth S6 switch.  Small smoke
    # horizons whose effective cap is below six do not manufacture an earlier
    # reserved slot.
    reserve_active = bool(switch_cap >= 6 and post_switches == 5)
    reserve_candidate = bool(
        reserve_active and proposed_operation in {"generate", "reactivate"}
    )
    constraint_candidate = generation_cap_candidate or reserve_candidate

    preview = None
    event_preview = None
    if constraint_candidate:
        preview = copy.deepcopy(policy).select(
            score=score,
            action_available=action_available,
            route_mature=route_mature,
            maintenance_due=maintenance_due,
        )
        event_preview = copy.deepcopy(policy).select(
            score=score,
            action_available=action_available,
            route_mature=route_mature,
            maintenance_due=False,
        )

    preview_accepted = bool(preview is not None and preview.accepted)
    preview_triggered = bool(preview is not None and preview.triggered)
    event_preview_accepted = bool(
        event_preview is not None and event_preview.accepted
    )
    event_preview_triggered = bool(
        event_preview is not None and event_preview.triggered
    )
    reserve_unconstrained_accepted = bool(
        reserve_candidate and preview_accepted
    )
    reserve_qualified = bool(
        reserve_unconstrained_accepted
        and preview_triggered
        and proposed_operation == "generate"
        and event_preview_accepted
        and event_preview_triggered
    )
    reserve_binding = bool(
        reserve_unconstrained_accepted and not reserve_qualified
    )
    # G5 is binding only if the unconstrained policy would accept and, at the
    # reserved slot, the candidate independently satisfies the reserve rule.
    generation_cap_binding = bool(
        generation_cap_candidate
        and preview_accepted
        and (not reserve_active or reserve_qualified)
    )
    constraint_binding = generation_cap_binding or reserve_binding
    effective_operation = "hold" if constraint_binding else proposed_operation

    return {
        "effective_operation": effective_operation,
        "constraint_candidate": constraint_candidate,
        "constraint_binding": constraint_binding,
        "generation_cap_candidate": generation_cap_candidate,
        "generation_cap_binding": generation_cap_binding,
        "reserve_active": reserve_active,
        "reserve_candidate": reserve_candidate,
        "reserve_preview_accepted": reserve_unconstrained_accepted,
        "reserve_preview_triggered": bool(
            reserve_candidate and preview_triggered
        ),
        "reserve_event_preview_accepted": bool(
            reserve_candidate and event_preview_accepted
        ),
        "reserve_event_preview_triggered": bool(
            reserve_candidate and event_preview_triggered
        ),
        "reserve_qualified": reserve_qualified,
        "reserve_binding": reserve_binding,
    }


def _keyed_index(size: int, *parts: object) -> int:
    if size <= 0:
        raise ValueError("keyed index requires a positive size")
    return _keyed_uint32(*parts) % size


def _endpoint_distribution(kiva_map: Any, center: int, sigma: float) -> list[float]:
    center_row, center_col = divmod(center, kiva_map.cols)
    values = []
    for endpoint in kiva_map.endpoint_locations:
        row, col = divmod(endpoint, kiva_map.cols)
        x_scale = 10.0 / max(1, kiva_map.cols - 1)
        y_scale = 10.0 / max(1, kiva_map.rows - 1)
        squared = ((col - center_col) * x_scale) ** 2 + (
            (row - center_row) * y_scale
        ) ** 2
        values.append(math.exp(-squared / (2.0 * sigma * sigma)))
    total = math.fsum(values)
    return [value / total for value in values]


def _js(left: list[float], right: list[float]) -> float:
    midpoint = [(a + b) / 2.0 for a, b in zip(left, right)]
    return 0.5 * math.fsum(
        value * math.log(value / target)
        for value, target in zip(left, midpoint)
        if value > 0
    ) + 0.5 * math.fsum(
        value * math.log(value / target)
        for value, target in zip(right, midpoint)
        if value > 0
    )


def _phase_plan(
    *,
    workload: str,
    warmup_time: int,
    horizon: int,
    kiva_map: Any,
    sigma: float,
    seed: int,
    minimum_adjacent_js: float = 0.30,
) -> tuple[list[int], list[int], list[int], list[float]]:
    """Return absolute starts, scored change offsets, and endpoint centres."""

    if workload not in WORKLOADS:
        raise ValueError(f"unknown workload {workload!r}")
    if workload == "stationary":
        phase_starts = [0]
        scored_changes: list[int] = []
        count = 1
    else:
        scored_changes = [horizon // 4, horizon // 2, (3 * horizon) // 4]
        if len(set(scored_changes)) != 3 or scored_changes[0] <= 0:
            raise ValueError("dynamic workloads require a horizon of at least 4")
        phase_starts = [0] + [warmup_time + value for value in scored_changes]
        count = 4

    endpoints = kiva_map.endpoint_locations
    first_index = _keyed_index(
        len(endpoints), "dai-claim-phase", seed, workload, 0
    )
    selected = [endpoints[first_index]]
    distributions = {
        endpoint: _endpoint_distribution(kiva_map, endpoint, sigma)
        for endpoint in endpoints
    }
    adjacent_js: list[float] = []
    for phase in range(1, count):
        previous = selected[-1]
        candidates = [endpoint for endpoint in endpoints if endpoint not in selected]
        if not candidates:
            raise ValueError("not enough distinct Kiva endpoints for phase centres")
        # Max-separation greedy selection prevents a nominally dynamic tape
        # from becoming nearly stationary for an unlucky root seed.  The
        # keyed value gives a deterministic tie-break independent of policies.
        candidate = max(
            candidates,
            key=lambda endpoint: (
                _js(distributions[previous], distributions[endpoint]),
                _keyed_uint32("dai-claim-phase-tie", seed, workload, phase, endpoint),
            ),
        )
        separation = _js(distributions[previous], distributions[candidate])
        if separation < minimum_adjacent_js:
            raise RuntimeError(
                "map/sigma cannot realize the registered dynamic JS separation: "
                f"{separation:.6f} < {minimum_adjacent_js:.6f}"
            )
        selected.append(candidate)
        adjacent_js.append(separation)
    if workload == "recurrent":
        # A -> B -> A -> B, with A and B selected independently of policies.
        selected = [selected[0], selected[1], selected[0], selected[1]]
        separation = _js(distributions[selected[0]], distributions[selected[1]])
        adjacent_js = [separation, separation, separation]
    return phase_starts, scored_changes, selected, adjacent_js


def _staggered_release_schedules(
    *, n_agents: int, total_steps: int, interval: int, guard_suffix: int
) -> tuple[list[list[int]], dict[str, Any]]:
    if n_agents <= 0 or total_steps <= 1 or interval <= 0:
        raise ValueError("release schedule dimensions must be positive")
    if guard_suffix < 4:
        raise ValueError(
            "at least four final guard tasks are required for a conservative "
            "non-exhaustion sentinel"
        )
    schedules: list[list[int]] = []
    regular_counts: dict[int, int] = {}
    for agent_id in range(n_agents):
        offset = (agent_id * interval) // n_agents
        regular = list(range(offset, total_steps - 1, interval))
        for release in regular:
            regular_counts[release] = regular_counts.get(release, 0) + 1
        schedules.append(regular + [total_steps - 1] * guard_suffix)
    metadata = {
        "schedule": "deterministic_agent_stagger/v1",
        "release_interval_per_agent": interval,
        "nominal_arrival_rate_tasks_per_timestep": n_agents / interval,
        "maximum_regular_arrivals_in_one_timestep": max(regular_counts.values()),
        "regular_release_count": sum(map(len, schedules)) - n_agents * guard_suffix,
        "guard_suffix_tasks_per_agent": guard_suffix,
        "guard_suffix_release_timestep": total_steps - 1,
        "guard_suffix_purpose": (
            "non-scoring end sentinel that prevents any method from consuming "
            "the complete finite tape before the horizon"
        ),
    }
    return schedules, metadata


def _configure_paths(workspace: Path) -> tuple[Path, Path]:
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    for path in (workspace / "src", cmaes):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return onlineggo, cmaes


def _build_manifest(spec: Mapping[str, Any]) -> tuple[dict[str, Any], Any, Path]:
    cache_key = tuple(
        spec[field]
        for field in (
            "workspace",
            "map_path",
            "seed",
            "workload",
            "agents",
            "warmup_time",
            "horizon",
            "release_interval",
            "guard_suffix",
            "sigma",
        )
    )
    cached = _MANIFEST_CACHE.get(cache_key)
    if cached is not None:
        return cached
    workspace = Path(spec["workspace"])
    onlineggo, _ = _configure_paths(workspace)
    from dai_lmapf.absolute_workload import (
        build_absolute_task_tape_manifest,
        generate_phase_shifted_kiva_tape,
        read_kiva_map,
    )
    from env_search.iterative_update.envs.trafficflow_online_env import (
        _dai_derive_seed,
        generate_kiva_saturated_goal_tape,
    )

    map_path = Path(spec["map_path"])
    kiva_map = read_kiva_map(map_path)
    seed = int(spec["seed"])
    agents = int(spec["agents"])
    total_steps = int(spec["warmup_time"]) + int(spec["horizon"])
    starts_artifact = generate_kiva_saturated_goal_tape(
        str(map_path), agents, 1, seed
    )
    starts = [int(value) for value in starts_artifact["start_locations"]]
    if len(starts) != agents or len(set(starts)) != agents:
        raise RuntimeError("start generator did not return unique per-agent starts")

    phase_starts, scored_changes, centers, adjacent_js = _phase_plan(
        workload=str(spec["workload"]),
        warmup_time=int(spec["warmup_time"]),
        horizon=int(spec["horizon"]),
        kiva_map=kiva_map,
        sigma=float(spec["sigma"]),
        seed=seed,
    )
    schedules, arrival = _staggered_release_schedules(
        n_agents=agents,
        total_steps=total_steps,
        interval=int(spec["release_interval"]),
        guard_suffix=int(spec["guard_suffix"]),
    )
    task_seed = _dai_derive_seed(seed, 2)
    tape: list[list[list[int]]] = []
    for agent_id, (start, releases) in enumerate(zip(starts, schedules)):
        # Per-agent construction permits staggered absolute releases while the
        # keyed task seed keeps goal generation independent across agents.
        generated = generate_phase_shifted_kiva_tape(
            kiva_map=kiva_map,
            start_locations=[start],
            release_timesteps=releases,
            phase_starts=phase_starts,
            endpoint_phase_centers=centers,
            task_seed=_keyed_uint32(task_seed, "agent", agent_id),
            sigma=float(spec["sigma"]),
        )
        tape.append(generated[0])

    effective_phase_release_starts = [
        min(
            release
            for schedule in schedules
            for release in schedule[:-int(spec["guard_suffix"])]
            if release >= phase_start
        )
        for phase_start in phase_starts
    ]
    generator_metadata = {
        "name": "dai_claim_absolute_workload/v1",
        "root_seed": seed,
        "task_seed": task_seed,
        "workload": spec["workload"],
        "sigma": float(spec["sigma"]),
        "phase_starts_absolute": phase_starts,
        "phase_change_offsets_scored": scored_changes,
        "effective_phase_release_starts_absolute": effective_phase_release_starts,
        "endpoint_phase_centers": centers,
        "adjacent_endpoint_distribution_js": adjacent_js,
        "minimum_registered_adjacent_js": 0.30,
        "warmup_time": int(spec["warmup_time"]),
        "scored_horizon": int(spec["horizon"]),
        **arrival,
    }
    manifest = build_absolute_task_tape_manifest(
        starts, tape, generator=generator_metadata
    )
    manifest["manifest_id"] = (
        f"{map_path.stem}:{spec['workload']}:{seed}:"
        f"{manifest['manifest_sha256'][:16]}"
    )
    result = (manifest, kiva_map, onlineggo)
    _MANIFEST_CACHE[cache_key] = result
    return result


def _task_tape_identity(trace: Mapping[str, Any]) -> dict[str, Any]:
    task_tape = trace.get("task_tape")
    if not isinstance(task_tape, dict) or task_tape.get("enabled") is not True:
        raise RuntimeError("claim run requires an enabled absolute task tape")
    fields = (
        "mode",
        "schema_version",
        "manifest_sha256",
        "content_fnv1a64",
        "start_locations",
        "per_agent_lengths",
        "total_tasks",
    )
    if any(field not in task_tape for field in fields):
        raise RuntimeError("absolute task-tape trace is missing identity fields")
    return {field: task_tape[field] for field in fields}


def _validate_tape_trace(
    trace: Mapping[str, Any],
    *,
    expected_sha: str,
    expected_fnv: str,
    prior_prefixes: Mapping[str, list[int]] | None,
) -> tuple[dict[str, list[int]], int]:
    task_tape = trace["task_tape"]
    if task_tape["manifest_sha256"] != expected_sha:
        raise RuntimeError("simulator absolute-tape SHA differs from manifest")
    if task_tape["content_fnv1a64"] != expected_fnv:
        raise RuntimeError("simulator absolute-tape FNV differs from manifest")
    online_draws = task_tape.get("online_workload_rng_draws")
    if online_draws != 0:
        raise RuntimeError("absolute task tape consumed online workload RNG")
    prefixes = {
        name: [int(value) for value in task_tape[name]]
        for name in (
            "released_prefix_lengths",
            "assigned_prefix_lengths",
            "completed_prefix_lengths",
        )
    }
    if not all(
        completed <= assigned <= released
        for completed, assigned, released in zip(
            prefixes["completed_prefix_lengths"],
            prefixes["assigned_prefix_lengths"],
            prefixes["released_prefix_lengths"],
        )
    ):
        raise RuntimeError("absolute task-tape prefixes violate FIFO ordering")
    if prior_prefixes is not None:
        for name, values in prefixes.items():
            if any(before > after for before, after in zip(prior_prefixes[name], values)):
                raise RuntimeError(f"{name} moved backwards")
    return prefixes, int(online_draws)


def _release_records(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = [
        {
            "agent_id": event["agent_id"],
            "task_id": event["task_id"],
            "timestep": event["timestep"],
            "goal_loc": event["goal_loc"],
        }
        for event in trace["recent_events"]
        if event["event_type"] == "released"
    ]
    return sorted(
        records,
        key=lambda item: (item["timestep"], item["agent_id"], item["task_id"]),
    )


def _absolute_tape_has_unassigned_guard(task_tape: Mapping[str, Any]) -> bool:
    """Absolute v1 has no ``exhausted`` field; infer suffix availability."""

    assigned = task_tape.get("assigned_prefix_lengths")
    lengths = task_tape.get("per_agent_lengths")
    if not isinstance(assigned, list) or not isinstance(lengths, list):
        raise TypeError("absolute task tape must expose assigned prefixes and lengths")
    if len(assigned) != len(lengths) or not assigned:
        raise ValueError("absolute assigned prefixes must align with tape lengths")
    return all(
        isinstance(before, int)
        and isinstance(limit, int)
        and not isinstance(before, bool)
        and not isinstance(limit, bool)
        and 0 <= before < limit
        for before, limit in zip(assigned, lengths)
    )


def _reset_fingerprint(trace: Mapping[str, Any], canonical_sha256: Any) -> str:
    return canonical_sha256(
        {
            "seed_bundle": trace["seed_bundle"],
            "start": trace["start"],
            "planner_initial_priority_order": trace["planner_initial_priority_order"],
            "curr_pos": trace["curr_pos"],
            "curr_tasks": trace["curr_tasks"],
            "curr_task_active": trace["curr_task_active"],
            "actual_paths": trace["actual_paths"],
            "task_tape_identity": _task_tape_identity(trace),
        }
    )


def _fatal_integrity_counts(counts: Mapping[str, int]) -> dict[str, int]:
    """Timeout is an outcome; only state/safety corruption invalidates a run."""

    fields = (
        "collision_count",
        "edge_swap_count",
        "invalid_move_count",
        "endpoint_mismatch_count",
        "route_trace_invalid_count",
    )
    return {field: counts[field] for field in fields if counts[field] != 0}


class _ForbiddenUniformGenerator:
    calls = 0
    metadata = {"mode": "uniform_zero_cnn"}

    def __call__(self, observation: Any) -> Any:  # pragma: no cover - sentinel
        del observation
        raise RuntimeError("uniform control must never invoke the CNN")


def _run_one(spec: Mapping[str, Any]) -> dict[str, Any]:
    run_started = time.perf_counter()
    workspace = Path(spec["workspace"])
    _, cmaes = _configure_paths(workspace)
    from dai_lmapf.claim_runner import (
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
        CausalFeatureTracker,
        EXACT_BUDGET_METHODS,
        audit_joint_paths,
        canonical_sha256,
        decision_to_dict,
        js_divergence,
        make_exact_policy,
        method_budget,
        method_generation_cap,
        period_80_refresh,
        score_for_method,
    )
    from dai_lmapf.frozen_cnn_generator import FrozenCNNGuidanceGenerator
    from dai_lmapf.online_ggo_adapter import (
        GuidanceCommand,
        GuidanceOperation,
        OnlineGGOAdapter,
    )
    from env_search.iterative_update.envs.trafficflow_online_env import (
        TrafficFlowOnlineEnv,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig

    method = str(spec["method"])
    seed = int(spec["seed"])
    manifest, kiva_map, _ = _build_manifest(spec)
    tape = manifest["absolute_task_tape"]
    starts = manifest["start_locations"]
    map_path = Path(spec["map_path"])
    horizon = int(spec["horizon"])
    decision_window = int(spec["decision_window"])
    total_windows = horizon // decision_window
    eligible = total_windows - 1
    registered_budget = method_budget(method, total_windows)
    generation_cap = method_generation_cap(method, total_windows)
    config = TrafficMAPFConfig(
        map_path=str(map_path),
        simu_time=horizon,
        num_agents=int(spec["agents"]),
        num_tasks=sum(map(len, tape)),
        gen_tasks=True,
        num_tasks_reveal=1,
        task_assignment_strategy="roundrobin",
        update_gg_interval=decision_window,
        warmup_time=int(spec["warmup_time"]),
        past_traffic_interval=decision_window,
        task_dist_change_interval=-1,
        initial_task_distribution_phase=0,
        absolute_task_tape=tape,
        absolute_task_tape_start_locations=starts,
        has_traffic_obs=True,
        has_gg_obs=False,
        has_task_obs=True,
        has_map_obs=False,
    )
    env = TrafficFlowOnlineEnv(config=config, seed=seed)
    if method == "uniform":
        generator: Any = _ForbiddenUniformGenerator()
    else:
        generator = FrozenCNNGuidanceGenerator.from_path(
            spec["checkpoint"],
            expected_file_sha256=spec["checkpoint_sha256"],
            expected_params_sha256=spec["checkpoint_params_sha256"],
        )
    adapter = OnlineGGOAdapter(
        env, generator, height=env.comp_map.height, width=env.comp_map.width
    )
    _, reset_info = adapter.reset(seed=seed)
    reset_trace = dict(reset_info["dai_trace"])
    identity = _task_tape_identity(reset_trace)
    if identity["manifest_sha256"] != manifest["manifest_sha256"]:
        raise RuntimeError("reset trace received the wrong task-tape manifest")
    if identity["content_fnv1a64"] != manifest["content_fnv1a64"]:
        raise RuntimeError("reset trace received the wrong task-tape content")
    prefixes, online_rng_draws = _validate_tape_trace(
        reset_trace,
        expected_sha=manifest["manifest_sha256"],
        expected_fnv=manifest["content_fnv1a64"],
        prior_prefixes=None,
    )
    releases = _release_records(reset_trace)
    distribution_updates = list(reset_trace["recent_distribution_updates"])

    raw_graph = env.comp_map.graph
    graph = raw_graph.tolist() if hasattr(raw_graph, "tolist") else raw_graph
    warmup_safety = audit_joint_paths(
        start_positions=reset_trace["start"],
        actual_paths=reset_trace["actual_paths"],
        end_positions=reset_trace["curr_pos"],
        graph=graph,
    )
    safety_totals = {
        "collision_count": warmup_safety.collision_count,
        "edge_swap_count": warmup_safety.edge_swap_count,
        "invalid_move_count": warmup_safety.invalid_move_count,
        "endpoint_mismatch_count": warmup_safety.endpoint_mismatch_count,
        "planner_timeout_count": sum(
            record["timed_out"] for record in reset_trace["recent_planner_times"]
        ),
        "route_trace_invalid_count": int(
            reset_trace["route_build_trace_valid"] is not True
        ),
    }
    if fatal := _fatal_integrity_counts(safety_totals):
        raise RuntimeError(f"warmup safety/integrity failure: {fatal}")

    tracker = CausalFeatureTracker(
        n_agents=int(spec["agents"]),
        rows=env.comp_map.height,
        cols=env.comp_map.width,
        total_windows=total_windows,
    )
    tracker.ingest_trace(reset_trace)
    bootstrap_seconds = 0.0
    mandatory_bootstrap_calls = 0
    if method != "uniform":
        bootstrap_seconds = adapter.bootstrap_guidance()
        mandatory_bootstrap_calls = 1
        tracker.mark_publication(version=1, decision_index=0)

    memory_contexts: dict[int, tuple[float, ...]] = {}
    memory_catalog: dict[int, dict[str, Any]] = {}
    memory_methods = frozenset({
        "context_memory_B25",
        "random_memory_B25",
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
    })
    context_memory_methods = frozenset({
        "context_memory_B25",
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
    })
    if method in memory_methods:
        if adapter.active_generation_id is None:
            raise RuntimeError("guidance memory requires a bootstrap generation")
        bootstrap_context = tracker.active_goal_context_4x4()
        memory_contexts[adapter.active_generation_id] = bootstrap_context
        memory_catalog[adapter.active_generation_id] = {
            "generation_id": adapter.active_generation_id,
            "generated_at_decision": 0,
            "context_sha256": canonical_sha256(bootstrap_context),
            "context": list(bootstrap_context),
        }

    # random_memory_B25 is a paired intervention on random_B25: its opportunity
    # schedule must be bit-for-bit identical, with only the action at an
    # accepted opportunity changing from always-generate to recall-or-generate.
    policy = make_exact_policy(
        method,
        num_scored_windows=total_windows,
        policy_seed=_publication_policy_seed(seed, method),
        pacing_slack=int(spec["pacing_slack"]),
        minimum_history=int(spec["minimum_history"]),
        context_min_score=float(spec["context_min_score"]),
        context_min_gap=int(spec["context_min_gap"]),
    )
    publication_timeline: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    previous_positions = reset_trace["curr_pos"]
    post_publications = 0
    post_generations = 0
    post_reactivations = 0
    dualcap_generation_candidate_count = 0
    dualcap_generation_binding_count = 0
    generation_cap_candidate_count = 0
    generation_cap_binding_count = 0
    reserve_candidate_count = 0
    reserve_preview_accept_count = 0
    reserve_qualified_count = 0
    reserve_binding_count = 0
    reserve_generation_cap_binding_count = 0
    reserve_execution_count = 0
    budget_violation_attempts = 0
    reward_sum = 0.0
    generator_seconds = bootstrap_seconds
    simulator_seconds = 0.0

    for decision_index in range(total_windows):
        features = tracker.snapshot(decision_index=decision_index)
        policy_record: dict[str, Any] | None = None
        refresh = False
        guidance_command: Any | None = None
        requested_operation = "hold"
        target_generation_id: int | None = None
        active_context_distance: float | None = None
        nearest_context_distance: float | None = None
        decision_context: tuple[float, ...] | None = None
        uncapped_proposed_operation: str | None = None
        dualcap_generation_candidate = False
        dualcap_generation_binding = False
        eventreserve_audit = {
            "effective_operation": None,
            "constraint_candidate": False,
            "constraint_binding": False,
            "generation_cap_candidate": False,
            "generation_cap_binding": False,
            "reserve_active": False,
            "reserve_candidate": False,
            "reserve_preview_accepted": False,
            "reserve_preview_triggered": False,
            "reserve_event_preview_accepted": False,
            "reserve_event_preview_triggered": False,
            "reserve_qualified": False,
            "reserve_binding": False,
        }
        version_before_decision = adapter.guidance_version
        if decision_index == 0:
            action_reason = (
                "uniform_zero_cnn" if method == "uniform" else "mandatory_bootstrap"
            )
            publication_timeline.append(
                {
                    "decision_index": 0,
                    "scored_timestep": 0,
                    "absolute_timestep": int(spec["warmup_time"]),
                    "requested": method != "uniform",
                    "accepted": method != "uniform",
                    "charged_to_post_bootstrap_budget": False,
                    "charged_to_post_bootstrap_switch_cap": False,
                    "charged_to_post_bootstrap_generation_cap": False,
                    "charged_to_generator_budget": False,
                    "reason": action_reason,
                    "guidance_version_before_decision": 0,
                    "guidance_version_installed_for_window": adapter.guidance_version,
                    "requested_operation": (
                        "uniform" if method == "uniform" else "bootstrap_generate"
                    ),
                    "executed_operation": (
                        "uniform" if method == "uniform" else "bootstrap_generate"
                    ),
                    "active_generation_id_after": adapter.active_generation_id,
                }
            )
        elif method == "uniform":
            action_reason = "uniform_reuse"
        elif method == "period_80":
            refresh = period_80_refresh(decision_index, decision_window)
            requested_operation = "generate" if refresh else "hold"
            action_reason = "nominal_period_80" if refresh else "nominal_period_80_reuse"
        else:
            if policy is None:
                raise RuntimeError("registered exact-budget method has no policy")
            score = score_for_method(method, features)
            if method == "causal_block_B25":
                if score is None:
                    raise RuntimeError("causal block method lacks its causal score")
                decision = policy.select(
                    score=score,
                    route_mature=features.current_version_maturity >= 0.5,
                )
            elif method == "random_memory_B25":
                decision = policy.select(score=score)
                if adapter.active_generation_id is None:
                    raise RuntimeError("random memory lost its active generation")
                if decision.accepted:
                    decision_context = tracker.active_goal_context_4x4()
                    active_context = memory_contexts[adapter.active_generation_id]

                    def random_memory_context_distance(
                        reference: tuple[float, ...],
                    ) -> float:
                        return js_divergence(
                            decision_context, reference
                        ) / math.log(2.0)

                    active_context_distance = random_memory_context_distance(
                        active_context
                    )
                    historical = [
                        (random_memory_context_distance(context), generation_id)
                        for generation_id, context in memory_contexts.items()
                        if generation_id != adapter.active_generation_id
                    ]
                    if historical:
                        nearest_context_distance, nearest_generation_id = min(
                            historical
                        )
                    else:
                        nearest_generation_id = None
                    recall_available = bool(
                        nearest_generation_id is not None
                        and nearest_context_distance is not None
                        and nearest_context_distance
                        <= float(spec["context_match_threshold"])
                        and active_context_distance - nearest_context_distance
                        >= float(spec["context_recall_margin"])
                    )
                    if recall_available:
                        target_generation_id = nearest_generation_id
                        guidance_command = GuidanceCommand.reactivate(
                            target_generation_id
                        )
                        requested_operation = "reactivate"
                    else:
                        guidance_command = GuidanceCommand.generate()
                        requested_operation = "generate"
                else:
                    guidance_command = GuidanceCommand.hold()
                    requested_operation = "hold"
            elif method in context_memory_methods:
                if score is None:
                    raise RuntimeError("context memory method lacks its causal score")
                if adapter.active_generation_id is None:
                    raise RuntimeError("context memory lost its active generation")
                decision_context = tracker.active_goal_context_4x4()
                active_context = memory_contexts[adapter.active_generation_id]

                def context_distance(reference: tuple[float, ...]) -> float:
                    return js_divergence(decision_context, reference) / math.log(2.0)

                active_context_distance = context_distance(active_context)
                historical = [
                    (context_distance(context), generation_id)
                    for generation_id, context in memory_contexts.items()
                    if generation_id != adapter.active_generation_id
                ]
                if historical:
                    nearest_context_distance, nearest_generation_id = min(historical)
                else:
                    nearest_generation_id = None
                recall_threshold = float(spec["context_match_threshold"])
                recall_margin = float(spec["context_recall_margin"])
                maintenance_due = (
                    features.guidance_age_windows
                    >= int(spec["context_maintenance_age"])
                    and features.released_goal_js_recent_vs_history
                    <= float(spec["context_maintenance_stability"])
                )
                recall_available = bool(
                    nearest_generation_id is not None
                    and nearest_context_distance is not None
                    and nearest_context_distance <= recall_threshold
                    and active_context_distance - nearest_context_distance
                    >= recall_margin
                )
                active_matches = active_context_distance <= recall_threshold
                if recall_available:
                    proposed_operation = "reactivate"
                    target_generation_id = nearest_generation_id
                    action_available = True
                elif maintenance_due:
                    proposed_operation = "generate"
                    action_available = True
                elif active_matches:
                    proposed_operation = "hold"
                    action_available = False
                else:
                    proposed_operation = "generate"
                    action_available = True
                uncapped_proposed_operation = proposed_operation
                if method == CONTEXT_DUALCAP_METHOD:
                    if generation_cap is None:
                        raise RuntimeError(
                            "dual-cap context method lacks generation cap"
                        )
                    route_mature = (
                        features.current_version_route_fraction >= 0.5
                    )
                    (
                        proposed_operation,
                        dualcap_generation_candidate,
                        dualcap_generation_binding,
                    ) = _resolve_context_generation_cap(
                        policy,
                        proposed_operation=proposed_operation,
                        post_generations=post_generations,
                        generation_cap=generation_cap,
                        score=score,
                        action_available=action_available,
                        route_mature=route_mature,
                        maintenance_due=maintenance_due,
                    )
                    action_available = proposed_operation != "hold"
                elif method == CONTEXT_EVENTRESERVE_METHOD:
                    if generation_cap is None or registered_budget is None:
                        raise RuntimeError(
                            "event-reserve context method lacks a hard cap"
                        )
                    route_mature = (
                        features.current_version_route_fraction >= 0.5
                    )
                    eventreserve_audit = _resolve_context_eventreserve(
                        policy,
                        proposed_operation=proposed_operation,
                        post_generations=post_generations,
                        post_switches=post_publications,
                        generation_cap=generation_cap,
                        switch_cap=registered_budget,
                        score=score,
                        action_available=action_available,
                        route_mature=route_mature,
                        maintenance_due=maintenance_due,
                    )
                    proposed_operation = str(
                        eventreserve_audit["effective_operation"]
                    )
                    action_available = proposed_operation != "hold"
                decision = policy.select(
                    score=score,
                    action_available=action_available,
                    route_mature=features.current_version_route_fraction >= 0.5,
                    maintenance_due=maintenance_due,
                )
                if (
                    method == CONTEXT_DUALCAP_METHOD
                    and dualcap_generation_binding
                    and decision.accepted
                ):
                    raise RuntimeError(
                        "dual-cap binding failed to suppress a generation"
                    )
                if method == CONTEXT_EVENTRESERVE_METHOD:
                    if eventreserve_audit["constraint_binding"] and decision.accepted:
                        raise RuntimeError(
                            "event-reserve binding failed to suppress a switch"
                        )
                    reserve_should_execute = bool(
                        eventreserve_audit["reserve_qualified"]
                        and not eventreserve_audit["generation_cap_binding"]
                    )
                    if reserve_should_execute and not decision.accepted:
                        raise RuntimeError(
                            "qualified event-reserve generation was not accepted"
                        )
                if decision.accepted and proposed_operation == "reactivate":
                    if target_generation_id is None:
                        raise RuntimeError("reactivation lacks a target generation")
                    guidance_command = GuidanceCommand.reactivate(target_generation_id)
                    requested_operation = "reactivate"
                elif decision.accepted and proposed_operation == "generate":
                    guidance_command = GuidanceCommand.generate()
                    requested_operation = "generate"
                else:
                    guidance_command = GuidanceCommand.hold()
                    requested_operation = proposed_operation
            else:
                decision = policy.select(score=score)
            policy_record = decision_to_dict(decision)
            refresh = bool(
                decision.accepted and requested_operation == "generate"
            ) if method in memory_methods else decision.accepted
            if method not in memory_methods:
                requested_operation = "generate" if refresh else "hold"
            action_reason = decision.reason
            dualcap_generation_candidate_count += int(
                dualcap_generation_candidate
            )
            dualcap_generation_binding_count += int(
                dualcap_generation_binding
            )
            generation_cap_candidate_count += int(
                eventreserve_audit["generation_cap_candidate"]
            )
            generation_cap_binding_count += int(
                eventreserve_audit["generation_cap_binding"]
            )
            reserve_candidate_count += int(
                eventreserve_audit["reserve_candidate"]
            )
            reserve_preview_accept_count += int(
                eventreserve_audit["reserve_preview_accepted"]
            )
            reserve_qualified_count += int(
                eventreserve_audit["reserve_qualified"]
            )
            reserve_binding_count += int(
                eventreserve_audit["reserve_binding"]
            )
            reserve_generation_cap_binding_count += int(
                eventreserve_audit["reserve_qualified"]
                and eventreserve_audit["generation_cap_binding"]
            )
            if eventreserve_audit["generation_cap_binding"]:
                action_reason = "context_eventreserve_generation_cap"
            elif eventreserve_audit["reserve_binding"]:
                action_reason = "context_eventreserve_reserved_switch"
            elif dualcap_generation_binding:
                action_reason = "context_dualcap_generation_cap"
            violation = bool(decision.requested and not decision.accepted)
            budget_violation_attempts += int(violation)
            if violation:
                refresh = False

        if method in memory_methods:
            if guidance_command is None:
                guidance_command = GuidanceCommand.hold()
            window = adapter.advance(command=guidance_command)
            executed_operation = window.operation.value
            actual_switch = window.operation in {
                GuidanceOperation.GENERATE,
                GuidanceOperation.REACTIVATE,
            }
        else:
            window = adapter.advance(refresh=refresh)
            executed_operation = "generate" if refresh else "hold"
            actual_switch = refresh

        if decision_index > 0 and actual_switch:
            if eventreserve_audit["reserve_active"]:
                if (
                    method != CONTEXT_EVENTRESERVE_METHOD
                    or executed_operation != "generate"
                    or not eventreserve_audit["reserve_qualified"]
                    or eventreserve_audit["generation_cap_binding"]
                ):
                    raise RuntimeError(
                        "reserved sixth switch violated its fresh event rule"
                    )
                reserve_execution_count += 1
            tracker.mark_publication(
                version=window.guidance_version,
                decision_index=decision_index,
            )
            post_publications += 1
            if executed_operation == "generate":
                post_generations += 1
            elif executed_operation == "reactivate":
                post_reactivations += 1

        if (
            method in memory_methods
            and executed_operation == "generate"
            and decision_context is not None
        ):
            if window.generation_id is None:
                raise RuntimeError("generated guidance lacks a generation id")
            memory_contexts[window.generation_id] = decision_context
            memory_catalog[window.generation_id] = {
                "generation_id": window.generation_id,
                "generated_at_decision": decision_index,
                "context_sha256": canonical_sha256(decision_context),
                "context": list(decision_context),
            }

        if decision_index > 0:
            publication_timeline.append(
                {
                    "decision_index": decision_index,
                    "scored_timestep": decision_index * decision_window,
                    "absolute_timestep": int(spec["warmup_time"])
                    + decision_index * decision_window,
                    "requested": (
                        policy_record["requested"]
                        if policy_record is not None
                        else refresh
                    ),
                    "accepted": actual_switch,
                    "charged_to_post_bootstrap_budget": actual_switch,
                    "charged_to_post_bootstrap_switch_cap": actual_switch,
                    "charged_to_post_bootstrap_generation_cap": (
                        executed_operation == "generate"
                    ),
                    "charged_to_generator_budget": executed_operation == "generate",
                    "reason": action_reason,
                    "score": score_for_method(method, features),
                    "policy": policy_record,
                    "requested_operation": requested_operation,
                    "uncapped_proposed_operation": uncapped_proposed_operation,
                    "constraint_candidate": eventreserve_audit[
                        "constraint_candidate"
                    ],
                    "constraint_binding": eventreserve_audit[
                        "constraint_binding"
                    ],
                    "generation_cap_candidate_suppressed": (
                        dualcap_generation_candidate
                    ),
                    "generation_cap_blocked": dualcap_generation_binding,
                    "generation_cap_candidate": eventreserve_audit[
                        "generation_cap_candidate"
                    ],
                    "generation_cap_binding": (
                        dualcap_generation_binding
                        if method == CONTEXT_DUALCAP_METHOD
                        else eventreserve_audit["generation_cap_binding"]
                    ),
                    "eventreserve_reserve_active": eventreserve_audit[
                        "reserve_active"
                    ],
                    "eventreserve_reserve_candidate": eventreserve_audit[
                        "reserve_candidate"
                    ],
                    "eventreserve_preview_accepted": eventreserve_audit[
                        "reserve_preview_accepted"
                    ],
                    "eventreserve_preview_triggered": eventreserve_audit[
                        "reserve_preview_triggered"
                    ],
                    "eventreserve_event_preview_accepted": eventreserve_audit[
                        "reserve_event_preview_accepted"
                    ],
                    "eventreserve_event_preview_triggered": eventreserve_audit[
                        "reserve_event_preview_triggered"
                    ],
                    "eventreserve_reserve_qualified": eventreserve_audit[
                        "reserve_qualified"
                    ],
                    "eventreserve_reserve_binding": eventreserve_audit[
                        "reserve_binding"
                    ],
                    "executed_operation": executed_operation,
                    "target_generation_id": target_generation_id,
                    "active_generation_id_after": window.generation_id,
                    "active_context_distance": active_context_distance,
                    "nearest_context_distance": nearest_context_distance,
                    "guidance_version_before_decision": version_before_decision,
                    "guidance_version_installed_for_window": window.guidance_version,
                }
            )
        trace = dict(window.info["dai_trace"])
        prefixes, draws = _validate_tape_trace(
            trace,
            expected_sha=manifest["manifest_sha256"],
            expected_fnv=manifest["content_fnv1a64"],
            prior_prefixes=prefixes,
        )
        online_rng_draws += draws
        releases.extend(_release_records(trace))
        distribution_updates.extend(trace["recent_distribution_updates"])
        safety = audit_joint_paths(
            start_positions=previous_positions,
            actual_paths=trace["actual_paths"],
            end_positions=trace["curr_pos"],
            graph=graph,
        )
        safety_totals["collision_count"] += safety.collision_count
        safety_totals["edge_swap_count"] += safety.edge_swap_count
        safety_totals["invalid_move_count"] += safety.invalid_move_count
        safety_totals["endpoint_mismatch_count"] += safety.endpoint_mismatch_count
        safety_totals["planner_timeout_count"] += sum(
            record["timed_out"] for record in trace["recent_planner_times"]
        )
        safety_totals["route_trace_invalid_count"] += int(
            trace["route_build_trace_valid"] is not True
        )
        if fatal := _fatal_integrity_counts(safety_totals):
            raise RuntimeError(
                f"safety/integrity failure at decision {decision_index}: {fatal}"
            )
        tracker.ingest_trace(trace)
        tracker.observe_reward(window.reward)
        reward_sum += window.reward
        generator_seconds += window.generator_seconds
        simulator_seconds += window.simulator_seconds
        windows.append(
            {
                "decision_index": decision_index,
                "window_start_timestep": trace["window_start_timestep"],
                "window_end_timestep": trace["window_end_timestep"],
                "reward": window.reward,
                "refreshed_post_bootstrap": (
                    decision_index > 0 and executed_operation == "generate"
                ),
                "guidance_switched_post_bootstrap": (
                    decision_index > 0 and actual_switch
                ),
                "guidance_operation": executed_operation,
                "generation_id": window.generation_id,
                "installation_version": window.installation_version,
                "guidance_version": trace["guidance_version"],
                "guidance_sha256": trace["guidance_sha256"],
                "applied_guidance_sha256": trace["applied_guidance_sha256"],
                "map_weights_revision": trace.get("map_weights_revision"),
                "num_task_finished": trace["num_task_finished"],
                "planner_seconds": sum(
                    record["seconds"] for record in trace["recent_planner_times"]
                ),
                "generator_seconds": window.generator_seconds,
                "simulator_seconds": window.simulator_seconds,
                "released_count": len(_release_records(trace)),
                "assigned_prefix_total": sum(prefixes["assigned_prefix_lengths"]),
                "completed_prefix_total": sum(prefixes["completed_prefix_lengths"]),
                "features": features.as_dict(),
            }
        )
        previous_positions = trace["curr_pos"]

    if not adapter.done:
        raise RuntimeError("simulator did not terminate at the registered horizon")
    if len(windows) != total_windows:
        raise RuntimeError("simulator window count differs from H/D")
    if policy is not None:
        policy.finalize()
    if not math.isclose(reward_sum, trace["num_task_finished"], abs_tol=1e-9):
        raise RuntimeError("window rewards do not sum to scored task completions")
    generator_call_conservation_satisfied = bool(
        generator.calls == mandatory_bootstrap_calls + post_generations
    )
    if not generator_call_conservation_satisfied:
        raise RuntimeError("generator-call audit differs from generation timeline")
    switch_operation_partition_satisfied = bool(
        post_generations + post_reactivations == post_publications
    )
    if not switch_operation_partition_satisfied:
        raise RuntimeError("guidance switch audit does not partition by operation")
    if adapter.refresh_count != post_generations:
        raise RuntimeError("adapter generation count differs from run audit")
    if adapter.reactivation_count != post_reactivations:
        raise RuntimeError("adapter reactivation count differs from run audit")
    dualcap_generation_cap_binding_audit_satisfied = bool(
        0
        <= dualcap_generation_binding_count
        <= dualcap_generation_candidate_count
    )
    eventreserve_generation_cap_binding_audit_satisfied = bool(
        0 <= generation_cap_binding_count <= generation_cap_candidate_count
    )
    generation_cap_binding_audit_satisfied = bool(
        dualcap_generation_cap_binding_audit_satisfied
        and eventreserve_generation_cap_binding_audit_satisfied
    )
    if not generation_cap_binding_audit_satisfied:
        raise RuntimeError("generation-cap binding audit is inconsistent")
    eventreserve_audit_conservation_satisfied = bool(
        0
        <= reserve_preview_accept_count
        <= reserve_candidate_count
        and reserve_preview_accept_count
        == reserve_qualified_count + reserve_binding_count
        and reserve_qualified_count
        == reserve_execution_count + reserve_generation_cap_binding_count
        and 0 <= reserve_execution_count <= 1
    )
    if not eventreserve_audit_conservation_satisfied:
        raise RuntimeError("event-reserve candidate/binding audit is inconsistent")
    if method == CONTEXT_EVENTRESERVE_METHOD:
        if policy is None or policy.spent != post_publications:
            raise RuntimeError(
                "event-reserve policy spend differs from executed switches"
            )
        if reserve_execution_count and not (
            post_publications == registered_budget == 6
        ):
            raise RuntimeError(
                "reserved execution did not install the sixth switch"
            )

    exact_required = method in EXACT_BUDGET_METHODS or method == "uniform"
    exact_satisfied = (
        post_publications == registered_budget
        if registered_budget is not None
        else True
    )
    cap_satisfied = (
        post_publications <= registered_budget
        if registered_budget is not None
        else True
    )
    generation_cap_satisfied = (
        post_generations <= generation_cap
        if generation_cap is not None
        else True
    )
    total_generator_call_cap = (
        mandatory_bootstrap_calls + generation_cap
        if generation_cap is not None
        else None
    )
    total_generator_call_cap_satisfied = (
        generator.calls <= total_generator_call_cap
        if total_generator_call_cap is not None
        else True
    )
    if exact_required and not exact_satisfied:
        raise RuntimeError("exact post-bootstrap quota was not satisfied")
    if not cap_satisfied:
        raise RuntimeError("post-bootstrap publication cap was exceeded")
    if not generation_cap_satisfied:
        raise RuntimeError("post-bootstrap generator cap was exceeded")
    if not total_generator_call_cap_satisfied:
        raise RuntimeError("total generator-call cap was exceeded")
    final_tape = trace["task_tape"]
    tape_not_exhausted = _absolute_tape_has_unassigned_guard(final_tape)
    if not tape_not_exhausted:
        raise RuntimeError(
            "at least one agent consumed its complete finite absolute tape; "
            "extend the guard suffix"
        )
    elapsed = time.perf_counter() - run_started
    final_finished = int(trace["num_task_finished"])
    releases = sorted(
        releases,
        key=lambda item: (item["timestep"], item["agent_id"], item["task_id"]),
    )
    # Endpoint replay mismatches are invalid moves for the public schema while
    # remaining separately visible for debugging.
    safety_result = {
        **safety_totals,
        "invalid_move_count": safety_totals["invalid_move_count"]
        + safety_totals["endpoint_mismatch_count"],
        "passed": not bool(_fatal_integrity_counts(safety_totals)),
    }
    reported_budget = (
        post_publications if registered_budget is None else registered_budget
    )
    final_prefixes = {
        field: final_tape[field]
        for field in (
            "released_prefix_lengths",
            "assigned_prefix_lengths",
            "completed_prefix_lengths",
            "all_released",
            "all_completed",
        )
    }
    guidance_catalog: list[dict[str, Any]] = []
    if method in memory_methods:
        for record in adapter.guidance_catalog:
            metadata = memory_catalog.get(record.generation_id)
            if metadata is None:
                raise RuntimeError("cached guidance lacks causal context metadata")
            guidance_catalog.append({
                **metadata,
                "source": record.source,
                "raw_guidance_sha256": record.raw_guidance_digest,
                "applied_guidance_sha256": record.applied_guidance_digest,
            })
    result = {
        "method": method,
        "seed": seed,
        "root_seed": seed,
        "split": spec["split"],
        "evidence_class": spec["split"],
        "map_id": map_path.stem,
        "map_path": str(map_path),
        "workload": spec["workload"],
        "manifest_id": manifest["manifest_id"],
        "num_task_finished": final_finished,
        "throughput_per_timestep": final_finished / horizon,
        "scored_horizon": horizon,
        "decision_window": decision_window,
        "window_count": total_windows,
        "mandatory_bootstrap_calls": mandatory_bootstrap_calls,
        "post_bootstrap_publication_count": post_publications,
        "post_bootstrap_generation_count": post_generations,
        "post_bootstrap_reactivation_count": post_reactivations,
        "effective_guidance_switch_count": post_publications,
        "publication_budget": reported_budget,
        "budget_violation_count": budget_violation_attempts,
        "budget": {
            "mandatory_bootstrap_calls": mandatory_bootstrap_calls,
            "mandatory_bootstrap_counts_toward_post_caps": False,
            "eligible_post_bootstrap_decisions": eligible,
            "post_bootstrap_budget": reported_budget,
            "effective_guidance_switch_cap": registered_budget,
            "post_bootstrap_generation_cap": generation_cap,
            "total_generator_call_cap": total_generator_call_cap,
            "post_bootstrap_publication_count": post_publications,
            "post_bootstrap_generation_count": post_generations,
            "post_bootstrap_reactivation_count": post_reactivations,
            "effective_guidance_switch_count": post_publications,
            "total_generator_calls": generator.calls,
            "generator_call_conservation_satisfied": (
                generator_call_conservation_satisfied
            ),
            "switch_operation_partition_satisfied": (
                switch_operation_partition_satisfied
            ),
            "generation_cap_candidate_suppression_count": (
                dualcap_generation_candidate_count
            ),
            "generation_cap_block_count": dualcap_generation_binding_count,
            "generation_cap_candidate_count": generation_cap_candidate_count,
            "generation_cap_binding_count": (
                dualcap_generation_binding_count
                if method == CONTEXT_DUALCAP_METHOD
                else generation_cap_binding_count
            ),
            "generation_cap_binding_audit_satisfied": (
                generation_cap_binding_audit_satisfied
            ),
            "eventreserve_candidate_count": reserve_candidate_count,
            "eventreserve_preview_accept_count": (
                reserve_preview_accept_count
            ),
            "eventreserve_qualified_count": reserve_qualified_count,
            "eventreserve_binding_count": reserve_binding_count,
            "eventreserve_generation_cap_binding_count": (
                reserve_generation_cap_binding_count
            ),
            "eventreserve_execution_count": reserve_execution_count,
            "eventreserve_audit_conservation_satisfied": (
                eventreserve_audit_conservation_satisfied
            ),
            "budget_violation_attempts": budget_violation_attempts,
            "budget_semantics": (
                "generation_cap_4_switch_cap_5"
                if method == CONTEXT_DUALCAP_METHOD
                else "generation_cap_5_switch_cap_6_event_reserved_sixth"
                if method == CONTEXT_EVENTRESERVE_METHOD
                else "at_most_switch_and_generator_on_random_B25_opportunities"
                if method == "random_memory_B25"
                else "at_most_switch_and_generator"
                if method == "context_memory_B25"
                else "at_most" if method == "js_cap_B25"
                else "nominal_period" if method == "period_80"
                else "exact"
            ),
            "cap_satisfied": cap_satisfied,
            "switch_cap_satisfied": cap_satisfied,
            "generation_cap_satisfied": generation_cap_satisfied,
            "total_generator_call_cap_satisfied": (
                total_generator_call_cap_satisfied
            ),
            "exact_quota_required": exact_required,
            "exact_quota_satisfied": exact_satisfied,
            "nominal_period_steps": 80 if method == "period_80" else None,
        },
        "safety": safety_result,
        "collisions": safety_totals["collision_count"],
        "edge_swaps": safety_totals["edge_swap_count"],
        "invalid_moves": safety_totals["invalid_move_count"]
        + safety_totals["endpoint_mismatch_count"],
        "planner_timeouts": safety_totals["planner_timeout_count"],
        "route_build_reason_counts": dict(
            sorted(tracker.route_build_reason_counts.items())
        ),
        "task_tape_identity": identity,
        "final_task_tape_prefixes": final_prefixes,
        "reset_causal_fingerprint": _reset_fingerprint(
            reset_trace, canonical_sha256
        ),
        "release_projection_fingerprint": canonical_sha256(releases),
        "distribution_update_fingerprint": canonical_sha256(distribution_updates),
        "publication_timeline": publication_timeline,
        "guidance_catalog": guidance_catalog,
        "windows": windows,
        "workload_arrival": manifest["generator"],
        "generator_calls": generator.calls,
        "generator_seconds": generator_seconds,
        "simulator_seconds": simulator_seconds,
        "elapsed_seconds": elapsed,
        "timing_evidence_valid": bool(spec["timing_evidence_valid"]),
        "cohort_attribution_audit": {
            "route_exposed_completion_count": tracker.route_exposed_completion_count,
            "unexposed_zero_route_completion_count": (
                tracker.unexposed_zero_route_completion_count
            ),
            "unexposed_zero_route_completions_excluded": True,
            "admission_rule": (
                "assignment identity matches; finish latency is exactly one; "
                "route_build_trace_valid is true"
            ),
            "route_build_reason_counts": dict(
                sorted(tracker.route_build_reason_counts.items())
            ),
        },
        "invariants": {
            "passed": True,
            "online_workload_rng_draws": online_rng_draws,
            "release_projection_count": len(releases),
            "tape_not_exhausted": tape_not_exhausted,
            "reward_sum_matches_completed": True,
            "unexposed_completions_excluded_from_cohorts": True,
        },
    }
    del adapter, generator, env
    gc.collect()
    return result


def _run_cell(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep all method arms for one manifest in one worker process."""

    return [_run_one(spec) for spec in specs]


def _canonical_split(split: str) -> str:
    """Map a legacy split spelling to the only label new artifacts may use."""

    canonical = LEGACY_SPLIT_ALIASES.get(split, split)
    if canonical not in SPLIT_SEEDS:
        choices = sorted(set(SPLIT_SEEDS) | set(LEGACY_SPLIT_ALIASES))
        raise ValueError(f"unknown split {split!r}; expected one of {choices}")
    return canonical


def _split_protocol_metadata(split: str) -> dict[str, Any]:
    """Return audit metadata without exposing or mutating another split."""

    split = _canonical_split(split)
    metadata: dict[str, Any] = {
        "canonical_name": split,
        "preregistered_seeds": list(SPLIT_SEED_ORDER[split]),
        "sortation_maps_reserved_for_locked_test": True,
    }
    if split == "contaminated_pilot_validation":
        metadata.update({
            "classification": "contaminated_pilot_evidence_only",
            "legacy_artifact_split_labels": ["validation"],
            "fresh_validation_claim_permitted": False,
        })
    elif split == "validation_v2":
        metadata.update({
            "classification": "fresh_validation_v2",
            "seed_derivation_source_development_artifact_sha256": (
                VALIDATION_V2_SOURCE_DEVELOPMENT_SHA256
            ),
            "complete_registered_method_family_required": True,
            "complete_workload_family_required": True,
            "artifact_overwrite_permitted": False,
        })
    elif split == "locked_test":
        metadata["classification"] = "sealed_locked_test"
    else:
        metadata["classification"] = "development"
    return metadata


def _validate_split(split: str, seeds: Iterable[int], confirm_locked: bool) -> None:
    split = _canonical_split(split)
    seeds = tuple(seeds)
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("seeds must be non-empty and unique")
    if not set(seeds).issubset(SPLIT_SEEDS[split]):
        raise ValueError(f"{split} seeds must lie in {sorted(SPLIT_SEEDS[split])}")
    if split in COMPLETE_MATRIX_SPLITS and set(seeds) != set(
        SPLIT_SEEDS[split]
    ):
        raise ValueError(
            f"{split} must run its complete preregistered seed set in one artifact"
        )
    if split == "locked_test" and not confirm_locked:
        raise ValueError("locked test requires explicit --confirm-locked-test")


def _validate_protocol_matrix(
    split: str,
    methods: Iterable[str],
    workloads: Iterable[str],
    registered_methods: Iterable[str],
) -> None:
    """Require complete arms for protected evaluation splits."""

    split = _canonical_split(split)
    if split not in COMPLETE_MATRIX_SPLITS:
        return
    if set(methods) != set(registered_methods):
        raise ValueError(
            f"{split} must include the complete registered method family"
        )
    if set(workloads) != set(WORKLOADS):
        raise ValueError(
            f"{split} must include stationary, abrupt, and recurrent"
        )


def _ensure_output_is_writable(split: str, output: Path) -> None:
    """Protect every evaluation artifact from accidental replacement."""

    split = _canonical_split(split)
    protected_outputs = (output, output.with_suffix(".csv"))
    existing = [path for path in protected_outputs if path.exists()]
    if existing and split in OVERWRITE_PROTECTED_SPLITS:
        raise FileExistsError(
            f"refusing to overwrite protected {split} output(s): "
            + ", ".join(map(str, existing))
        )


def _validate_map_reservation(split: str, map_path: Path) -> None:
    """Keep every sortation map sealed until an explicit locked-test run."""

    split = _canonical_split(split)
    if "sortation" in map_path.stem.lower() and split != "locked_test":
        raise ValueError("sortation maps remain reserved for locked_test")


def _cross_method_gate(runs: list[dict[str, Any]], methods: list[str]) -> None:
    cells: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        key = (run["seed"], run["map_id"], run["workload"])
        cells.setdefault(key, []).append(run)
    for key, arms in cells.items():
        if {run["method"] for run in arms} != set(methods):
            raise RuntimeError(f"cell {key} is missing registered method arms")
        for field in (
            "manifest_id",
            "reset_causal_fingerprint",
            "release_projection_fingerprint",
            "distribution_update_fingerprint",
        ):
            if len({run[field] for run in arms}) != 1:
                raise RuntimeError(f"cell {key} is not paired on {field}")
        if len(
            {
                json.dumps(run["task_tape_identity"], sort_keys=True)
                for run in arms
            }
        ) != 1:
            raise RuntimeError(f"cell {key} has different task-tape identities")
        if any(not run["safety"]["passed"] for run in arms):
            raise RuntimeError(f"cell {key} contains a safety failure")


def _summaries(runs: list[dict[str, Any]], methods: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    exact = {
        (run["seed"], run["map_id"], run["workload"]): run
        for run in runs
        if run["method"] == "exact_even_B25"
    }
    for method in methods:
        selected = [run for run in runs if run["method"] == method]
        throughputs = [run["throughput_per_timestep"] for run in selected]
        summary: dict[str, Any] = {
            "mean_throughput": statistics.fmean(throughputs),
            "mean_num_task_finished": statistics.fmean(
                run["num_task_finished"] for run in selected
            ),
            "mean_post_bootstrap_publications": statistics.fmean(
                run["post_bootstrap_publication_count"] for run in selected
            ),
        }
        if exact and method != "exact_even_B25":
            effects = []
            for run in selected:
                baseline = exact[(run["seed"], run["map_id"], run["workload"])]
                effects.append(
                    (run["throughput_per_timestep"] - baseline["throughput_per_timestep"])
                    / baseline["throughput_per_timestep"]
                )
            summary["mean_paired_relative_vs_exact_even_B25"] = statistics.fmean(
                effects
            )
        result[method] = summary
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256")
    parser.add_argument("--checkpoint-params-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--development-matrix-config-sha256",
        help=(
            "optional frozen development-matrix config digest to seal into "
            "the emitted artifact"
        ),
    )
    parser.add_argument(
        "--split",
        choices=tuple(SPLIT_SEEDS) + tuple(LEGACY_SPLIT_ALIASES),
        default="development",
    )
    parser.add_argument("--confirm-locked-test", action="store_true")
    parser.add_argument("--seeds", nargs="+", type=int, default=[17, 18, 19])
    parser.add_argument("--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS))
    parser.add_argument("--methods", nargs="+", default=None)
    parser.add_argument("--map-path", type=Path)
    parser.add_argument("--agents", type=int, default=400)
    parser.add_argument("--warmup-time", type=int, default=200)
    parser.add_argument("--horizon", type=int, default=2000)
    parser.add_argument("--decision-window", type=int, default=20)
    parser.add_argument("--release-interval", type=int, default=110)
    parser.add_argument("--guard-suffix", type=int, default=4)
    parser.add_argument("--sigma", type=float, default=0.75)
    parser.add_argument("--pacing-slack", type=int, default=2)
    parser.add_argument("--minimum-history", type=int, default=4)
    parser.add_argument("--context-match-threshold", type=float, default=0.10)
    parser.add_argument("--context-recall-margin", type=float, default=0.02)
    parser.add_argument("--context-min-score", type=float, default=0.10)
    parser.add_argument("--context-min-gap", type=int, default=6)
    parser.add_argument("--context-maintenance-age", type=int, default=25)
    parser.add_argument("--context-maintenance-stability", type=float, default=0.20)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--exclusive-timing",
        action="store_true",
        help="declare exclusive hardware allocation for a sequential timing run",
    )
    args = parser.parse_args()
    # The legacy spelling is accepted only to reproduce an old invocation;
    # newly emitted artifacts always carry the canonical contaminated label.
    args.split = _canonical_split(args.split)

    if args.development_matrix_config_sha256 is not None:
        digest = args.development_matrix_config_sha256.lower()
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError(
                "--development-matrix-config-sha256 must be 64 hexadecimal digits"
            )
        if args.split != "development":
            raise ValueError(
                "a development-matrix config digest is valid only for development"
            )
        args.development_matrix_config_sha256 = digest

    workspace = args.workspace.resolve()
    onlineggo, cmaes = _configure_paths(workspace)
    from dai_lmapf.claim_runner import (
        AVAILABLE_METHODS,
        CLAIM_RUNNER_SCHEMA,
        REGISTERED_METHODS,
    )
    from dai_lmapf.frozen_cnn_generator import load_frozen_cnn_checkpoint

    methods = list(REGISTERED_METHODS) if args.methods is None else args.methods
    if len(methods) != len(set(methods)) or not set(methods).issubset(
        AVAILABLE_METHODS
    ):
        raise ValueError("methods must be unique available method names")
    if "exact_even_B25" not in methods:
        raise ValueError("claim runner requires the primary exact_even_B25 comparator")
    if len(args.workloads) != len(set(args.workloads)):
        raise ValueError("workloads must be unique")
    _validate_split(args.split, args.seeds, args.confirm_locked_test)
    _validate_protocol_matrix(
        args.split, methods, args.workloads, REGISTERED_METHODS
    )
    if args.horizon <= 0 or args.horizon % args.decision_window:
        raise ValueError("horizon must be positive and divisible by decision-window")
    if args.horizon // args.decision_window < 2:
        raise ValueError("at least two scored windows are required")
    if args.split == "locked_test" and (
        args.horizon != 2000 or args.decision_window != 20
    ):
        raise ValueError("locked test protocol requires H=2000,D=20")
    if args.jobs <= 0:
        raise ValueError("jobs must be positive")
    if not 0.0 <= args.context_match_threshold <= 1.0:
        raise ValueError("--context-match-threshold must lie in [0, 1]")
    if not 0.0 <= args.context_recall_margin <= 1.0:
        raise ValueError("--context-recall-margin must lie in [0, 1]")
    if not 0.0 <= args.context_min_score <= 1.0:
        raise ValueError("--context-min-score must lie in [0, 1]")
    if args.context_min_gap < 0:
        raise ValueError("--context-min-gap must be non-negative")
    if args.context_maintenance_age < 1:
        raise ValueError("--context-maintenance-age must be positive")
    if not 0.0 <= args.context_maintenance_stability <= 1.0:
        raise ValueError("--context-maintenance-stability must lie in [0, 1]")
    if args.guard_suffix < 4:
        raise ValueError("--guard-suffix must be at least 4")
    if args.exclusive_timing and args.jobs != 1:
        raise ValueError("exclusive timing evidence requires --jobs 1")
    map_path = (
        args.map_path.resolve()
        if args.map_path is not None
        else (
            onlineggo
            / "Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
            / "warehouse_small_narrow_kiva.map"
        ).resolve()
    )
    if not map_path.is_file():
        raise FileNotFoundError(map_path)
    _validate_map_reservation(args.split, map_path)
    checkpoint = load_frozen_cnn_checkpoint(
        args.checkpoint.resolve(),
        expected_file_sha256=args.checkpoint_sha256,
        expected_params_sha256=args.checkpoint_params_sha256,
    )
    if args.split != "development" and (
        args.checkpoint_sha256 is None or args.checkpoint_params_sha256 is None
    ):
        raise ValueError(
            f"{args.split} requires both predeclared checkpoint hashes"
        )
    output = args.output.resolve()
    _ensure_output_is_writable(args.split, output)

    module_paths = sorted(
        (cmaes / "simulators" / "trafficMAPF_on").glob("period_on_sim*.so")
    )
    if len(module_paths) != 1:
        raise RuntimeError("expected exactly one compiled period_on_sim module")
    common = {
        "workspace": str(workspace),
        "checkpoint": str(checkpoint.path),
        "checkpoint_sha256": checkpoint.file_sha256,
        "checkpoint_params_sha256": checkpoint.params_sha256,
        "split": args.split,
        "map_path": str(map_path),
        "agents": args.agents,
        "warmup_time": args.warmup_time,
        "horizon": args.horizon,
        "decision_window": args.decision_window,
        "release_interval": args.release_interval,
        "guard_suffix": args.guard_suffix,
        "sigma": args.sigma,
        "pacing_slack": args.pacing_slack,
        "minimum_history": args.minimum_history,
        "context_match_threshold": args.context_match_threshold,
        "context_recall_margin": args.context_recall_margin,
        "context_min_score": args.context_min_score,
        "context_min_gap": args.context_min_gap,
        "context_maintenance_age": args.context_maintenance_age,
        "context_maintenance_stability": args.context_maintenance_stability,
        "timing_evidence_valid": args.jobs == 1 and args.exclusive_timing,
    }
    cells: list[list[dict[str, Any]]] = []
    for seed in args.seeds:
        for workload in args.workloads:
            method_order = list(methods)
            # Each cell's order is precommitted by a stream independent of all
            # simulator/task/policy RNG streams.
            random.Random(
                _keyed_uint32("method-order", args.split, seed, workload)
            ).shuffle(method_order)
            cells.append([
                {**common, "seed": seed, "workload": workload, "method": method}
                for method in method_order
            ])
    random.Random(_keyed_uint32("cell-order", args.split, *args.seeds)).shuffle(cells)
    work = [spec for cell in cells for spec in cell]
    runs: list[dict[str, Any]] = []
    if args.jobs == 1:
        for index, spec in enumerate(work, 1):
            print(
                f"CLAIM_RUN start {index}/{len(work)} method={spec['method']} "
                f"seed={spec['seed']} workload={spec['workload']}",
                flush=True,
            )
            run = _run_one(spec)
            runs.append(run)
            print(
                f"CLAIM_RUN done method={run['method']} seed={run['seed']} "
                f"workload={run['workload']} tasks={run['num_task_finished']} "
                f"post_pubs={run['post_bootstrap_publication_count']}",
                flush=True,
            )
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=args.jobs, mp_context=context) as executor:
            futures = {executor.submit(_run_cell, cell): cell for cell in cells}
            for future in as_completed(futures):
                cell_runs = future.result()
                runs.extend(cell_runs)
                for run in cell_runs:
                    print(
                        f"CLAIM_RUN done method={run['method']} seed={run['seed']} "
                        f"workload={run['workload']} tasks={run['num_task_finished']} "
                        f"post_pubs={run['post_bootstrap_publication_count']}",
                        flush=True,
                    )
    runs.sort(key=lambda run: (run["seed"], run["workload"], run["method"]))
    _cross_method_gate(runs, methods)
    manifests = {
        run["manifest_id"]: {
            "seed": run["seed"],
            "map_id": run["map_id"],
            "workload": run["workload"],
            "task_tape_identity": run["task_tape_identity"],
            "release_projection_fingerprint": run["release_projection_fingerprint"],
            "arrival": run["workload_arrival"],
        }
        for run in runs
    }
    artifact = {
        "schema": CLAIM_RUNNER_SCHEMA,
        "status": "complete",
        "evidence_class": args.split,
        "split": args.split,
        "development_matrix_config_sha256": (
            args.development_matrix_config_sha256
        ),
        "split_protocol": _split_protocol_metadata(args.split),
        "claim_scope": (
            "paired causal throughput-publication comparison on absolute release "
            "tapes; a global LMAPF SOTA claim additionally requires the complete "
            "registered map/backbone/locked-test matrix"
        ),
        "seeds": args.seeds,
        "methods": methods,
        "workloads": args.workloads,
        "map_id": map_path.stem,
        "map_path": str(map_path),
        "map_sha256": _sha256_file(map_path),
        "period_on_sim_sha256": _sha256_file(module_paths[0]),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "protocol": {
            "agents": args.agents,
            "warmup_time": args.warmup_time,
            "scored_horizon": args.horizon,
            "decision_window": args.decision_window,
            "num_scored_windows": args.horizon // args.decision_window,
            "eligible_post_bootstrap_decisions": args.horizon // args.decision_window - 1,
            "b25_budget": math.ceil(
                0.25 * (args.horizon // args.decision_window - 1)
            ),
            "release_interval_per_agent": args.release_interval,
            "deterministic_agent_stagger": True,
            "guard_suffix_tasks_per_agent": args.guard_suffix,
            "sigma": args.sigma,
            "pacing_slack": args.pacing_slack,
            "minimum_history": args.minimum_history,
            "causal_block_B25": {
                "score": "release_only_4x4_fast2_vs_prior6_js",
                "score_quantile": 0.75,
                "max_advance_windows": 2,
                "min_gap_windows": 2,
                "early_route_maturity_threshold": 0.5,
                "quota_rule": "exactly_one_publication_per_even_quota_bucket",
            },
            "js_cap_B25": {
                "score": "active_goal_js_since_last_publication",
                "score_quantile": 0.75,
                "min_gap_windows": 2,
                "minimum_effect_windows": 3,
                "quota_rule": "at_most_B25_with_no_catch_up_or_forced_fill",
            },
            "context_memory_B25": {
                "actions": ["hold", "reactivate", "generate"],
                "score": "release_only_4x4_fast2_vs_prior6_js",
                "score_quantile": 0.75,
                "absolute_score_gate": args.context_min_score,
                "active_route_fraction_gate": 0.5,
                "min_gap_windows": args.context_min_gap,
                "maintenance_age_windows": args.context_maintenance_age,
                "maintenance_stability_gate": args.context_maintenance_stability,
                "minimum_effect_windows": 3,
                "context": "causal_active_goal_4x4",
                "recall_threshold": args.context_match_threshold,
                "recall_margin": args.context_recall_margin,
                "quota_rule": "at_most_B25_for_both_switches_and_generations",
            },
            "context_dualcap_G4S5": {
                "development_only": True,
                "base_controller": "context_memory_B25",
                "actions": ["hold", "reactivate", "generate"],
                "score": "release_only_4x4_fast2_vs_prior6_js",
                "score_quantile": 0.75,
                "absolute_score_gate": args.context_min_score,
                "active_route_fraction_gate": 0.5,
                "min_gap_windows": args.context_min_gap,
                "maintenance_age_windows": args.context_maintenance_age,
                "maintenance_stability_gate": args.context_maintenance_stability,
                "minimum_effect_windows": 3,
                "context": "causal_active_goal_4x4",
                "recall_threshold": args.context_match_threshold,
                "recall_margin": args.context_recall_margin,
                "post_bootstrap_generation_cap": 4,
                "effective_guidance_switch_cap": 5,
                "mandatory_bootstrap_counts_toward_post_caps": False,
                "total_generator_call_cap": 5,
                "generation_cap_state": (
                    "past_executed_post_bootstrap_generations_only"
                ),
                "quota_rule": "at_most_G4_fresh_generations_and_S5_switches",
            },
            "context_eventreserve_G5S6": {
                "development_only": True,
                "base_controller": "context_memory_B25",
                "actions": ["hold", "reactivate", "generate"],
                "score": "release_only_4x4_fast2_vs_prior6_js",
                "score_quantile": 0.75,
                "absolute_score_gate": args.context_min_score,
                "active_route_fraction_gate": 0.5,
                "min_gap_windows": args.context_min_gap,
                "maintenance_age_windows": args.context_maintenance_age,
                "maintenance_stability_gate": args.context_maintenance_stability,
                "minimum_effect_windows": 3,
                "context": "causal_active_goal_4x4",
                "recall_threshold": args.context_match_threshold,
                "recall_margin": args.context_recall_margin,
                "post_bootstrap_generation_cap": 5,
                "effective_guidance_switch_cap": 6,
                "mandatory_bootstrap_counts_toward_post_caps": False,
                "total_generator_call_cap": 6,
                "generation_cap_state": (
                    "past_executed_post_bootstrap_generations_only"
                ),
                "sixth_switch_reserve": (
                    "fresh_generation_only_with_accepted_triggered_"
                    "unconstrained_preview_and_not_maintenance_only"
                ),
                "reactivation_generation_charge": 0,
                "quota_rule": (
                    "at_most_G5_fresh_generations_and_S6_switches_with_"
                    "event_reserved_sixth_switch"
                ),
            },
            "random_memory_B25": {
                "actions": ["hold", "reactivate", "generate"],
                "opportunity_schedule": (
                    "bit_for_bit_shared_with_random_B25_for_each_root_seed"
                ),
                "context": "causal_active_goal_4x4",
                "recall_threshold": args.context_match_threshold,
                "recall_margin": args.context_recall_margin,
                "fallback": "generate_at_each_accepted_random_opportunity",
                "quota_rule": "at_most_B25_for_both_switches_and_generations",
            },
            "method_order_randomized_with_independent_seed": True,
            "jobs": args.jobs,
            "exclusive_timing_declared": args.exclusive_timing,
            "timing_evidence_valid": args.jobs == 1 and args.exclusive_timing,
            "causal_feature_allowlist": (
                "released/current goals, completed rewards, executed paths, waits, "
                "route-build versions, service outcomes, guidance age and spent budget"
            ),
            "causal_feature_forbidden_fields": [
                "recent_distribution_updates",
                "manifest phase boundaries or centres",
                "unreleased absolute-task-tape suffix",
                "future rewards or route builds",
            ],
            "distribution_update_fingerprint_semantics": (
                "pairing/instrumentation audit only; it is not the absolute-tape "
                "phase fingerprint and is never consumed by a controller"
            ),
            "planner_timeout_semantics": (
                "timeout count is a method outcome, not a collision/safety failure; "
                "if the pinned backend invalidates state and aborts, the runner "
                "refuses to emit a complete artifact rather than silently delete "
                "or splice the arm"
            ),
        },
        "generator": checkpoint.metadata(),
        "manifests": manifests,
        "summaries": _summaries(runs, methods),
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        fields = [
            "method",
            "seed",
            "map_id",
            "workload",
            "num_task_finished",
            "throughput_per_timestep",
            "mandatory_bootstrap_calls",
            "post_bootstrap_publication_count",
            "publication_budget",
            "budget_violation_count",
            "generator_seconds",
            "simulator_seconds",
            "elapsed_seconds",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            writer.writerow({field: run[field] for field in fields})
    print(json.dumps(artifact["summaries"], indent=2, sort_keys=True))
    print(f"artifact={output}")
    print(f"csv={csv_path}")


if __name__ == "__main__":
    main()
