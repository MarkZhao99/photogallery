#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.short_session_boundary import watch_loop  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="监听短会话边界文件并触发安全模式提醒。")
    parser.add_argument("--interval", type=float, default=1.0, help="轮询间隔秒数。")
    parser.add_argument("--once", action="store_true", help="只检查一次并退出。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return watch_loop(
        project_root=PROJECT_ROOT,
        interval_seconds=args.interval,
        once=args.once,
    )


if __name__ == "__main__":
    raise SystemExit(main())
