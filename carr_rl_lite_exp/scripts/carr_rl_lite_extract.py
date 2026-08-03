#!/usr/bin/env python3
"""Extract CARR-RL-lite training data from existing dev confirmation artifacts.

Pure offline transform of already-collected, integrity-audited dev data.  Emits
one row per scored decision window of each context_memory_B25 run with the four
lightweight features proposed for CARR-RL-lite, the controller's causal internal
state, and the frozen rule-based accept/hold label.  No simulation is re-run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _rows_from_run(run: dict) -> list[dict]:
    if run.get("method") != "context_memory_B25":
        return []
    timeline = run.get("publication_timeline") or []
    windows = run.get("windows") or []
    by_index = {int(t["decision_index"]): t for t in timeline}
    rows: list[dict] = []
    for w in windows:
        di = int(w["decision_index"])
        if di == 0:
            continue  # mandatory bootstrap; not a policy decision
        t = by_index.get(di)
        feats = w.get("features") or {}
        if t is None or not feats:
            continue
        acd = t.get("active_context_distance")
        if acd is None:
            continue
        pol = t.get("policy") or {}
        rows.append(
            {
                "seed": int(run["seed"]),
                "workload": str(run["workload"]),
                "map_id": str(run["map_id"]),
                "decision_index": di,
                "js_change": float(feats["causal_block_score"]),
                "age": float(feats["guidance_age_windows"]),
                "adoption": float(feats["current_version_route_fraction"]),
                "context_distance": float(acd),
                "score": float(pol.get("score", feats["causal_block_score"])),
                "threshold": (
                    None if pol.get("threshold") is None else float(pol["threshold"])
                ),
                "persistence_count": float(pol.get("persistence_count", 0)),
                "spent_before": float(pol.get("spent_before", 0)),
                "remaining_epochs_after": float(pol.get("remaining_epochs_after", 0)),
                "maintenance_due": bool(pol.get("maintenance_due", False)),
                "route_mature": bool(pol.get("route_mature", True)),
                "action_available": bool(pol.get("action_available", True)),
                "minimum_score": float(pol.get("minimum_score", 0.10)),
                "rule_accepted": bool(t.get("accepted")),
                "rule_reason": str(t.get("reason")),
                "throughput_per_timestep": float(run["throughput_per_timestep"]),
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    n_rows = 0
    n_accept = 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for path in args.inputs:
            data = json.loads(Path(path).read_text())
            for run in data.get("runs", []):
                for row in _rows_from_run(run):
                    n_rows += 1
                    n_accept += int(row["rule_accepted"])
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(
        f"wrote {n_rows} decision rows ({n_accept} accepted, "
        f"{n_rows - n_accept} held) -> {out}"
    )


if __name__ == "__main__":
    main()
