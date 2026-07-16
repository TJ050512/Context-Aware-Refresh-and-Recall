"""Build and freeze the Gate 0 causal publication trigger.

No simulator is started by this script.  Development data must first be
generated with the complete shift-mask method set emitted by ``plan``.  The
``dataset`` command constructs seven prefix-paired, next-shift labels per seed;
``train`` selects ridge regularization by leave-one-seed-out grouped CV and
freezes both mean and conservative LCB decision rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--config", type=Path, required=True)

    dataset_parser = subparsers.add_parser("dataset")
    dataset_parser.add_argument("--config", type=Path, required=True)
    dataset_parser.add_argument(
        "--artifacts", type=Path, nargs="+", required=True
    )
    dataset_parser.add_argument("--output", type=Path, required=True)

    train_parser = subparsers.add_parser("train")
    train_parser.add_argument("--config", type=Path, required=True)
    train_parser.add_argument("--dataset", type=Path, required=True)
    train_parser.add_argument("--output", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify-evaluation")
    verify_parser.add_argument("--config", type=Path, required=True)
    verify_parser.add_argument("--model", type=Path, required=True)

    args = parser.parse_args()
    workspace = args.workspace.resolve()
    sys.path.insert(0, str(workspace / "src"))
    from dai_lmapf.causal_trigger import (
        DEFAULT_FEATURE_NAMES,
        FrozenRidgeTrigger,
        build_prefix_dataset,
        canonical_hash,
        fit_frozen_ridge_trigger,
        methods_for_shift_count,
    )

    config = _load_json(args.config.resolve())
    if config.get("schema") != "dai.gate0.causal-trigger-config/v1":
        raise ValueError("unsupported causal trigger config schema")
    protocol = config["protocol"]
    model_config = config["model"]
    split_sets = {
        "development": set(map(int, protocol["development_seeds"])),
        "evaluation": set(map(int, protocol["evaluation_seeds"])),
        "locked_test": set(map(int, protocol.get("locked_test_seeds", []))),
    }
    split_names = tuple(split_sets)
    for index, left_name in enumerate(split_names):
        for right_name in split_names[index + 1:]:
            overlap = split_sets[left_name] & split_sets[right_name]
            if overlap:
                raise ValueError(
                    f"seed split overlap between {left_name} and "
                    f"{right_name}: {sorted(overlap)!r}"
                )
    shift_count = int(protocol["shift_count"])
    methods = list(methods_for_shift_count(shift_count))
    if methods != protocol["development_methods"]:
        raise ValueError(
            "config development_methods is not the complete binary tree"
        )
    feature_names = tuple(config.get(
        "feature_names", DEFAULT_FEATURE_NAMES
    ))

    if args.command == "plan":
        experiment = config["experiment"]
        output = {
            "schema": "dai.gate0.causal-trigger-plan/v1",
            "config_id": canonical_hash(config),
            "claim_scope": config["claim_scope"],
            "development": {
                "seeds": protocol["development_seeds"],
                "methods": methods,
                "expected_trajectories": (
                    len(protocol["development_seeds"]) * len(methods)
                ),
                "expected_labels": (
                    len(protocol["development_seeds"])
                    * ((1 << shift_count) - 1)
                ),
                "runner_arguments": experiment,
            },
            "evaluation": {
                "seeds": protocol["evaluation_seeds"],
                "role": "validation/evaluation; frozen model only",
                "methods": [
                    "never",
                    "oracle_boundary_ridge",
                    "oracle_boundary_lcb",
                    "oracle_shift",
                ],
                "runner_arguments": experiment,
            },
            "locked_test": {
                "seeds": protocol.get("locked_test_seeds", []),
                "role": "sealed one-shot confirmatory block",
                "status": "reserved; this diagnostic pipeline must not run it",
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return

    if args.command == "dataset":
        artifacts = [_load_json(path.resolve()) for path in args.artifacts]
        dataset = build_prefix_dataset(
            artifacts,
            development_seeds=protocol["development_seeds"],
            shift_count=shift_count,
            label_horizon_steps=int(protocol["label_horizon_steps"]),
            publication_penalty_tasks=float(
                protocol["publication_penalty_tasks"]
            ),
            feature_names=feature_names,
        )
        dataset["config_id"] = canonical_hash(config)
        dataset["claim_scope"] = config["claim_scope"]
        # Recompute after attaching the registered config identity.
        dataset_core = dict(dataset)
        dataset_core.pop("dataset_id", None)
        dataset["dataset_id"] = canonical_hash(dataset_core)
        _write_json(args.output.resolve(), dataset)
        print(f"dataset={args.output.resolve()}")
        print(f"rows={len(dataset['rows'])}")
        print(f"dataset_id={dataset['dataset_id']}")
        return

    if args.command == "train":
        dataset = _load_json(args.dataset.resolve())
        if dataset.get("config_id") != canonical_hash(config):
            raise ValueError("dataset was not built from this frozen config")
        model = fit_frozen_ridge_trigger(
            dataset,
            candidate_lambdas=model_config["candidate_lambdas"],
            beta=float(model_config["beta"]),
            threshold=float(model_config["threshold"]),
            evaluation_seeds=protocol["evaluation_seeds"],
        )
        model["config_id"] = canonical_hash(config)
        model["claim_scope"] = config["claim_scope"]
        model_core = dict(model)
        model_core.pop("model_id", None)
        model["model_id"] = canonical_hash(model_core)
        _write_json(args.output.resolve(), model)
        print(f"model={args.output.resolve()}")
        print(f"model_id={model['model_id']}")
        print(f"ridge_lambda={model['ridge_lambda']}")
        return

    if args.command == "verify-evaluation":
        model = FrozenRidgeTrigger.from_path(args.model.resolve())
        if model.artifact.get("config_id") != canonical_hash(config):
            raise ValueError("model was not frozen from this config")
        for seed in protocol["evaluation_seeds"]:
            model.validate_evaluation_seed(int(seed))
        if set(model.training_seeds) != set(protocol["development_seeds"]):
            raise ValueError("model training split differs from config")
        result = {
            "status": "pass",
            "model_id": model.model_id,
            "training_seeds": sorted(model.training_seeds),
            "evaluation_seeds": sorted(model.evaluation_seeds),
            "feature_names": list(model.feature_names),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    raise RuntimeError("unreachable command")


if __name__ == "__main__":
    main()
