"""Capture a reproducibility manifest for the configured AutoDL instance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _run(command: list[str], cwd: Optional[Path] = None) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _package_versions(names: list[str]) -> dict[str, Optional[str]]:
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("/root/autodl-tmp/dai/research_workspace"),
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=Path("/root/autodl-tmp/dai/build/guided-pibt-gate0"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    onlineggo = workspace / "external" / "OnlineGGO"
    module_paths = sorted(
        (onlineggo / "CMAES" / "simulators" / "trafficMAPF_on").glob(
            "period_on_sim*.so"
        )
    )
    if len(module_paths) != 1:
        raise RuntimeError("expected exactly one period_on_sim shared module")
    module_path = module_paths[0]

    git_revision = _run(["git", "rev-parse", "HEAD"], cwd=onlineggo)
    git_status = _run(["git", "status", "--short"], cwd=onlineggo)
    git_diff = subprocess.run(
        ["git", "diff", "--binary"],
        cwd=str(onlineggo),
        check=False,
        capture_output=True,
    )
    disk = shutil.disk_usage("/root/autodl-tmp")

    torch_info: dict[str, Any]
    try:
        import torch

        torch_info = {
            "version": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "compiled_cuda": torch.version.cuda,
            "device_count": torch.cuda.device_count(),
        }
    except Exception as error:  # pragma: no cover - diagnostic path
        torch_info = {"error": repr(error)}

    manifest = {
        "schema": "dai.autodl.environment-manifest/v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count_visible": os.cpu_count(),
        "cgroup_cpu_max": _read_text(Path("/sys/fs/cgroup/cpu.max")),
        "meminfo": _read_text(Path("/proc/meminfo")),
        "autodl_tmp_disk_bytes": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
        },
        "nvidia_smi": _run([
            "nvidia-smi",
            "--query-gpu=name,uuid,driver_version,memory.total",
            "--format=csv,noheader",
        ]),
        "tool_versions": {
            "cmake": _run(["cmake", "--version"]),
            "cxx": _run(["c++", "--version"]),
            "git": _run(["git", "--version"]),
        },
        "python_packages": _package_versions([
            "numpy",
            "matplotlib",
            "imageio",
            "tqdm",
            "gin-config",
            "gymnasium",
            "torch",
            "dask",
            "distributed",
            "pytest",
        ]),
        "torch": torch_info,
        "onlineggo": {
            "revision": git_revision["stdout"],
            "revision_command_returncode": git_revision["returncode"],
            "status_short": git_status["stdout"].splitlines(),
            "diff_sha256": hashlib.sha256(git_diff.stdout).hexdigest(),
            "diff_bytes": len(git_diff.stdout),
        },
        "gate0_build_dir": str(args.build_dir.resolve()),
        "cmake_cache_sha256": (
            _sha256(args.build_dir / "CMakeCache.txt")
            if (args.build_dir / "CMakeCache.txt").is_file()
            else None
        ),
        "period_on_sim": {
            "path": str(module_path),
            "sha256": _sha256(module_path),
            "size_bytes": module_path.stat().st_size,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
