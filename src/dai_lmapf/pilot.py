"""Command-line runner and statistics for the local mechanism smoke pilot."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .controller import (
    BudgetedEventTriggeredController,
    DriftThresholdController,
    FixedController,
    GuidanceAction,
    GuidanceController,
    PeriodicRefreshController,
)
from .smoke_sim import (
    DecisionRecord,
    SmokeRunResult,
    build_smoke_manifest,
    run_smoke_episode,
)


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def _bootstrap_ci(values: list[float], *, seed: int = 19, samples: int = 10_000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    if len(values) == 1:
        return [values[0], values[0]]
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        means.append(_mean(rng.choice(values) for _ in range(len(values))))
    means.sort()
    return [means[int(0.025 * samples)], means[int(0.975 * samples)]]


def _sign_flip_pvalue(values: list[float], *, seed: int = 23) -> float:
    if not values:
        return 1.0
    observed = abs(_mean(values))
    if len(values) <= 16:
        permutations = itertools.product((-1.0, 1.0), repeat=len(values))
        extreme = total = 0
        for signs in permutations:
            total += 1
            statistic = abs(_mean(value * sign for value, sign in zip(values, signs)))
            if statistic >= observed - 1e-15:
                extreme += 1
        return extreme / total
    rng = random.Random(seed)
    samples = 100_000
    extreme = 0
    for _ in range(samples):
        statistic = abs(
            _mean(value * (-1.0 if rng.randrange(2) else 1.0) for value in values)
        )
        if statistic >= observed - 1e-15:
            extreme += 1
    return (extreme + 1) / (samples + 1)


def _controller_for(
    method: str,
    *,
    decision_interval: int,
    always_refresh_cost: float,
) -> GuidanceController | None:
    if method == "shortest":
        return None
    if method == "always_refresh":
        return FixedController(GuidanceAction(True, "smoke_cached_heat"))
    if method == "always_reuse":
        return FixedController(GuidanceAction(False, "smoke_cached_heat"))
    if method.startswith("periodic_"):
        period = int(method.rsplit("_", 1)[1])
        return PeriodicRefreshController(period, generator_id="smoke_cached_heat")
    if method.startswith("drift_"):
        fraction = int(method.rsplit("_", 1)[1]) / 100.0
        return DriftThresholdController(
            threshold=0.018,
            max_refresh_fraction=fraction,
            refresh_burst_capacity=2.0,
            minimum_gap_steps=decision_interval,
            use_edge_drift=False,
        )
    if method.startswith("betg_"):
        fraction = int(method.rsplit("_", 1)[1]) / 100.0
        # The local smoke backend is too fast for stable millisecond feedback:
        # timer jitter changed action traces across identical replays.  Use a
        # deterministic token budget here and only log wall-clock cost.  The
        # official Online GGO stage will freeze a budget from a separate
        # calibration split before any test runs.
        del always_refresh_cost
        return BudgetedEventTriggeredController(
            sliding_window=30,
            exploration_alpha=0.25,
            ridge=1.0,
            budget_seconds_per_window=None,
            dual_step_size=0.005,
            hysteresis_margin=0.005,
            max_refresh_fraction=fraction,
            refresh_burst_capacity=2.0,
            minimum_gap_steps=decision_interval,
            safety_goal_js_threshold=0.06,
            safety_wait_threshold=0.22,
        )
    raise ValueError(f"unknown method: {method}")


def _controller_seed(seed: int, method: str) -> int:
    return seed * 10_000 + sum((index + 1) * ord(char) for index, char in enumerate(method))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _condition_summaries(results: list[SmokeRunResult]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str, int], list[SmokeRunResult]] = defaultdict(list)
    for result in results:
        grouped[(result.method, result.map_id, result.workload, result.n_agents)].append(result)
    rows: list[dict[str, object]] = []
    for (method, map_id, workload, n_agents), group in sorted(grouped.items()):
        rows.append(
            {
                "method": method,
                "map_id": map_id,
                "workload": workload,
                "n_agents": n_agents,
                "n_runs": len(group),
                "throughput_mean": _mean(item.throughput for item in group),
                "throughput_std": statistics.pstdev(
                    [item.throughput for item in group]
                ) if len(group) > 1 else 0.0,
                "wait_rate_mean": _mean(item.wait_rate for item in group),
                "refresh_rate_mean": _mean(item.refresh_rate for item in group),
                "wall_time_seconds_mean": _mean(item.wall_time_seconds for item in group),
                "refresh_seconds_mean": _mean(item.refresh_seconds for item in group),
                "budget_violation_rate": _mean(item.budget_violation for item in group),
                "deadlock_rate": _mean(float(item.deadlocked) for item in group),
                "collision_count": sum(item.collision_count for item in group),
            }
        )
    return rows


def _paired_analysis(
    results: list[SmokeRunResult],
    *,
    proposed: str,
    baseline: str,
    dynamic_workloads: set[str],
    eligible_maps: set[str] | None = None,
    eligible_agent_counts: set[int] | None = None,
) -> dict[str, object]:
    by_key = {
        (
            result.method,
            result.map_id,
            result.workload,
            result.n_agents,
            result.layout_seed,
        ): result
        for result in results
    }
    seed_effects: dict[int, list[float]] = defaultdict(list)
    condition_effects: list[dict[str, object]] = []
    conditions = sorted(
        {
            (result.map_id, result.workload, result.n_agents, result.layout_seed)
            for result in results
            if result.workload in dynamic_workloads
            and (eligible_maps is None or result.map_id in eligible_maps)
            and (
                eligible_agent_counts is None
                or result.n_agents in eligible_agent_counts
            )
        }
    )
    for map_id, workload, n_agents, layout_seed in conditions:
        proposed_result = by_key.get((proposed, map_id, workload, n_agents, layout_seed))
        baseline_result = by_key.get((baseline, map_id, workload, n_agents, layout_seed))
        if proposed_result is None or baseline_result is None:
            continue
        relative = (
            proposed_result.throughput - baseline_result.throughput
        ) / max(1e-12, baseline_result.throughput)
        seed_effects[layout_seed].append(relative)
        condition_effects.append(
            {
                "map_id": map_id,
                "workload": workload,
                "n_agents": n_agents,
                "layout_seed": layout_seed,
                "relative_throughput_gain": relative,
                "absolute_throughput_gain": (
                    proposed_result.throughput - baseline_result.throughput
                ),
            }
        )
    paired = [_mean(values) for _, values in sorted(seed_effects.items())]
    ci = _bootstrap_ci(paired)
    return {
        "proposed": proposed,
        "baseline": baseline,
        "n_paired_seeds": len(paired),
        "eligible_maps": sorted(eligible_maps) if eligible_maps is not None else None,
        "eligible_agent_counts": (
            sorted(eligible_agent_counts)
            if eligible_agent_counts is not None
            else None
        ),
        "mean_relative_throughput_gain": _mean(paired),
        "median_relative_throughput_gain": statistics.median(paired) if paired else 0.0,
        "paired_bootstrap_ci95": ci,
        "sign_flip_pvalue": _sign_flip_pvalue(paired),
        "per_seed_effects": paired,
        "condition_effects": condition_effects,
    }


def _overall_method_summary(results: list[SmokeRunResult]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[SmokeRunResult]] = defaultdict(list)
    for result in results:
        grouped[result.method].append(result)
    return {
        method: {
            "throughput_mean": _mean(item.throughput for item in group),
            "wait_rate_mean": _mean(item.wait_rate for item in group),
            "refresh_rate_mean": _mean(item.refresh_rate for item in group),
            "wall_time_seconds_mean": _mean(item.wall_time_seconds for item in group),
            "refresh_seconds_mean": _mean(item.refresh_seconds for item in group),
            "budget_violation_rate": _mean(item.budget_violation for item in group),
        }
        for method, group in sorted(grouped.items())
    }


def _write_report(path: Path, summary: Mapping[str, object]) -> None:
    paired = summary["primary_paired_analysis"]
    overall = summary["overall_methods"]
    lines = [
        "# Local mechanism smoke-pilot report",
        "",
        "> Diagnostic two/three-corridor results only. These are not Online GGO, public-map, or SOTA results.",
        "",
        "## Primary paired comparison",
        "",
        f"- Proposed: `{paired['proposed']}`",
        f"- Baseline: `{paired['baseline']}`",
        f"- Paired seeds: {paired['n_paired_seeds']}",
        f"- Mean relative throughput gain: {100 * paired['mean_relative_throughput_gain']:.2f}%",
        f"- Paired bootstrap 95% CI: [{100 * paired['paired_bootstrap_ci95'][0]:.2f}%, {100 * paired['paired_bootstrap_ci95'][1]:.2f}%]",
        f"- Exact/Monte-Carlo sign-flip p-value: {paired['sign_flip_pvalue']:.6f}",
        "",
        "## Overall method means",
        "",
        "| Method | Throughput | Wait rate | Refresh rate | Wall time (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for method, metrics in overall.items():
        lines.append(
            f"| {method} | {metrics['throughput_mean']:.4f} | "
            f"{metrics['wait_rate_mean']:.4f} | {metrics['refresh_rate_mean']:.4f} | "
            f"{metrics['wall_time_seconds_mean']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation gate",
            "",
            summary["interpretation"],
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_pilot(config: Mapping[str, object], output_dir: Path) -> dict[str, object]:
    horizon = int(config["horizon_steps"])
    decision_interval = int(config["decision_interval_steps"])
    guidance_scale = float(config["guidance_scale"])
    maps = [str(value) for value in config["maps"]]
    agent_counts = [int(value) for value in config["agent_counts"]]
    workloads = [str(value) for value in config["workloads"]]
    seeds = [int(value) for value in config["seeds"]]
    methods = [str(value) for value in config["methods"]]
    if "always_refresh" not in methods:
        raise ValueError("always_refresh is required to calibrate wall-clock budgets")

    results: list[SmokeRunResult] = []
    decisions: list[dict[str, object]] = []
    scenarios = list(itertools.product(maps, agent_counts, workloads, seeds))
    for scenario_index, (map_id, n_agents, workload, seed) in enumerate(scenarios, start=1):
        manifest = build_smoke_manifest(
            map_id=map_id,
            workload=workload,
            n_agents=n_agents,
            horizon_steps=horizon,
            seed=seed,
        )
        always = _controller_for(
            "always_refresh", decision_interval=decision_interval, always_refresh_cost=1.0
        )
        always_result, always_decisions = run_smoke_episode(
            manifest=manifest,
            workload=workload,
            method="always_refresh",
            controller=always,
            decision_interval=decision_interval,
            controller_seed=_controller_seed(seed, "always_refresh"),
            guidance_scale=guidance_scale,
        )
        calibrated_cost = always_result.refresh_seconds / max(1, always_result.refresh_count)
        scenario_results = {"always_refresh": (always_result, always_decisions)}
        for method in methods:
            if method == "always_refresh":
                continue
            controller = _controller_for(
                method,
                decision_interval=decision_interval,
                always_refresh_cost=calibrated_cost,
            )
            scenario_results[method] = run_smoke_episode(
                manifest=manifest,
                workload=workload,
                method=method,
                controller=controller,
                decision_interval=decision_interval,
                controller_seed=_controller_seed(seed, method),
                guidance_scale=guidance_scale,
            )
        for method in methods:
            result, records = scenario_results[method]
            results.append(result)
            for record in records:
                row = record.as_dict()
                row.update(
                    {
                        "method": method,
                        "scenario_id": result.scenario_id,
                        "map_id": map_id,
                        "workload": workload,
                        "n_agents": n_agents,
                        "layout_seed": result.layout_seed,
                    }
                )
                decisions.append(row)
        print(
            f"[{scenario_index}/{len(scenarios)}] {map_id} n={n_agents} "
            f"{workload} seed={seed}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    run_rows = [result.as_dict() for result in results]
    _write_csv(output_dir / "runs.csv", run_rows)
    condition_rows = _condition_summaries(results)
    _write_csv(output_dir / "condition_summary.csv", condition_rows)
    with (output_dir / "decisions.jsonl").open("w", encoding="utf-8") as handle:
        for row in decisions:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    comparison = config["primary_comparison"]
    paired = _paired_analysis(
        results,
        proposed=str(comparison["proposed"]),
        baseline=str(comparison["baseline"]),
        dynamic_workloads={str(item) for item in comparison["dynamic_workloads"]},
        eligible_maps={str(item) for item in comparison.get("maps", [])} or None,
        eligible_agent_counts={
            int(item) for item in comparison.get("agent_counts", [])
        } or None,
    )
    lower = paired["paired_bootstrap_ci95"][0]
    mean_gain = paired["mean_relative_throughput_gain"]
    if mean_gain >= 0.05 and lower > 0:
        interpretation = (
            "GO for official-backbone replication: the local mechanism cleared the "
            "registered 5% paired throughput gate. This still is not a paper result."
        )
    elif mean_gain >= 0.03:
        interpretation = (
            "BORDERLINE: expand locked smoke seeds once without changing parameters, "
            "then decide whether official-backbone integration is worth the cost."
        )
    else:
        interpretation = (
            "NO-GO on the current controller/configuration: do not claim value. Diagnose "
            "the action trace and improve the mechanism before large public runs."
        )
    summary: dict[str, object] = {
        "disclaimer": (
            "Local transactional smoke simulator only; not public benchmark or SOTA evidence."
        ),
        "config": dict(config),
        "n_runs": len(results),
        "n_decision_records": len(decisions),
        "overall_methods": _overall_method_summary(results),
        "primary_paired_analysis": paired,
        "interpretation": interpretation,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_report(output_dir / "REPORT.md", summary)
    return summary


def _load_config(path: Path, *, quick: bool) -> dict[str, object]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != "1":
        raise ValueError("unsupported smoke-pilot config schema")
    if quick:
        config["horizon_steps"] = min(250, int(config["horizon_steps"]))
        config["maps"] = list(config["maps"])[:1]
        config["agent_counts"] = [max(int(value) for value in config["agent_counts"])]
        config["seeds"] = list(config["seeds"])[:3]
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/smoke_pilot.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("results/smoke_pilot_quick")
    )
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    config = _load_config(args.config, quick=args.quick)
    summary = run_pilot(config, args.output)
    paired = summary["primary_paired_analysis"]
    print(
        "Primary paired mean gain: "
        f"{100 * paired['mean_relative_throughput_gain']:.2f}% "
        f"(95% CI {100 * paired['paired_bootstrap_ci95'][0]:.2f}% to "
        f"{100 * paired['paired_bootstrap_ci95'][1]:.2f}%)"
    )
    print(summary["interpretation"])


if __name__ == "__main__":
    main()
