#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ALL_ZERO_SHA = "0" * 40
RULES = (
    {
        "rule": "github_pat",
        "pattern": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
        "allowlistable": False,
    },
    {
        "rule": "github_classic_pat",
        "pattern": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
        "allowlistable": False,
    },
    {
        "rule": "openai_key",
        "pattern": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "allowlistable": False,
    },
    {
        "rule": "private_key",
        "pattern": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "allowlistable": False,
    },
    {
        "rule": "sensitive_assignment",
        "pattern": re.compile(r"\b[A-Z0-9_]*(API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*="),
        "allowlistable": True,
    },
    {
        "rule": "authorization_bearer",
        "pattern": re.compile(r"Authorization:\s*Bearer\b", re.IGNORECASE),
        "allowlistable": True,
    },
    {
        "rule": "local_absolute_path",
        "pattern": re.compile(r"/Users/[^/\s]+/"),
        "allowlistable": True,
    },
)
TEMPLATE_MARKERS = (
    "change-this-",
    "your-password",
    "your-username",
    "your-webdav-host",
    "your-api-key",
    "your gemini api key",
    "replace_with_",
    "example.com",
)
TEST_FIXTURE_MARKERS = (
    "github_pat_test_",
    "ghp_test_",
    "sk-test-",
    "test-user",
    "test-",
    "dummy",
    "fake",
    "mock",
)


def run_git(args: list[str], *, runner=subprocess.run, cwd: Path | None = None) -> str:
    result = runner(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def is_allowlisted(path: str, line: str, rule: str) -> bool:
    normalized_path = path.strip()
    normalized_line = line.strip()
    lowered_line = normalized_line.lower()

    if normalized_path in {".env.example", "README.md"} and any(marker in lowered_line for marker in TEMPLATE_MARKERS):
        return True
    if normalized_path.endswith(".example.yml") and any(marker in lowered_line for marker in TEMPLATE_MARKERS):
        return True
    if normalized_path.startswith("tests/") and "test" in lowered_line:
        return True
    if normalized_path.startswith("tests/") and any(marker in lowered_line for marker in TEMPLATE_MARKERS):
        return True
    if normalized_path.startswith("tests/") and any(marker in lowered_line for marker in TEST_FIXTURE_MARKERS):
        return True
    if normalized_path.startswith("tests/") and "re.compile(" in normalized_line:
        return True
    if normalized_path == "scripts/check_repo_secrets.py" and "re.compile(" in normalized_line:
        return True
    if rule == "local_absolute_path" and "/path/to/" in normalized_line:
        return True
    return False


def iter_added_lines(patch_text: str) -> Iterable[dict[str, object]]:
    current_path = ""
    new_line_number = 0
    in_hunk = False

    for raw_line in patch_text.splitlines():
        if raw_line.startswith("diff --git "):
            in_hunk = False
            match = re.match(r"diff --git a/(.+) b/(.+)", raw_line)
            if match:
                current_path = match.group(2)
            continue

        if raw_line.startswith("@@"):
            in_hunk = True
            match = re.search(r"\+(\d+)", raw_line)
            new_line_number = int(match.group(1)) if match else 0
            continue

        if not in_hunk:
            continue

        if raw_line.startswith("+++"):
            continue

        if raw_line.startswith("+"):
            yield {
                "path": current_path,
                "line_number": new_line_number,
                "line": raw_line[1:],
            }
            new_line_number += 1
            continue

        if raw_line.startswith("-"):
            continue

        if raw_line.startswith(" "):
            new_line_number += 1


def scan_patch_text(patch_text: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for entry in iter_added_lines(patch_text):
        path = str(entry["path"])
        line = str(entry["line"])
        for rule in RULES:
            if not rule["pattern"].search(line):
                continue
            if is_allowlisted(path, line, str(rule["rule"])):
                continue
            findings.append(
                {
                    "rule": str(rule["rule"]),
                    "path": path,
                    "line_number": int(entry["line_number"]),
                    "line": line,
                }
            )
            break
    return findings


def commits_for_pre_push(stdin_text: str, *, runner=subprocess.run, cwd: Path | None = None) -> list[str]:
    commits: list[str] = []
    seen: set[str] = set()

    for raw_line in stdin_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ALL_ZERO_SHA:
            continue
        if remote_sha == ALL_ZERO_SHA:
            rev_list = run_git(["rev-list", "--reverse", local_sha, "--not", "--remotes"], runner=runner, cwd=cwd)
            resolved = [item.strip() for item in rev_list.splitlines() if item.strip()]
            if not resolved:
                resolved = [local_sha]
        else:
            rev_list = run_git(["rev-list", "--reverse", f"{remote_sha}..{local_sha}"], runner=runner, cwd=cwd)
            resolved = [item.strip() for item in rev_list.splitlines() if item.strip()]
        for commit in resolved:
            if commit in seen:
                continue
            seen.add(commit)
            commits.append(commit)
    return commits


def collect_patch_for_commits(commits: list[str], *, runner=subprocess.run, cwd: Path | None = None) -> str:
    chunks: list[str] = []
    for commit in commits:
        chunks.append(run_git(["show", "--format=", "--unified=0", commit], runner=runner, cwd=cwd))
    return "\n".join(chunk for chunk in chunks if chunk)


def collect_patch_text(
    *,
    pre_push: bool = False,
    stdin_text: str = "",
    rev_range: str = "",
    runner=subprocess.run,
    cwd: Path | None = None,
) -> str:
    if rev_range:
        commits = run_git(["rev-list", "--reverse", rev_range], runner=runner, cwd=cwd)
        commit_list = [item.strip() for item in commits.splitlines() if item.strip()]
        return collect_patch_for_commits(commit_list, runner=runner, cwd=cwd)
    if pre_push:
        commit_list = commits_for_pre_push(stdin_text, runner=runner, cwd=cwd)
        return collect_patch_for_commits(commit_list, runner=runner, cwd=cwd)
    return run_git(["diff", "--cached", "--unified=0"], runner=runner, cwd=cwd)


def print_findings(findings: list[dict[str, object]], *, stream=sys.stderr) -> None:
    stream.write("Push blocked: likely secret or local-machine data found in outgoing diff.\n")
    for finding in findings:
        stream.write(
            f"- {finding['rule']}: {finding['path']}:{finding['line_number']} -> {finding['line']}\n"
        )
    stream.write(
        "Fix the lines above, or move real credentials into local .env / platform secrets, then retry.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan outgoing Git changes for likely secrets.")
    parser.add_argument("--pre-push", action="store_true", help="Read ref updates from stdin like a Git pre-push hook.")
    parser.add_argument("--rev-range", default="", help="Optional explicit git rev-list range to scan.")
    parser.add_argument("remote_name", nargs="?", default="", help=argparse.SUPPRESS)
    parser.add_argument("remote_url", nargs="?", default="", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None, *, runner=subprocess.run, stdin_text: str | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    patch_text = collect_patch_text(
        pre_push=args.pre_push,
        stdin_text=sys.stdin.read() if stdin_text is None else stdin_text,
        rev_range=args.rev_range,
        runner=runner,
        cwd=project_root,
    )
    findings = scan_patch_text(patch_text)
    if findings:
        print_findings(findings)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
