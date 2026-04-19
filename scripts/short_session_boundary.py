from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


Runner = Callable[..., Any]


def runtime_paths(project_root: Path) -> dict[str, Path]:
    runtime_dir = project_root / ".runtime"
    return {
        "runtime_dir": runtime_dir,
        "boundary": runtime_dir / "short-session-boundary.json",
        "resume_text": runtime_dir / "last-resume-command.txt",
        "state": runtime_dir / "short-session-boundary.state.json",
    }


def ensure_runtime_dir(project_root: Path) -> dict[str, Path]:
    paths = runtime_paths(project_root)
    paths["runtime_dir"].mkdir(parents=True, exist_ok=True)
    return paths


def latest_handoff_path(project_root: Path) -> Path:
    handoff_dir = project_root / "docs" / "superpowers" / "handoffs"
    candidates = [path for path in handoff_dir.glob("*.md") if path.is_file()]
    if not candidates:
        raise FileNotFoundError("未找到可用的 handoff 文件。")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def default_resume_command(handoff_path: Path) -> str:
    return f"继续短会话：读取 {handoff_path.resolve()} ，然后继续上一个任务。"


def build_boundary_payload(
    *,
    project_root: Path,
    handoff_path: Path,
    resume_command: str,
    reason: str,
    created_at: str | None = None,
) -> dict[str, str]:
    paths = ensure_runtime_dir(project_root)
    normalized_handoff = handoff_path.resolve()
    normalized_command = " ".join(str(resume_command or "").split()).strip()
    if not normalized_command:
        raise ValueError("resume_command 不能为空。")
    normalized_reason = " ".join(str(reason or "").split()).strip() or "manual_boundary"
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "created_at": timestamp,
        "reason": normalized_reason,
        "handoff_path": str(normalized_handoff),
        "resume_command": normalized_command,
        "resume_text_path": str(paths["resume_text"].resolve()),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def emit_boundary(
    *,
    project_root: Path,
    handoff_path: Path,
    resume_command: str,
    reason: str = "manual_boundary",
    created_at: str | None = None,
) -> dict[str, str]:
    paths = ensure_runtime_dir(project_root)
    payload = build_boundary_payload(
        project_root=project_root,
        handoff_path=handoff_path,
        resume_command=resume_command,
        reason=reason,
        created_at=created_at,
    )
    write_json(paths["boundary"], payload)
    return payload


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def boundary_fingerprint(payload: dict[str, Any]) -> str:
    stable_payload = {
        "created_at": str(payload.get("created_at") or ""),
        "reason": str(payload.get("reason") or ""),
        "handoff_path": str(payload.get("handoff_path") or ""),
        "resume_command": str(payload.get("resume_command") or ""),
    }
    return json.dumps(stable_payload, ensure_ascii=False, sort_keys=True)


def load_state(project_root: Path) -> dict[str, Any]:
    paths = ensure_runtime_dir(project_root)
    if not paths["state"].exists():
        return {}
    try:
        data = load_json(paths["state"])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(project_root: Path, *, fingerprint: str) -> None:
    paths = ensure_runtime_dir(project_root)
    write_json(paths["state"], {"last_fingerprint": fingerprint})


def build_notification_command(payload: dict[str, Any]) -> list[str]:
    title = "Codex 短会话提醒"
    message = "已到安全边界，续跑指令已复制到剪贴板。"
    if str(payload.get("reason") or "").strip():
        message = f"{message} 原因：{payload['reason']}。"
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    return ["osascript", "-e", script]


def process_boundary_if_new(
    *,
    project_root: Path,
    runner: Runner = subprocess.run,
) -> bool:
    paths = ensure_runtime_dir(project_root)
    if not paths["boundary"].exists():
        return False

    payload = load_json(paths["boundary"])
    fingerprint = boundary_fingerprint(payload)
    state = load_state(project_root)
    if state.get("last_fingerprint") == fingerprint:
        return False

    resume_command = str(payload.get("resume_command") or "").strip()
    if not resume_command:
        raise ValueError("边界文件缺少 resume_command。")

    try:
        runner(build_notification_command(payload), check=False, text=True)
    except Exception:
        pass

    try:
        runner(["pbcopy"], input=resume_command, text=True, check=False)
    except Exception:
        pass

    paths["resume_text"].write_text(resume_command + "\n", encoding="utf-8")
    save_state(project_root, fingerprint=fingerprint)
    return True


def watch_loop(
    *,
    project_root: Path,
    interval_seconds: float = 1.0,
    runner: Runner = subprocess.run,
    once: bool = False,
) -> int:
    while True:
        processed = process_boundary_if_new(project_root=project_root, runner=runner)
        if once:
            return 0 if processed else 1
        time.sleep(max(0.1, float(interval_seconds)))
