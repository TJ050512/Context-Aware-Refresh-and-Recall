import copy
import math
import unittest

try:
    import numpy  # noqa: F401
except ImportError:
    numpy = None

from dai_lmapf.causal_trigger import (
    DATASET_SCHEMA,
    DEFAULT_FEATURE_NAMES,
    FrozenRidgeTrigger,
    build_prefix_dataset,
    canonical_hash,
    fit_frozen_ridge_trigger,
    methods_for_shift_count,
    prefix_pairs,
)


def _features(prefix: str, shift_index: int) -> dict[str, float]:
    values = {
        "guidance_age_windows": float(shift_index + 1),
        "task_js_since_refresh": 0.1 + 0.01 * len(prefix),
        "task_entropy": 0.7,
        "task_hotspot": 0.04,
        "recent_completed_per_agent": 0.2 + 0.01 * prefix.count("1"),
        "recent_route_builds_per_agent": 0.2,
        "recent_wait_ratio": 0.3,
        "opposite_flow_ratio": 0.1,
        "candidate_l1_relative": 0.05 * (shift_index + 1),
        "candidate_cosine_distance": 0.01 * (prefix.count("1") + 1),
    }
    return {name: values[name] for name in DEFAULT_FEATURE_NAMES}


def _effect(shift_index: int, prefix: str) -> float:
    table = {
        (0, ""): 10.0,
        (1, "0"): 5.0,
        (1, "1"): -3.0,
        (2, "00"): 2.0,
        (2, "01"): 4.0,
        (2, "10"): -6.0,
        (2, "11"): 8.0,
    }
    return table[(shift_index, prefix)]


def _synthetic_artifact(seeds=(20, 21)):
    runs = []
    shift_count = 3
    for seed in seeds:
        for method in methods_for_shift_count(shift_count):
            mask = "000" if method == "never" else method.split("_", 1)[1]
            windows = []
            cumulative = 0.0
            for shift_index in range(shift_count):
                prefix = mask[:shift_index]
                features = _features(prefix, shift_index)
                snapshot = {
                    "schema": "dai.gate0.predecision-features/v1",
                    "decision_timestep": 160 * (shift_index + 1),
                    "shift_index": shift_index,
                    "current_guidance_sha256": canonical_hash(prefix),
                    "candidate_guidance_sha256": canonical_hash(
                        [prefix, shift_index]
                    ),
                    "features": features,
                    "audit_context": {"distribution_js": 0.5},
                }
                feature_hash = canonical_hash(snapshot)
                reward = 100.0
                if mask[shift_index] == "1":
                    reward += _effect(shift_index, prefix)
                cumulative += reward
                windows.append({
                    "window_start_timestep": 160 * (shift_index + 1),
                    "window_end_timestep": 160 * (shift_index + 2),
                    "reward": reward,
                    "observed_shift_index": shift_index,
                    "decision_feature_snapshot": snapshot,
                    "decision_feature_fingerprint": feature_hash,
                    "decision_state_fingerprint": canonical_hash(
                        [seed, shift_index, prefix, feature_hash]
                    ),
                })
            runs.append({
                "method": method,
                "seed": seed,
                "num_task_finished": cumulative,
                "reset_causal_fingerprint": canonical_hash([seed, "reset"]),
                "distribution_update_fingerprint": canonical_hash(
                    [seed, "distribution"]
                ),
                "windows": windows,
            })
    return {
        "schema": "dai.gate0.publication-mvp/v1",
        "agents": 400,
        "warmup_time": 40,
        "horizon": 600,
        "decision_window": 20,
        "shift_interval": 160,
        "map_sha256": "a" * 64,
        "period_on_sim_sha256": "b" * 64,
        "generator": {"mode": "next_route_flow", "flow_bias": 0.1},
        "workload": {"task_random_type": "Gaussian"},
        "runs": runs,
    }


class PrefixProtocolTests(unittest.TestCase):
    def test_complete_three_shift_tree_has_registered_pairs(self) -> None:
        observed = [
            (pair.control_mask, pair.treatment_mask)
            for pair in prefix_pairs(3)
        ]
        self.assertEqual(observed, [
            ("000", "100"),
            ("000", "010"),
            ("100", "110"),
            ("000", "001"),
            ("010", "011"),
            ("100", "101"),
            ("110", "111"),
        ])

    def test_local_labels_recover_prefix_conditional_interactions(self) -> None:
        dataset = build_prefix_dataset(
            [_synthetic_artifact()],
            development_seeds=[20, 21],
            shift_count=3,
            label_horizon_steps=160,
            publication_penalty_tasks=1.0,
        )
        self.assertEqual(dataset["schema"], DATASET_SCHEMA)
        self.assertEqual(len(dataset["rows"]), 14)
        indexed = {
            (row["seed"], row["shift_index"], row["prefix"]): row
            for row in dataset["rows"]
        }
        self.assertEqual(indexed[(20, 1, "0")]["marginal_tasks"], 5.0)
        self.assertEqual(indexed[(20, 1, "1")]["marginal_tasks"], -3.0)
        self.assertEqual(indexed[(20, 2, "10")]["net_value_tasks"], -7.0)

    def test_mismatched_prefix_feature_hash_is_rejected(self) -> None:
        artifact = _synthetic_artifact(seeds=(20,))
        treatment = next(
            run for run in artifact["runs"] if run["method"] == "shiftmask_100"
        )
        treatment["windows"][0]["decision_feature_fingerprint"] = "bad"
        with self.assertRaisesRegex(ValueError, "identical prefix feature"):
            build_prefix_dataset(
                [artifact],
                development_seeds=[20],
                shift_count=3,
                label_horizon_steps=160,
                publication_penalty_tasks=1.0,
            )

    def test_oracle_protocol_fields_cannot_be_model_features(self) -> None:
        with self.assertRaisesRegex(ValueError, "oracle/protocol"):
            build_prefix_dataset(
                [_synthetic_artifact(seeds=(20,))],
                development_seeds=[20],
                shift_count=3,
                label_horizon_steps=160,
                publication_penalty_tasks=1.0,
                feature_names=["task_entropy", "distribution_js"],
            )


@unittest.skipUnless(numpy is not None, "ridge fitting requires NumPy")
class FrozenRidgeTests(unittest.TestCase):
    def test_grouped_cv_model_is_frozen_and_split_safe(self) -> None:
        dataset = build_prefix_dataset(
            [_synthetic_artifact(seeds=(20, 21, 22))],
            development_seeds=[20, 21, 22],
            shift_count=3,
            label_horizon_steps=160,
            publication_penalty_tasks=1.0,
        )
        model = fit_frozen_ridge_trigger(
            dataset,
            candidate_lambdas=[0.1, 1.0, 10.0],
            beta=1.0,
            threshold=0.0,
            evaluation_seeds=[30, 31],
        )
        trigger = FrozenRidgeTrigger(model)
        with self.assertRaisesRegex(ValueError, "used to train"):
            trigger.validate_evaluation_seed(20)
        trigger.validate_evaluation_seed(30)
        score = trigger.score(_features("0", 1))
        self.assertTrue(math.isfinite(score["predicted_net_value"]))
        self.assertTrue(math.isfinite(score["lcb_net_value"]))
        self.assertIsInstance(score["ridge_refresh"], bool)
        self.assertIsInstance(score["lcb_refresh"], bool)


if __name__ == "__main__":
    unittest.main()
