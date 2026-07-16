"""Compare two independent Gate 0 runtime artifacts for causal replay.

Wall-clock measurements are intentionally excluded.  Everything that can
affect simulator behaviour remains in the canonical payload: effective seed
bundle, starts, initial planner priority order, distribution updates, task
events, paths, route builds, guidance identities, and final throughput count.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Optional


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _replay_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(artifact)
    payload.pop("elapsed_seconds", None)
    # Platform and interpreter labels document the run but do not describe
    # simulator state.  Binary/map/config hashes remain in the payload.
    payload.pop("platform", None)
    payload.pop("python", None)
    for trace in payload.get("traces", []):
        for record in trace.get("recent_planner_times", []):
            if record.get("timed_out"):
                raise ValueError("deterministic replay is invalid after a timeout")
            record.pop("seconds", None)
    return payload


def _first_difference(
    left: Any, right: Any, path: str = "$"
) -> Optional[str]:
    if type(left) is not type(right):
        return f"{path}: type {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        if set(left) != set(right):
            missing_left = sorted(set(right) - set(left))
            missing_right = sorted(set(left) - set(right))
            return (
                f"{path}: keys differ; only_right={missing_left!r}, "
                f"only_left={missing_right!r}"
            )
        for key in sorted(left):
            difference = _first_difference(
                left[key], right[key], f"{path}.{key}"
            )
            if difference is not None:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} != {len(right)}"
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            difference = _first_difference(
                left_item, right_item, f"{path}[{index}]"
            )
            if difference is not None:
                return difference
        return None
    if left != right:
        return f"{path}: {left!r} != {right!r}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    left = json.loads(args.left.read_text(encoding="utf-8"))
    right = json.loads(args.right.read_text(encoding="utf-8"))
    left_payload = _replay_payload(left)
    right_payload = _replay_payload(right)
    left_hash = _sha256_bytes(_canonical_bytes(left_payload))
    right_hash = _sha256_bytes(_canonical_bytes(right_payload))
    difference = _first_difference(left_payload, right_payload)
    passed = difference is None and left_hash == right_hash

    result = {
        "schema": "dai.gate0.replay-comparison/v1",
        "status": "pass" if passed else "fail",
        "comparison_semantics": (
            "exact causal replay excluding wall-clock duration and per-step "
            "steady-clock planner seconds; timeouts are forbidden"
        ),
        "left_path": str(args.left.resolve()),
        "right_path": str(args.right.resolve()),
        "left_artifact_sha256": _sha256_file(args.left),
        "right_artifact_sha256": _sha256_file(args.right),
        "left_replay_payload_sha256": left_hash,
        "right_replay_payload_sha256": right_hash,
        "first_difference": difference,
        "period_on_sim_sha256": left.get("period_on_sim_sha256"),
        "seed": left.get("seed"),
        "agents": left.get("agents"),
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
