"""Confirm that different episode seeds produce distinct causal scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _fingerprints(artifact: dict[str, Any]) -> dict[str, str]:
    traces = artifact["traces"]
    return {
        "seed_bundle": _hash(traces[0]["seed_bundle"]),
        "starts": _hash(traces[0]["start"]),
        "planner_initial_priority_order": _hash(
            traces[0]["planner_initial_priority_order"]
        ),
        "distribution_update_tape": _hash([
            update
            for trace in traces
            for update in trace["recent_distribution_updates"]
        ]),
        "task_event_tape": _hash([
            event for trace in traces for event in trace["recent_events"]
        ]),
        "actual_paths": _hash([
            trace["actual_paths"] for trace in traces
        ]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    left = json.loads(args.left.read_text(encoding="utf-8"))
    right = json.loads(args.right.read_text(encoding="utf-8"))
    left_fp = _fingerprints(left)
    right_fp = _fingerprints(right)
    changed = {
        field: left_fp[field] != right_fp[field]
        for field in sorted(left_fp)
    }
    same_backbone = all(
        left[field] == right[field]
        for field in (
            "period_on_sim_sha256",
            "map_sha256",
            "agents",
            "simulation_time_post_warmup",
            "warmup_time",
            "update_interval",
        )
    )
    distinct_seeds = left["seed"] != right["seed"]
    passed = same_backbone and distinct_seeds and all(changed.values())
    result = {
        "schema": "dai.gate0.seed-sensitivity/v1",
        "status": "pass" if passed else "fail",
        "same_backbone": same_backbone,
        "left_seed": left["seed"],
        "right_seed": right["seed"],
        "distinct_seeds": distinct_seeds,
        "causal_components_changed": changed,
        "left_fingerprints": left_fp,
        "right_fingerprints": right_fp,
        "period_on_sim_sha256": left["period_on_sim_sha256"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
