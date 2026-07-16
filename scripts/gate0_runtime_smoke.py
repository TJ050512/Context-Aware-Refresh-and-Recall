"""Run a short official OnlineGGO/GPIBT instrumentation smoke test.

This is a bring-up check, not a performance experiment.  It exercises one
future-only guidance publication followed by reuse of the same raw action and
archives the validated C++ trace for inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summary(trace: dict[str, object]) -> dict[str, object]:
    return {
        "window_start_timestep": trace["window_start_timestep"],
        "window_end_timestep": trace["window_end_timestep"],
        "actual_executed_steps": trace["actual_executed_steps"],
        "is_warmup": trace["is_warmup"],
        "guidance_version": trace["guidance_version"],
        "guidance_sha256": trace["guidance_sha256"],
        "applied_guidance_sha256": trace["applied_guidance_sha256"],
        "map_weights_revision": trace["map_weights_revision"],
        "num_task_finished": trace["num_task_finished"],
        "event_count": len(trace["recent_events"]),
        "route_build_count": len(trace["recent_route_builds"]),
        "planner_record_count": len(trace["recent_planner_times"]),
        "done": trace["done"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument(
        "--map",
        dest="map_path",
        type=Path,
        default=Path(
            "Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
            "warehouse_small_narrow_kiva.map"
        ),
    )
    parser.add_argument("--agents", type=int, default=40)
    parser.add_argument(
        "--simulation-time",
        type=int,
        default=15,
        help="post-warmup evaluation horizon used by the C++ simulator",
    )
    parser.add_argument("--warmup-time", type=int, default=5)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.simulation_time != 3 * args.interval:
        raise ValueError(
            "smoke schedule requires exactly three post-warmup windows"
        )

    workspace = args.workspace.resolve()
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    sys.path.insert(0, str(workspace / "src"))
    sys.path.insert(0, str(cmaes))

    import numpy as np

    from dai_lmapf.online_ggo_adapter import OnlineGGOAdapter
    from env_search.iterative_update.envs.trafficflow_online_env import (
        TrafficFlowOnlineEnv,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig

    map_path = args.map_path
    if not map_path.is_absolute():
        map_path = onlineggo / map_path
    map_path = map_path.resolve()

    config = TrafficMAPFConfig(
        map_path=str(map_path),
        simu_time=args.simulation_time,
        num_agents=args.agents,
        num_tasks=100_000,
        gen_tasks=True,
        task_assignment_strategy="roundrobin",
        update_gg_interval=args.interval,
        warmup_time=args.warmup_time,
        past_traffic_interval=args.interval,
        task_dist_change_interval=2 * args.interval,
        task_random_type="Gaussian",
        dist_sigma=0.5,
        dist_K=3,
        has_traffic_obs=True,
        has_gg_obs=False,
        has_task_obs=True,
        has_map_obs=False,
    )
    env = TrafficFlowOnlineEnv(config=config, seed=args.seed)
    height, width = env.comp_map.height, env.comp_map.width

    def asymmetric_generator(_observation: object) -> object:
        row_ramp = np.linspace(0.0, 0.3, height, dtype=np.float64)[:, None]
        col_ramp = np.linspace(0.0, 0.2, width, dtype=np.float64)[None, :]
        bases = (0.4, 1.3, 2.7, 4.2)  # declared adapter order: R,D,L,U
        return np.stack(
            [base + row_ramp + col_ramp for base in bases], axis=0
        )

    adapter = OnlineGGOAdapter(
        env,
        asymmetric_generator,
        height=height,
        width=width,
    )
    started = time.perf_counter()
    _, reset_info = adapter.reset(
        seed=args.seed,
        initial_action=np.ones((4, height, width), dtype=np.float64),
    )
    windows = [
        adapter.advance(refresh=False),
        adapter.advance(refresh=True),
        adapter.advance(refresh=False),
    ]
    elapsed = time.perf_counter() - started

    traces = [reset_info["dai_trace"]]
    traces.extend(window.info["dai_trace"] for window in windows)
    summaries = [_summary(trace) for trace in traces]

    expected_bounds = [
        (0, args.warmup_time),
        (args.warmup_time, args.warmup_time + args.interval),
        (
            args.warmup_time + args.interval,
            args.warmup_time + 2 * args.interval,
        ),
        (
            args.warmup_time + 2 * args.interval,
            args.warmup_time + args.simulation_time,
        ),
    ]
    observed_bounds = [
        (trace["window_start_timestep"], trace["window_end_timestep"])
        for trace in traces
    ]
    if observed_bounds != expected_bounds:
        raise AssertionError(
            f"unexpected trace windows: {observed_bounds!r}"
        )
    expected_flags = {
        "guidance": True,
        "guidance_lns": 0,
        "flow_guidance": False,
        "init_pp": True,
        "objective": 5,
    }
    if any(trace["build_flags"] != expected_flags for trace in traces):
        raise AssertionError("compiled build flags differ from the frozen Gate 0 flags")
    refresh_trace = traces[2]
    reuse_trace = traces[3]
    for field in (
        "guidance_version",
        "guidance_sha256",
        "applied_guidance_sha256",
        "map_weights_revision",
    ):
        if refresh_trace[field] != reuse_trace[field]:
            raise AssertionError(f"refresh/reuse mismatch in {field}")
    if refresh_trace["guidance_version"] != 1:
        raise AssertionError("the single publication must create guidance version 1")
    if not windows[-1].terminated or not windows[-1].truncated:
        raise AssertionError("the final smoke window did not terminate cleanly")

    module_paths = sorted(
        (cmaes / "simulators" / "trafficMAPF_on").glob("period_on_sim*.so")
    )
    if len(module_paths) != 1:
        raise AssertionError("expected exactly one period_on_sim module")

    artifact = {
        "schema": "dai.gate0.runtime-smoke/v1",
        "status": "pass",
        "purpose": "bring-up only; not performance evidence",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "onlineggo_revision": "ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256",
        "period_on_sim_path": str(module_paths[0]),
        "period_on_sim_sha256": _sha256(module_paths[0]),
        "map_path": str(map_path),
        "map_sha256": _sha256(map_path),
        "seed": args.seed,
        "agents": args.agents,
        "simulation_time_post_warmup": args.simulation_time,
        "total_timesteps": args.warmup_time + args.simulation_time,
        "warmup_time": args.warmup_time,
        "update_interval": args.interval,
        "elapsed_seconds": elapsed,
        "window_summaries": summaries,
        "traces": traces,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "elapsed_seconds": elapsed,
                "period_on_sim_sha256": artifact["period_on_sim_sha256"],
                "window_summaries": summaries,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
