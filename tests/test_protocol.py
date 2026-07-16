import unittest

from dai_lmapf.protocol import ScenarioManifest, WorkloadPhase


def make_manifest() -> ScenarioManifest:
    return ScenarioManifest(
        schema_version="1",
        map_id="unit-map",
        map_family="unit",
        horizon_steps=40,
        layout_seed=1,
        start_seed=2,
        task_seed=3,
        arrival_seed=4,
        policy_seed=5,
        phases=(
            WorkloadPhase("a", 0, 20, 8, "uniform"),
            WorkloadPhase("b", 20, 40, 12, "top_hotspot"),
        ),
    )


class ScenarioManifestTests(unittest.TestCase):
    def test_manifest_id_is_deterministic(self) -> None:
        first = make_manifest()
        second = make_manifest()
        self.assertEqual(first.manifest_id, second.manifest_id)

    def test_rejects_phase_gap(self) -> None:
        manifest = make_manifest()
        invalid = ScenarioManifest(
            schema_version=manifest.schema_version,
            map_id=manifest.map_id,
            map_family=manifest.map_family,
            horizon_steps=manifest.horizon_steps,
            layout_seed=manifest.layout_seed,
            start_seed=manifest.start_seed,
            task_seed=manifest.task_seed,
            arrival_seed=manifest.arrival_seed,
            policy_seed=manifest.policy_seed,
            phases=(
                WorkloadPhase("a", 0, 10, 8, "uniform"),
                WorkloadPhase("b", 20, 40, 12, "top_hotspot"),
            ),
        )
        with self.assertRaisesRegex(ValueError, "contiguous"):
            invalid.validate()


if __name__ == "__main__":
    unittest.main()
