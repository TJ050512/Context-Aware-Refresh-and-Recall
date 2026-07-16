"""Immutable scenario manifests for paired, deterministic experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WorkloadPhase:
    phase_id: str
    start_step: int
    end_step: int
    active_agents: int
    goal_distribution: str
    topology_event: str = "none"

    def validate(self, horizon_steps: int) -> None:
        if not self.phase_id:
            raise ValueError("phase_id must be non-empty")
        if not (0 <= self.start_step < self.end_step <= horizon_steps):
            raise ValueError(
                f"invalid phase interval [{self.start_step}, {self.end_step}) "
                f"for horizon {horizon_steps}"
            )
        if self.active_agents <= 0:
            raise ValueError("active_agents must be positive")
        if not self.goal_distribution:
            raise ValueError("goal_distribution must be non-empty")


@dataclass(frozen=True)
class ScenarioManifest:
    schema_version: str
    map_id: str
    map_family: str
    horizon_steps: int
    layout_seed: int
    start_seed: int
    task_seed: int
    arrival_seed: int
    policy_seed: int
    phases: tuple[WorkloadPhase, ...]

    def validate(self) -> None:
        if self.schema_version != "1":
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if not self.map_id or not self.map_family:
            raise ValueError("map_id and map_family must be non-empty")
        if self.horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive")
        if not self.phases:
            raise ValueError("at least one workload phase is required")

        expected_start = 0
        phase_ids: set[str] = set()
        for phase in self.phases:
            phase.validate(self.horizon_steps)
            if phase.phase_id in phase_ids:
                raise ValueError(f"duplicate phase_id: {phase.phase_id}")
            phase_ids.add(phase.phase_id)
            if phase.start_step != expected_start:
                raise ValueError(
                    f"phases must be contiguous: expected {expected_start}, "
                    f"got {phase.start_step}"
                )
            expected_start = phase.end_step
        if expected_start != self.horizon_steps:
            raise ValueError(
                f"phases end at {expected_start}, horizon is {self.horizon_steps}"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        self.validate()
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @property
    def manifest_id(self) -> str:
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return digest[:16]
