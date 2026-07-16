import unittest

from dai_lmapf.publication_policy import (
    CappedScorePublicationPolicy,
    CausalBlockPublicationPolicy,
    ContextMemoryPublicationPolicy,
    ExactBudgetPublicationPolicy,
    evenly_spaced_indices,
)


class ExactBudgetPublicationPolicyTests(unittest.TestCase):
    def test_exact_even_b25_schedule(self) -> None:
        self.assertEqual(
            evenly_spaced_indices(100, 25), tuple(range(3, 100, 4))
        )
        policy = ExactBudgetPublicationPolicy(
            method="even", total_epochs=100, budget=25, policy_seed=17
        )
        accepted = [
            decision.epoch
            for _ in range(100)
            if (decision := policy.select()).accepted
        ]
        policy.finalize()
        self.assertEqual(accepted, list(range(3, 100, 4)))

    def test_random_schedule_is_exact_and_seeded(self) -> None:
        def run(seed):
            policy = ExactBudgetPublicationPolicy(
                method="random", total_epochs=31, budget=8, policy_seed=seed
            )
            result = [policy.select().accepted for _ in range(31)]
            policy.finalize()
            return result

        self.assertEqual(run(123), run(123))
        self.assertNotEqual(run(123), run(124))
        self.assertEqual(sum(run(123)), 8)

    def test_score_policy_preserves_exact_quota_for_extreme_scores(self) -> None:
        for scores in (
            [0.0] * 37,
            [float(index) for index in range(37)],
            [float(-index) for index in range(37)],
        ):
            policy = ExactBudgetPublicationPolicy(
                method="proposed",
                total_epochs=37,
                budget=9,
                policy_seed=5,
                pacing_slack=2,
            )
            decisions = [policy.select(score=score) for score in scores]
            policy.finalize()
            self.assertEqual(sum(item.accepted for item in decisions), 9)
            self.assertFalse(any(item.reason == "hard_budget_guard" for item in decisions))

    def test_invalid_budget_contract_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ExactBudgetPublicationPolicy(
                method="always", total_epochs=10, budget=9, policy_seed=0
            )
        with self.assertRaises(ValueError):
            ExactBudgetPublicationPolicy(
                method="bootstrap_only", total_epochs=10, budget=1, policy_seed=0
            )


class CausalBlockPublicationPolicyTests(unittest.TestCase):
    def test_no_event_falls_back_to_one_exact_even_token_per_bucket(self) -> None:
        policy = CausalBlockPublicationPolicy(
            total_epochs=29,
            budget=8,
            score_quantile=0.75,
            max_advance=2,
            min_gap=2,
            minimum_history=4,
        )
        decisions = [
            policy.select(score=0.0, route_mature=False) for _ in range(29)
        ]
        policy.finalize()
        accepted = [item.epoch for item in decisions if item.accepted]
        self.assertEqual(accepted, list(evenly_spaced_indices(29, 8)))
        self.assertEqual(policy.bucket_publication_epochs, tuple(accepted))
        self.assertTrue(
            all(
                item.reason == "causal_block_bucket_end"
                for item in decisions
                if item.accepted
            )
        )

    def test_causal_events_move_each_token_by_at_most_two_epochs(self) -> None:
        policy = CausalBlockPublicationPolicy(
            total_epochs=29,
            budget=8,
            score_quantile=0.75,
            max_advance=2,
            min_gap=2,
            minimum_history=1,
        )
        decisions = [
            policy.select(score=float(epoch), route_mature=True)
            for epoch in range(29)
        ]
        policy.finalize()
        accepted = [item for item in decisions if item.accepted]
        self.assertEqual(len(accepted), 8)
        self.assertEqual({item.bucket_index for item in accepted}, set(range(8)))
        self.assertTrue(
            all(0 <= item.bucket_end - item.epoch <= 2 for item in accepted)
        )
        self.assertTrue(
            all(
                right.epoch - left.epoch >= 2
                for left, right in zip(accepted, accepted[1:])
            )
        )
        self.assertTrue(
            any(item.reason == "causal_block_event" for item in accepted)
        )

    def test_causal_block_rejects_non_boolean_maturity(self) -> None:
        policy = CausalBlockPublicationPolicy(total_epochs=4, budget=1)
        with self.assertRaises(TypeError):
            policy.select(score=0.0, route_mature=1)  # type: ignore[arg-type]


