#!/usr/bin/env python3
"""Analyze a complete paired method matrix without modifying its source.

The root seed is the independent sampling unit.  Every workload/map cell for
the same root seed is kept together in the paired bootstrap and exact
sign-flip tests.  This avoids the common, anti-conservative mistake of
treating the workload cells as independent replicates.

The script is intended for development screening.  It reports all pairwise
comparisons against one candidate, but never upgrades development evidence to
a validation, locked-test, paper, or SOTA claim.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SOURCE_SCHEMA = "dai.claim-aware-absolute-budget/v1"
ANALYSIS_SCHEMA = "dai.full-method-matrix-analysis/v1"
DEFAULT_CANDIDATE = "context_memory_B25"
DEFAULT_RANDOM_BASELINE = "random_B25"
DEFAULT_BOOTSTRAP_SAMPLES = 20_000
BOOTSTRAP_SEED = 20260714


class MatrixError(ValueError):
    """The source artifact is incomplete or internally inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MatrixError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise MatrixError(f"{name} must be finite and >= {minimum}")
    return result


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MatrixError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sequence")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(
        sorted_values[lower] * (1.0 - weight)
        + sorted_values[upper] * weight
    )


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


def _normalize_artifact(
    artifact: Mapping[str, Any], candidate: str
) -> tuple[list[str], list[int], list[str], list[str], list[dict[str, Any]]]:
    if artifact.get("schema") != SOURCE_SCHEMA:
        raise MatrixError(
            f"schema must be {SOURCE_SCHEMA!r}, got {artifact.get('schema')!r}"
        )
    if artifact.get("status") != "complete":
        raise MatrixError("artifact.status must be 'complete'")
    methods = artifact.get("methods")
    seeds = artifact.get("seeds")
    workloads = artifact.get("workloads")
    raw_runs = artifact.get("runs")
    if (
        not isinstance(methods, list)
        or not methods
        or len(methods) != len(set(methods))
        or not all(isinstance(value, str) and value for value in methods)
    ):
        raise MatrixError("artifact.methods must be a non-empty unique string list")
    if candidate not in methods:
        raise MatrixError(f"candidate {candidate!r} is absent from artifact.methods")
    if (
        not isinstance(seeds, list)
        or not seeds
        or len(seeds) != len(set(seeds))
        or not all(isinstance(value, int) and not isinstance(value, bool) for value in seeds)
    ):
        raise MatrixError("artifact.seeds must be a non-empty unique integer list")
    if (
        not isinstance(workloads, list)
        or not workloads
        or len(workloads) != len(set(workloads))
        or not all(isinstance(value, str) and value for value in workloads)
    ):
        raise MatrixError("artifact.workloads must be a non-empty unique string list")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise MatrixError("artifact.runs must be a non-empty list")

    runs: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for index, raw in enumerate(raw_runs):
        if not isinstance(raw, dict):
            raise MatrixError(f"runs[{index}] must be an object")
        method = raw.get("method")
        seed = raw.get("seed")
        root_seed = raw.get("root_seed", seed)
        map_id = raw.get("map_id")
        workload = raw.get("workload")
        if method not in methods:
            raise MatrixError(f"runs[{index}].method is not declared")
        if seed not in seeds or root_seed != seed:
            raise MatrixError(f"runs[{index}] has invalid seed/root_seed")
        if not isinstance(map_id, str) or not map_id:
            raise MatrixError(f"runs[{index}].map_id must be non-empty")
        if workload not in workloads:
            raise MatrixError(f"runs[{index}].workload is not declared")
        tasks = _integer(raw.get("num_task_finished"), f"runs[{index}].num_task_finished")
        horizon = _integer(raw.get("scored_horizon"), f"runs[{index}].scored_horizon", minimum=1)
        throughput = _number(
            raw.get("throughput_per_timestep"),
            f"runs[{index}].throughput_per_timestep",
            minimum=0.0,
        )
        if not math.isclose(throughput, tasks / horizon, rel_tol=1e-12, abs_tol=1e-12):
            raise MatrixError(f"runs[{index}] has inconsistent tasks/throughput")
        post_publications = _integer(
            raw.get("post_bootstrap_publication_count"),
            f"runs[{index}].post_bootstrap_publication_count",
        )
        generator_calls = _integer(
            raw.get("generator_calls"), f"runs[{index}].generator_calls"
        )
        budget = raw.get("budget")
        if not isinstance(budget, dict):
            raise MatrixError(f"runs[{index}].budget must be an object")
        if budget.get("post_bootstrap_publication_count") != post_publications:
            raise MatrixError(f"runs[{index}] has inconsistent publication counts")
        if budget.get("total_generator_calls") != generator_calls:
            raise MatrixError(f"runs[{index}] has inconsistent generator calls")
        key = (str(method), int(seed), map_id, str(workload))
        if key in seen:
            raise MatrixError(f"duplicate run cell {key!r}")
        seen.add(key)
        normalized = dict(raw)
        normalized.update(
            {
                "method": str(method),
                "seed": int(seed),
                "root_seed": int(root_seed),
                "map_id": map_id,
                "workload": str(workload),
                "tasks": tasks,
                "throughput": throughput,
                "post_publications": post_publications,
                "generator_calls_normalized": generator_calls,
                "post_generations": _integer(
                    budget.get("post_bootstrap_generation_count", post_publications),
                    f"runs[{index}].budget.post_bootstrap_generation_count",
                ),
                "post_reactivations": _integer(
                    budget.get("post_bootstrap_reactivation_count", 0),
                    f"runs[{index}].budget.post_bootstrap_reactivation_count",
                ),
            }
        )
        runs.append(normalized)

    maps = sorted({run["map_id"] for run in runs})
    expected = set(itertools.product(methods, seeds, maps, workloads))
    if seen != expected:
        raise MatrixError(
            "runs must form a complete method×seed×map×workload grid; "
            f"missing={sorted(expected - seen)[:8]}, extra={sorted(seen - expected)[:8]}"
        )

    # Exogenous pairing checks: a comparison is invalid if methods did not see
    # the same tape and release process in a seed/map/workload cell.
    paired_fields = (
        "scored_horizon",
        "decision_window",
        "window_count",
        "manifest_id",
        "reset_causal_fingerprint",
        "release_projection_fingerprint",
        "distribution_update_fingerprint",
    )
    by_cell: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_cell[(run["seed"], run["map_id"], run["workload"])].append(run)
    for cell, cell_runs in by_cell.items():
        reference = cell_runs[0]
        for run in cell_runs[1:]:
            for field in paired_fields:
                if run.get(field) != reference.get(field):
                    raise MatrixError(f"unpaired {field} in cell {cell!r}")
            if run.get("task_tape_identity") != reference.get("task_tape_identity"):
                raise MatrixError(f"unpaired task_tape_identity in cell {cell!r}")
            run_prefix = run.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            )
            ref_prefix = reference.get("final_task_tape_prefixes", {}).get(
                "released_prefix_lengths"
            )
            if run_prefix != ref_prefix:
                raise MatrixError(f"unpaired released task prefix in cell {cell!r}")
    return list(methods), list(seeds), maps, list(workloads), runs


