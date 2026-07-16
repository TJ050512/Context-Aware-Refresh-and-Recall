#!/usr/bin/env python3
"""Paired development-tape gate for frozen OnlineGGO CNN checkpoints.

This is a checkpoint-selection diagnostic, not the full trigger/SOTA test.  It
compares both bootstrap-once and a common nominal-m80 publication schedule
under exactly the same absolute-time workload manifest for every candidate.
Both Python SHA-256 and C++ FNV tape identities are checked.  Validation/test
seeds are rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


DEV_SEEDS = tuple(range(17, 27))
CONTAMINATED_PILOT_VALIDATION_SEEDS = frozenset(range(101, 111))
FRESH_VALIDATION_V2_SEEDS = frozenset({
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
})
LOCKED_TEST_SEEDS = frozenset(range(1001, 1031))
FORBIDDEN_SEEDS = (
    CONTAMINATED_PILOT_VALIDATION_SEEDS
    | FRESH_VALIDATION_V2_SEEDS
    | LOCKED_TEST_SEEDS
)


def _candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("checkpoint must be LABEL=/path/file.json")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise argparse.ArgumentTypeError("checkpoint label and path are required")
    return label, Path(raw_path)


def _keyed_index(size: int, *parts: object) -> int:
    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _keyed_uint32(*parts: object) -> int:
    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _bootstrap_ci(values: list[float], *, draws: int = 10_000) -> list[float]:
    import numpy as np

    if not values:
        raise ValueError("bootstrap requires paired values")
    rng = np.random.default_rng(20260714)
    data = np.asarray(values, dtype=float)
    sampled = data[rng.integers(0, len(data), size=(draws, len(data)))].mean(axis=1)
    return [float(value) for value in np.quantile(sampled, [0.025, 0.975])]


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


def _js_divergence(left: list[float], right: list[float]) -> float:
    midpoint = [(a + b) / 2.0 for a, b in zip(left, right)]

    def kl(first: list[float], second: list[float]) -> float:
        return math.fsum(
            value * math.log(value / target)
            for value, target in zip(first, second)
            if value > 0
        )

    return 0.5 * kl(left, midpoint) + 0.5 * kl(right, midpoint)


def _separated_phase_centers(
    *, kiva_map: Any, seed: int, phase_count: int, sigma: float, minimum_js: float
) -> tuple[list[int], list[float]]:
    endpoints = kiva_map.endpoint_locations
    centers: list[int] = []
    distributions: list[list[float]] = []
    adjacent_js: list[float] = []
    for phase_index in range(phase_count):
        start = _keyed_index(
            len(endpoints), "dai-dev-centre", seed, phase_index
        )
        selected = None
        selected_distribution = None
        selected_js = None
        for offset in range(len(endpoints)):
            candidate = endpoints[(start + offset) % len(endpoints)]
            if candidate in centers:
                continue
            distribution = _endpoint_distribution(kiva_map, candidate, sigma)
            divergence = (
                None
                if not distributions
                else _js_divergence(distributions[-1], distribution)
            )
            if divergence is None or divergence >= minimum_js:
                selected = candidate
                selected_distribution = distribution
                selected_js = divergence
                break
        if selected is None or selected_distribution is None:
            raise RuntimeError(
                "could not construct deterministically separated workload phases"
            )
        centers.append(selected)
        distributions.append(selected_distribution)
        if selected_js is not None:
            adjacent_js.append(selected_js)
    return centers, adjacent_js


def _snap_phase_starts(
    *, release_times: list[int], warmup_time: int,
    requested_scored_starts: list[int],
) -> tuple[list[int], list[int]]:
    """Snap latent phase boundaries to actual exogenous release epochs."""

    if not release_times or release_times[0] != 0:
        raise ValueError("release_times must begin at zero")
    requested_absolute = [
        warmup_time + offset for offset in requested_scored_starts
    ]
    absolute = [0] + [
        min(release_times, key=lambda release: (abs(release - target), release))
        for target in requested_absolute
    ]
    if any(left >= right for left, right in zip(absolute, absolute[1:])):
        raise ValueError("effective phase starts must be strictly increasing")
    return absolute, [start - warmup_time for start in absolute[1:]]


def _staggered_release_schedules(
    *, n_agents: int, total_steps: int, interval: int, guard_suffix: int
) -> tuple[list[list[int]], dict[str, Any]]:
    """Construct the deterministic per-agent stagger used by the claim runner."""

    if n_agents <= 0 or total_steps <= 1 or interval <= 0:
        raise ValueError("release schedule dimensions must be positive")
    if guard_suffix < 4:
        raise ValueError(
            "at least four final guard tasks are required for a conservative "
            "non-exhaustion sentinel"
        )
    guard_timestep = total_steps - 1
    schedules: list[list[int]] = []
    regular_counts: dict[int, int] = {}
    for agent_id in range(n_agents):
        offset = (agent_id * interval) // n_agents
        regular = list(range(offset, guard_timestep, interval))
        for release in regular:
            regular_counts[release] = regular_counts.get(release, 0) + 1
        schedules.append(regular + [guard_timestep] * guard_suffix)
    regular_release_count = sum(regular_counts.values())
    metadata = {
        "schedule": "deterministic_agent_stagger/v1",
        "release_interval_per_agent": interval,
        "nominal_arrival_rate_tasks_per_timestep": n_agents / interval,
        "maximum_regular_arrivals_in_one_timestep": max(regular_counts.values()),
        "regular_release_count": regular_release_count,
        "regular_release_timestep_count": len(regular_counts),
        "guard_suffix_tasks_per_agent": guard_suffix,
        "guard_suffix_total_tasks": n_agents * guard_suffix,
        "guard_suffix_release_timestep": guard_timestep,
        "guard_suffix_purpose": (
            "non-scoring end sentinel that prevents any method from consuming "
            "the complete finite tape before the horizon"
        ),
        "total_task_tape_entries": regular_release_count + n_agents * guard_suffix,
    }
    return schedules, metadata


def _regular_release_union(
    schedules: list[list[int]], *, guard_suffix: int
) -> list[int]:
    if not schedules or guard_suffix < 4:
        raise ValueError("regular release projection requires guarded schedules")
    regular = sorted({
        release
        for schedule in schedules
        for release in schedule[:-guard_suffix]
    })
    if not regular or regular[0] != 0:
        raise ValueError("regular release projection must begin at zero")
    return regular


def _expected_schedule_calls(
    schedule: str, *, horizon: int, decision_window: int
) -> int:
    if horizon <= 0 or decision_window <= 0 or horizon % decision_window:
        raise ValueError("call-count protocol requires complete decision windows")
    window_count = horizon // decision_window
    if schedule == "never":
        return 1
    if schedule.startswith("period_"):
        period = int(schedule.split("_", 1)[1])
        if period <= 0:
            raise ValueError("publication period must be positive")
        return len({
            (decision_index * decision_window) // period
            for decision_index in range(window_count)
        })
    raise ValueError(f"unsupported checkpoint-gate schedule {schedule!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--checkpoint", action="append", type=_candidate, required=True)
    parser.add_argument("--baseline-label", default="2k")
    parser.add_argument("--candidate-label", default="10k")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEV_SEEDS))
    parser.add_argument("--agents", type=int, default=400)
    parser.add_argument("--warmup-time", type=int, default=200)
    parser.add_argument("--horizon", type=int, default=2000)
    parser.add_argument("--decision-window", type=int, default=20)
    # With 400 agents this is roughly 3.64 exogenous arrivals/timestep, above
    # the observed 3.2--3.4 completion rate without creating the enormous
    # backlog induced by interval 40. A much shorter
    # interval (e.g. 40) creates a growing queue whose phase labels may not
    # become visible until hundreds of steps after their registered release.
    parser.add_argument("--release-interval", type=int, default=110)
    parser.add_argument("--guard-suffix", type=int, default=4)
    parser.add_argument("--sigma", type=float, default=0.75)
    parser.add_argument("--minimum-adjacent-phase-js", type=float, default=0.30)
    args = parser.parse_args()

    labels = [label for label, _ in args.checkpoint]
    if len(labels) < 2 or len(labels) != len(set(labels)):
        raise ValueError("provide at least two uniquely labelled checkpoints")
    if args.baseline_label not in labels or args.candidate_label not in labels:
        raise ValueError("baseline-label and candidate-label must name checkpoints")
    if args.baseline_label == args.candidate_label:
        raise ValueError("baseline-label and candidate-label must differ")
    if len(args.seeds) != len(set(args.seeds)):
        raise ValueError("seeds must be unique")
    if not set(args.seeds).issubset(DEV_SEEDS) or set(args.seeds) & FORBIDDEN_SEEDS:
        raise ValueError("checkpoint gate is restricted to development seeds 17--26")
    if set(args.seeds) != set(DEV_SEEDS):
        raise ValueError(
            "checkpoint selection requires the complete development block 17--26"
        )
    if args.horizon % args.decision_window:
        raise ValueError("horizon must be divisible by decision-window")
    if args.release_interval <= 0:
        raise ValueError("release-interval must be positive")
    if args.guard_suffix < 4:
        raise ValueError("guard-suffix must be at least four")
    if not math.isfinite(args.sigma) or args.sigma <= 0:
        raise ValueError("sigma must be finite and positive")
    if not 0.0 <= args.minimum_adjacent_phase_js <= math.log(2.0):
        raise ValueError("minimum-adjacent-phase-js must lie in [0, log(2)]")

    workspace = args.workspace.resolve()
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    sys.path[:0] = [str(workspace / "src"), str(cmaes), str(workspace / "scripts")]

    from dai_lmapf.absolute_workload import (
        build_absolute_task_tape_manifest,
        generate_phase_shifted_kiva_tape,
        read_kiva_map,
    )
    from dai_lmapf.frozen_cnn_generator import load_frozen_cnn_checkpoint
    from dai_lmapf.online_ggo_adapter import OnlineGGOAdapter
    from env_search.iterative_update.envs.trafficflow_online_env import (
        TrafficFlowOnlineEnv,
        _dai_derive_seed,
        generate_kiva_saturated_goal_tape,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig
    from gate0_publication_mvp import _run_condition

    map_path = (
        onlineggo / "Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
        "warehouse_small_narrow_kiva.map"
    ).resolve()
    kiva_map = read_kiva_map(map_path)
    checkpoints = {
        label: load_frozen_cnn_checkpoint(path.resolve())
        for label, path in args.checkpoint
    }
    total_steps = args.warmup_time + args.horizon
    release_schedules, arrival_metadata = _staggered_release_schedules(
        n_agents=args.agents,
        total_steps=total_steps,
        interval=args.release_interval,
        guard_suffix=args.guard_suffix,
    )
    regular_release_times = _regular_release_union(
        release_schedules, guard_suffix=args.guard_suffix
    )
    requested_scored_phase_starts = [500, 1000, 1500]
    phase_starts, effective_scored_phase_starts = _snap_phase_starts(
        release_times=regular_release_times,
        warmup_time=args.warmup_time,
        requested_scored_starts=requested_scored_phase_starts,
    )
    if phase_starts[-1] >= total_steps:
        raise ValueError(
            "registered scored phase starts require at least 1501 horizon steps"
        )

    runs: list[dict[str, Any]] = []
    manifests: dict[str, dict[str, Any]] = {}
    for seed in args.seeds:
        starts_artifact = generate_kiva_saturated_goal_tape(
            str(map_path), args.agents, 1, seed
        )
        centers, adjacent_phase_js = _separated_phase_centers(
            kiva_map=kiva_map,
            seed=seed,
            phase_count=len(phase_starts),
            sigma=args.sigma,
            minimum_js=args.minimum_adjacent_phase_js,
        )
        starts = [int(value) for value in starts_artifact["start_locations"]]
        if len(starts) != args.agents or len(set(starts)) != args.agents:
            raise RuntimeError("start generator did not return unique agent starts")
        task_seed = _dai_derive_seed(seed, 2)
        tape: list[list[list[int]]] = []
        for agent_id, (start, schedule) in enumerate(
            zip(starts, release_schedules)
        ):
            generated = generate_phase_shifted_kiva_tape(
                kiva_map=kiva_map,
                start_locations=[start],
                release_timesteps=schedule,
                phase_starts=phase_starts,
                endpoint_phase_centers=centers,
                task_seed=_keyed_uint32(task_seed, "agent", agent_id),
                sigma=args.sigma,
            )
            tape.append(generated[0])
        total_tape_tasks = sum(len(sequence) for sequence in tape)
        if total_tape_tasks != arrival_metadata["total_task_tape_entries"]:
            raise RuntimeError("staggered tape length disagrees with arrival manifest")
        manifest = build_absolute_task_tape_manifest(
            starts, tape,
            generator={
                "name": "dai_dev_abrupt_checkpoint_gate/v1",
                "root_seed": seed,
                "phase_starts": phase_starts,
                "requested_scored_phase_starts": requested_scored_phase_starts,
                "effective_scored_phase_starts": effective_scored_phase_starts,
                "phase_centers": centers,
                "adjacent_endpoint_distribution_js": adjacent_phase_js,
                "minimum_adjacent_phase_js": args.minimum_adjacent_phase_js,
                "warmup_time": args.warmup_time,
                "scored_horizon": args.horizon,
                "task_seed": task_seed,
                **arrival_metadata,
            },
        )
        manifests[str(seed)] = {
            "manifest_sha256": manifest["manifest_sha256"],
            "content_fnv1a64": manifest["content_fnv1a64"],
            "phase_centers": centers,
            "adjacent_endpoint_distribution_js": adjacent_phase_js,
            "effective_scored_phase_starts": effective_scored_phase_starts,
            "generator": manifest["generator"],
        }

        def config_factory() -> Any:
            return TrafficMAPFConfig(
                map_path=str(map_path), simu_time=args.horizon,
                num_agents=args.agents, num_tasks=total_tape_tasks,
                gen_tasks=True, num_tasks_reveal=1,
                task_assignment_strategy="roundrobin",
                update_gg_interval=args.decision_window,
                warmup_time=args.warmup_time,
                past_traffic_interval=args.decision_window,
                task_dist_change_interval=-1, initial_task_distribution_phase=0,
                absolute_task_tape=tape,
                absolute_task_tape_start_locations=starts,
                has_traffic_obs=True, has_gg_obs=False, has_task_obs=True,
                has_map_obs=False,
            )

        seed_runs = []
        for schedule in ("never", "period_80"):
            for label, checkpoint in checkpoints.items():
                print(
                    f"CHECKPOINT_GATE start checkpoint={label} "
                    f"schedule={schedule} seed={seed}", flush=True,
                )
                run = _run_condition(
                    method=schedule, seed=seed, config_factory=config_factory,
                    env_class=TrafficFlowOnlineEnv, adapter_class=OnlineGGOAdapter,
                    generator_mode="frozen_cnn",
                    generator_kwargs={
                        "checkpoint_path": str(checkpoint.path),
                        "expected_file_sha256": checkpoint.file_sha256,
                        "expected_params_sha256": checkpoint.params_sha256,
                    },
                    decision_window=args.decision_window,
                    warmup_time=args.warmup_time,
                    shift_interval=phase_starts[1],
                    event_threshold=0.02, event_minimum_gap=40,
                    cohort_delay=40, cohort_min_route_builds=40,
                    horizon=args.horizon,
                )
                identity = run["task_tape_identity"]
                if identity["manifest_sha256"] != manifest["manifest_sha256"]:
                    raise RuntimeError(
                        "checkpoint arms received different workload content"
                    )
                if identity["content_fnv1a64"] != manifest["content_fnv1a64"]:
                    raise RuntimeError("C++ workload fingerprint differs from manifest")
                expected_calls = _expected_schedule_calls(
                    schedule,
                    horizon=args.horizon,
                    decision_window=args.decision_window,
                )
                if run["generator_calls"] != expected_calls:
                    raise RuntimeError(
                        f"{schedule} made {run['generator_calls']} generator "
                        f"calls; expected {expected_calls}"
                    )
                if run["publication_count"] != expected_calls:
                    raise RuntimeError(
                        f"{schedule} made {run['publication_count']} publications; "
                        f"expected {expected_calls}"
                    )
                final_prefixes = run["final_task_tape_prefixes"]
                if final_prefixes["all_released"] is not True:
                    raise RuntimeError("guard suffix was not released by the horizon")
                if any(
                    assigned >= length
                    for assigned, length in zip(
                        final_prefixes["assigned_prefix_lengths"],
                        identity["per_agent_lengths"],
                    )
                ):
                    raise RuntimeError(
                        "final guard suffix failed to keep every per-agent tape live"
                    )
                run["expected_generator_calls"] = expected_calls
                run["checkpoint_label"] = label
                run["checkpoint_schedule"] = schedule
                seed_runs.append(run)
                runs.append(run)
                print(
                    f"CHECKPOINT_GATE done checkpoint={label} "
                    f"schedule={schedule} seed={seed} "
                    f"tasks={run['num_task_finished']}", flush=True,
                )
        if len({run["reset_causal_fingerprint"] for run in seed_runs}) != 1:
            raise RuntimeError(f"seed {seed} reset prefix is not paired")

    baseline = args.baseline_label
    candidate = args.candidate_label
    summaries: dict[str, Any] = {}
    for schedule in ("never", "period_80"):
        schedule_runs = [
            run for run in runs if run["checkpoint_schedule"] == schedule
        ]
        baseline_counts = {
            run["seed"]: run["num_task_finished"]
            for run in schedule_runs if run["checkpoint_label"] == baseline
        }
        summaries[schedule] = {}
        for label in labels:
            selected = [
                run for run in schedule_runs if run["checkpoint_label"] == label
            ]
            counts = {run["seed"]: run["num_task_finished"] for run in selected}
            deltas = [counts[seed] - baseline_counts[seed] for seed in args.seeds]
            relatives = [
                (counts[seed] - baseline_counts[seed]) / baseline_counts[seed]
                for seed in args.seeds
            ]
            summaries[schedule][label] = {
                "mean_num_task_finished": statistics.fmean(counts.values()),
                "counts_by_seed": {str(seed): counts[seed] for seed in args.seeds},
                "baseline": baseline,
                "mean_paired_task_delta": statistics.fmean(deltas),
                "mean_paired_relative_delta": statistics.fmean(relatives),
                "minimum_paired_relative_delta": min(relatives),
                "paired_relative_bootstrap_95_ci": _bootstrap_ci(relatives),
                "win_tie_loss_vs_baseline": {
                    "wins": sum(delta > 0 for delta in deltas),
                    "ties": sum(delta == 0 for delta in deltas),
                    "losses": sum(delta < 0 for delta in deltas),
                },
            }

    primary = summaries["period_80"][candidate]
    anchor = summaries["never"][candidate]
    selection_checks = {
        "primary_mean_relative_at_least_0_5pct": (
            primary["mean_paired_relative_delta"] >= 0.005
        ),
        "primary_wins_at_least_6_of_10": (
            primary["win_tie_loss_vs_baseline"]["wins"] >= 6
        ),
        "primary_ci_lower_above_minus_1pct": (
            primary["paired_relative_bootstrap_95_ci"][0] > -0.01
        ),
        "bootstrap_anchor_mean_above_minus_1pct": (
            anchor["mean_paired_relative_delta"] > -0.01
        ),
        "bootstrap_anchor_no_seed_below_minus_5pct": (
            anchor["minimum_paired_relative_delta"] > -0.05
        ),
    }
    selected_checkpoint = candidate if all(selection_checks.values()) else baseline
    selection_gate = {
        "status": "pass" if selected_checkpoint == candidate else "retain_baseline",
        "primary_schedule": "period_80",
        "safety_anchor_schedule": "never",
        "baseline_checkpoint": baseline,
        "candidate_checkpoint": candidate,
        "selected_checkpoint": selected_checkpoint,
        "checks": selection_checks,
        "claim_scope": (
            "development-only checkpoint selection; not a method or SOTA result"
        ),
    }
    artifact = {
        "schema": "dai.onlineggo.absolute-checkpoint-gate/v2",
        "status": "complete",
        "evidence_class": "development_checkpoint_selection",
        "sota_claim_permitted": False,
        "seeds": args.seeds,
        "baseline_checkpoint": baseline,
        "candidate_checkpoint": candidate,
        "schedules": ["never", "period_80"],
        "map_path": str(map_path),
        "checkpoints": {label: checkpoint.metadata() for label, checkpoint in checkpoints.items()},
        "workload_manifests": manifests,
        "summaries": summaries,
        "selection_gate": selection_gate,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summaries, indent=2, sort_keys=True))
    print(json.dumps({"selection_gate": selection_gate}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
