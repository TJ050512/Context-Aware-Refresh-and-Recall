import tempfile
import unittest
from pathlib import Path

from dai_lmapf.absolute_workload import (
    absolute_task_tape_fnv1a64,
    absolute_task_tape_sha256,
    build_absolute_task_tape_manifest,
    generate_phase_shifted_kiva_tape,
    normalize_absolute_task_tape,
    read_kiva_map,
)


class AbsoluteWorkloadTests(unittest.TestCase):
    def test_fingerprints_are_stable_and_release_sensitive(self) -> None:
        starts = [4, 5]
        tape = [[[1, 0], [2, 3]], [[3, 0]]]
        self.assertEqual(
            absolute_task_tape_sha256(starts, tape),
            "50efc6040ee8ecfcc7e09975877574845ec80301b8901685e8e2648bf3004054",
        )
        self.assertEqual(absolute_task_tape_fnv1a64(starts, tape),
                         "fde122a89c5810d5")
        changed = [[[1, 0], [2, 4]], [[3, 0]]]
        self.assertNotEqual(
            absolute_task_tape_sha256(starts, tape),
            absolute_task_tape_sha256(starts, changed),
        )
        manifest = build_absolute_task_tape_manifest(starts, tape)
        self.assertEqual(manifest["manifest_sha256"],
                         absolute_task_tape_sha256(starts, tape))

    def test_normalizer_rejects_ambiguous_or_future_records(self) -> None:
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            normalize_absolute_task_tape(
                [[[1, 3], [2, 2]]],
                start_locations=[0],
                map_size=4,
                horizon_steps=5,
            )
        with self.assertRaisesRegex(TypeError, "must be int"):
            normalize_absolute_task_tape(
                [[[True, 0]]],
                start_locations=[0],
                map_size=4,
                horizon_steps=5,
            )
        with self.assertRaisesRegex(ValueError, "outside"):
            normalize_absolute_task_tape(
                [[[1, 5]]],
                start_locations=[0],
                map_size=4,
                horizon_steps=5,
            )

    def test_phase_generator_is_stateless_and_kiva_alternating(self) -> None:
        map_text = "\n".join([
            "type octile",
            "height 3",
            "width 5",
            "map",
            ".W.W.",
            "EE.EE",
            ".....",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.map"
            path.write_text(map_text, encoding="utf-8")
            kiva_map = read_kiva_map(path)
            kwargs = dict(
                kiva_map=kiva_map,
                start_locations=[10, 14],
                release_timesteps=[0, 0, 3, 6],
                phase_starts=[0, 3],
                endpoint_phase_centers=[5, 9],
                task_seed=123,
                sigma=0.5,
            )
            first = generate_phase_shifted_kiva_tape(**kwargs)
            second = generate_phase_shifted_kiva_tape(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual([[entry[1] for entry in sequence] for sequence in first],
                         [[0, 0, 3, 6], [0, 0, 3, 6]])
        for start, sequence in zip([10, 14], first):
            previous = start
            for goal, _ in sequence:
                if kiva_map.grid_types[previous] in {".", "E"}:
                    self.assertIn(goal, kiva_map.home_locations)
                else:
                    self.assertIn(goal, kiva_map.endpoint_locations)
                previous = goal


if __name__ == "__main__":
    unittest.main()
