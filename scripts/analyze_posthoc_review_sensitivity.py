#!/usr/bin/env python3
"""Post-hoc robustness checks added after the prespecified analysis.

This script reuses the completed Experiment B matrix.  It does not modify the
prespecified estimand or tests and must be described as exploratory.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import fmean


FOCAL = "context_memory_B25"
LABELS = {
    "bootstrap_only": "Bootstrap",
    "exact_even_G4": "Exact-G4",
    "exact_even_G5": "Exact-G5",
    "random_G5": "Random-G5",
    "js_cap_G5": "JS-G5",
    "context_no_reactivation_B25": "CARR-NoRecall",
    "context_memory_B25": "CARR",
    "exact_even_B25": "Exact-B25",
}


def quantile(values: list[float], probability: float) -> float:
    """R-7/NumPy-default linearly interpolated sample quantile."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def percentile_interval(values: list[float]) -> list[float]:
    return [quantile(values, 0.025), quantile(values, 0.975)]


def point_dominates(left: tuple[float, float], right: tuple[float, float]) -> bool:
    """Points are (calls, tasks); fewer calls and more tasks are preferred."""
    lcalls, ltasks = left
    rcalls, rtasks = right
    return (
        lcalls <= rcalls
        and ltasks >= rtasks
        and (lcalls < rcalls or ltasks > rtasks)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("results/same_call_confirmation_b/compact_runs.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/posthoc_review_sensitivity_2026-08-03.json"),
    )
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()

    with args.csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    methods = sorted({row["method"] for row in rows})
    if set(methods) != set(LABELS):
        raise ValueError(f"unexpected method set: {methods}")

    roots = sorted({int(row["root_seed"]) for row in rows})
    scenarios = sorted({row["scenario"] for row in rows})
    workloads = sorted({row["workload"] for row in rows})
    expected = len(roots) * len(scenarios) * len(workloads) * len(methods)
    if len(rows) != expected:
        raise ValueError(f"incomplete matrix: found {len(rows)}, expected {expected}")

    by_key = {}
    for row in rows:
        key = (
            int(row["root_seed"]),
            row["scenario"],
            row["workload"],
            row["method"],
        )
        if key in by_key:
            raise ValueError(f"duplicate row: {key}")
        by_key[key] = row

    task_by_method_root: dict[str, list[float]] = defaultdict(list)
    call_by_method_root: dict[str, list[float]] = defaultdict(list)
    for method in methods:
        for root in roots:
            task_by_method_root[method].append(
                fmean(
                    float(by_key[(root, scenario, workload, method)]["num_task_finished"])
                    for scenario in scenarios
                    for workload in workloads
                )
            )
            call_by_method_root[method].append(
                fmean(
                    float(by_key[(root, scenario, workload, method)]["generator_calls"])
                    for scenario in scenarios
                    for workload in workloads
                )
            )

    random_generator = random.Random(args.seed)
    bootstrap_indices = [
        [random_generator.randrange(len(roots)) for _ in roots]
        for _ in range(args.bootstrap_samples)
    ]

    log_ratio = {}
    call_difference = {}
    for comparator in methods:
        if comparator == FOCAL:
            continue
        root_log_ratios = []
        root_call_differences = []
        for root in roots:
            root_log_ratios.append(
                fmean(
                    math.log(
                        float(by_key[(root, scenario, workload, FOCAL)]["num_task_finished"])
                        / float(by_key[(root, scenario, workload, comparator)]["num_task_finished"])
                    )
                    for scenario in scenarios
                    for workload in workloads
                )
            )
            root_call_differences.append(
                fmean(
                    float(by_key[(root, scenario, workload, FOCAL)]["generator_calls"])
                    - float(by_key[(root, scenario, workload, comparator)]["generator_calls"])
                    for scenario in scenarios
                    for workload in workloads
                )
            )

        boot_log_means = [
            fmean(root_log_ratios[index] for index in draw)
            for draw in bootstrap_indices
        ]
        transformed_boot = [100.0 * math.expm1(value) for value in boot_log_means]
        log_ratio[comparator] = {
            "label": LABELS[comparator],
            "effect_percent": 100.0 * math.expm1(fmean(root_log_ratios)),
            "percentile_95_ci": percentile_interval(transformed_boot),
        }

        boot_call_means = [
            fmean(root_call_differences[index] for index in draw)
            for draw in bootstrap_indices
        ]
        call_difference[comparator] = {
            "label": LABELS[comparator],
            "mean_calls": fmean(root_call_differences),
            "percentile_95_ci": percentile_interval(boot_call_means),
        }

    non_dominated_counts = {method: 0 for method in methods}
    focal_dominance_counts = {method: 0 for method in methods if method != FOCAL}
    for draw in bootstrap_indices:
        points = {
            method: (
                fmean(call_by_method_root[method][index] for index in draw),
                fmean(task_by_method_root[method][index] for index in draw),
            )
            for method in methods
        }
        for method in methods:
            dominated = any(
                point_dominates(points[other], points[method])
                for other in methods
                if other != method
            )
            non_dominated_counts[method] += int(not dominated)
        for comparator in focal_dominance_counts:
            focal_dominance_counts[comparator] += int(
                point_dominates(points[FOCAL], points[comparator])
            )

    result = {
        "status": "post_hoc_exploratory",
        "input_csv": str(args.csv),
        "rows": len(rows),
        "roots": len(roots),
        "bootstrap_samples": args.bootstrap_samples,
        "seed": args.seed,
        "log_ratio_sensitivity": log_ratio,
        "call_difference_sensitivity": call_difference,
        "frontier_bootstrap": {
            "non_dominated_frequency": {
                method: non_dominated_counts[method] / args.bootstrap_samples
                for method in methods
            },
            "carr_point_dominance_frequency": {
                method: focal_dominance_counts[method] / args.bootstrap_samples
                for method in focal_dominance_counts
            },
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
