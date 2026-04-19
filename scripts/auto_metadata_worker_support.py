from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


Runner = Callable[..., Any]

DEFAULT_CODEX_BINARY = "codex"
DEFAULT_MODEL = ""


def prompt_template_path(project_root: Path) -> Path:
    return project_root / "scripts" / "prompts" / "gallery_auto_metadata_worker.md"


def load_prompt_template(project_root: Path) -> str:
    path = prompt_template_path(project_root)
    return path.read_text(encoding="utf-8")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def build_codex_exec_command(
    *,
    project_root: Path,
    output_path: Path,
    image_paths: list[Path],
    codex_binary: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> list[str]:
    binary = str((codex_binary or Path(shutil.which(DEFAULT_CODEX_BINARY) or DEFAULT_CODEX_BINARY)))
    command = [
        binary,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(project_root.resolve()),
        "--output-last-message",
        str(output_path.resolve()),
    ]
    if model:
        command.extend(["--model", model])
    for image_path in image_paths:
        command.extend(["--image", str(image_path.resolve())])
    return command


def build_prompt(batch: dict[str, Any], *, template: str) -> str:
    return f"{template.strip()}\n\n<batch>\n{json.dumps(batch, ensure_ascii=False, indent=2)}\n</batch>\n"


def run_codex_batch(
    *,
    project_root: Path,
    batch: dict[str, Any],
    runner: Runner = subprocess.run,
    codex_binary: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    template = load_prompt_template(project_root)
    image_paths = [Path(str(photo.get("absolute_path") or "")) for photo in batch.get("photos", []) if str(photo.get("absolute_path") or "").strip()]
    prompt = build_prompt(batch, template=template)
    runtime_dir = project_root / ".runtime" / "auto-metadata"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix="codex-auto-metadata-",
        suffix=".json",
        dir=runtime_dir,
        delete=False,
    ) as handle:
        output_path = Path(handle.name)

    command = build_codex_exec_command(
        project_root=project_root,
        output_path=output_path,
        image_paths=image_paths,
        codex_binary=codex_binary,
        model=model,
    )
    runner(
        command,
        input=prompt,
        text=True,
        check=True,
        cwd=str(project_root.resolve()),
    )
    return json.loads(output_path.read_text(encoding="utf-8"))


def load_app_module(project_root: Path):
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    import app  # noqa: WPS433

    return app


def process_once(
    *,
    project_root: Path,
    app_module: Any | None = None,
    runner: Runner = subprocess.run,
    codex_binary: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    app_module = app_module or load_app_module(project_root)
    app_module.recover_stale_processing_batches(
        timeout_seconds=app_module.auto_metadata_processing_timeout_seconds()
    )
    batch = app_module.claim_pending_review_batch(
        limit=app_module.MAX_METADATA_BATCH_SIZE,
        owner=worker_id(),
    )
    if not batch.get("photos"):
        return {"status": "idle", "country": "", "updated_count": 0}

    try:
        payload = run_codex_batch(
            project_root=project_root,
            batch=batch,
            runner=runner,
            codex_binary=codex_binary,
            model=model,
        )
        result = app_module.complete_processing_batch(batch["batch_id"], payload)
        return {
            "status": "completed",
            "country": batch.get("country", ""),
            "updated_count": int(result.get("updated_count", 0)),
            "batch_id": batch.get("batch_id", ""),
        }
    except Exception as exc:  # pragma: no cover - exercised through tests with fake runner
        app_module.release_processing_batch(
            batch.get("batch_id", ""),
            error=str(exc),
            retryable=True,
        )
        return {
            "status": "failed",
            "country": batch.get("country", ""),
            "updated_count": 0,
            "batch_id": batch.get("batch_id", ""),
            "error": str(exc),
        }