class CappedScorePublicationPolicyTests(unittest.TestCase):
    def test_constant_score_can_abstain_without_forced_quota_fill(self) -> None:
        policy = CappedScorePublicationPolicy(
            total_epochs=29, budget=8, minimum_history=4
        )
        decisions = [policy.select(score=0.0) for _ in range(29)]
        policy.finalize()
        self.assertEqual(sum(item.accepted for item in decisions), 0)
        self.assertEqual(policy.spent, 0)

    def test_causal_pulses_respect_cap_gap_and_effect_horizon(self) -> None:
        policy = CappedScorePublicationPolicy(
            total_epochs=12,
            budget=3,
            score_quantile=0.75,
            minimum_history=2,
            min_gap=2,
            minimum_effect_epochs=3,
        )
        scores = [0.0, 0.0, 1.0, 2.0, 0.0, 3.0, 0.0, 4.0, 0.0, 9.0, 10.0, 11.0]
        decisions = [policy.select(score=value) for value in scores]
        policy.finalize()
        accepted = [item.epoch for item in decisions if item.accepted]
        self.assertLessEqual(len(accepted), 3)
        self.assertTrue(
            all(right - left >= 2 for left, right in zip(accepted, accepted[1:]))
        )
        self.assertTrue(all(epoch <= 9 for epoch in accepted))


class ContextMemoryPublicationPolicyTests(unittest.TestCase):
    def test_switch_cap_is_not_spent_when_active_context_already_matches(self) -> None:
        policy = ContextMemoryPublicationPolicy(
            total_epochs=8,
            budget=2,
            minimum_history=2,
            min_gap=1,
            minimum_effect_epochs=1,
        )
        decisions = []
        for epoch, score in enumerate([0.0, 0.0, 1.0, 2.0, 0.0, 3.0, 0.0, 4.0]):
            decisions.append(policy.select(
                score=score,
                action_available=epoch != 2,
                route_mature=True,
            ))
        policy.finalize()
        self.assertFalse(decisions[2].accepted)
        self.assertEqual(decisions[2].reason, "context_memory_active_context_match")
        self.assertLessEqual(policy.spent, 2)

    def test_maturity_and_effect_horizon_are_hard_guards(self) -> None:
        policy = ContextMemoryPublicationPolicy(
            total_epochs=6,
            budget=3,
            minimum_history=1,
            min_gap=0,
            minimum_effect_epochs=2,
        )
        decisions = [
            policy.select(
                score=float(epoch),
                action_available=True,
                route_mature=epoch != 1,
            )
            for epoch in range(6)
        ]
        policy.finalize()
        self.assertFalse(decisions[1].accepted)
        self.assertEqual(decisions[1].reason, "context_memory_maturity_guard")
        self.assertFalse(decisions[-1].accepted)
        self.assertEqual(decisions[-1].reason, "context_memory_effect_horizon")

    def test_mature_long_residence_can_trigger_causal_maintenance(self) -> None:
        policy = ContextMemoryPublicationPolicy(
            total_epochs=6,
            budget=2,
            minimum_history=4,
            min_gap=1,
            minimum_effect_epochs=1,
        )
        decisions = [
            policy.select(
                score=0.0,
                action_available=epoch == 4,
                route_mature=True,
                maintenance_due=epoch == 4,
            )
            for epoch in range(6)
        ]
        policy.finalize()
        self.assertTrue(decisions[4].accepted)
        self.assertEqual(decisions[4].reason, "context_memory_maintenance")
        self.assertEqual(policy.spent, 1)


if __name__ == "__main__":
    unittest.main()
