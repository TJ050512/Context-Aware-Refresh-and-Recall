"""Environment audit for the pinned official OnlineGGO checkout."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class OnlineGGOPreflight:
    repository: str
    revision: str | None
    platform: str
    machine: str
    python: str
    checks: dict[str, bool]
    ready_to_build: bool
    ready_to_run: bool
    blockers: tuple[str, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _nonempty_directory(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def _git_revision(repository: Path) -> str | None:
    if not repository.exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def inspect_online_ggo(repository: Path) -> OnlineGGOPreflight:
    repository = repository.resolve()
    system = platform.system()
    machine = platform.machine()
    version = platform.python_version()
    compiled = list(
        (repository / "CMAES" / "simulators" / "trafficMAPF_on").glob(
            "period_on_sim*.so"
        )
    )
    checks = {
        "source_present": (repository / "README.md").is_file(),
        "pinned_revision_available": _git_revision(repository) is not None,
        "linux_x86_64": system == "Linux" and machine.lower() in {"x86_64", "amd64"},
        "python_3_9": sys.version_info[:2] == (3, 9),
        "cmake_available": shutil.which("cmake") is not None,
        "make_available": shutil.which("make") is not None,
        "cxx_available": any(shutil.which(name) for name in ("g++", "c++", "clang++")),
        "eigen_submodule": _nonempty_directory(repository / "third_party" / "eigen"),
        "minidnn_submodule": _nonempty_directory(repository / "third_party" / "MiniDNN"),
        "pybind11_submodule": _nonempty_directory(repository / "third_party" / "pybind11"),
        "period_on_module": bool(compiled),
    }
    build_keys = (
        "source_present",
        "pinned_revision_available",
        "linux_x86_64",
        "python_3_9",
        "cmake_available",
        "make_available",
        "cxx_available",
        "eigen_submodule",
        "minidnn_submodule",
        "pybind11_submodule",
    )
    ready_to_build = all(checks[key] for key in build_keys)
    ready_to_run = ready_to_build and checks["period_on_module"]
    blockers = tuple(key for key, passed in checks.items() if not passed)
    notes = (
        "Official reference builds use Ubuntu 20.04, Python 3.9 and x86_64 Singularity.",
        "Boost 1.71 and the pinned Python requirements still need verification inside the container.",
        "Audit action channels on an asymmetric map: Python observations use R,U,L,D while C++ weights use R,D,L,U.",
        "The repository does not ship the trained OnlineGGO CMA-ES checkpoint.",
    )
    return OnlineGGOPreflight(
        repository=str(repository),
        revision=_git_revision(repository),
        platform=system,
        machine=machine,
        python=version,
        checks=checks,
        ready_to_build=ready_to_build,
        ready_to_run=ready_to_run,
        blockers=blockers,
        notes=notes,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository",
        "--repo",
        dest="repository",
        type=Path,
        default=Path("external/OnlineGGO"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = inspect_online_ggo(args.repository)
    rendered = json.dumps(result.as_dict(), indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.strict and not result.ready_to_run:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
