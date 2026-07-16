"""Post-process the locked smoke validation without rerunning simulations."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .pilot import _bootstrap_ci, _sign_flip_pvalue


Row = dict[str, str]
Predicate = Callable[[Row], bool]


def _number(row: Row, key: str) -> float:
    return float(row[key])


def _paired(
    rows: list[Row], proposed: str, baseline: str, predicate: Predicate
) -> dict[str, object]:
    indexed = {
        (
            row["method"],
            row["map_id"],
            row["workload"],
            int(row["n_agents"]),
            int(row["layout_seed"]),
        ): row
        for row in rows
    }
    conditions = sorted(
        {
            (
                row["map_id"],
                row["workload"],
                int(row["n_agents"]),
                int(row["layout_seed"]),
            )
            for row in rows
            if row["method"] == proposed and predicate(row)
        }
    )
    per_seed: dict[int, list[float]] = defaultdict(list)
    absolute: dict[int, list[float]] = defaultdict(list)
    for map_id, workload, n_agents, seed in conditions:
        first = indexed.get((proposed, map_id, workload, n_agents, seed))
        second = indexed.get((baseline, map_id, workload, n_agents, seed))
        if first is None or second is None:
            continue
        first_value = _number(first, "throughput")
        second_value = _number(second, "throughput")
        per_seed[seed].append((first_value - second_value) / max(1e-12, second_value))
        absolute[seed].append(first_value - second_value)
    relative_values = [statistics.fmean(values) for _, values in sorted(per_seed.items())]
    absolute_values = [statistics.fmean(values) for _, values in sorted(absolute.items())]
    return {
        "proposed": proposed,
        "baseline": baseline,
        "n_seeds": len(relative_values),
        "mean_relative_gain": statistics.fmean(relative_values) if relative_values else 0.0,
        "median_relative_gain": statistics.median(relative_values) if relative_values else 0.0,
        "relative_ci95": _bootstrap_ci(relative_values),
        "mean_absolute_gain": statistics.fmean(absolute_values) if absolute_values else 0.0,
        "sign_flip_pvalue": _sign_flip_pvalue(relative_values),
        "per_seed_relative_gain": relative_values,
    }


def _paired_ratio(
    rows: list[Row], numerator: str, denominator: str, key: str, predicate: Predicate
) -> float:
    indexed = {
        (
            row["method"],
            row["map_id"],
            row["workload"],
            int(row["n_agents"]),
            int(row["layout_seed"]),
        ): row
        for row in rows
    }
    ratios = []
    for row in rows:
        if row["method"] != numerator or not predicate(row):
            continue
        comparison = indexed.get(
            (
                denominator,
                row["map_id"],
                row["workload"],
                int(row["n_agents"]),
                int(row["layout_seed"]),
            )
        )
        if comparison is None:
            continue
        ratios.append(_number(row, key) / max(1e-12, _number(comparison, key)))
    return statistics.fmean(ratios) if ratios else 0.0


def assess(runs_path: Path) -> dict[str, object]:
    with runs_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    corridor_maps = {"two_corridor", "three_corridor"}
    dynamic = {"abrupt", "recurring"}

    def main(row: Row) -> bool:
        return (
            row["map_id"] in corridor_maps
            and row["workload"] in dynamic
            and int(row["n_agents"]) == 24
        )

    def three_corridor(row: Row) -> bool:
        return row["map_id"] == "three_corridor" and row["workload"] in dynamic and int(row["n_agents"]) == 24

    def static(row: Row) -> bool:
        return row["workload"] == "static"

    def open_control(row: Row) -> bool:
        return row["map_id"] == "open"

    def low_density_control(row: Row) -> bool:
        return int(row["n_agents"]) == 16

    primary = _paired(rows, "betg_25", "periodic_20", main)
    versus_heuristic = _paired(rows, "betg_25", "drift_25", main)
    low_budget = _paired(rows, "betg_10", "periodic_50", main)
    static_control = _paired(rows, "betg_25", "periodic_20", static)
    open_noninferiority = _paired(rows, "betg_25", "periodic_20", open_control)
    low_density_noninferiority = _paired(
        rows, "betg_25", "periodic_20", low_density_control
    )
    three_corridor_effect = _paired(
        rows, "betg_25", "periodic_20", three_corridor
    )

    main_betg = [row for row in rows if row["method"] == "betg_25" and main(row)]
    refresh_rate = statistics.fmean(_number(row, "refresh_rate") for row in main_betg)
    controller_overhead = statistics.fmean(
        _number(row, "controller_seconds") / max(1e-12, _number(row, "wall_time_seconds"))
        for row in main_betg
    )
    throughput_fraction_of_always = _paired_ratio(
        rows, "betg_25", "always_refresh", "throughput", main
    )
    runtime_fraction_of_always = _paired_ratio(
        rows, "betg_25", "always_refresh", "wall_time_seconds", main
    )
    collision_count = sum(int(row["collision_count"]) for row in rows)
    proposed_deadlock_rate = statistics.fmean(
        float(row["deadlocked"] == "True") for row in main_betg
    )
    all_method_deadlock_rate = statistics.fmean(
        float(row["deadlocked"] == "True") for row in rows
    )
    budget_violation_rate = statistics.fmean(
        _number(row, "budget_violation") for row in main_betg
    )

    checks = {
        "primary_gain_at_least_5pct": primary["mean_relative_gain"] >= 0.05,
        "primary_ci_excludes_zero": primary["relative_ci95"][0] > 0.0,
        "beats_simple_drift_trigger_significantly": (
            versus_heuristic["mean_relative_gain"] > 0.0
            and versus_heuristic["relative_ci95"][0] > 0.0
        ),
        "three_corridor_direction_positive": three_corridor_effect["mean_relative_gain"] > 0.0,
        "static_degradation_within_2pct": static_control["mean_relative_gain"] >= -0.02,
        "open_degradation_within_2pct": open_noninferiority["mean_relative_gain"] >= -0.02,
        "n16_degradation_within_2pct": low_density_noninferiority["mean_relative_gain"] >= -0.02,
        "at_least_95pct_always_refresh_throughput": throughput_fraction_of_always >= 0.95,
        "at_least_20pct_faster_than_always_refresh": runtime_fraction_of_always <= 0.80,
        "refresh_rate_at_most_25pct": refresh_rate <= 0.2500001,
        "controller_overhead_below_5pct": controller_overhead < 0.05,
        "budget_violation_at_most_5pct": budget_violation_rate <= 0.05,
        "zero_collisions": collision_count == 0,
        "zero_proposed_deadlocks": proposed_deadlock_rate == 0.0,
    }
    return {
        "primary": primary,
        "versus_drift_heuristic": versus_heuristic,
        "low_budget": low_budget,
        "static_control": static_control,
        "open_control": open_noninferiority,
        "n16_control": low_density_noninferiority,
        "three_corridor": three_corridor_effect,
        "throughput_fraction_of_always_refresh": throughput_fraction_of_always,
        "runtime_fraction_of_always_refresh": runtime_fraction_of_always,
        "main_refresh_rate": refresh_rate,
        "controller_overhead_fraction": controller_overhead,
        "budget_violation_rate": budget_violation_rate,
        "collision_count": collision_count,
        "proposed_deadlock_rate": proposed_deadlock_rate,
        "all_method_deadlock_rate": all_method_deadlock_rate,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


def write_markdown(path: Path, assessment: dict[str, object]) -> None:
    def effect_line(label: str, key: str) -> str:
        effect = assessment[key]
        return (
            f"- {label}: {100 * effect['mean_relative_gain']:.2f}% "
            f"(95% CI [{100 * effect['relative_ci95'][0]:.2f}%, "
            f"{100 * effect['relative_ci95'][1]:.2f}%], "
            f"p={effect['sign_flip_pvalue']:.6f})"
        )

    lines = [
        "# Locked smoke-validation assessment",
        "",
        "> This is local mechanism evidence, not an Online GGO or public-benchmark result.",
        "",
        "## Paired effects",
        "",
        effect_line("BETG-25 vs periodic-20 (primary)", "primary"),
        effect_line("BETG-25 vs drift-25", "versus_drift_heuristic"),
        effect_line("BETG-10 vs periodic-50", "low_budget"),
        effect_line("Static BETG-25 vs periodic-20", "static_control"),
        effect_line("Open-map BETG-25 vs periodic-20", "open_control"),
        effect_line("16-agent BETG-25 vs periodic-20", "n16_control"),
        effect_line("Three-corridor BETG-25 vs periodic-20", "three_corridor"),
        "",
        "## Cost and safety",
        "",
        f"- Throughput fraction of always-refresh: {100 * assessment['throughput_fraction_of_always_refresh']:.2f}%",
        f"- Runtime fraction of always-refresh: {100 * assessment['runtime_fraction_of_always_refresh']:.2f}%",
        f"- Refresh rate: {100 * assessment['main_refresh_rate']:.2f}%",
        f"- Controller overhead: {100 * assessment['controller_overhead_fraction']:.2f}%",
        f"- Budget violation rate: {100 * assessment['budget_violation_rate']:.2f}%",
        f"- Collisions: {assessment['collision_count']}",
        f"- Proposed-method deadlock rate: {100 * assessment['proposed_deadlock_rate']:.2f}%",
        f"- All-method deadlock rate: {100 * assessment['all_method_deadlock_rate']:.2f}%",
        "",
        "## Registered checks",
        "",
    ]
    for check, passed in assessment["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{check}`")
    lines.extend(
        [
            "",
            f"Overall: **{'PASS' if assessment['all_checks_pass'] else 'NOT YET PASS'}**",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs", type=Path, default=Path("results/smoke_validation_locked/runs.csv")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/smoke_validation_locked/ASSESSMENT.json"),
    )
    args = parser.parse_args()
    assessment = assess(args.runs)
    args.output.write_text(
        json.dumps(assessment, indent=2, sort_keys=True), encoding="utf-8"
    )
    write_markdown(args.output.with_suffix(".md"), assessment)
    print(json.dumps(assessment, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
