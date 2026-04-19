from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


Runner = Callable[..., Any]

DEFAULT_LABEL = "com.mark.vscode1.auto-metadata-worker"
DEFAULT_INTERVAL_SECONDS = 15


def normalize_interval(interval_seconds: float) -> int:
    try:
        value = int(float(interval_seconds))
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(1, value)


def launch_agent_paths(
    project_root: Path,
    *,
    home_dir: Path | None = None,
    label: str = DEFAULT_LABEL,
) -> dict[str, Path]:
    normalized_root = project_root.resolve()
    normalized_home = (home_dir or Path.home()).resolve()
    runtime_dir = normalized_root / ".runtime" / "launchd"
    launch_agents_dir = normalized_home / "Library" / "LaunchAgents"
    return {
        "project_root": normalized_root,
        "worker_script": normalized_root / "scripts" / "auto_metadata_worker.py",
        "runtime_dir": runtime_dir,
        "stdout_log": runtime_dir / f"{label}.stdout.log",
        "stderr_log": runtime_dir / f"{label}.stderr.log",
        "launch_agents_dir": launch_agents_dir,
        "plist": launch_agents_dir / f"{label}.plist",
    }


def ensure_launch_agent_dirs(
    project_root: Path,
    *,
    home_dir: Path | None = None,
    label: str = DEFAULT_LABEL,
) -> dict[str, Path]:
    paths = launch_agent_paths(project_root, home_dir=home_dir, label=label)
    paths["runtime_dir"].mkdir(parents=True, exist_ok=True)
    paths["launch_agents_dir"].mkdir(parents=True, exist_ok=True)
    return paths


def build_launch_agent_plist(
    *,
    project_root: Path,
    home_dir: Path | None = None,
    python_binary: Path | None = None,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    label: str = DEFAULT_LABEL,
) -> dict[str, Any]:
    paths = ensure_launch_agent_dirs(project_root, home_dir=home_dir, label=label)
    python_path = (python_binary or Path(sys.executable)).resolve()
    return {
        "Label": label,
        "ProgramArguments": [
            str(python_path),
            str(paths["worker_script"].resolve()),
        ],
        "RunAtLoad": True,
        "StartInterval": normalize_interval(interval_seconds),
        "WorkingDirectory": str(paths["project_root"]),
        "ProcessType": "Background",
        "StandardOutPath": str(paths["stdout_log"]),
        "StandardErrorPath": str(paths["stderr_log"]),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }


def write_launch_agent_plist(
    *,
    project_root: Path,
    home_dir: Path | None = None,
    python_binary: Path | None = None,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    label: str = DEFAULT_LABEL,
) -> Path:
    paths = ensure_launch_agent_dirs(project_root, home_dir=home_dir, label=label)
    payload = build_launch_agent_plist(
        project_root=project_root,
        home_dir=home_dir,
        python_binary=python_binary,
        interval_seconds=interval_seconds,
        label=label,
    )
    with paths["plist"].open("wb") as handle:
        plistlib.dump(payload, handle, fmt=plistlib.FMT_XML, sort_keys=False)
    return paths["plist"]


def install_launch_agent(
    *,
    project_root: Path,
    home_dir: Path | None = None,
    python_binary: Path | None = None,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    label: str = DEFAULT_LABEL,
    uid: int | None = None,
    launchctl_binary: Path = Path("/bin/launchctl"),
    runner: Runner = subprocess.run,
) -> dict[str, Path | str]:
    paths = ensure_launch_agent_dirs(project_root, home_dir=home_dir, label=label)
    plist_path = write_launch_agent_plist(
        project_root=project_root,
        home_dir=home_dir,
        python_binary=python_binary,
        interval_seconds=interval_seconds,
        label=label,
    )
    resolved_uid = int(uid if uid is not None else os.getuid())
    domain = f"gui/{resolved_uid}"
    launchctl_path = str(launchctl_binary)
    runner([launchctl_path, "bootout", domain, str(plist_path)], check=False, capture_output=True, text=True)
    runner([launchctl_path, "bootstrap", domain, str(plist_path)], check=True, capture_output=True, text=True)
    runner(
        [launchctl_path, "kickstart", "-k", f"{domain}/{label}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "label": label,
        "plist_path": plist_path,
        "stdout_log": paths["stdout_log"],
        "stderr_log": paths["stderr_log"],
    }


def uninstall_launch_agent(
    *,
    project_root: Path,
    home_dir: Path | None = None,
    label: str = DEFAULT_LABEL,
    uid: int | None = None,
    launchctl_binary: Path = Path("/bin/launchctl"),
    runner: Runner = subprocess.run,
) -> Path:
    paths = ensure_launch_agent_dirs(project_root, home_dir=home_dir, label=label)
    resolved_uid = int(uid if uid is not None else os.getuid())
    runner(
        [str(launchctl_binary), "bootout", f"gui/{resolved_uid}", str(paths["plist"])],
        check=False,
        capture_output=True,
        text=True,
    )
    if paths["plist"].exists():
        paths["plist"].unlink()
    return paths["plist"]
