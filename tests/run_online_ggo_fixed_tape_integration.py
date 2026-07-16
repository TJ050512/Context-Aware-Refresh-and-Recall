"""Linux-only integration sentinel for the compiled fixed-goal-tape path."""

from __future__ import annotations

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
        TrafficFlowOnlineEnv,
        generate_kiva_saturated_goal_tape,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig

    episode_seed = 17
    num_agents = 8
    warmup_time = 2
    simulation_time = 10
    update_interval = 5
    num_tasks_reveal = 1
    map_path = (
        onlineggo
        / "Guided-PIBT"
        / "guided-pibt"
        / "benchmark-lifelong"
        / "maps"
        / "warehouse_small_narrow_kiva.map"
    ).resolve()
    # An agent can finish at most one task per simulator timestep. This bound
    # leaves one additional unrevealed item after the final scored step.
    goals_per_agent = (
        warmup_time + simulation_time + num_tasks_reveal + 1
    )
    manifest = generate_kiva_saturated_goal_tape(
        str(map_path), num_agents, goals_per_agent, episode_seed
    )

    config = TrafficMAPFConfig(
        map_path=str(map_path),
        simu_time=simulation_time,
        num_agents=num_agents,
        num_tasks=num_agents * goals_per_agent,
        gen_tasks=True,
        num_tasks_reveal=num_tasks_reveal,
        task_assignment_strategy="roundrobin",
        update_gg_interval=update_interval,
        warmup_time=warmup_time,
        past_traffic_interval=update_interval,
        task_dist_change_interval=-1,
        initial_task_distribution_phase=0,
        fixed_goal_tape=manifest["goal_tape"],
        fixed_goal_tape_start_locations=manifest["start_locations"],
        has_traffic_obs=True,
        has_gg_obs=False,
        has_task_obs=True,
        has_map_obs=False,
    )

    def run(scale: float):
        env = TrafficFlowOnlineEnv(config=config, seed=episode_seed)
        height, width = env.comp_map.height, env.comp_map.width
        _, reset_info = env.reset(seed=episode_seed)
        traces = [reset_info["dai_trace"]]
        action = np.ones((4, height, width), dtype=np.float64)
        action[0] *= scale
        action[1] *= 1.0 + 0.1 * scale
        terminated = False
        while not terminated:
            _, _, terminated, truncated, info = env.step(action)
            if terminated != truncated:
                raise AssertionError("termination and truncation must agree")
            traces.append(info["dai_trace"])
        return traces

    first = run(1.0)
    second = run(2.0)
    identity_fields = (
        "mode",
        "manifest_sha256",
        "content_fnv1a64",
        "start_locations",
        "per_agent_lengths",
        "total_tasks",
    )
    first_identity = {
        field: first[0]["task_tape"][field] for field in identity_fields
    }
    second_identity = {
        field: second[0]["task_tape"][field] for field in identity_fields
    }
    if first_identity != second_identity:
        raise AssertionError("cross-method fixed-tape identity differs")
    if first[0]["start"] != second[0]["start"]:
        raise AssertionError("cross-method start locations differ")
    if first_identity["content_fnv1a64"] != manifest["content_fnv1a64"]:
        raise AssertionError("pre-generation and simulator fingerprints differ")

    for traces in (first, second):
        previous_assigned = [0] * num_agents
        previous_completed = [0] * num_agents
        for trace in traces:
            tape = trace["task_tape"]
            if tape["enabled"] is not True or tape["exhausted"] is not False:
                raise AssertionError("fixed tape must stay enabled and unexhausted")
            assigned = tape["assigned_prefix_lengths"]
            completed = tape["completed_prefix_lengths"]
            if any(
                not previous_assigned[index] <= assigned[index]
                <= goals_per_agent
                for index in range(num_agents)
            ):
                raise AssertionError("assigned tape prefix decreased or overflowed")
            if any(
                not previous_completed[index] <= completed[index]
                <= assigned[index]
                for index in range(num_agents)
            ):
                raise AssertionError("completed tape prefix is inconsistent")
            previous_assigned = assigned
            previous_completed = completed

    print(json.dumps({
        "status": "pass",
        "trace_schema": first[0]["trace_schema_version"],
        "task_tape_identity": first_identity,
        "first_final_assigned_prefix": first[-1]["task_tape"][
            "assigned_prefix_lengths"
        ],
        "second_final_assigned_prefix": second[-1]["task_tape"][
            "assigned_prefix_lengths"
        ],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
