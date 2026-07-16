"""Development-only sweep for repair timing and guidance strength."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

from .selective_repair_pilot import _paired_effect
from .selective_repair_smoke import SelectiveRepairResult, run_selective_repair_episode
from .smoke_sim import build_smoke_manifest


def _mean(values) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def run(config_path: Path, output_dir: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    results: list[SelectiveRepairResult] = []
    for scale in config["guidance_scales"]:
        for delay in config["event_delays"]:
            for map_id in config["maps"]:
                for workload in config["workloads"]:
                    for seed in config["seeds"]:
                        manifest = build_smoke_manifest(
                            map_id=map_id,
                            workload=workload,
                            n_agents=int(config["n_agents"]),
                            horizon_steps=int(config["horizon_steps"]),
                            seed=int(seed),
                        )
                        for method in config["methods"]:
                            selector_seeds = (
                                config["random_selector_seeds"]
                                if method.startswith("random_")
                                else [0]
                            )
                            for selector_seed in selector_seeds:
                                result, _ = run_selective_repair_episode(
                                    manifest=manifest,
                                    workload=workload,
                                    method=method,
                                    selector_seed=int(selector_seed),
                                    guidance_scale=float(scale),
                                    post_shift_window=int(config["post_shift_window"]),
                                    event_delay=int(delay),
                                )
                                results.append(result)

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [result.as_dict() for result in results]
    with (output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    settings: list[dict[str, object]] = []
    metric = "post_shift_throughput_100"
    for scale in config["guidance_scales"]:
        for delay in config["event_delays"]:
            subset = [
                result
                for result in results
                if result.guidance_scale == float(scale) and result.event_delay == int(delay)
            ]
            lazy_vs_no_update = _paired_effect(
                subset, proposed="lazy_0", baseline="no_update", metric=metric
            )
            all_vs_lazy = _paired_effect(
                subset, proposed="repair_all", baseline="lazy_0", metric=metric
            )
            top_vs_random = _paired_effect(
                subset, proposed="top_25", baseline="random_25", metric=metric
            )
            total_top_vs_random = _paired_effect(
                subset, proposed="top_25", baseline="random_25", metric="throughput"
            )
            viable = (
                lazy_vs_no_update["mean_absolute_gain"] >= 0.0
                and all_vs_lazy["mean_absolute_gain"] > 0.0
                and top_vs_random["mean_absolute_gain"] > 0.0
            )
            settings.append(
                {
                    "guidance_scale": float(scale),
                    "event_delay": int(delay),
                    "viable": viable,
                    "lazy_vs_no_update_post_absolute": lazy_vs_no_update["mean_absolute_gain"],
                    "all_vs_lazy_post_absolute": all_vs_lazy["mean_absolute_gain"],
                    "top_vs_random_post_absolute": top_vs_random["mean_absolute_gain"],
                    "top_vs_random_total_absolute": total_top_vs_random["mean_absolute_gain"],
                    "mean_lazy_post": _mean(
                        result.post_shift_throughput_100
                        for result in subset
                        if result.method == "lazy_0"
                    ),
                    "mean_all_post": _mean(
                        result.post_shift_throughput_100
                        for result in subset
                        if result.method == "repair_all"
                    ),
                    "mean_top_post": _mean(
                        result.post_shift_throughput_100
                        for result in subset
                        if result.method == "top_25"
                    ),
                    "mean_random_post": _mean(
                        result.post_shift_throughput_100
                        for result in subset
                        if result.method == "random_25"
                    ),
                }
            )
    viable = [setting for setting in settings if setting["viable"]]
    recommended = (
        max(
            viable,
            key=lambda setting: (
                setting["top_vs_random_post_absolute"],
                setting["all_vs_lazy_post_absolute"],
            ),
        )
        if viable
        else None
    )
    summary: dict[str, object] = {
        "config": config,
        "n_runs": len(results),
        "settings": settings,
        "recommended_setting": recommended,
        "development_only": True,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    lines = [
        "# Selective-repair development sweep",
        "",
        "> Development seeds only; no inferential claim may use this table.",
        "",
        "| scale | delay | lazy-no-update | all-lazy | top-random | viable |",
        "|---:|---:|---:|---:|---:|:---:|",
    ]
    for setting in settings:
        lines.append(
            "| {guidance_scale:.1f} | {event_delay} | {lazy_vs_no_update_post_absolute:+.4f} "
            "| {all_vs_lazy_post_absolute:+.4f} | {top_vs_random_post_absolute:+.4f} "
            "| {viable} |".format(**setting)
        )
    lines.extend(
        [
            "",
            f"Recommended frozen setting: `{recommended}`",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
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
