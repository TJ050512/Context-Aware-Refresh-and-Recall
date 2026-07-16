"""Validate a period-online checkpoint and compare it to pinned OnlineGGO."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _float32_sha256(value: Any) -> str:
    import numpy as np

    array = np.ascontiguousarray(value, dtype=np.float32).astype(
        "<f4", copy=False
    )
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    workspace_default = Path(__file__).resolve().parents[1]
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--expected-file-sha256", default=None)
    parser.add_argument("--expected-params-sha256", default=None)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    cmaes = workspace / "external" / "OnlineGGO" / "CMAES"
    sys.path.insert(0, str(workspace / "src"))
    sys.path.insert(0, str(cmaes))

    import numpy as np

    from dai_lmapf.frozen_cnn_generator import (
        FrozenCNNGuidanceGenerator,
    )
    from env_search.traffic_mapf.update_model.update_model import (
        CNNUpdateModel,
    )

    generator = FrozenCNNGuidanceGenerator.from_path(
        args.checkpoint.resolve(),
        expected_file_sha256=args.expected_file_sha256,
        expected_params_sha256=args.expected_params_sha256,
    )
    values = np.linspace(-1.25, 2.0, 6 * 5 * 7, dtype=np.float64)
    observation = (values + 0.1 * np.sin(values * 3.0)).reshape(6, 5, 7)
    official = CNNUpdateModel(
        np.asarray(generator.checkpoint.params, dtype=np.float32),
        nc=6,
        kernel_size=3,
        n_hid_chan=32,
    )
    official_output = official.get_update_values_from_obs(observation)
    frozen_output = generator(observation)
    exact_equal = bool(np.array_equal(frozen_output, official_output))
    report = {
        "schema": "dai.onlineggo.frozen-cnn-verification/v1",
        "status": "pass" if exact_equal else "fail",
        "checkpoint": generator.metadata,
        "synthetic_observation_shape": list(observation.shape),
        "synthetic_observation_sha256": _float32_sha256(observation),
        "output_shape": list(frozen_output.shape),
        "output_sha256": _float32_sha256(frozen_output),
        "official_output_sha256": _float32_sha256(official_output),
        "official_exact_equal": exact_equal,
        "official_max_abs_error": float(
            np.max(np.abs(frozen_output - official_output))
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not exact_equal:
        raise RuntimeError("frozen CNN output differs from pinned OnlineGGO")


if __name__ == "__main__":
    main()
