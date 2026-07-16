import math
import unittest

from dai_lmapf.online_ggo_adapter import (
    GuidanceCommand,
    GuidanceOperation,
    OnlineGGOAdapter,
    action_digest,
    uniform_action,
    validate_official_action,
)


class _TickingClock:
    def __init__(self, increment_ns: int = 2_000_000) -> None:
        self.value = 0
        self.increment_ns = increment_ns

    def __call__(self) -> int:
        current = self.value
        self.value += self.increment_ns
        return current


class _FakeEnv:
    def __init__(self) -> None:
        self.actions = []
        self.steps = 0

    def reset(self, *, seed=None, options=None):
        self.steps = 0
        return {"seed": seed}, {"options": options}

    def step(self, action):
        self.actions.append(action)
        self.steps += 1
        return {"step": self.steps}, self.steps, self.steps == 3, False, {"ok": True}


class OfficialActionValidationTests(unittest.TestCase):
    def test_uniform_action_has_expected_shape(self) -> None:
        action = uniform_action(2, 3)
        validate_official_action(action, height=2, width=3)
        self.assertEqual(len(action), 4)
        self.assertEqual(action[0][0], [1.0, 1.0, 1.0])
        self.assertEqual(
            action_digest(action, height=2, width=3),
            action_digest(uniform_action(2, 3), height=2, width=3),
        )

    def test_rejects_wrong_shape_and_nonfinite_values(self) -> None:
        with self.assertRaises(ValueError):
            validate_official_action([[[1.0]]], height=1, width=1)
        invalid = uniform_action(1, 1)
        invalid[2][0][0] = math.nan
        with self.assertRaises(ValueError):
            validate_official_action(invalid, height=1, width=1)


