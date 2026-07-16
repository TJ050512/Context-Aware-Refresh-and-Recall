"""CLI and paired statistics for the selective stale-field repair smoke gate."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .pilot import _bootstrap_ci, _sign_flip_pvalue
from .selective_repair_smoke import (
    RepairEvent,
    SelectiveRepairResult,
    run_selective_repair_episode,
)
from .smoke_sim import build_smoke_manifest


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _scenario_values(
    results: list[SelectiveRepairResult], metric: str
) -> dict[tuple[str, str, str, int, int], float]:
    grouped: dict[tuple[str, str, str, int, int], list[float]] = defaultdict(list)
    for result in results:
        key = (
            result.method,
            result.map_id,
            result.workload,
            result.n_agents,
            result.seed,
        )
        grouped[key].append(float(getattr(result, metric)))
    return {key: _mean(values) for key, values in grouped.items()}


def _paired_effect(
    results: list[SelectiveRepairResult],
    *,
    proposed: str,
    baseline: str,
    metric: str,
) -> dict[str, object]:
    values = _scenario_values(results, metric)
    seeds = sorted({result.seed for result in results})
    per_seed: list[float] = []
    absolute_per_seed: list[float] = []
    for seed in seeds:
        proposed_values: list[float] = []
        baseline_values: list[float] = []
        conditions = sorted(
            {
                (result.map_id, result.workload, result.n_agents)
                for result in results
                if result.seed == seed
            }
        )
        for map_id, workload, n_agents in conditions:
            first = values.get((proposed, map_id, workload, n_agents, seed))
            second = values.get((baseline, map_id, workload, n_agents, seed))
            if first is None or second is None:
                continue
            proposed_values.append(first)
            baseline_values.append(second)
        if proposed_values:
            proposed_mean = _mean(proposed_values)
            baseline_mean = _mean(baseline_values)
            absolute = proposed_mean - baseline_mean
            # Aggregate conditions before taking the ratio.  Individual
            # post-shift cells can legitimately have zero completions, for
            # which a cell-wise relative effect is undefined and explosive.
            per_seed.append(absolute / max(1e-12, baseline_mean))
            absolute_per_seed.append(absolute)
    return {
        "proposed": proposed,
        "baseline": baseline,
        "metric": metric,
        "n_seeds": len(per_seed),
        "mean_relative_gain": _mean(per_seed),
        "median_relative_gain": statistics.median(per_seed) if per_seed else 0.0,
        "relative_ci95": _bootstrap_ci(per_seed),
        "sign_flip_pvalue": _sign_flip_pvalue(per_seed),
        "mean_absolute_gain": _mean(absolute_per_seed),
        "per_seed_relative_gain": per_seed,
    }


def _map_direction(
    results: list[SelectiveRepairResult], proposed: str, baseline: str, metric: str
) -> dict[str, float]:
    output: dict[str, float] = {}
    for map_id in sorted({result.map_id for result in results}):
        subset = [result for result in results if result.map_id == map_id]
        output[map_id] = float(
            _paired_effect(
                subset, proposed=proposed, baseline=baseline, metric=metric
            )["mean_relative_gain"]
        )
    return output


def _report(summary: dict[str, object]) -> str:
    def line(label: str, key: str) -> str:
        effect = summary[key]
        return (
            f"- {label}: {100 * effect['mean_relative_gain']:.2f}% "
            f"(95% CI [{100 * effect['relative_ci95'][0]:.2f}%, "
            f"{100 * effect['relative_ci95'][1]:.2f}%], "
            f"p={effect['sign_flip_pvalue']:.6f})"
        )

    lines = [
        "# Selective stale-field repair smoke gate",
        "",
        "> This is a potential-field mechanism diagnostic, not an OnlineGGO/GPIBT result.",
        "",
        line("All repair vs lazy (mechanism headroom)", "all_vs_lazy"),
        line("Top-25 vs random-25 (selector value)", "top_vs_random"),
        line("Top-25 vs lazy", "top_vs_lazy"),
        line("Lazy update vs no update (generator validity)", "lazy_vs_no_update"),
        line("Lazy update vs no update (total throughput)", "lazy_total_vs_no_update"),
        line("All repair vs lazy (total throughput)", "all_total_vs_lazy"),
        line("Top-25 vs lazy (total throughput)", "top_total_vs_lazy"),
        "",
        f"- Top-25 gain capture: {100 * summary['gain_capture']:.2f}%",
        f"- Top-25 exposure capture: {100 * summary['mean_exposure_capture']:.2f}%",
        f"- Lazy stale-fraction AUC: {summary['lazy_stale_fraction_auc']:.3f}",
        f"- Top-25 mechanism overhead: {100 * summary['top_mechanism_overhead_fraction']:.2f}%",
        "",
        "## Checks",
        "",
    ]
    for check, passed in summary["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{check}`")
    lines.extend(
        [
            "",
            f"Overall: **{'GO TO OFFICIAL BACKBONE' if summary['all_checks_pass'] else 'NO-GO / REVISE'}**",
            "",
        ]
    )
    return "\n".join(lines)


def run(config_path: Path, output_dir: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    results: list[SelectiveRepairResult] = []
    event_rows: list[dict[str, object]] = []
    random_seeds = [int(seed) for seed in config.get("random_selector_seeds", [0])]
    for map_id in config["maps"]:
        for n_agents in config["agent_counts"]:
            for workload in config["workloads"]:
                for seed in config["seeds"]:
                    manifest = build_smoke_manifest(
                        map_id=map_id,
                        workload=workload,
                        n_agents=int(n_agents),
                        horizon_steps=int(config["horizon_steps"]),
                        seed=int(seed),
                    )
                    for method in config["methods"]:
                        selector_seeds = random_seeds if method.startswith("random_") else [0]
                        for selector_seed in selector_seeds:
                            result, events = run_selective_repair_episode(
                                manifest=manifest,
                                workload=workload,
                                method=method,
                                selector_seed=selector_seed,
                                guidance_scale=float(config.get("guidance_scale", 8.0)),
                                post_shift_window=int(config.get("post_shift_window", 100)),
                                event_delay=int(config.get("event_delay", 0)),
                            )
                            results.append(result)
                            for event in events:
                                row = event.as_dict()
                                row.update(
                                    {
                                        "run_id": result.run_id,
                                        "method": method,
                                        "map_id": map_id,
                                        "workload": workload,
                                        "n_agents": n_agents,
                                        "seed": seed,
                                        "selector_seed": selector_seed,
                                    }
                                )
                                event_rows.append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "runs.csv", [result.as_dict() for result in results])
    with (output_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
        for row in event_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    metric = "post_shift_throughput_100"
    all_vs_lazy = _paired_effect(
        results, proposed="repair_all", baseline="lazy_0", metric=metric
    )
    top_vs_random = _paired_effect(
        results, proposed="top_25", baseline="random_25", metric=metric
    )
    top_vs_lazy = _paired_effect(
        results, proposed="top_25", baseline="lazy_0", metric=metric
    )
    lazy_vs_no_update = _paired_effect(
        results, proposed="lazy_0", baseline="no_update", metric=metric
    )
    lazy_total_vs_no_update = _paired_effect(
        results, proposed="lazy_0", baseline="no_update", metric="throughput"
    )
    all_total_vs_lazy = _paired_effect(
        results, proposed="repair_all", baseline="lazy_0", metric="throughput"
    )
    top_total_vs_lazy = _paired_effect(
        results, proposed="top_25", baseline="lazy_0", metric="throughput"
    )
    all_gain = float(all_vs_lazy["mean_absolute_gain"])
    top_gain = float(top_vs_lazy["mean_absolute_gain"])
    gain_capture = top_gain / all_gain if all_gain > 1e-12 else 0.0
    top_events = [row for row in event_rows if row["method"] == "top_25"]
    mean_exposure_capture = _mean(float(row["exposure_capture"]) for row in top_events)
    lazy_results = [result for result in results if result.method == "lazy_0"]
    top_results = [result for result in results if result.method == "top_25"]
    lazy_stale_auc = _mean(result.stale_fraction_auc for result in lazy_results)
    top_overhead = _mean(
        (
            result.exposure_seconds
            + result.repair_field_build_seconds
            + result.guidance_generation_seconds
        )
        / max(1e-12, result.wall_time_seconds)
        for result in top_results
    )
    map_direction = _map_direction(results, "top_25", "random_25", metric)
    collisions = sum(result.collision_count for result in results)
    checks = {
        "all_vs_lazy_gain_at_least_5pct": all_vs_lazy["mean_relative_gain"] >= 0.05,
        "all_vs_lazy_ci_excludes_zero": all_vs_lazy["relative_ci95"][0] > 0.0,
        "top_vs_random_gain_at_least_3pct": top_vs_random["mean_relative_gain"] >= 0.03,
        "top_vs_random_ci_excludes_zero": top_vs_random["relative_ci95"][0] > 0.0,
        "updated_guidance_beats_no_update": lazy_vs_no_update["mean_absolute_gain"] > 0.0,
        "updated_guidance_total_ci_excludes_zero": lazy_total_vs_no_update["relative_ci95"][0] > 0.0,
        "top_total_gain_at_least_3pct": top_total_vs_lazy["mean_relative_gain"] >= 0.03,
        "top_captures_at_least_70pct_all_gain": gain_capture >= 0.70,
        "top_captures_at_least_60pct_exposure": mean_exposure_capture >= 0.60,
        "lazy_stale_auc_at_least_0_30": lazy_stale_auc >= 0.30,
        "map_directions_nonnegative": all(value >= 0.0 for value in map_direction.values()),
        "mechanism_overhead_below_10pct": top_overhead < 0.10,
        "zero_collisions": collisions == 0,
    }
    summary: dict[str, object] = {
        "config": config,
        "n_runs": len(results),
        "all_vs_lazy": all_vs_lazy,
        "top_vs_random": top_vs_random,
        "top_vs_lazy": top_vs_lazy,
        "lazy_vs_no_update": lazy_vs_no_update,
        "lazy_total_vs_no_update": lazy_total_vs_no_update,
        "all_total_vs_lazy": all_total_vs_lazy,
        "top_total_vs_lazy": top_total_vs_lazy,
        "gain_capture": gain_capture,
        "mean_exposure_capture": mean_exposure_capture,
        "lazy_stale_fraction_auc": lazy_stale_auc,
        "top_mechanism_overhead_fraction": top_overhead,
        "map_direction_top_vs_random": map_direction,
        "collision_count": collisions,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "REPORT.md").write_text(_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.config, args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
