"""Static fixed-task-tape validation for a frozen OnlineGGO CNN.

This runner is deliberately narrower than ``gate0_publication_mvp.py``.  It
uses a pre-generated per-agent saturated goal tape, so every publication
policy receives the same starts and the same ordered goals.  The present tape
schema is stationary and has no release times; results from this script can
validate the guidance channel and publication mechanics, but cannot support a
non-stationary or SOTA claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any


SUPPORTED_METHODS = {"uniform", "never", "always", "period_50", "period_100"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity_from_manifest(
    manifest: dict[str, Any],
    *,
    sha256_fn: Any,
    fnv1a64_fn: Any,
) -> dict[str, Any]:
    starts = manifest["start_locations"]
    goal_tape = manifest["goal_tape"]
    return {
        "mode": "saturated_backlog_per_agent",
        "manifest_sha256": sha256_fn(starts, goal_tape),
        "content_fnv1a64": fnv1a64_fn(starts, goal_tape),
        "start_locations": starts,
        "per_agent_lengths": [
            len(sequence) for sequence in goal_tape
        ],
        "total_tasks": sum(len(sequence) for sequence in goal_tape),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--checkpoint-params-sha256", default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--seeds", nargs="+", type=int,
        default=[101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
    )
    parser.add_argument(
        "--methods", nargs="+",
        default=["uniform", "never", "always", "period_50", "period_100"],
    )
    parser.add_argument("--agents", type=int, default=400)
    parser.add_argument("--warmup-time", type=int, default=100)
    parser.add_argument("--horizon", type=int, default=600)
    parser.add_argument("--decision-window", type=int, default=20)
    args = parser.parse_args()

    if len(args.seeds) != len(set(args.seeds)):
        raise ValueError("seeds must be unique")
    if len(args.methods) != len(set(args.methods)):
        raise ValueError("methods must be unique")
    unknown = set(args.methods) - SUPPORTED_METHODS
    if unknown:
        raise ValueError(f"unsupported static fixed-tape methods: {sorted(unknown)}")
    if not {"uniform", "never"}.issubset(args.methods):
        raise ValueError("methods must include uniform and never")
    if args.horizon % args.decision_window != 0:
        raise ValueError("horizon must be divisible by decision window")

    workspace = args.workspace.resolve()
    onlineggo = workspace / "external" / "OnlineGGO"
    cmaes = onlineggo / "CMAES"
    sys.path.insert(0, str(workspace / "src"))
    sys.path.insert(0, str(cmaes))
    sys.path.insert(0, str(workspace / "scripts"))

    from dai_lmapf.frozen_cnn_generator import load_frozen_cnn_checkpoint
    from dai_lmapf.online_ggo_adapter import OnlineGGOAdapter
    from env_search.iterative_update.envs.trafficflow_online_env import (
        TrafficFlowOnlineEnv,
        _dai_fixed_goal_tape_fnv1a64,
        _dai_fixed_goal_tape_sha256,
        generate_kiva_saturated_goal_tape,
    )
    from env_search.traffic_mapf.config import TrafficMAPFConfig
    from gate0_publication_mvp import _run_condition

    map_path = (
        onlineggo
        / "Guided-PIBT/guided-pibt/benchmark-lifelong/maps/"
        / "warehouse_small_narrow_kiva.map"
    ).resolve()
    checkpoint = load_frozen_cnn_checkpoint(
        args.checkpoint.resolve(),
        expected_file_sha256=args.checkpoint_sha256,
        expected_params_sha256=args.checkpoint_params_sha256,
    )
    module_paths = sorted(
        (cmaes / "simulators" / "trafficMAPF_on").glob("period_on_sim*.so")
    )
    if len(module_paths) != 1:
        raise RuntimeError("expected exactly one compiled period_on_sim module")

    # An agent can finish at most one task per simulator timestep.  The extra
    # two entries cover the initially revealed task and leave an unrevealed
    # sentinel, making exhaustion an infrastructure error rather than a
    # method-specific fallback.
    goals_per_agent = args.warmup_time + args.horizon + 2
    runs: list[dict[str, Any]] = []
    manifest_identities: dict[str, dict[str, Any]] = {}

    for seed in args.seeds:
        manifest = generate_kiva_saturated_goal_tape(
            str(map_path), args.agents, goals_per_agent, seed
        )
        expected_identity = _identity_from_manifest(
            manifest,
            sha256_fn=_dai_fixed_goal_tape_sha256,
            fnv1a64_fn=_dai_fixed_goal_tape_fnv1a64,
        )
        manifest_identities[str(seed)] = expected_identity

        def config_factory() -> Any:
            return TrafficMAPFConfig(
                map_path=str(map_path),
                simu_time=args.horizon,
                num_agents=args.agents,
                num_tasks=expected_identity["total_tasks"],
                gen_tasks=True,
                num_tasks_reveal=1,
                task_assignment_strategy="roundrobin",
                update_gg_interval=args.decision_window,
                warmup_time=args.warmup_time,
                past_traffic_interval=args.decision_window,
                task_dist_change_interval=-1,
                initial_task_distribution_phase=0,
                fixed_goal_tape=manifest["goal_tape"],
                fixed_goal_tape_start_locations=manifest["start_locations"],
                has_traffic_obs=True,
                has_gg_obs=False,
                has_task_obs=True,
                has_map_obs=False,
            )

        seed_runs = []
        for method in args.methods:
            print(f"FIXED start method={method} seed={seed}", flush=True)
            run = _run_condition(
                method=method,
                seed=seed,
                config_factory=config_factory,
                env_class=TrafficFlowOnlineEnv,
                adapter_class=OnlineGGOAdapter,
                generator_mode="frozen_cnn",
                generator_kwargs={
                    "checkpoint_path": str(checkpoint.path),
                    "expected_file_sha256": checkpoint.file_sha256,
                    "expected_params_sha256": checkpoint.params_sha256,
                },
                decision_window=args.decision_window,
                warmup_time=args.warmup_time,
                shift_interval=args.warmup_time + args.horizon + 1,
                event_threshold=0.02,
                event_minimum_gap=40,
                cohort_delay=40,
                cohort_min_route_builds=40,
                horizon=args.horizon,
            )
            if run["task_tape_identity"] != expected_identity:
                raise RuntimeError(
                    f"seed {seed} method {method} changed fixed-tape identity"
                )
            if run["final_task_tape_prefixes"]["exhausted"] is not False:
                raise RuntimeError(
                    f"seed {seed} method {method} exhausted the fixed tape"
                )
            seed_runs.append(run)
            runs.append(run)
            print(
                f"FIXED done method={method} seed={seed} "
                f"tasks={run['num_task_finished']} "
                f"pubs={run['publication_count']}",
                flush=True,
            )

        if len({run["reset_causal_fingerprint"] for run in seed_runs}) != 1:
            raise RuntimeError(f"seed {seed} reset state differs across methods")
        if len({json.dumps(run["task_tape_identity"], sort_keys=True)
                for run in seed_runs}) != 1:
            raise RuntimeError(f"seed {seed} tape identity differs across methods")

    counts = {
        method: {
            run["seed"]: run["num_task_finished"]
            for run in runs if run["method"] == method
        }
        for method in args.methods
    }
    publications = {
        method: {
            run["seed"]: run["publication_count"]
            for run in runs if run["method"] == method
        }
        for method in args.methods
    }
    summaries = {}
    for method in args.methods:
        values = [counts[method][seed] for seed in args.seeds]
        summaries[method] = {
            "mean_num_task_finished": sum(values) / len(values),
            "mean_publication_count": (
                sum(publications[method].values()) / len(args.seeds)
            ),
            "task_counts_by_seed": {
                str(seed): counts[method][seed] for seed in args.seeds
            },
            "paired_deltas_vs_uniform": {
                str(seed): counts[method][seed] - counts["uniform"][seed]
                for seed in args.seeds
            },
            "paired_deltas_vs_never": {
                str(seed): counts[method][seed] - counts["never"][seed]
                for seed in args.seeds
            },
        }
        summaries[method]["mean_paired_delta_vs_uniform"] = sum(
            summaries[method]["paired_deltas_vs_uniform"].values()
        ) / len(args.seeds)
        summaries[method]["mean_paired_delta_vs_never"] = sum(
            summaries[method]["paired_deltas_vs_never"].values()
        ) / len(args.seeds)

    artifact = {
        "schema": "dai.gate0.static-fixed-tape-cnn/v1",
        "status": "complete",
        "evidence_class": "validation_diagnostic",
        "sota_claim_permitted": False,
        "claim_scope": (
            "stationary saturated-backlog fixed-tape validation of the frozen "
            "CNN and publication mechanics; no nonstationary or SOTA claim"
        ),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "map_path": str(map_path),
        "map_sha256": _sha256(map_path),
        "period_on_sim_sha256": _sha256(module_paths[0]),
        "checkpoint": checkpoint.metadata(),
        "seeds": args.seeds,
        "methods": args.methods,
        "agents": args.agents,
        "warmup_time": args.warmup_time,
        "horizon": args.horizon,
        "decision_window": args.decision_window,
        "goals_per_agent": goals_per_agent,
        "workload": {
            "mode": "saturated_backlog_per_agent",
            "stationary": True,
            "absolute_release_times": False,
            "online_task_rng": False,
        },
        "task_tape_identities": manifest_identities,
        "summaries": summaries,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "method", "seed", "num_task_finished", "publication_count",
                "generator_seconds", "simulator_seconds", "elapsed_seconds",
            ),
        )
        writer.writeheader()
        for run in runs:
            writer.writerow({field: run[field] for field in writer.fieldnames})
    print(json.dumps(summaries, indent=2, sort_keys=True))
    print(f"artifact={args.output}")
    print(f"csv={csv_path}")


if __name__ == "__main__":
    main()
