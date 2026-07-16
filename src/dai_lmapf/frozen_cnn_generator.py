"""Strict loader for the official 3,084-parameter OnlineGGO CNN.

The period-online traffic-MAPF configs use a six-channel observation and the
``CNNUpdateModel`` defined in OnlineGGO.  This module intentionally duplicates
that tiny architecture instead of importing the training stack at runtime.  A
synthetic parity test compares it directly with the pinned official class.

Two hashes are exposed:

``file_sha256``
    SHA-256 of the exact checkpoint bytes.
``params_sha256``
    SHA-256 of the effective little-endian float32 parameter vector.  This is
    invariant to JSON whitespace while still identifying every value actually
    consumed by PyTorch.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


INPUT_CHANNELS = 6
OUTPUT_CHANNELS = 4
KERNEL_SIZE = 3
HIDDEN_CHANNELS = 32
EXPECTED_NUM_PARAMS = 3084

# This is the exact trainable state_dict order used by the pinned official
# ``CNNUpdateModel``. BatchNorm running statistics are buffers, not checkpoint
# parameters, and therefore do not occur in ``optimal_update_model.json``.
PARAMETER_LAYOUT = (
    ("initial:conv:in_chan-32.weight", (32, 6, 3, 3)),
    ("initial:conv:in_chan-32.bias", (32,)),
    ("initial:BatchNorm.weight", (32,)),
    ("initial:BatchNorm.bias", (32,)),
    ("internal1:conv:32-32.weight", (32, 32, 1, 1)),
    ("internal1:conv:32-32.bias", (32,)),
    ("internal1:BatchNorm.weight", (32,)),
    ("internal1:BatchNorm.bias", (32,)),
    ("internal2:conv:32-4.weight", (4, 32, 1, 1)),
    ("internal2:conv:32-4.bias", (4,)),
    ("internal2:BatchNorm.weight", (4,)),
    ("internal2:BatchNorm.bias", (4,)),
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_BATCH_NORM_BUFFER_MARKERS = (
    "BatchNorm.running_mean",
    "BatchNorm.running_var",
    "BatchNorm.num_batches_tracked",
)


class CheckpointValidationError(ValueError):
    """The checkpoint cannot represent the pinned period-online CNN."""


@dataclass(frozen=True)
class FrozenCNNCheckpoint:
    """Validated checkpoint values and reproducibility metadata."""

    path: Path
    params: Any
    file_sha256: str
    params_sha256: str
    model_type: Optional[str]
    num_params: int = EXPECTED_NUM_PARAMS

    def metadata(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "file_sha256": self.file_sha256,
            "params_sha256": self.params_sha256,
            "model_type": self.model_type,
            "num_params": self.num_params,
            "input_channels": INPUT_CHANNELS,
            "output_channels": OUTPUT_CHANNELS,
            "kernel_size": KERNEL_SIZE,
            "hidden_channels": HIDDEN_CHANNELS,
            "batch_norm_mode": "training (matches pinned official evaluator)",
        }


def _parameter_count(layout: Iterable[tuple[str, tuple[int, ...]]]) -> int:
    return sum(math.prod(shape) for _, shape in layout)


if _parameter_count(PARAMETER_LAYOUT) != EXPECTED_NUM_PARAMS:
    raise AssertionError("frozen OnlineGGO parameter layout is inconsistent")


def _normalized_expected_hash(value: Optional[str], label: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CheckpointValidationError(
            f"{label} must be exactly 64 hexadecimal characters"
        )
    return value.lower()


def _reject_json_constant(value: str) -> None:
    raise CheckpointValidationError(
        f"checkpoint contains non-standard non-finite JSON value {value!r}"
    )


def load_frozen_cnn_checkpoint(
    path: str | Path,
    *,
    expected_file_sha256: Optional[str] = None,
    expected_params_sha256: Optional[str] = None,
) -> FrozenCNNCheckpoint:
    """Load and validate an official ``optimal_update_model.json`` file."""

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("loading the OnlineGGO CNN requires NumPy") from exc

    checkpoint_path = Path(path).expanduser().resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(checkpoint_path)
    raw = checkpoint_path.read_bytes()
    file_sha256 = hashlib.sha256(raw).hexdigest()
    expected_file = _normalized_expected_hash(
        expected_file_sha256, "expected_file_sha256"
    )
    if expected_file is not None and file_sha256 != expected_file:
        raise CheckpointValidationError(
            "checkpoint file SHA-256 mismatch: "
            f"expected {expected_file}, received {file_sha256}"
        )

    try:
        payload = json.loads(
            raw.decode("utf-8"), parse_constant=_reject_json_constant
        )
    except UnicodeDecodeError as exc:
        raise CheckpointValidationError("checkpoint is not UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise CheckpointValidationError("checkpoint is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CheckpointValidationError("checkpoint root must be a JSON object")
    values = payload.get("params")
    if not isinstance(values, list):
        raise CheckpointValidationError("checkpoint 'params' must be a JSON list")
    if len(values) != EXPECTED_NUM_PARAMS:
        raise CheckpointValidationError(
            "checkpoint parameter count mismatch: "
            f"expected {EXPECTED_NUM_PARAMS}, received {len(values)}"
        )
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CheckpointValidationError(
                f"checkpoint parameter {index} is not a JSON number"
            )
        try:
            finite = math.isfinite(float(value))
        except (OverflowError, ValueError) as exc:
            raise CheckpointValidationError(
                f"checkpoint parameter {index} cannot be represented"
            ) from exc
        if not finite:
            raise CheckpointValidationError(
                f"checkpoint parameter {index} is not finite"
            )

    with np.errstate(over="ignore", invalid="ignore"):
        params = np.asarray(values, dtype=np.float32)
    if params.shape != (EXPECTED_NUM_PARAMS,):
        raise CheckpointValidationError("checkpoint parameter vector is not flat")
    if not bool(np.isfinite(params).all()):
        raise CheckpointValidationError(
            "checkpoint contains a value outside the finite float32 range"
        )
    params = np.ascontiguousarray(params, dtype=np.float32)
    params.setflags(write=False)
    little_endian_params = params.astype("<f4", copy=False)
    params_sha256 = hashlib.sha256(
        little_endian_params.tobytes(order="C")
    ).hexdigest()
    expected_params = _normalized_expected_hash(
        expected_params_sha256, "expected_params_sha256"
    )
    if expected_params is not None and params_sha256 != expected_params:
        raise CheckpointValidationError(
            "checkpoint parameter SHA-256 mismatch: "
            f"expected {expected_params}, received {params_sha256}"
        )

    model_type = payload.get("type")
    if model_type is not None and not isinstance(model_type, str):
        raise CheckpointValidationError("checkpoint 'type' must be a string")
    return FrozenCNNCheckpoint(
        path=checkpoint_path,
        params=params,
        file_sha256=file_sha256,
        params_sha256=params_sha256,
        model_type=model_type,
    )


def _build_official_architecture() -> Any:
    try:
        import torch.nn as nn
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("running the OnlineGGO CNN requires PyTorch") from exc

    model = nn.Sequential()
    model.add_module(
        "initial:conv:in_chan-32",
        nn.Conv2d(6, 32, 3, 1, 1, bias=True),
    )
    model.add_module("initial:relu", nn.ReLU(inplace=True))
    model.add_module("initial:BatchNorm", nn.BatchNorm2d(32))
    model.add_module(
        "internal1:conv:32-32",
        nn.Conv2d(32, 32, 1, 1, 0, bias=True),
    )
    model.add_module("internal1:relu", nn.ReLU(inplace=True))
    model.add_module("internal1:BatchNorm", nn.BatchNorm2d(32))
    model.add_module(
        "internal2:conv:32-4",
        nn.Conv2d(32, 4, 1, 1, 0, bias=True),
    )
    model.add_module("internal2:relu", nn.ReLU(inplace=True))
    model.add_module("internal2:BatchNorm", nn.BatchNorm2d(4))
    return model


class FrozenCNNGuidanceGenerator:
    """Frozen checkpoint adapter with the official ``[6,H,W] -> [4,H,W]`` API.

    The pinned official evaluator never calls ``model.eval()``. Consequently
    all three BatchNorm layers use per-observation spatial statistics. Keeping
    training mode here is required for numerical equivalence; all learned
    parameters remain frozen and inference runs under ``torch.no_grad()``.
    """

    def __init__(self, checkpoint: FrozenCNNCheckpoint) -> None:
        try:
            import numpy as np
            import torch
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                "running the OnlineGGO CNN requires NumPy and PyTorch"
            ) from exc

        if checkpoint.num_params != EXPECTED_NUM_PARAMS:
            raise CheckpointValidationError("unsupported CNN checkpoint size")
        self.checkpoint = checkpoint
        self.model = _build_official_architecture()
        state_dict = self.model.state_dict()
        trainable_layout = tuple(
            (name, tuple(int(value) for value in tensor.shape))
            for name, tensor in state_dict.items()
            if not any(marker in name for marker in _BATCH_NORM_BUFFER_MARKERS)
        )
        if trainable_layout != PARAMETER_LAYOUT:
            raise RuntimeError(
                "installed PyTorch produced an unexpected CNN state layout"
            )

        offset = 0
        with torch.no_grad():
            for name, shape in PARAMETER_LAYOUT:
                state_value = state_dict[name]
                count = math.prod(shape)
                replacement = torch.tensor(
                    np.asarray(checkpoint.params[offset:offset + count]),
                    dtype=state_value.dtype,
                    requires_grad=True,
                    device=state_value.device,
                ).reshape(shape)
                state_dict[name] = replacement
                offset += count
            if offset != EXPECTED_NUM_PARAMS:
                raise RuntimeError("CNN parameter loader consumed wrong length")
            self.model.load_state_dict(state_dict)
        self.model.train(True)
        self.calls = 0

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        expected_file_sha256: Optional[str] = None,
        expected_params_sha256: Optional[str] = None,
    ) -> "FrozenCNNGuidanceGenerator":
        checkpoint = load_frozen_cnn_checkpoint(
            path,
            expected_file_sha256=expected_file_sha256,
            expected_params_sha256=expected_params_sha256,
        )
        return cls(checkpoint)

    @property
    def metadata(self) -> dict[str, Any]:
        return self.checkpoint.metadata()

    def _forward(self, observation: Any, *, count_call: bool) -> Any:
        import numpy as np
        import torch

        try:
            obs = np.asarray(observation, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise TypeError("CNN observation must be a numeric array") from exc
        if obs.ndim != 3 or obs.shape[0] != INPUT_CHANNELS:
            raise ValueError(
                "CNN observation must have shape [6,H,W], received "
                f"{obs.shape!r}"
            )
        if obs.shape[1] <= 0 or obs.shape[2] <= 0:
            raise ValueError("CNN observation spatial dimensions must be positive")
        if obs.shape[1] * obs.shape[2] <= 1:
            raise ValueError(
                "official training-mode BatchNorm requires at least two spatial "
                "values per channel"
            )
        if not bool(np.isfinite(obs).all()):
            raise ValueError("CNN observation contains a non-finite value")
        tensor = torch.from_numpy(np.ascontiguousarray(obs)).to(
            torch.float32
        ).unsqueeze(0)
        with torch.no_grad():
            output = self.model.forward(tensor).squeeze(0).cpu().numpy()
        expected_shape = (OUTPUT_CHANNELS, obs.shape[1], obs.shape[2])
        if output.shape != expected_shape:
            raise RuntimeError(
                f"CNN returned {output.shape!r}, expected {expected_shape!r}"
            )
        if not bool(np.isfinite(output).all()):
            raise RuntimeError("CNN produced a non-finite guidance value")
        if count_call:
            self.calls += 1
        return output

    def __call__(self, observation: Any) -> Any:
        return self._forward(observation, count_call=True)

    def preview(self, observation: Any) -> Any:
        """Compute a candidate without changing calls or BatchNorm buffers."""

        import torch

        buffers = {
            name: value.detach().clone()
            for name, value in self.model.named_buffers()
        }
        try:
            return self._forward(observation, count_call=False)
        finally:
            with torch.no_grad():
                for name, value in self.model.named_buffers():
                    value.copy_(buffers[name])


__all__ = [
    "CheckpointValidationError",
    "EXPECTED_NUM_PARAMS",
    "FrozenCNNCheckpoint",
    "FrozenCNNGuidanceGenerator",
    "HIDDEN_CHANNELS",
    "INPUT_CHANNELS",
    "KERNEL_SIZE",
    "OUTPUT_CHANNELS",
    "PARAMETER_LAYOUT",
    "load_frozen_cnn_checkpoint",
]
