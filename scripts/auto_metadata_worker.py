#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.auto_metadata_worker_support import process_once  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行一次自动 pending 图片元数据处理。")
    parser.add_argument("--model", default="", help="可选：覆盖 Codex model。")
    parser.add_argument("--codex-binary", default="", help="可选：指定 codex 可执行文件路径。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = process_once(
        project_root=PROJECT_ROOT,
        codex_binary=Path(args.codex_binary) if args.codex_binary else None,
        model=args.model,
    )
    print(result)
    return 0 if result["status"] in {"idle", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
