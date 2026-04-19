# Pre-Push Secret Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repository-managed `pre-push` secret scan that blocks pushes containing likely secrets or local-machine leakage.

**Architecture:** Keep the Git hook thin and move scan logic into a Python script that can be tested directly. Install the hook through a repo script that sets `core.hooksPath` to `.githooks`.

**Tech Stack:** Git hooks, Python 3 standard library, POSIX shell, `unittest`

---

### Task 1: Add failing tests for secret scan logic

**Files:**
- Create: `tests/test_repo_secret_scan.py`
- Create: `scripts/check_repo_secrets.py`

- [ ] **Step 1: Write the failing test**

```python
def test_scan_blocks_github_pat_in_diff(self):
    findings = secret_scan.scan_patch_text("<patch containing a blocked token>")
    self.assertTrue(findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_repo_secret_scan.RepoSecretScanTests.test_scan_blocks_github_pat_in_diff -v`
Expected: FAIL because `scripts.check_repo_secrets` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def scan_patch_text(text: str) -> list[dict[str, str]]:
    return []
```

- [ ] **Step 4: Run test to verify it passes after later work**

Run: `python3 -m unittest tests.test_repo_secret_scan.RepoSecretScanTests.test_scan_blocks_github_pat_in_diff -v`
Expected: PASS after full scan rules are implemented.

- [ ] **Step 5: Commit**

```bash
git add tests/test_repo_secret_scan.py scripts/check_repo_secrets.py
git commit -m "test: add pre-push secret scan coverage"
```

### Task 2: Add failing tests for installer behavior

**Files:**
- Modify: `tests/test_repo_secret_scan.py`
- Create: `scripts/install_git_hooks.sh`

- [ ] **Step 1: Write the failing test**

```python
def test_install_script_sets_core_hookspath(self):
    result = subprocess.run(
        ["bash", "scripts/install_git_hooks.sh"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    self.assertEqual(result.returncode, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_repo_secret_scan.RepoSecretScanTests.test_install_script_sets_core_hookspath -v`
Expected: FAIL because the install script does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```bash
#!/bin/sh
git config core.hooksPath .githooks
```

- [ ] **Step 4: Run test to verify it passes after later work**

Run: `python3 -m unittest tests.test_repo_secret_scan.RepoSecretScanTests.test_install_script_sets_core_hookspath -v`
Expected: PASS after script is executable and the test repo contains `.githooks/pre-push`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_repo_secret_scan.py scripts/install_git_hooks.sh
git commit -m "test: cover git hook installer"
```

### Task 3: Implement scan engine and repo-managed pre-push hook

**Files:**
- Modify: `scripts/check_repo_secrets.py`
- Create: `.githooks/pre-push`
- Test: `tests/test_repo_secret_scan.py`

- [ ] **Step 1: Implement diff-based scan helpers**

```python
def scan_patch_text(text: str) -> list[dict[str, str]]:
    ...

def collect_push_patch(runner=subprocess.run) -> str:
    ...
```

- [ ] **Step 2: Implement allowlist logic for templates and tests**

```python
def is_allowlisted(path: str, line: str) -> bool:
    ...
```

- [ ] **Step 3: Add CLI exit codes and human-readable output**

```python
def main() -> int:
    findings = ...
    if findings:
        print(...)
        return 1
    return 0
```

- [ ] **Step 4: Add the thin Git hook**

```sh
#!/bin/sh
exec python3 scripts/check_repo_secrets.py --staged-push
```

- [ ] **Step 5: Run targeted tests**

Run: `python3 -m unittest tests.test_repo_secret_scan -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add .githooks/pre-push scripts/check_repo_secrets.py tests/test_repo_secret_scan.py
git commit -m "feat: add pre-push secret scan"
```

### Task 4: Document installation and usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a short setup section**

```md
## Git Hooks

```bash
./scripts/install_git_hooks.sh
```
```

- [ ] **Step 2: Document what the hook blocks and how to fix false positives**

```md
- blocks likely secrets and local absolute paths
- review `git diff --cached` and rerun push
```

- [ ] **Step 3: Run a quick docs check**

Run: `sed -n '1,260p' README.md`
Expected: New section appears with correct commands.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add git hook installation"
```

### Task 5: Full verification

**Files:**
- Verify only

- [ ] **Step 1: Run targeted tests**

Run: `python3 -m unittest tests.test_repo_secret_scan -v`
Expected: PASS

- [ ] **Step 2: Run full regression**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 3: Verify clean status**

Run: `git status -sb`
Expected: no unexpected modified files

- [ ] **Step 4: Push**

Run: `git push origin main`
Expected: PASS, with the new pre-push hook active for future pushes
