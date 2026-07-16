#!/usr/bin/env python3
"""Generate a claim-bearing absolute-time Kiva workload artifact offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dai_lmapf.absolute_workload import (
    build_absolute_task_tape_manifest,
    generate_phase_shifted_kiva_tape,
    normalize_absolute_task_tape,
    read_kiva_map,
)


def _integer_list(value: str) -> list[int]:
    try:
        result = [int(item) for item in value.split(",") if item != ""]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not result:
        raise argparse.ArgumentTypeError("integer list must be non-empty")
    return result


def _load_starts(path: Path) -> list[int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("start_locations")
    if (
        not isinstance(payload, list)
        or not payload
        or any(isinstance(value, bool) or not isinstance(value, int) for value in payload)
    ):
        raise ValueError("starts JSON must be a list or contain start_locations")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument(
        "--starts-json", required=True, type=Path,
        help="JSON list or saturated-generator artifact with start_locations",
    )
    parser.add_argument("--release-timesteps", required=True, type=_integer_list)
    parser.add_argument("--phase-starts", required=True, type=_integer_list)
    parser.add_argument("--phase-centers", required=True, type=_integer_list)
    parser.add_argument("--task-seed", required=True, type=int)
    parser.add_argument("--sigma", type=float, default=0.75)
    parser.add_argument("--horizon", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    kiva_map = read_kiva_map(args.map)
    starts = _load_starts(args.starts_json)
    tape = generate_phase_shifted_kiva_tape(
        kiva_map=kiva_map,
        start_locations=starts,
        release_timesteps=args.release_timesteps,
        phase_starts=args.phase_starts,
        endpoint_phase_centers=args.phase_centers,
        task_seed=args.task_seed,
        sigma=args.sigma,
    )
    tape = normalize_absolute_task_tape(
        tape,
        start_locations=starts,
        map_size=kiva_map.rows * kiva_map.cols,
        horizon_steps=args.horizon,
    )
    manifest = build_absolute_task_tape_manifest(
        starts,
        tape,
        generator={
            "name": "phase_shifted_kiva_sha256_quantile",
            "map": str(args.map.resolve()),
            "release_timesteps": args.release_timesteps,
            "phase_starts": args.phase_starts,
            "phase_centers": args.phase_centers,
            "task_seed": args.task_seed,
            "sigma": args.sigma,
            "horizon": args.horizon,
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "manifest_sha256": manifest["manifest_sha256"],
        "content_fnv1a64": manifest["content_fnv1a64"],
        "num_agents": len(starts),
        "tasks_per_agent": len(args.release_timesteps),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
