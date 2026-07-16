"""Linux integration sentinel for absolute-time exogenous Kiva workloads."""

from __future__ import annotations

from bisect import bisect_right
import json
import sys
from pathlib import Path


def main() -> None:
    workspace = Path(__file__).resolve().parents[1]
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    sys.path.insert(0, str(workspace / "src"))
    sys.path.insert(0, str(cmaes))

    import numpy as np

    from env_search.iterative_update.envs.trafficflow_online_env import (
        DAI_ABSOLUTE_TASK_TAPE_SCHEMA_VERSION,
        TrafficFlowOnlineEnv,
        _dai_absolute_task_tape_fnv1a64,
        _dai_absolute_task_tape_sha256,
        generate_kiva_saturated_goal_tape,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig

    episode_seed = 17
    num_agents = 8
    warmup_time = 2
    simulation_time = 10
    update_interval = 5
    # No t=0 task: the warmup window explicitly exercises the planner-only
    # holding target and verifies it is not exposed as a real task.
    release_times = [4, 8]
    map_path = (
        onlineggo / "Guided-PIBT" / "guided-pibt" /
        "benchmark-lifelong" / "maps" /
        "warehouse_small_narrow_kiva.map"
    ).resolve()
    generated = generate_kiva_saturated_goal_tape(
        str(map_path), num_agents, len(release_times), episode_seed
    )
    absolute_tape = [
        [[goal, release] for goal, release in zip(goals, release_times)]
        for goals in generated["goal_tape"]
    ]
    expected_sha = _dai_absolute_task_tape_sha256(
        generated["start_locations"], absolute_tape
    )
    expected_fnv = _dai_absolute_task_tape_fnv1a64(
        generated["start_locations"], absolute_tape
    )
    config = TrafficMAPFConfig(
        map_path=str(map_path),
        simu_time=simulation_time,
        num_agents=num_agents,
        num_tasks=num_agents * len(release_times),
        gen_tasks=True,
        num_tasks_reveal=1,
        task_assignment_strategy="roundrobin",
        update_gg_interval=update_interval,
        warmup_time=warmup_time,
        past_traffic_interval=update_interval,
        task_dist_change_interval=-1,
        initial_task_distribution_phase=0,
        absolute_task_tape=absolute_tape,
        absolute_task_tape_start_locations=generated["start_locations"],
        has_traffic_obs=True,
        has_gg_obs=False,
        has_task_obs=True,
        has_map_obs=False,
    )

    def run(scale: float):
        env = TrafficFlowOnlineEnv(config=config, seed=episode_seed)
        height, width = env.comp_map.height, env.comp_map.width
        reset_observation, reset_info = env.reset(seed=episode_seed)
        if np.any(reset_observation[-1] != 0.0):
            raise AssertionError(
                "pre-release holding goals leaked into the task observation"
            )
        traces = [reset_info["dai_trace"]]
        action = np.ones((4, height, width), dtype=np.float64)
        action[0] *= scale
        terminated = False
        while not terminated:
            _, _, terminated, truncated, info = env.step(action)
            if terminated != truncated:
                raise AssertionError("termination and truncation must agree")
            traces.append(info["dai_trace"])
        return traces

    first = run(1.0)
    second = run(2.0)
    if any(first[0]["curr_task_active"]) or any(second[0]["curr_task_active"]):
        raise AssertionError("pre-release holding goals leaked as active tasks")
    for traces in (first, second):
        assigned_at = {}
        exposed = set()
        for trace in traces:
            pending_finishes = []
            tape = trace["task_tape"]
            if tape["schema_version"] != DAI_ABSOLUTE_TASK_TAPE_SCHEMA_VERSION:
                raise AssertionError("wrong absolute task-tape schema")
            if tape["manifest_sha256"] != expected_sha:
                raise AssertionError("manifest SHA differs from Python identity")
            if tape["content_fnv1a64"] != expected_fnv:
                raise AssertionError("C++ and Python FNV fingerprints differ")
            if tape["online_workload_rng_draws"] != 0:
                raise AssertionError("absolute workload used online RNG")
            expected_prefix = bisect_right(release_times, trace["timestep"])
            if tape["released_prefix_lengths"] != [expected_prefix] * num_agents:
                raise AssertionError("release prefix is not a function of time")
            if any(
                not completed <= assigned <= released
                for completed, assigned, released in zip(
                    tape["completed_prefix_lengths"],
                    tape["assigned_prefix_lengths"],
                    tape["released_prefix_lengths"],
                )
            ):
                raise AssertionError("released/assigned/completed prefixes conflict")
            for event in trace["recent_events"]:
                if event["event_type"] == "assigned":
                    assigned_at[event["task_id"]] = event["timestep"]
                elif event["event_type"] == "finished":
                    pending_finishes.append(event)
            for route in trace["recent_route_builds"]:
                if route["task_id"] not in assigned_at:
                    raise AssertionError("route exposure precedes assignment")
                exposed.add(route["task_id"])
            for event in pending_finishes:
                service_steps = (
                    event["timestep"] - assigned_at[event["task_id"]]
                )
                if service_steps > 1 and event["task_id"] not in exposed:
                    raise AssertionError(
                        "long-lived finished task lacks route exposure"
                    )
                exposed.discard(event["task_id"])

    def release_projection(traces):
        return [
            (event["agent_id"], event["task_id"], event["timestep"],
             event["goal_loc"])
            for trace in traces
            for event in trace["recent_events"]
            if event["event_type"] == "released"
        ]

    if release_projection(first) != release_projection(second):
        raise AssertionError("cross-method task contents or release times differ")
    print(json.dumps({
        "status": "pass",
        "trace_schema": first[0]["trace_schema_version"],
        "manifest_sha256": expected_sha,
        "content_fnv1a64": expected_fnv,
        "release_event_count": len(release_projection(first)),
        "final_released_prefix": first[-1]["task_tape"][
            "released_prefix_lengths"
        ],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