class OnlineGGOAdapterTests(unittest.TestCase):
    def test_refresh_generates_once_and_reuse_still_steps(self) -> None:
        env = _FakeEnv()
        generated = []

        def generator(observation):
            generated.append(observation)
            return uniform_action(2, 2, value=7.0)

        adapter = OnlineGGOAdapter(
            env,
            generator,
            height=2,
            width=2,
            clock_ns=_TickingClock(),
        )
        adapter.reset(seed=11)
        refreshed = adapter.advance(refresh=True)
        reused = adapter.advance(refresh=False)

        self.assertEqual(len(generated), 1)
        self.assertEqual(env.steps, 2)
        self.assertEqual(env.actions[0], env.actions[1])
        self.assertIsNot(env.actions[0], env.actions[1])
        self.assertTrue(refreshed.refreshed)
        self.assertFalse(reused.refreshed)
        self.assertAlmostEqual(refreshed.generator_seconds, 0.002)
        self.assertAlmostEqual(refreshed.simulator_seconds, 0.002)
        self.assertEqual(adapter.refresh_count, 1)
        self.assertEqual(adapter.reuse_count, 1)
        self.assertEqual(refreshed.guidance_version, 1)
        self.assertEqual(reused.guidance_version, 1)
        self.assertEqual(refreshed.guidance_digest, reused.guidance_digest)

    def test_bootstrap_is_cached_without_advancing_or_spending_refresh_budget(self) -> None:
        env = _FakeEnv()
        adapter = OnlineGGOAdapter(
            env,
            lambda observation: uniform_action(2, 2, value=5.0),
            height=2,
            width=2,
            clock_ns=_TickingClock(),
        )
        adapter.reset(seed=17)

        seconds = adapter.bootstrap_guidance()
        first_window = adapter.advance(refresh=False)

        self.assertAlmostEqual(seconds, 0.002)
        self.assertEqual(env.steps, 1)
        self.assertEqual(adapter.bootstrap_count, 1)
        self.assertEqual(adapter.refresh_count, 0)
        self.assertEqual(adapter.reuse_count, 1)
        self.assertEqual(first_window.guidance_version, 1)
        self.assertEqual(env.actions[0], uniform_action(2, 2, value=5.0))
        with self.assertRaisesRegex(RuntimeError, "precede"):
            adapter.bootstrap_guidance()

    def test_backend_cannot_advance_after_done(self) -> None:
        env = _FakeEnv()
        adapter = OnlineGGOAdapter(
            env,
            lambda observation: uniform_action(1, 1),
            height=1,
            width=1,
        )
        adapter.reset()
        adapter.advance(refresh=False)
        adapter.advance(refresh=False)
        adapter.advance(refresh=False)
        with self.assertRaises(RuntimeError):
            adapter.advance(refresh=False)

    def test_generated_action_is_validated_before_step(self) -> None:
        env = _FakeEnv()
        adapter = OnlineGGOAdapter(
            env,
            lambda observation: [[[1.0]]],
            height=1,
            width=1,
        )
        adapter.reset()
        with self.assertRaises(ValueError):
            adapter.advance(refresh=True)
        self.assertEqual(env.steps, 0)

    def test_instrumented_env_receives_publication_version_and_raw_digest(self) -> None:
        class MetadataEnv(_FakeEnv):
            def __init__(self) -> None:
                super().__init__()
                self.metadata = []

            def set_dai_guidance_metadata(self, *, version, sha256):
                self.metadata.append((version, sha256))

            def step(self, action):
                observation, reward, terminated, truncated, info = super().step(action)
                version, raw_digest = self.metadata[-1]
                info["dai_trace"] = {
                    "guidance_version": version,
                    "guidance_sha256": raw_digest,
                    "applied_guidance_sha256": "a" * 64,
                }
                return observation, reward, terminated, truncated, info

        env = MetadataEnv()
        generated_action = uniform_action(1, 1, value=3.0)
        adapter = OnlineGGOAdapter(
            env,
            lambda observation: generated_action,
            height=1,
            width=1,
        )
        adapter.reset()
        refreshed = adapter.advance(refresh=True)
        reused = adapter.advance(refresh=False)

        self.assertEqual(env.metadata[0], (1, refreshed.guidance_digest))
        self.assertEqual(env.metadata[1], (1, reused.guidance_digest))
        self.assertEqual(refreshed.applied_guidance_digest, "a" * 64)
        self.assertEqual(reused.applied_guidance_digest, "a" * 64)

    def test_generate_then_reactivate_bootstrap_without_generator_call(self) -> None:
        class MetadataEnv(_FakeEnv):
            def __init__(self) -> None:
                super().__init__()
                self.metadata = []

            def set_dai_guidance_metadata(self, *, version, sha256):
                self.metadata.append((version, sha256))

            def step(self, action):
                observation, reward, terminated, truncated, info = super().step(action)
                version, raw_digest = self.metadata[-1]
                marker = int(action[0][0][0])
                info["dai_trace"] = {
                    "guidance_version": version,
                    "guidance_sha256": raw_digest,
                    "applied_guidance_sha256": f"{marker:064x}",
                }
                return observation, reward, terminated, truncated, info

        env = MetadataEnv()
        calls = []
        generated = iter(
            [
                uniform_action(1, 1, value=1.0),
                uniform_action(1, 1, value=2.0),
            ]
        )

        def generator(observation):
            calls.append(observation)
            return next(generated)

        adapter = OnlineGGOAdapter(env, generator, height=1, width=1)
        adapter.reset(seed=17)
        adapter.bootstrap_guidance()
        bootstrap_generation = adapter.active_generation_id
        first = adapter.advance(refresh=False)
        second = adapter.advance(command=GuidanceCommand.generate())
        calls_before_reactivation = len(calls)
        third = adapter.advance(
            command=GuidanceCommand.reactivate(int(bootstrap_generation))
        )

        self.assertEqual(len(calls), calls_before_reactivation)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [action[0][0][0] for action in env.actions],
            [1.0, 2.0, 1.0],
        )
        self.assertEqual(first.generation_id, bootstrap_generation)
        self.assertNotEqual(second.generation_id, bootstrap_generation)
        self.assertEqual(third.generation_id, bootstrap_generation)
        self.assertEqual(third.requested_operation, GuidanceOperation.REACTIVATE)
        self.assertEqual(third.operation, GuidanceOperation.REACTIVATE)
        self.assertTrue(third.reactivated)
        self.assertFalse(third.refreshed)
        self.assertEqual(adapter.reactivation_count, 1)
        self.assertEqual(adapter.installation_version, 3)
        self.assertEqual(third.installation_version, 3)
        self.assertEqual(
            [record.generation_id for record in adapter.guidance_catalog],
            [1, 2],
        )

    def test_reactivating_active_generation_downgrades_to_hold(self) -> None:
        class LongEnv(_FakeEnv):
            def step(self, action):
                self.actions.append(action)
                self.steps += 1
                return {"step": self.steps}, self.steps, False, False, {"ok": True}

        calls = []

        def generator(observation):
            calls.append(observation)
            return uniform_action(1, 1, value=3.0)

        env = LongEnv()
        adapter = OnlineGGOAdapter(env, generator, height=1, width=1)
        adapter.reset()
        adapter.bootstrap_guidance()
        generation_id = int(adapter.active_generation_id)
        adapter.advance(refresh=False)
        replay = adapter.advance(
            command=GuidanceCommand.reactivate(generation_id)
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(replay.requested_operation, GuidanceOperation.REACTIVATE)
        self.assertEqual(replay.operation, GuidanceOperation.HOLD)
        self.assertFalse(replay.reactivated)
        self.assertEqual(adapter.reactivation_count, 0)
        self.assertEqual(adapter.installation_version, 1)
        self.assertEqual(adapter.reuse_count, 2)

    def test_known_applied_equivalence_downgrades_reactivation_to_hold(self) -> None:
        class EquivalentEnv(_FakeEnv):
            def __init__(self) -> None:
                super().__init__()
                self.metadata = []

            def set_dai_guidance_metadata(self, *, version, sha256):
                self.metadata.append((version, sha256))

            def step(self, action):
                self.actions.append(action)
                self.steps += 1
                version, raw_digest = self.metadata[-1]
                return (
                    {"step": self.steps},
                    self.steps,
                    False,
                    False,
                    {
                        "dai_trace": {
                            "guidance_version": version,
                            "guidance_sha256": raw_digest,
                            "applied_guidance_sha256": "e" * 64,
                        }
                    },
                )

        generated = iter(
            [
                uniform_action(1, 1, value=1.0),
                uniform_action(1, 1, value=9.0),
            ]
        )
        env = EquivalentEnv()
        adapter = OnlineGGOAdapter(
            env,
            lambda observation: next(generated),
            height=1,
            width=1,
        )
        adapter.reset()
        adapter.bootstrap_guidance()
        bootstrap_generation = int(adapter.active_generation_id)
        adapter.advance(refresh=False)
        generated_window = adapter.advance(command=GuidanceCommand.generate())
        active_after_generation = generated_window.generation_id
        replay = adapter.advance(
            command=GuidanceCommand.reactivate(bootstrap_generation)
        )

        self.assertNotEqual(active_after_generation, bootstrap_generation)
        self.assertEqual(replay.operation, GuidanceOperation.HOLD)
        self.assertEqual(replay.generation_id, active_after_generation)
        self.assertEqual(adapter.installation_version, 2)
        self.assertEqual(adapter.reactivation_count, 0)

    def test_rejects_non_rdlu_output_contract(self) -> None:
        with self.assertRaises(ValueError):
            OnlineGGOAdapter(
                _FakeEnv(),
                lambda observation: uniform_action(1, 1),
                height=1,
                width=1,
                direction_order=("R", "U", "L", "D"),
            )

    def test_simulator_exception_faults_adapter_until_reset(self) -> None:
        class FailingEnv(_FakeEnv):
            def step(self, action):
                raise RuntimeError("backend failed")

        adapter = OnlineGGOAdapter(
            FailingEnv(),
            lambda observation: uniform_action(1, 1),
            height=1,
            width=1,
        )
        adapter.reset()
        with self.assertRaises(RuntimeError):
            adapter.advance(refresh=False)
        with self.assertRaisesRegex(RuntimeError, "faulted"):
            adapter.advance(refresh=False)


if __name__ == "__main__":
    unittest.main()
