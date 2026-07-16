#!/usr/bin/env python3
"""A2 control-plane entry point for the frozen same-call behavior runner.

The delegated v1 module remains byte-identical.  This wrapper verifies those
bytes, replaces only the retired confirmation root registry and the non-causal
same-call split provenance with their frozen A2 values, and then invokes the
unchanged v1 ``main``.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import sys
from typing import Any


V1_PATH = Path(__file__).with_name("run_same_call_confirmation_v1.py")
V1_SHA256 = "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538"
SPLIT = "same_call_confirmation_v1"
A2_DERIVATION_SOURCE_SHA256 = (
    "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"
)
A2_DERIVATION_DOMAIN = "dai-same-call-confirmatory-a2-pid-reuse-correction"
A2_ROOTS = (
    691817,
    376110,
    263001,
    293231,
    296805,
    274330,
    997942,
    319782,
    807287,
    326454,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_frozen_v1() -> Any:
    actual = _sha256_file(V1_PATH)
    if actual != V1_SHA256:
        raise RuntimeError(
            "frozen v1 behavior-runner SHA256 mismatch: "
            f"expected={V1_SHA256} actual={actual} path={V1_PATH}"
        )
    scripts_dir = str(V1_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    module = importlib.import_module("run_same_call_confirmation_v1")
    if Path(module.__file__).resolve() != V1_PATH.resolve():
        raise RuntimeError(
            "frozen v1 behavior-runner import resolved to the wrong file: "
            f"{module.__file__}"
        )
    return module


V1 = _load_frozen_v1()
V1_SPLIT_PROTOCOL_METADATA = V1._split_protocol_metadata


def _split_protocol_metadata_a2(split: str) -> dict[str, Any]:
    """Replace provenance only for the frozen same-call split.

    This metadata is non-causal: it is emitted after an arm has completed and
    is never consumed by simulation, workload, policy, or RNG code.  All other
    split metadata remains delegated to the frozen v1 function.
    """

    metadata = V1_SPLIT_PROTOCOL_METADATA(split)
    if V1._canonical_split(split) != SPLIT:
        return metadata
    metadata.update({
        "preregistered_seeds": list(A2_ROOTS),
        "seed_derivation_source_sha256": A2_DERIVATION_SOURCE_SHA256,
        "seed_derivation_domain": A2_DERIVATION_DOMAIN,
        "seed_derivation": (
            "s_i = 100000 + (int(SHA256(source|domain|i)[0:16], 16) "
            "mod 900000), where source="
            f"{A2_DERIVATION_SOURCE_SHA256} and domain="
            f"{A2_DERIVATION_DOMAIN} for i=0..9"
        ),
    })
    return metadata


def _bind_a2_control_plane() -> None:
    """Bind the A2 roots and their non-causal emitted provenance."""

    split_order = dict(V1.SPLIT_SEED_ORDER)
    split_order[SPLIT] = A2_ROOTS
    split_sets = dict(V1.SPLIT_SEEDS)
    split_sets[SPLIT] = frozenset(A2_ROOTS)
    V1.SAME_CALL_CONFIRMATION_V1_SEEDS = A2_ROOTS
    V1.SPLIT_SEED_ORDER = split_order
    V1.SPLIT_SEEDS = split_sets
    V1._split_protocol_metadata = _split_protocol_metadata_a2


def _bind_a2_root_registry() -> None:
    """Backward-compatible name for the complete A2 control-plane binding."""

    _bind_a2_control_plane()


def main() -> None:
    _bind_a2_control_plane()
    V1.main()


if __name__ == "__main__":
    main()
