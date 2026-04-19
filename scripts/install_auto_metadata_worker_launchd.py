#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.auto_metadata_worker_launchd import (  # noqa: E402
    DEFAULT_INTERVAL_SECONDS,
    build_launch_agent_plist,
    install_launch_agent,
    uninstall_launch_agent,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安装或移除自动图片元数据 worker 的 launchd LaunchAgent。")
    parser.add_argument(
        "action",
        nargs="?",
        choices=["install", "uninstall", "print-plist"],
        default="install",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="轮询 pending 队列的秒数。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.action == "print-plist":
        payload = build_launch_agent_plist(project_root=PROJECT_ROOT, interval_seconds=args.interval)
        sys.stdout.write(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8"))
        return 0
    if args.action == "uninstall":
        plist_path = uninstall_launch_agent(project_root=PROJECT_ROOT)
        print(f"已移除 LaunchAgent：{plist_path}")
        return 0

    result = install_launch_agent(project_root=PROJECT_ROOT, interval_seconds=args.interval)
    print(f"已安装 LaunchAgent：{result['plist_path']}")
    print(f"stdout 日志：{result['stdout_log']}")
    print(f"stderr 日志：{result['stderr_log']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