def _cluster_bootstrap(
    candidate_cells: Mapping[int, Sequence[float]],
    baseline_cells: Mapping[int, Sequence[float]],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    seeds = sorted(candidate_cells)
    if seeds != sorted(baseline_cells):
        raise MatrixError("candidate and baseline seed clusters do not match")
    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    for root_seed in seeds:
        if len(candidate_cells[root_seed]) != len(baseline_cells[root_seed]):
            raise MatrixError(f"cluster size mismatch for seed {root_seed}")
    rng = random.Random(seed)
    absolute_draws: list[float] = []
    relative_draws: list[float] = []
    n = len(seeds)
    for _ in range(samples):
        selected = [seeds[rng.randrange(n)] for _ in range(n)]
        candidate = [value for s in selected for value in candidate_cells[s]]
        baseline = [value for s in selected for value in baseline_cells[s]]
        candidate_mean = _mean(candidate)
        baseline_mean = _mean(baseline)
        absolute_draws.append(candidate_mean - baseline_mean)
        relative_draws.append(100.0 * (candidate_mean / baseline_mean - 1.0))
    absolute_draws.sort()
    relative_draws.sort()
    return {
        "method": "root_seed_cluster_percentile_bootstrap",
        "samples": samples,
        "seed": seed,
        "confidence_level": 0.95,
        "absolute_task_delta_ci": [
            _percentile(absolute_draws, 0.025),
            _percentile(absolute_draws, 0.975),
        ],
        "relative_mean_task_delta_percent_ci": [
            _percentile(relative_draws, 0.025),
            _percentile(relative_draws, 0.975),
        ],
    }


def _exact_sign_flip(seed_effects: Sequence[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in seed_effects if value != 0.0]
    if not nonzero:
        return {
            "method": "exact",
            "statistic": "mean seed-cluster absolute task delta",
            "nonzero_seed_clusters": 0,
            "assignments": 1,
            "p_two_sided": 1.0,
            "p_greater": 1.0,
        }
    if len(nonzero) > 24:
        raise MatrixError("exact sign-flip is intentionally capped at 24 nonzero clusters")
    observed = math.fsum(nonzero)
    total = 1 << len(nonzero)
    greater = 0
    two_sided = 0
    tolerance = 1e-12
    for bits in range(total):
        signed = math.fsum(
            value if bits & (1 << index) else -value
            for index, value in enumerate(nonzero)
        )
        if signed >= observed - tolerance:
            greater += 1
        if abs(signed) >= abs(observed) - tolerance:
            two_sided += 1
    return {
        "method": "exact",
        "statistic": "mean seed-cluster absolute task delta",
        "nonzero_seed_clusters": len(nonzero),
        "assignments": total,
        "p_two_sided": two_sided / total,
        "p_greater": greater / total,
    }


def _holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values for one named family."""

    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, p_value) in enumerate(ordered):
        running = max(running, (count - rank) * float(p_value))
        adjusted[name] = min(1.0, running)
    return adjusted


def _method_summaries(
    methods: Sequence[str], runs: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for method in methods:
        selected = [run for run in runs if run["method"] == method]
        tasks = [float(run["tasks"]) for run in selected]
        summaries.append(
            {
                "method": method,
                "n_cells": len(selected),
                "mean_tasks": _mean(tasks),
                "median_tasks": statistics.median(tasks),
                "sd_tasks_across_cells": statistics.stdev(tasks) if len(tasks) > 1 else 0.0,
                "mean_throughput_per_timestep": _mean(
                    float(run["throughput"]) for run in selected
                ),
                "mean_post_bootstrap_publications": _mean(
                    float(run["post_publications"]) for run in selected
                ),
                "mean_generator_calls": _mean(
                    float(run["generator_calls_normalized"]) for run in selected
                ),
                "mean_post_bootstrap_generations": _mean(
                    float(run["post_generations"]) for run in selected
                ),
                "mean_post_bootstrap_reactivations": _mean(
                    float(run["post_reactivations"]) for run in selected
                ),
                "mean_generator_seconds": _mean(
                    float(run.get("generator_seconds", 0.0)) for run in selected
                ),
            }
        )
    summaries.sort(key=lambda row: (-row["mean_tasks"], row["method"]))
    for rank, row in enumerate(summaries, start=1):
        row["task_rank"] = rank
    return summaries


def _workload_rankings(
    methods: Sequence[str], workloads: Sequence[str], runs: Sequence[Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for workload in workloads:
        rows: list[dict[str, Any]] = []
        for method in methods:
            selected = [
                run
                for run in runs
                if run["method"] == method and run["workload"] == workload
            ]
            rows.append(
                {
                    "method": method,
                    "mean_tasks": _mean(float(run["tasks"]) for run in selected),
                    "mean_post_bootstrap_publications": _mean(
                        float(run["post_publications"]) for run in selected
                    ),
                    "mean_generator_calls": _mean(
                        float(run["generator_calls_normalized"]) for run in selected
                    ),
                }
            )
        rows.sort(key=lambda row: (-row["mean_tasks"], row["method"]))
        for rank, row in enumerate(rows, start=1):
            row["task_rank"] = rank
        result[workload] = rows
    return result


def _pairwise_comparisons(
    candidate: str,
    methods: Sequence[str],
    seeds: Sequence[int],
    maps: Sequence[str],
    workloads: Sequence[str],
    runs: Sequence[Mapping[str, Any]],
    *,
    bootstrap_samples: int,
) -> list[dict[str, Any]]:
    indexed = {
        (run["method"], run["seed"], run["map_id"], run["workload"]): run
        for run in runs
    }
    comparisons: list[dict[str, Any]] = []
    for comparator in methods:
        if comparator == candidate:
            continue
        candidate_clusters: dict[int, list[float]] = defaultdict(list)
        comparator_clusters: dict[int, list[float]] = defaultdict(list)
        cell_deltas: list[float] = []
        cell_relative: list[float] = []
        workload_rows: dict[str, dict[str, Any]] = {}
        for seed, map_id, workload in itertools.product(seeds, maps, workloads):
            candidate_tasks = float(indexed[(candidate, seed, map_id, workload)]["tasks"])
            comparator_tasks = float(indexed[(comparator, seed, map_id, workload)]["tasks"])
            candidate_clusters[seed].append(candidate_tasks)
            comparator_clusters[seed].append(comparator_tasks)
            cell_deltas.append(candidate_tasks - comparator_tasks)
            cell_relative.append(100.0 * (candidate_tasks / comparator_tasks - 1.0))
        seed_effects = [
            _mean(candidate_clusters[seed]) - _mean(comparator_clusters[seed])
            for seed in seeds
        ]
        candidate_all = [value for values in candidate_clusters.values() for value in values]
        comparator_all = [value for values in comparator_clusters.values() for value in values]
        for workload in workloads:
            candidate_values = [
                float(indexed[(candidate, seed, map_id, workload)]["tasks"])
                for seed, map_id in itertools.product(seeds, maps)
            ]
            comparator_values = [
                float(indexed[(comparator, seed, map_id, workload)]["tasks"])
                for seed, map_id in itertools.product(seeds, maps)
            ]
            workload_rows[workload] = {
                "candidate_mean_tasks": _mean(candidate_values),
                "comparator_mean_tasks": _mean(comparator_values),
                "mean_absolute_task_delta": _mean(
                    a - b for a, b in zip(candidate_values, comparator_values)
                ),
                "relative_mean_task_delta_percent": 100.0
                * (_mean(candidate_values) / _mean(comparator_values) - 1.0),
                "win_tie_loss_cells": {
                    "wins": sum(a > b for a, b in zip(candidate_values, comparator_values)),
                    "ties": sum(a == b for a, b in zip(candidate_values, comparator_values)),
                    "losses": sum(a < b for a, b in zip(candidate_values, comparator_values)),
                },
            }
        sign_flip = _exact_sign_flip(seed_effects)
        comparisons.append(
            {
                "candidate": candidate,
                "comparator": comparator,
                "n_seed_clusters": len(seeds),
                "cells_per_seed_cluster": len(maps) * len(workloads),
                "candidate_mean_tasks": _mean(candidate_all),
                "comparator_mean_tasks": _mean(comparator_all),
                "mean_absolute_task_delta": _mean(cell_deltas),
                "relative_mean_task_delta_percent": 100.0
                * (_mean(candidate_all) / _mean(comparator_all) - 1.0),
                "mean_cellwise_relative_task_delta_percent": _mean(cell_relative),
                "median_cellwise_absolute_task_delta": statistics.median(cell_deltas),
                "win_tie_loss_cells": {
                    "wins": sum(value > 0 for value in cell_deltas),
                    "ties": sum(value == 0 for value in cell_deltas),
                    "losses": sum(value < 0 for value in cell_deltas),
                },
                "win_tie_loss_seed_clusters": {
                    "wins": sum(value > 0 for value in seed_effects),
                    "ties": sum(value == 0 for value in seed_effects),
                    "losses": sum(value < 0 for value in seed_effects),
                },
                "seed_cluster_absolute_task_deltas": {
                    str(seed): effect for seed, effect in zip(seeds, seed_effects)
                },
                "cluster_bootstrap": _cluster_bootstrap(
                    candidate_clusters,
                    comparator_clusters,
                    samples=bootstrap_samples,
                    seed=BOOTSTRAP_SEED,
                ),
                "exact_sign_flip": sign_flip,
                "by_workload": workload_rows,
            }
        )

    two_sided = {
        row["comparator"]: row["exact_sign_flip"]["p_two_sided"]
        for row in comparisons
    }
    greater = {
        row["comparator"]: row["exact_sign_flip"]["p_greater"]
        for row in comparisons
    }
    holm_two_sided = _holm_adjust(two_sided)
    holm_greater = _holm_adjust(greater)
    for row in comparisons:
        comparator = row["comparator"]
        row["exact_sign_flip"]["holm_adjusted_p_two_sided_family_all_comparators"] = (
            holm_two_sided[comparator]
        )
        row["exact_sign_flip"]["holm_adjusted_p_greater_family_all_comparators"] = (
            holm_greater[comparator]
        )
    comparisons.sort(key=lambda row: (-row["comparator_mean_tasks"], row["comparator"]))
    return comparisons


def _pareto_frontier(
    summaries: Sequence[Mapping[str, Any]], cost_field: str
) -> dict[str, Any]:
    frontier: list[str] = []
    dominated_by: dict[str, list[str]] = {}
    for row in summaries:
        dominators: list[str] = []
        for other in summaries:
            if other["method"] == row["method"]:
                continue
            weak_better = (
                other["mean_tasks"] >= row["mean_tasks"]
                and other[cost_field] <= row[cost_field]
            )
            strict = (
                other["mean_tasks"] > row["mean_tasks"]
                or other[cost_field] < row[cost_field]
            )
            if weak_better and strict:
                dominators.append(str(other["method"]))
        if dominators:
            dominated_by[str(row["method"])] = sorted(dominators)
        else:
            frontier.append(str(row["method"]))
    frontier.sort(
        key=lambda method: next(
            row[cost_field] for row in summaries if row["method"] == method
        )
    )
    return {
        "objectives": {"mean_tasks": "maximize", cost_field: "minimize"},
        "frontier_methods": frontier,
        "dominated_by": dominated_by,
    }


def _random_driver_diagnostic(
    candidate: str,
    random_method: str,
    seeds: Sequence[int],
    maps: Sequence[str],
    workloads: Sequence[str],
    runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    methods = {str(run["method"]) for run in runs}
    if random_method not in methods or random_method == candidate:
        return None
    indexed = {
        (run["method"], run["seed"], run["map_id"], run["workload"]): run
        for run in runs
    }
    # Positive values favor random; this orientation makes concentration of
    # the surprisingly strong random baseline easy to read.
    cell_rows: list[dict[str, Any]] = []
    for seed, map_id, workload in itertools.product(seeds, maps, workloads):
        random_tasks = float(indexed[(random_method, seed, map_id, workload)]["tasks"])
        candidate_tasks = float(indexed[(candidate, seed, map_id, workload)]["tasks"])
        cell_rows.append(
            {
                "seed": seed,
                "map_id": map_id,
                "workload": workload,
                "random_tasks": random_tasks,
                "candidate_tasks": candidate_tasks,
                "random_minus_candidate_tasks": random_tasks - candidate_tasks,
            }
        )
    by_seed = []
    for seed in seeds:
        values = [
            row["random_minus_candidate_tasks"]
            for row in cell_rows
            if row["seed"] == seed
        ]
        by_seed.append({"seed": seed, "mean_random_advantage_tasks": _mean(values)})
    by_workload = []
    for workload in workloads:
        values = [
            row["random_minus_candidate_tasks"]
            for row in cell_rows
            if row["workload"] == workload
        ]
        by_workload.append(
            {"workload": workload, "mean_random_advantage_tasks": _mean(values)}
        )
    leave_one_seed_out = []
    for omitted in seeds:
        values = [
            row["random_minus_candidate_tasks"]
            for row in cell_rows
            if row["seed"] != omitted
        ]
        leave_one_seed_out.append(
            {"omitted_seed": omitted, "mean_random_advantage_tasks": _mean(values)}
        )
    positive_seed_values = sorted(
        (row["mean_random_advantage_tasks"] for row in by_seed if row["mean_random_advantage_tasks"] > 0),
        reverse=True,
    )
    positive_seed_mass = math.fsum(positive_seed_values)
    top_two_seed_share = (
        math.fsum(positive_seed_values[:2]) / positive_seed_mass
        if positive_seed_mass > 0
        else 0.0
    )
    positive_workload_values = sorted(
        (
            row["mean_random_advantage_tasks"]
            for row in by_workload
            if row["mean_random_advantage_tasks"] > 0
        ),
        reverse=True,
    )
    positive_workload_mass = math.fsum(positive_workload_values)
    top_workload_share = (
        positive_workload_values[0] / positive_workload_mass
        if positive_workload_mass > 0
        else 0.0
    )
    positive_seed_count = sum(
        row["mean_random_advantage_tasks"] > 0 for row in by_seed
    )
    positive_workload_count = sum(
        row["mean_random_advantage_tasks"] > 0 for row in by_workload
    )
    loo_values = [row["mean_random_advantage_tasks"] for row in leave_one_seed_out]
    if positive_seed_count >= math.ceil(0.6 * len(seeds)) and min(loo_values) > 0:
        seed_diagnosis = "broad_across_seeds_and_not_reversed_by_any_single_seed"
    elif positive_seed_count <= len(seeds) // 2:
        seed_diagnosis = "concentrated_in_a_minority_of_seed_clusters"
    elif min(loo_values) <= 0:
        seed_diagnosis = "fragile_to_at_least_one_seed_cluster"
    else:
        seed_diagnosis = "mixed_across_seed_clusters"
    if positive_workload_count >= math.ceil(0.6 * len(workloads)) and top_workload_share < 0.75:
        workload_diagnosis = "broad_across_workloads"
    elif positive_workload_count <= len(workloads) // 2:
        workload_diagnosis = "concentrated_in_a_minority_of_workloads"
    else:
        workload_diagnosis = "mixed_or_uneven_across_workloads"
    return {
        "orientation": f"{random_method} minus {candidate}; positive favors random",
        "mean_random_advantage_tasks": _mean(
            row["random_minus_candidate_tasks"] for row in cell_rows
        ),
        "win_tie_loss_cells_for_random": {
            "wins": sum(row["random_minus_candidate_tasks"] > 0 for row in cell_rows),
            "ties": sum(row["random_minus_candidate_tasks"] == 0 for row in cell_rows),
            "losses": sum(row["random_minus_candidate_tasks"] < 0 for row in cell_rows),
        },
        "positive_seed_cluster_count": positive_seed_count,
        "seed_cluster_count": len(seeds),
        "top_two_positive_seed_share": top_two_seed_share,
        "seed_diagnosis": seed_diagnosis,
        "positive_workload_count": positive_workload_count,
        "workload_count": len(workloads),
        "top_positive_workload_share": top_workload_share,
        "workload_diagnosis": workload_diagnosis,
        "by_seed": sorted(by_seed, key=lambda row: row["seed"]),
        "by_workload": by_workload,
        "leave_one_seed_out": leave_one_seed_out,
        "leave_one_seed_out_range": [min(loo_values), max(loo_values)],
        "largest_random_advantage_cells": sorted(
            cell_rows,
            key=lambda row: -row["random_minus_candidate_tasks"],
        )[:10],
        "largest_candidate_advantage_cells": sorted(
            cell_rows,
            key=lambda row: row["random_minus_candidate_tasks"],
        )[:10],
    }


def analyze(
    artifact: Mapping[str, Any],
    *,
    candidate: str,
    random_method: str,
    bootstrap_samples: int,
    source_path: str,
    source_sha256: str,
) -> dict[str, Any]:
    methods, seeds, maps, workloads, runs = _normalize_artifact(artifact, candidate)
    summaries = _method_summaries(methods, runs)
    comparisons = _pairwise_comparisons(
        candidate,
        methods,
        seeds,
        maps,
        workloads,
        runs,
        bootstrap_samples=bootstrap_samples,
    )
    top_level_count_fields = (
        "collisions",
        "edge_swaps",
        "invalid_moves",
        "planner_timeouts",
        "budget_violation_count",
    )
    unsafe_totals = {
        field: sum(int(run.get(field, 0)) for run in runs)
        for field in top_level_count_fields
    }
    nested_safety_fields = (
        "collision_count",
        "edge_swap_count",
        "endpoint_mismatch_count",
        "invalid_move_count",
        "planner_timeout_count",
        "route_trace_invalid_count",
    )
    for field in nested_safety_fields:
        unsafe_totals[f"safety.{field}"] = sum(
            int(run.get("safety", {}).get(field, 0)) for run in runs
        )
    failed_safety_flags = sum(
        run.get("safety", {}).get("passed") is not True for run in runs
    )
    failed_invariant_flags = sum(
        run.get("invariants", {}).get("passed") is not True for run in runs
    )
    online_workload_rng_draws = sum(
        int(run.get("invariants", {}).get("online_workload_rng_draws", 0))
        for run in runs
    )
    return {
        "schema": ANALYSIS_SCHEMA,
        "source": {"path": source_path, "sha256": source_sha256},
        "evidence": {
            "split": artifact.get("split"),
            "evidence_class": artifact.get("evidence_class"),
            "development_only": artifact.get("split") == "development",
            "claim_warning": (
                "Development screening only; do not report as locked-test, "
                "confirmatory, paper-grade SOTA, or global LMAPF SOTA evidence."
            ),
        },
        "design": {
            "candidate": candidate,
            "methods": methods,
            "seeds": seeds,
            "maps": maps,
            "workloads": workloads,
            "run_count": len(runs),
            "independent_unit": "root seed",
            "cells_kept_together_per_cluster": len(maps) * len(workloads),
            "multiplicity_family": f"{candidate} versus all {len(methods) - 1} comparators",
        },
        "audit": {
            "complete_paired_grid": True,
            "pairing_fingerprints_match": True,
            "unsafe_or_invalid_totals": unsafe_totals,
            "failed_safety_flags": failed_safety_flags,
            "failed_invariant_flags": failed_invariant_flags,
            "online_workload_rng_draws": online_workload_rng_draws,
            "all_zero_unsafe_or_invalid_totals": (
                all(value == 0 for value in unsafe_totals.values())
                and failed_safety_flags == 0
                and failed_invariant_flags == 0
                and online_workload_rng_draws == 0
            ),
        },
        "method_macro_ranking": summaries,
        "workload_rankings": _workload_rankings(methods, workloads, runs),
        "pairwise_candidate_comparisons": comparisons,
        "multiplicity": {
            "procedure": "Holm step-down",
            "families": [
                "two-sided exact sign-flip p-values over all candidate comparisons",
                "one-sided greater exact sign-flip p-values over all candidate comparisons",
            ],
            "note": (
                "Raw one-sided p-values answer candidate superiority for one named "
                "comparison; Holm-adjusted values protect the full exploratory family."
            ),
        },
        "pareto": {
            "tasks_vs_post_bootstrap_publications": _pareto_frontier(
                summaries, "mean_post_bootstrap_publications"
            ),
            "tasks_vs_total_generator_calls": _pareto_frontier(
                summaries, "mean_generator_calls"
            ),
        },
        "random_driver_diagnostic": _random_driver_diagnostic(
            candidate, random_method, seeds, maps, workloads, runs
        ),
    }


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def render_markdown(report: Mapping[str, Any]) -> str:
    design = report["design"]
    audit = report["audit"]
    evidence = report["evidence"]
    lines = [
        "# Full development matrix analysis",
        "",
        f"Candidate: `{design['candidate']}`. Source split: `{evidence['split']}`. ",
        "",
        f"> **Scope:** {evidence['claim_warning']}",
        "",
        (
            f"The complete paired grid contains {design['run_count']} runs: "
            f"{len(design['methods'])} methods × {len(design['seeds'])} root seeds × "
            f"{len(design['maps'])} maps × {len(design['workloads'])} workloads. "
            "Inference clusters by root seed."
        ),
        "",
        f"Pairing audit: **{'PASS' if audit['complete_paired_grid'] and audit['pairing_fingerprints_match'] else 'FAIL'}**. "
        f"Zero safety/invalid outcomes: **{'PASS' if audit['all_zero_unsafe_or_invalid_totals'] else 'FAIL'}**.",
        "",
        "## Macro ranking",
        "",
        "| Rank | Method | Mean tasks | Post pubs | Generator calls |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in report["method_macro_ranking"]:
        lines.append(
            f"| {row['task_rank']} | `{row['method']}` | {_fmt(row['mean_tasks'])} | "
            f"{_fmt(row['mean_post_bootstrap_publications'])} | {_fmt(row['mean_generator_calls'])} |"
        )
    lines.extend(["", "## Per-workload rankings", ""])
    for workload, rows in report["workload_rankings"].items():
        lines.extend(
            [
                f"### {workload}",
                "",
                "| Rank | Method | Mean tasks |",
                "|---:|---|---:|",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['task_rank']} | `{row['method']}` | {_fmt(row['mean_tasks'])} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Candidate pairwise inference",
            "",
            (
                "Effects are candidate minus comparator. Bootstrap intervals resample "
                "whole root-seed clusters; p-values use all exact sign assignments."
            ),
            "",
            "| Comparator | Δ tasks | Δ % | 95% CI tasks | W/T/L seeds | p> raw | p> Holm | p2 Holm |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["pairwise_candidate_comparisons"]:
        ci = row["cluster_bootstrap"]["absolute_task_delta_ci"]
        wtl = row["win_tie_loss_seed_clusters"]
        sign = row["exact_sign_flip"]
        lines.append(
            f"| `{row['comparator']}` | {_fmt(row['mean_absolute_task_delta'])} | "
            f"{_fmt(row['relative_mean_task_delta_percent'])}% | "
            f"[{_fmt(ci[0])}, {_fmt(ci[1])}] | "
            f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} | "
            f"{sign['p_greater']:.4g} | "
            f"{sign['holm_adjusted_p_greater_family_all_comparators']:.4g} | "
            f"{sign['holm_adjusted_p_two_sided_family_all_comparators']:.4g} |"
        )
    lines.extend(["", "## Pareto frontiers", ""])
    for name, item in report["pareto"].items():
        lines.append(
            f"- {name}: " + ", ".join(f"`{method}`" for method in item["frontier_methods"])
        )
    diagnostic = report.get("random_driver_diagnostic")
    if diagnostic:
        lines.extend(
            [
                "",
                "## Random-baseline driver diagnostic",
                "",
                f"Mean random advantage: {_fmt(diagnostic['mean_random_advantage_tasks'])} tasks. "
                f"Random cell W/T/L: {diagnostic['win_tie_loss_cells_for_random']['wins']}/"
                f"{diagnostic['win_tie_loss_cells_for_random']['ties']}/"
                f"{diagnostic['win_tie_loss_cells_for_random']['losses']}.",
                "",
                f"Seed diagnosis: `{diagnostic['seed_diagnosis']}`; workload diagnosis: "
                f"`{diagnostic['workload_diagnosis']}`.",
                "",
                "| Seed | Random − candidate tasks |",
                "|---:|---:|",
            ]
        )
        for row in diagnostic["by_seed"]:
            lines.append(
                f"| {row['seed']} | {_fmt(row['mean_random_advantage_tasks'])} |"
            )
        lines.extend(
            [
                "",
                "| Workload | Random − candidate tasks |",
                "|---|---:|",
            ]
        )
        for row in diagnostic["by_workload"]:
            lines.append(
                f"| {row['workload']} | {_fmt(row['mean_random_advantage_tasks'])} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation guardrail",
            "",
            (
                "A development-set rank is useful for method selection, not for a "
                "confirmatory superiority or SOTA claim. Freeze the selected controller "
                "before evaluating fresh validation and locked-test seeds/maps."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--random-method", default=DEFAULT_RANDOM_BASELINE)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    artifact_path = args.artifact.resolve()
    output_json = args.output_json or artifact_path.with_name(
        artifact_path.stem + "_matrix_analysis.json"
    )
    output_md = args.output_md or artifact_path.with_name(
        artifact_path.stem + "_matrix_analysis.md"
    )
    with artifact_path.open("r", encoding="utf-8") as stream:
        artifact = json.load(stream)
    report = analyze(
        artifact,
        candidate=args.candidate,
        random_method=args.random_method,
        bootstrap_samples=args.bootstrap_samples,
        source_path=str(artifact_path),
        source_sha256=_sha256(artifact_path),
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "output_json": str(output_json.resolve()),
                "output_md": str(output_md.resolve()),
                "source_sha256": report["source"]["sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
