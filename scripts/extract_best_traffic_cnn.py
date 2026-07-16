#!/usr/bin/env python3
"""Extract a lightweight, hash-audited CNN checkpoint from a CMA archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


EXPECTED_PARAMS = 3084


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _params_sha256(params: np.ndarray) -> str:
    return hashlib.sha256(params.astype("<f4", copy=False).tobytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--simulator", type=Path)
    parser.add_argument("--total-evals", type=int, required=True)
    args = parser.parse_args()

    archive = args.archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    frame = pd.read_pickle(archive)
    if frame.empty or "objective" not in frame.columns:
        raise ValueError("archive must contain at least one objective row")

    solution_columns = sorted(
        (column for column in frame.columns if column.startswith("solution_")),
        key=lambda column: int(column.split("_", 1)[1]),
    )
    if len(solution_columns) != EXPECTED_PARAMS:
        raise ValueError(
            f"expected {EXPECTED_PARAMS} solution columns, got {len(solution_columns)}"
        )
    row = frame.loc[frame["objective"].astype(float).idxmax()]
    params = row[solution_columns].to_numpy(dtype=np.float32)
    if params.shape != (EXPECTED_PARAMS,) or not np.isfinite(params).all():
        raise ValueError("selected parameter vector is malformed or non-finite")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {"type": "quad", "params": [float(value) for value in params]}
    output.write_text(
        json.dumps(checkpoint, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )

    metadata = {
        "schema": "dai.onlineggo.cma-checkpoint/v1",
        "total_evals": args.total_evals,
        "training_objective": float(row["objective"]),
        "num_params": int(params.size),
        "archive_path": str(archive),
        "archive_sha256": _sha256(archive),
        "checkpoint_path": str(output),
        "checkpoint_sha256": _sha256(output),
        "params_float32_sha256": _params_sha256(params),
    }
    for key, path in (("config", args.config), ("simulator", args.simulator)):
        if path is not None:
            resolved = path.resolve()
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            metadata[f"{key}_path"] = str(resolved)
            metadata[f"{key}_sha256"] = _sha256(resolved)

    metadata_output = (
        args.metadata_output.resolve()
        if args.metadata_output is not None
        else output.with_suffix(output.suffix + ".metadata.json")
    )
    metadata_output.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
