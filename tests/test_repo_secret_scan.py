import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts import check_repo_secrets as secret_scan


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RepoSecretScanTests(unittest.TestCase):
    def test_scan_patch_text_blocks_github_pat(self):
        findings = secret_scan.scan_patch_text(
            """diff --git a/demo.txt b/demo.txt
+++ b/demo.txt
@@ -0,0 +1 @@
+TOKEN=github_pat_test_1234567890abcdefghijklmnop
"""
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "github_pat")

    def test_scan_patch_text_blocks_local_absolute_path(self):
        findings = secret_scan.scan_patch_text(
            """diff --git a/README.md b/README.md
+++ b/README.md
@@ -0,0 +1 @@
+Path: /Users/test-user/private/project
"""
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "local_absolute_path")

    def test_scan_patch_text_allows_env_example_placeholders(self):
        findings = secret_scan.scan_patch_text(
            """diff --git a/.env.example b/.env.example
+++ b/.env.example
@@ -0,0 +1,2 @@
+ADMIN_PASSWORD=change-this-admin-password
+WEBDAV_PASSWORD=your-password
"""
        )

        self.assertEqual(findings, [])

    def test_scan_patch_text_allows_test_fixture_placeholders(self):
        findings = secret_scan.scan_patch_text(
            """diff --git a/tests/test_repo_secret_scan.py b/tests/test_repo_secret_scan.py
+++ b/tests/test_repo_secret_scan.py
@@ -0,0 +1,2 @@
++TOKEN=github_pat_test_1234567890abcdefghijklmnop
++Path: /Users/test-user/private/project
"""
        )

        self.assertEqual(findings, [])

    def test_scan_patch_text_allows_rule_definition_lines(self):
        findings = secret_scan.scan_patch_text(
            """diff --git a/scripts/check_repo_secrets.py b/scripts/check_repo_secrets.py
+++ b/scripts/check_repo_secrets.py
@@ -0,0 +1 @@
+        "pattern": re.compile(r"/Users/[^/\\s]+/"),
"""
        )

        self.assertEqual(findings, [])

    def test_scan_patch_text_allows_test_fixture_template_values(self):
        findings = secret_scan.scan_patch_text(
            """diff --git a/tests/test_repo_secret_scan.py b/tests/test_repo_secret_scan.py
+++ b/tests/test_repo_secret_scan.py
@@ -0,0 +1,2 @@
++ADMIN_PASSWORD=change-this-admin-password
++WEBDAV_PASSWORD=your-password
"""
        )

        self.assertEqual(findings, [])

    def test_install_script_sets_core_hookspath(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
            hook_dir = repo_dir / ".githooks"
            hook_dir.mkdir(parents=True, exist_ok=True)
            (hook_dir / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            result = subprocess.run(
                ["bash", str(PROJECT_ROOT / "scripts" / "install_git_hooks.sh")],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            configured = subprocess.run(
                ["git", "config", "--get", "core.hooksPath"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(configured.stdout.strip(), ".githooks")

    def test_main_accepts_pre_push_remote_arguments(self):
        runner = Mock()
        runner.return_value = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")

        exit_code = secret_scan.main(
            ["--pre-push", "origin", "https://github.com/example/repo.git"],
            runner=runner,
            stdin_text="",
        )

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
