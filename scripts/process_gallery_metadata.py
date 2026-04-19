#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import (  # noqa: E402
    MAX_METADATA_BATCH_SIZE,
    apply_manual_review_batch,
    build_pending_review_batch,
    queue_photos_for_metadata_audit,
)
from storage import resolve_storage_runtime_info  # noqa: E402


WORKFLOW_PROMPT_PATH = PROJECT_ROOT / "scripts" / "prompts" / "gallery_metadata_workflow.md"


def read_workflow_prompt() -> str:
    return WORKFLOW_PROMPT_PATH.read_text(encoding="utf-8")


def print_workflow_header() -> None:
    prompt = read_workflow_prompt()
    runtime = resolve_storage_runtime_info(PROJECT_ROOT)
    print(f"workflow_prompt={WORKFLOW_PROMPT_PATH}")
    print(f"provider={runtime['provider']}")
    print(f"root={runtime['root']}")
    print(f"metadata_path={runtime['metadata_path']}")
    print(f"prompt_guardrail={prompt.splitlines()[3] if len(prompt.splitlines()) > 3 else '不要请求体过大'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="为当前对话模型导出/回写画廊元数据批次。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending_parser = subparsers.add_parser("pending-batch", help="导出下一批待处理图片，交给当前对话模型处理。")
    pending_parser.add_argument("--limit", type=int, default=MAX_METADATA_BATCH_SIZE, help="单批数量，最大 5。")

    audit_parser = subparsers.add_parser("full-audit", help="全库重新入队，并导出第一批待处理图片。")
    audit_parser.add_argument("--country", action="append", default=[], help="只处理指定国家，可重复传入。")
    audit_parser.add_argument("--limit", type=int, default=MAX_METADATA_BATCH_SIZE, help="单批数量，最大 5。")

    apply_parser = subparsers.add_parser("apply-batch", help="回写当前对话模型已经确认过的批处理结果。")
    apply_parser.add_argument("--input", required=True, help="包含回写结果的 JSON 文件路径。")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    print_workflow_header()
    raw_limit = getattr(args, "limit", MAX_METADATA_BATCH_SIZE)
    limit = max(1, min(MAX_METADATA_BATCH_SIZE, int(raw_limit or MAX_METADATA_BATCH_SIZE)))

    if args.command == "pending-batch":
        result = build_pending_review_batch(limit=limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "apply-batch":
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = apply_manual_review_batch(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    queue_result = queue_photos_for_metadata_audit(
        countries=args.country or None,
        force_all=True,
        reason="library_audit",
    )

    print(
        json.dumps(
            {
                "queued": queue_result,
                "next_batch": build_pending_review_batch(limit=limit),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
