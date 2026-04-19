#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.short_session_boundary import (  # noqa: E402
    default_resume_command,
    emit_boundary,
    latest_handoff_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="写入短会话边界文件。")
    parser.add_argument("--handoff", default="", help="handoff 文件路径。默认取最新 handoff。")
    parser.add_argument("--resume-command", default="", help="续跑指令。默认根据 handoff 自动生成。")
    parser.add_argument("--reason", default="manual_boundary", help="边界原因短标签。")
    parser.add_argument("--created-at", default="", help="可选的 ISO 时间戳，主要用于测试。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handoff_path = Path(args.handoff).expanduser() if args.handoff else latest_handoff_path(PROJECT_ROOT)
    resume_command = str(args.resume_command or "").strip() or default_resume_command(handoff_path)
    payload = emit_boundary(
        project_root=PROJECT_ROOT,
        handoff_path=handoff_path,
        resume_command=resume_command,
        reason=args.reason,
        created_at=str(args.created_at or "").strip() or None,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
