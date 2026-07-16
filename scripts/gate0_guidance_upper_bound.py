"""Frozen-phase guidance-quality upper bound on the official GPIBT backend.

This is deliberately not a publication-controller experiment.  For each
exogenous Kiva task-distribution phase it first runs a uniform/default graph,
then evaluates three graphs that stay fixed for the complete post-warmup
phase:

* ``phase_static`` uses only the frozen distribution and warmup state;
* ``empirical_static`` is an optimistic hindsight candidate built from all
  movements in that phase's uniform rollout;
* ``empirical_reverse`` reverses the hindsight direction bias and is a channel
  sanity control.

The comparison separates a weak guidance generator from a weak publication
policy.  It is a diagnostic and must not be reported as a fair online method
or a mathematical upper bound: ``empirical_static`` intentionally sees future
phase data, but its copied-flow construction is only one static graph family.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable


RDLU = ((0, 1), (1, 0), (0, -1), (-1, 0))
OPPOSITE = (2, 3, 0, 1)
ACTION_TO_DIRECTION = {"R": 0, "D": 1, "L": 2, "U": 3}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FixedActionGenerator:
    def __init__(self, action: Any) -> None:
        self.action = copy.deepcopy(action)
        self.calls = 0

    def __call__(self, observation: Any) -> Any:
        del observation
        self.calls += 1
        return copy.deepcopy(self.action)


def _phase_distribution(reset_trace: dict[str, Any]) -> dict[str, Any]:
    updates = reset_trace["recent_distribution_updates"]
    if not updates:
        return {
            "kind": "uniform_constructor_default",
            "timestep": None,
            "primary_weights_sha256": None,
            "secondary_weights_sha256": None,
            "secondary_argmax": None,
        }
    if len(updates) != 1:
        raise RuntimeError("frozen phase must expose exactly one initial update")
    update = updates[0]
    secondary = list(map(float, update["secondary_weights"]))
    return {
        "kind": str(update["random_type"]),
        "timestep": int(update["timestep"]),
        "primary_weights_sha256": _canonical_hash(update["primary_weights"]),
        "secondary_weights_sha256": _canonical_hash(secondary),
        "secondary_argmax": max(range(len(secondary)), key=secondary.__getitem__),
    }


def _causal_reset_fingerprint(trace: dict[str, Any]) -> str:
    return _canonical_hash({
        "seed_bundle": trace["seed_bundle"],
        "start": trace["start"],
        "planner_initial_priority_order": trace[
            "planner_initial_priority_order"
        ],
        "curr_pos": trace["curr_pos"],
        "curr_tasks": trace["curr_tasks"],
        "actual_paths": trace["actual_paths"],
        "recent_events": trace["recent_events"],
        "recent_distribution_updates": trace[
            "recent_distribution_updates"
        ],
    })


def _run_static(
    *,
    condition: str,
    seed: int,
    phase: int,
    config_factory: Callable[[int], Any],
    env_class: Any,
    adapter_class: Any,
    action: Any,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    import numpy as np

    env = env_class(config=config_factory(phase), seed=seed)
    generator = FixedActionGenerator(action)
    adapter = adapter_class(
        env,
        generator,
        height=env.comp_map.height,
        width=env.comp_map.width,
    )
    observation, reset_info = adapter.reset(seed=seed)
    reset_trace = dict(reset_info["dai_trace"])
    windows = []
    traces = []
    started = time.perf_counter()
    while not adapter.done:
        window = adapter.advance(refresh=adapter.decision_index == 0)
        trace = dict(window.info["dai_trace"])
        if trace["recent_distribution_updates"]:
            raise RuntimeError("task distribution changed inside a frozen phase")
        if any(item["timed_out"] for item in trace["recent_planner_times"]):
            raise RuntimeError("planner timeout invalidates upper-bound run")
        traces.append(trace)
        windows.append({
            "start": int(trace["window_start_timestep"]),
            "end": int(trace["window_end_timestep"]),
            "reward": float(window.reward),
            "num_task_finished": int(trace["num_task_finished"]),
            "route_builds": len(trace["recent_route_builds"]),
            "planner_seconds": sum(
                float(item["seconds"])
                for item in trace["recent_planner_times"]
            ),
            "map_weights_revision": int(trace["map_weights_revision"]),
            "applied_guidance_sha256": trace[
                "applied_guidance_sha256"
            ],
        })
    elapsed = time.perf_counter() - started
    if generator.calls != 1:
        raise RuntimeError("a static condition must generate guidance exactly once")
    applied_hashes = {
        row["applied_guidance_sha256"] for row in windows
    }
    if len(applied_hashes) != 1:
        raise RuntimeError("a frozen static graph changed within the phase")
    final_tasks = int(windows[-1]["num_task_finished"])
    result = {
        "condition": condition,
        "seed": seed,
        "phase": phase,
        "num_task_finished": final_tasks,
        "throughput_per_timestep": final_tasks
        / float(config_factory(phase).simu_time),
        "generator_calls": generator.calls,
        "elapsed_seconds": elapsed,
        "planner_seconds": sum(row["planner_seconds"] for row in windows),
        "route_build_count": sum(row["route_builds"] for row in windows),
        "raw_action_sha256": _canonical_hash(
            np.asarray(action, dtype=np.float64).reshape(-1).tolist()
        ),
        "reset_causal_fingerprint": _causal_reset_fingerprint(reset_trace),
        "distribution": _phase_distribution(reset_trace),
        "windows": windows,
    }
    return result, {
        "reset_trace": reset_trace,
        "traces": traces,
    }, observation


def _empirical_signed_flow(
    *, graph: Any, reset_trace: dict[str, Any], traces: list[dict[str, Any]]
) -> Any:
    import numpy as np

    graph_array = np.asarray(graph, dtype=np.int8)
    height, width = graph_array.shape
    positions = [tuple(map(int, value[:2])) for value in reset_trace["curr_pos"]]
    directed = np.zeros((4, height, width), dtype=np.float64)

    for trace in traces:
        paths = [([] if path == "" else path.split(",")) for path in trace[
            "actual_paths"
        ]]
        steps = int(trace["actual_executed_steps"])
        if any(len(path) != steps for path in paths):
            raise RuntimeError("actual path length disagrees with trace window")
        for step in range(steps):
            for agent_id, path in enumerate(paths):
                action = path[step]
                row, col = positions[agent_id]
                if action == "W":
                    continue
                direction = ACTION_TO_DIRECTION[action]
                directed[direction, row, col] += 1.0
                delta_row, delta_col = RDLU[direction]
                positions[agent_id] = (row + delta_row, col + delta_col)
        expected = [tuple(map(int, value)) for value in trace["curr_pos"]]
        if positions != expected:
            raise RuntimeError("reconstructed phase positions disagree with C++")

    net = np.zeros_like(directed)
    for row in range(height):
        for col in range(width):
            if graph_array[row, col] != 0:
                continue
            for direction, (delta_row, delta_col) in enumerate(RDLU):
                next_row = row + delta_row
                next_col = col + delta_col
                if (
                    0 <= next_row < height
                    and 0 <= next_col < width
                    and graph_array[next_row, next_col] == 0
                ):
                    reverse = OPPOSITE[direction]
                    net[direction, row, col] = (
                        directed[direction, row, col]
                        - directed[reverse, next_row, next_col]
                    )
    nonzero = np.abs(net[np.nonzero(net)])
    scale = float(np.percentile(nonzero, 90.0)) if nonzero.size else 1.0
    return np.clip(net / max(scale, 1.0), -1.0, 1.0)


def _phase_static_action(
    *,
    graph: Any,
    home_locs: Any,
    endpoint_locs: Any,
    flow_bias: float,
    decision_window: int,
    observation: Any,
    reset_trace: dict[str, Any],
) -> Any:
    from gate0_publication_mvp import NextRouteFlowGuidanceGenerator

    generator = NextRouteFlowGuidanceGenerator(
        graph=graph,
        home_locs=home_locs,
        endpoint_locs=endpoint_locs,
        flow_bias=flow_bias,
        decision_window=decision_window,
    )
    generator.state_provider = lambda: reset_trace
    return generator(observation)


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    conditions = sorted({run["condition"] for run in runs})
    phases = sorted({int(run["phase"]) for run in runs})
    summaries: dict[str, Any] = {}
    for phase in phases:
        phase_runs = [run for run in runs if run["phase"] == phase]
        uniform = {
            run["seed"]: run["num_task_finished"]
            for run in phase_runs
            if run["condition"] == "uniform"
        }
        phase_summary = {}
        for condition in conditions:
            selected = [
                run for run in phase_runs if run["condition"] == condition
            ]
            if not selected:
                continue
            counts = [run["num_task_finished"] for run in selected]
            deltas = [
                run["num_task_finished"] - uniform[run["seed"]]
                for run in selected
            ]
            relative = [
                delta / max(1, uniform[run["seed"]])
                for delta, run in zip(deltas, selected)
            ]
            phase_summary[condition] = {
                "mean_num_task_finished": sum(counts) / len(counts),
                "paired_deltas_vs_uniform": deltas,
                "mean_paired_delta_vs_uniform": sum(deltas) / len(deltas),
                "mean_relative_delta_vs_uniform": (
                    sum(relative) / len(relative)
                ),
            }
        summaries[str(phase)] = phase_summary

    empirical_deltas = [
        summaries[str(phase)]["empirical_static"][
            "mean_paired_delta_vs_uniform"
        ]
        for phase in phases
    ]
    phase_static_deltas = [
        summaries[str(phase)]["phase_static"][
            "mean_paired_delta_vs_uniform"
        ]
        for phase in phases
    ]
    reverse_deltas = [
        summaries[str(phase)]["empirical_reverse"][
            "mean_paired_delta_vs_uniform"
        ]
        for phase in phases
    ]
    empirical_headroom = max(empirical_deltas) > 0
    phase_generator_headroom = max(phase_static_deltas) > 0
    directional_control_separates = max(
        forward - reverse
        for forward, reverse in zip(empirical_deltas, reverse_deltas)
    ) > 0
    if phase_generator_headroom:
        diagnosis = (
            "phase-static generator has headroom; a negative dynamic result "
            "implicates publication timing/state rather than graph quality"
        )
    elif empirical_headroom:
        diagnosis = (
            "hindsight phase graph has headroom but the causal phase generator "
            "does not; improve the frozen generator before controller research"
        )
    elif directional_control_separates:
        diagnosis = (
            "guidance directions affect outcomes, but neither tested forward "
            "static graph beats uniform; no quality headroom was established"
        )
    else:
        diagnosis = (
            "no static guidance headroom or directional separation observed; "
            "audit strength/channel semantics or change the workload setting"
        )
    return {
        "by_phase": summaries,
        "diagnostic_flags": {
            "phase_generator_headroom": phase_generator_headroom,
            "empirical_hindsight_headroom": empirical_headroom,
            "directional_control_separates": directional_control_separates,
        },
        "diagnosis": diagnosis,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[17, 18])
    parser.add_argument("--phases", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--agents", type=int, default=400)
    parser.add_argument("--warmup-time", type=int, default=100)
    parser.add_argument("--horizon", type=int, default=200)
    parser.add_argument("--decision-window", type=int, default=20)
    parser.add_argument("--flow-bias", type=float, default=0.30)
    args = parser.parse_args()

    if any(phase < 0 for phase in args.phases):
        raise ValueError("phase indices must be non-negative")
    if args.horizon % args.decision_window != 0:
        raise ValueError("horizon must be divisible by decision window")
    if not (0.0 < args.flow_bias < 1.0):
        raise ValueError("flow bias must be in (0, 1)")

    workspace = args.workspace.resolve()
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    sys.path.insert(0, str(workspace / "src"))
    sys.path.insert(0, str(cmaes))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from dai_lmapf.online_ggo_adapter import OnlineGGOAdapter
    from env_search.iterative_update.envs.trafficflow_online_env import (
        TrafficFlowOnlineEnv,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig

    map_path = (
        onlineggo
        / "Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
        / "warehouse_small_narrow_kiva.map"
    ).resolve()
    module_paths = sorted(
        (cmaes / "simulators" / "trafficMAPF_on").glob("period_on_sim*.so")
    )
    if len(module_paths) != 1:
        raise RuntimeError("expected exactly one compiled period_on_sim module")

    def config_factory(phase: int) -> Any:
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
            task_dist_change_interval=-1,
            task_random_type="Gaussian",
            dist_sigma=0.5,
            dist_K=3,
            initial_task_distribution_phase=phase,
            has_traffic_obs=True,
            has_gg_obs=False,
            has_task_obs=True,
            has_map_obs=False,
        )

    probe = TrafficFlowOnlineEnv(config=config_factory(0), seed=args.seeds[0])
    graph = probe.comp_map.graph.copy()
    home_locs = list(probe.comp_map.home_loc_ids)
    endpoint_locs = list(probe.comp_map.end_points_ids)
    del probe

    runs = []
    for seed in args.seeds:
        for phase in args.phases:
            print(f"upper-bound start seed={seed} phase={phase}", flush=True)
            import numpy as np

            uniform_action = np.ones(
                (4, graph.shape[0], graph.shape[1]), dtype=np.float64
            )
            uniform, uniform_payload, reset_observation = _run_static(
                condition="uniform",
                seed=seed,
                phase=phase,
                config_factory=config_factory,
                env_class=TrafficFlowOnlineEnv,
                adapter_class=OnlineGGOAdapter,
                action=uniform_action,
            )
            if phase > 0 and uniform["distribution"]["timestep"] != 0:
                raise RuntimeError(
                    "compiled simulator did not install the requested frozen "
                    "Gaussian phase; rebuild period_on_sim"
                )
            if phase == 0 and uniform["distribution"]["timestep"] is not None:
                raise RuntimeError("phase 0 must retain the uniform default")
            runs.append(uniform)

            phase_action = _phase_static_action(
                graph=graph,
                home_locs=home_locs,
                endpoint_locs=endpoint_locs,
                flow_bias=args.flow_bias,
                decision_window=args.decision_window,
                observation=reset_observation,
                reset_trace=uniform_payload["reset_trace"],
            )
            phase_static, _, _ = _run_static(
                condition="phase_static",
                seed=seed,
                phase=phase,
                config_factory=config_factory,
                env_class=TrafficFlowOnlineEnv,
                adapter_class=OnlineGGOAdapter,
                action=phase_action,
            )
            if (
                phase_static["reset_causal_fingerprint"]
                != uniform["reset_causal_fingerprint"]
            ):
                raise RuntimeError(
                    "phase-static and uniform warmup states are not paired"
                )
            runs.append(phase_static)

            signed = _empirical_signed_flow(
                graph=graph,
                reset_trace=uniform_payload["reset_trace"],
                traces=uniform_payload["traces"],
            )
            empirical_action = 1.0 - args.flow_bias * signed
            reverse_action = 1.0 + args.flow_bias * signed
            empirical, _, _ = _run_static(
                condition="empirical_static",
                seed=seed,
                phase=phase,
                config_factory=config_factory,
                env_class=TrafficFlowOnlineEnv,
                adapter_class=OnlineGGOAdapter,
                action=empirical_action,
            )
            reverse, _, _ = _run_static(
                condition="empirical_reverse",
                seed=seed,
                phase=phase,
                config_factory=config_factory,
                env_class=TrafficFlowOnlineEnv,
                adapter_class=OnlineGGOAdapter,
                action=reverse_action,
            )
            for paired in (empirical, reverse):
                if (
                    paired["reset_causal_fingerprint"]
                    != uniform["reset_causal_fingerprint"]
                ):
                    raise RuntimeError(
                        "static upper-bound warmup states are not paired"
                    )
            if (
                empirical["raw_action_sha256"]
                == reverse["raw_action_sha256"]
            ):
                raise RuntimeError(
                    "empirical phase has no directional signal to audit"
                )
            runs.extend([empirical, reverse])
            print(
                "upper-bound done "
                f"seed={seed} phase={phase} "
                f"tasks={{uniform:{uniform['num_task_finished']},"
                f"phase:{phase_static['num_task_finished']},"
                f"empirical:{empirical['num_task_finished']},"
                f"reverse:{reverse['num_task_finished']}}}",
                flush=True,
            )

    summary = _summarize(runs)
    artifact = {
        "schema": "dai.gate0.guidance-quality-upper-bound/v1",
        "status": "complete",
        "claim_scope": (
            "diagnostic only; empirical_static is an optimistic hindsight "
            "candidate, not a mathematical upper bound or online method"
        ),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "map_path": str(map_path),
        "map_sha256": _sha256(map_path),
        "period_on_sim_path": str(module_paths[0]),
        "period_on_sim_sha256": _sha256(module_paths[0]),
        "seeds": args.seeds,
        "phases": args.phases,
        "agents": args.agents,
        "warmup_time": args.warmup_time,
        "horizon": args.horizon,
        "decision_window": args.decision_window,
        "flow_bias": args.flow_bias,
        "conditions": [
            "uniform",
            "phase_static",
            "empirical_static",
            "empirical_reverse",
        ],
        "summary": summary,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"artifact={args.output}")


if __name__ == "__main__":
    main()
