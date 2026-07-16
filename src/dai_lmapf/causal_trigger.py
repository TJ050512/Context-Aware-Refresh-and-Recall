"""Causal prefix-pair labels and frozen linear publication triggers.

The Gate 0 trigger is trained only from a complete binary publication tree.
At a shift node, the refresh and reuse trajectories must have replayed the
same prefix exactly; both arms then reuse until the next shift.  Consequently
the local reward difference is a conditional one-step treatment effect rather
than a per-seed hindsight schedule label.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DATASET_SCHEMA = "dai.gate0.causal-prefix-dataset/v1"
MODEL_SCHEMA = "dai.gate0.frozen-ridge-trigger/v1"


DEFAULT_FEATURE_NAMES = (
    "guidance_age_windows",
    "task_js_since_refresh",
    "task_entropy",
    "task_hotspot",
    "recent_completed_per_agent",
    "recent_route_builds_per_agent",
    "recent_wait_ratio",
    "opposite_flow_ratio",
    "candidate_l1_relative",
    "candidate_cosine_distance",
)

FORBIDDEN_MODEL_FEATURES = frozenset({
    "distribution_js",
    "distribution_entropy",
    "distribution_hotspot",
    "episode_progress",
    "observed_shift_index",
    "pending_shift_timestep",
    "shift_index",
})


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def masks_for_shift_count(shift_count: int) -> tuple[str, ...]:
    if shift_count <= 0:
        raise ValueError("shift_count must be positive")
    return tuple(
        format(value, f"0{shift_count}b")
        for value in range(1 << shift_count)
    )


def methods_for_shift_count(shift_count: int) -> tuple[str, ...]:
    masks = masks_for_shift_count(shift_count)
    return ("never",) + tuple(
        f"shiftmask_{mask}" for mask in masks if "1" in mask
    )


@dataclass(frozen=True)
class PrefixPair:
    shift_index: int
    prefix: str
    control_mask: str
    treatment_mask: str


def prefix_pairs(shift_count: int) -> tuple[PrefixPair, ...]:
    """Return the edges of a complete binary prefix tree.

    Suffix bits are fixed to zero in both arms.  This implements a shared
    prefix, one-bit treatment contrast, and a common reuse-only suffix.
    """

    masks_for_shift_count(shift_count)
    pairs = []
    for shift_index in range(shift_count):
        suffix = "0" * (shift_count - shift_index - 1)
        for prefix_value in range(1 << shift_index):
            prefix = format(prefix_value, f"0{shift_index}b")
            if shift_index == 0:
                prefix = ""
            pairs.append(PrefixPair(
                shift_index=shift_index,
                prefix=prefix,
                control_mask=prefix + "0" + suffix,
                treatment_mask=prefix + "1" + suffix,
            ))
    return tuple(pairs)


def method_to_mask(method: str, shift_count: int) -> str:
    if method == "never":
        return "0" * shift_count
    prefix = "shiftmask_"
    if not method.startswith(prefix):
        raise ValueError(f"method {method!r} is not a shift-mask trajectory")
    mask = method[len(prefix):]
    if len(mask) != shift_count or any(bit not in "01" for bit in mask):
        raise ValueError(f"invalid {shift_count}-shift mask: {mask!r}")
    return mask


def _require_finite_features(
    features: Mapping[str, Any], names: Sequence[str]
) -> dict[str, float]:
    missing = [name for name in names if name not in features]
    if missing:
        raise ValueError(f"feature snapshot is missing {missing!r}")
    result = {}
    for name in names:
        value = features[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"feature {name!r} must be numeric")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"feature {name!r} must be finite")
        result[name] = value
    return result


def _run_local_reward(
    run: Mapping[str, Any], *, start: int, end: int
) -> float:
    selected = [
        window for window in run["windows"]
        if int(window["window_start_timestep"]) >= start
        and int(window["window_end_timestep"]) <= end
    ]
    if not selected:
        raise ValueError("paired suffix contains no reward windows")
    if int(selected[0]["window_start_timestep"]) != start:
        raise ValueError("paired suffix does not start at the decision boundary")
    if int(selected[-1]["window_end_timestep"]) != end:
        raise ValueError("paired suffix does not end at the registered horizon")
    for previous, current in zip(selected, selected[1:]):
        if previous["window_end_timestep"] != current["window_start_timestep"]:
            raise ValueError("paired suffix reward windows are not contiguous")
    return float(sum(float(window["reward"]) for window in selected))


def _shift_window(run: Mapping[str, Any], shift_index: int) -> Mapping[str, Any]:
    matches = [
        window for window in run["windows"]
        if window.get("observed_shift_index") == shift_index
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one decision for shift {shift_index}, found {len(matches)}"
        )
    return matches[0]


def build_prefix_dataset(
    artifacts: Iterable[Mapping[str, Any]],
    *,
    development_seeds: Sequence[int],
    shift_count: int,
    label_horizon_steps: int,
    publication_penalty_tasks: float,
    feature_names: Sequence[str] = DEFAULT_FEATURE_NAMES,
) -> dict[str, Any]:
    """Build conditional marginal-value labels from full-factorial replay."""

    if label_horizon_steps <= 0:
        raise ValueError("label_horizon_steps must be positive")
    if not math.isfinite(publication_penalty_tasks):
        raise ValueError("publication_penalty_tasks must be finite")
    seeds = tuple(int(seed) for seed in development_seeds)
    if len(set(seeds)) != len(seeds) or not seeds:
        raise ValueError("development_seeds must be non-empty and unique")
    names = tuple(feature_names)
    if len(set(names)) != len(names) or not names:
        raise ValueError("feature_names must be non-empty and unique")
    forbidden = sorted(set(names) & FORBIDDEN_MODEL_FEATURES)
    if forbidden:
        raise ValueError(
            f"model feature list contains oracle/protocol fields: {forbidden!r}"
        )

    required_masks = set(masks_for_shift_count(shift_count))
    runs_by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    artifact_fingerprints = []
    protocol_signature = None
    for artifact in artifacts:
        signature = {
            key: artifact[key]
            for key in (
                "agents",
                "warmup_time",
                "horizon",
                "decision_window",
                "shift_interval",
                "map_sha256",
                "period_on_sim_sha256",
                "generator",
                "workload",
            )
        }
        if protocol_signature is None:
            protocol_signature = signature
        elif signature != protocol_signature:
            raise ValueError("source artifacts use different experiment protocols")
        artifact_fingerprints.append(canonical_hash(artifact))
        for run in artifact["runs"]:
            seed = int(run["seed"])
            if seed not in seeds:
                continue
            mask = method_to_mask(str(run["method"]), shift_count)
            key = (seed, mask)
            if key in runs_by_key:
                raise ValueError(f"duplicate trajectory for seed/mask {key!r}")
            runs_by_key[key] = run

    for seed in seeds:
        present = {mask for run_seed, mask in runs_by_key if run_seed == seed}
        if present != required_masks:
            raise ValueError(
                f"seed {seed} masks differ from the complete factorial: "
                f"missing={sorted(required_masks - present)!r}, "
                f"extra={sorted(present - required_masks)!r}"
            )

    rows = []
    for seed in seeds:
        reset_hashes = {
            str(runs_by_key[(seed, mask)]["reset_causal_fingerprint"])
            for mask in required_masks
        }
        distribution_hashes = {
            str(runs_by_key[(seed, mask)]["distribution_update_fingerprint"])
            for mask in required_masks
        }
        if len(reset_hashes) != 1 or len(distribution_hashes) != 1:
            raise ValueError(f"seed {seed} is not causally paired across masks")

        for pair in prefix_pairs(shift_count):
            control = runs_by_key[(seed, pair.control_mask)]
            treatment = runs_by_key[(seed, pair.treatment_mask)]
            control_window = _shift_window(control, pair.shift_index)
            treatment_window = _shift_window(treatment, pair.shift_index)
            control_feature_hash = control_window.get(
                "decision_feature_fingerprint"
            )
            treatment_feature_hash = treatment_window.get(
                "decision_feature_fingerprint"
            )
            if not control_feature_hash or not treatment_feature_hash:
                raise ValueError("source artifact lacks causal feature fingerprints")
            if control_feature_hash != treatment_feature_hash:
                raise ValueError(
                    "paired children do not share an identical prefix feature state: "
                    f"seed={seed}, shift={pair.shift_index}, prefix={pair.prefix!r}"
                )
            if (
                control_window.get("decision_state_fingerprint")
                != treatment_window.get("decision_state_fingerprint")
            ):
                raise ValueError("paired children do not share exact simulator state")
            start = int(control_window["window_start_timestep"])
            if start != int(treatment_window["window_start_timestep"]):
                raise ValueError("paired children have different decision timesteps")
            end = start + label_horizon_steps
            control_reward = _run_local_reward(control, start=start, end=end)
            treatment_reward = _run_local_reward(
                treatment, start=start, end=end
            )
            snapshot = control_window["decision_feature_snapshot"]
            features = _require_finite_features(snapshot["features"], names)
            marginal = treatment_reward - control_reward
            rows.append({
                "seed": seed,
                "shift_index": pair.shift_index,
                "prefix": pair.prefix,
                "control_mask": pair.control_mask,
                "treatment_mask": pair.treatment_mask,
                "decision_timestep": start,
                "label_end_timestep": end,
                "control_reward": control_reward,
                "treatment_reward": treatment_reward,
                "marginal_tasks": marginal,
                "net_value_tasks": marginal - publication_penalty_tasks,
                "refresh_beneficial": marginal > publication_penalty_tasks,
                "decision_feature_fingerprint": control_feature_hash,
                "decision_state_fingerprint": control_window[
                    "decision_state_fingerprint"
                ],
                "features": features,
            })

    expected_rows = len(seeds) * ((1 << shift_count) - 1)
    if len(rows) != expected_rows:
        raise RuntimeError(
            f"built {len(rows)} labels, expected {expected_rows}"
        )
    core = {
        "schema": DATASET_SCHEMA,
        "development_seeds": list(seeds),
        "shift_count": shift_count,
        "label_horizon_steps": label_horizon_steps,
        "label_interval_semantics": {
            "decision_notation": "[shift_t,next_shift_t)",
            "simulator_trace_equivalent": "(shift_t,next_shift_t]",
            "reason": (
                "period_on_sim actions execute timesteps start+1 through end; "
                "the distribution update at end occurs after that timestep's "
                "task completions"
            ),
        },
        "publication_penalty_tasks": float(publication_penalty_tasks),
        "feature_names": list(names),
        "protocol_signature": protocol_signature,
        "source_artifact_fingerprints": sorted(artifact_fingerprints),
        "rows": rows,
    }
    core["dataset_id"] = canonical_hash(core)
    return core


def _ridge_fit(
    matrix: Any, target: Any, ridge_lambda: float
) -> tuple[Any, Any, float]:
    import numpy as np

    if ridge_lambda < 0 or not math.isfinite(ridge_lambda):
        raise ValueError("ridge lambda must be finite and non-negative")
    x = np.asarray(matrix, dtype=np.float64)
    y = np.asarray(target, dtype=np.float64)
    design = np.column_stack([np.ones(x.shape[0]), x])
    penalty = np.eye(design.shape[1], dtype=np.float64) * ridge_lambda
    penalty[0, 0] = 0.0
    gram = design.T @ design + penalty
    inverse = np.linalg.pinv(gram, hermitian=True)
    coefficients = inverse @ design.T @ y
    residual = y - design @ coefficients
    effective_df = float(np.trace(design @ inverse @ design.T))
    denominator = max(float(len(y)) - effective_df, 1.0)
    residual_sigma = math.sqrt(float(residual @ residual) / denominator)
    return coefficients, inverse, residual_sigma


def _standardize_fit(matrix: Any) -> tuple[Any, Any, Any]:
    import numpy as np

    x = np.asarray(matrix, dtype=np.float64)
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales = np.where(scales < 1e-12, 1.0, scales)
    return (x - means) / scales, means, scales


def fit_frozen_ridge_trigger(
    dataset: Mapping[str, Any],
    *,
    candidate_lambdas: Sequence[float],
    beta: float,
    threshold: float,
    evaluation_seeds: Sequence[int],
) -> dict[str, Any]:
    """Select ridge regularization by leave-one-seed-out development CV."""

    import numpy as np

    if dataset.get("schema") != DATASET_SCHEMA:
        raise ValueError("unsupported causal dataset schema")
    dataset_core = dict(dataset)
    expected_dataset_id = dataset_core.pop("dataset_id", None)
    if expected_dataset_id != canonical_hash(dataset_core):
        raise ValueError("dataset_id does not match causal dataset contents")
    if beta < 0 or not math.isfinite(beta):
        raise ValueError("beta must be finite and non-negative")
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    lambdas = tuple(float(value) for value in candidate_lambdas)
    if not lambdas or any(value < 0 or not math.isfinite(value) for value in lambdas):
        raise ValueError("candidate_lambdas must be finite and non-negative")
    feature_names = tuple(dataset["feature_names"])
    rows = list(dataset["rows"])
    development_seeds = tuple(int(seed) for seed in dataset["development_seeds"])
    held_out_seeds = tuple(int(seed) for seed in evaluation_seeds)
    if set(development_seeds) & set(held_out_seeds):
        raise ValueError("development and evaluation seeds overlap")
    x = np.asarray([
        [float(row["features"][name]) for name in feature_names]
        for row in rows
    ], dtype=np.float64)
    y = np.asarray([float(row["net_value_tasks"]) for row in rows])
    groups = np.asarray([int(row["seed"]) for row in rows])

    cv = []
    for ridge_lambda in lambdas:
        fold_squared_errors = []
        fold_summaries = []
        for held_seed in development_seeds:
            train = groups != held_seed
            valid = groups == held_seed
            if not train.any() or not valid.any():
                raise ValueError("each development seed must define one CV group")
            train_x, means, scales = _standardize_fit(x[train])
            valid_x = (x[valid] - means) / scales
            coefficients, _, _ = _ridge_fit(
                train_x, y[train], ridge_lambda
            )
            predictions = coefficients[0] + valid_x @ coefficients[1:]
            errors = (predictions - y[valid]) ** 2
            fold_squared_errors.extend(errors.tolist())
            fold_summaries.append({
                "held_out_seed": int(held_seed),
                "mse": float(errors.mean()),
            })
        cv.append({
            "ridge_lambda": ridge_lambda,
            "mean_squared_error": float(np.mean(fold_squared_errors)),
            "folds": fold_summaries,
        })
    # Prefer stronger regularization on an exact CV tie.
    selected = min(
        cv,
        key=lambda result: (
            result["mean_squared_error"],
            -result["ridge_lambda"],
        ),
    )
    standardized, means, scales = _standardize_fit(x)
    coefficients, inverse, residual_sigma = _ridge_fit(
        standardized, y, selected["ridge_lambda"]
    )
    design = np.column_stack([np.ones(len(y)), standardized])
    predictions = design @ coefficients
    leverage = np.sqrt(np.maximum(
        np.einsum("ij,jk,ik->i", design, inverse, design), 0.0
    ))
    uncertainty = residual_sigma * leverage
    lcb = predictions - beta * uncertainty

    def decision_metrics(scores: Any) -> dict[str, Any]:
        predicted = np.asarray(scores) > threshold
        actual = y > threshold
        tp = int(np.sum(predicted & actual))
        tn = int(np.sum(~predicted & ~actual))
        fp = int(np.sum(predicted & ~actual))
        fn = int(np.sum(~predicted & actual))
        return {
            "true_positive": tp,
            "true_negative": tn,
            "false_positive": fp,
            "false_negative": fn,
            "accuracy": float((tp + tn) / len(y)),
            "refresh_rate": float(predicted.mean()),
        }

    core = {
        "schema": MODEL_SCHEMA,
        "dataset_id": dataset["dataset_id"],
        "training_seeds": list(development_seeds),
        "evaluation_seeds": list(held_out_seeds),
        "feature_names": list(feature_names),
        "feature_means": means.tolist(),
        "feature_scales": scales.tolist(),
        "intercept": float(coefficients[0]),
        "coefficients": coefficients[1:].tolist(),
        "ridge_lambda": float(selected["ridge_lambda"]),
        "candidate_lambdas": list(lambdas),
        "grouped_cv": cv,
        "residual_sigma": residual_sigma,
        "augmented_gram_inverse": inverse.tolist(),
        "beta": float(beta),
        "threshold": float(threshold),
        "decision_rules": {
            "oracle_boundary_ridge": "predicted_net_value > threshold",
            "oracle_boundary_lcb": (
                "predicted_net_value - beta * residual_sigma * "
                "sqrt(x_aug^T A^-1 x_aug) > threshold"
            ),
        },
        "training_metrics": {
            "rmse": float(np.sqrt(np.mean((predictions - y) ** 2))),
            "ridge": decision_metrics(predictions),
            "lcb": decision_metrics(lcb),
        },
    }
    core["model_id"] = canonical_hash(core)
    return core


class FrozenRidgeTrigger:
    """Read-only inference wrapper for a frozen causal trigger artifact."""

    def __init__(self, artifact: Mapping[str, Any]) -> None:
        import numpy as np

        if artifact.get("schema") != MODEL_SCHEMA:
            raise ValueError("unsupported trigger model schema")
        expected_id = artifact.get("model_id")
        core = dict(artifact)
        core.pop("model_id", None)
        if expected_id != canonical_hash(core):
            raise ValueError("trigger model_id does not match its contents")
        self.artifact = dict(artifact)
        self.model_id = str(expected_id)
        self.feature_names = tuple(artifact["feature_names"])
        self.means = np.asarray(artifact["feature_means"], dtype=np.float64)
        self.scales = np.asarray(artifact["feature_scales"], dtype=np.float64)
        self.coefficients = np.asarray(
            artifact["coefficients"], dtype=np.float64
        )
        self.intercept = float(artifact["intercept"])
        self.inverse = np.asarray(
            artifact["augmented_gram_inverse"], dtype=np.float64
        )
        self.residual_sigma = float(artifact["residual_sigma"])
        self.beta = float(artifact["beta"])
        self.threshold = float(artifact["threshold"])
        self.training_seeds = frozenset(
            int(seed) for seed in artifact["training_seeds"]
        )
        self.evaluation_seeds = frozenset(
            int(seed) for seed in artifact["evaluation_seeds"]
        )

    @classmethod
    def from_path(cls, path: Path) -> "FrozenRidgeTrigger":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def validate_evaluation_seed(self, seed: int) -> None:
        if seed in self.training_seeds:
            raise ValueError(f"seed {seed} was used to train the frozen trigger")
        if self.evaluation_seeds and seed not in self.evaluation_seeds:
            raise ValueError(f"seed {seed} is outside the frozen evaluation split")

    def score(self, features: Mapping[str, Any]) -> dict[str, float | bool]:
        import numpy as np

        values = _require_finite_features(features, self.feature_names)
        vector = np.asarray(
            [values[name] for name in self.feature_names], dtype=np.float64
        )
        standardized = (vector - self.means) / self.scales
        mean = self.intercept + float(standardized @ self.coefficients)
        augmented = np.concatenate([[1.0], standardized])
        leverage_squared = float(augmented @ self.inverse @ augmented)
        leverage = math.sqrt(max(leverage_squared, 0.0))
        uncertainty = self.residual_sigma * leverage
        lcb = mean - self.beta * uncertainty
        return {
            "predicted_net_value": mean,
            "uncertainty": uncertainty,
            "lcb_net_value": lcb,
            "ridge_refresh": mean > self.threshold,
            "lcb_refresh": lcb > self.threshold,
        }


__all__ = [
    "DATASET_SCHEMA",
    "DEFAULT_FEATURE_NAMES",
    "FORBIDDEN_MODEL_FEATURES",
    "FrozenRidgeTrigger",
    "MODEL_SCHEMA",
    "PrefixPair",
    "build_prefix_dataset",
    "canonical_hash",
    "file_sha256",
    "fit_frozen_ridge_trigger",
    "masks_for_shift_count",
    "method_to_mask",
    "methods_for_shift_count",
    "prefix_pairs",
]
