# Short Session Boundary Notifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe local helper that notifies the user and copies a resume command to the clipboard whenever a short-session boundary is emitted.

**Architecture:** Implement a small Python module under `scripts/` that writes a compact boundary JSON file and a polling watcher that consumes that file. Keep the runtime surface inside `.runtime/`, use only macOS-native commands (`osascript`, `pbcopy`) via subprocess, and cover behavior with `unittest` using mocks instead of real system notifications.

**Tech Stack:** Python 3.9, argparse, json, pathlib, subprocess, unittest

---

## File Structure

**Create**
- `scripts/short_session_boundary.py`
  - Shared helpers for runtime paths, payload creation, boundary emission, and watcher-side processing
- `scripts/emit_short_session_boundary.py`
  - CLI wrapper that writes `.runtime/short-session-boundary.json`
- `scripts/watch_short_session_boundary.py`
  - CLI watcher that polls the boundary file and triggers notification, clipboard copy, and text write-out
- `tests/test_short_session_boundary.py`
  - Regression tests for emit/write behavior, absolute paths, duplicate suppression, and fallback behavior

---

### Task 1: Lock Down Emit Behavior With Failing Tests

**Files:**
- Create: `tests/test_short_session_boundary.py`
- Test: `tests/test_short_session_boundary.py`

- [ ] **Step 1: Write failing emit tests**
- [ ] **Step 2: Run `python3 -m unittest tests.test_short_session_boundary -v` and confirm failure**
- [ ] **Step 3: Implement shared path and emit helpers**
- [ ] **Step 4: Re-run `python3 -m unittest tests.test_short_session_boundary -v` and confirm emit tests pass**

### Task 2: Lock Down Watcher Behavior With Failing Tests

**Files:**
- Modify: `tests/test_short_session_boundary.py`
- Modify: `scripts/short_session_boundary.py`
- Create: `scripts/watch_short_session_boundary.py`

- [ ] **Step 1: Add failing tests for watcher notification, clipboard copy, text write-out, and duplicate suppression**
- [ ] **Step 2: Run `python3 -m unittest tests.test_short_session_boundary -v` and confirm failure**
- [ ] **Step 3: Implement watcher-side processing and CLI polling loop**
- [ ] **Step 4: Re-run `python3 -m unittest tests.test_short_session_boundary -v` and confirm watcher tests pass**

### Task 3: Final Verification And Usage Surface

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/superpowers/handoffs/2026-04-19-country-intro-and-413.md`

- [ ] **Step 1: Update repo instructions to reference the new notifier commands**
- [ ] **Step 2: Run `python3 -m unittest tests.test_short_session_boundary tests.test_gallery_metadata_workflow tests.test_local_public_share -v`**
- [ ] **Step 3: Summarize exact startup and manual trigger commands in the final response**

---

## Self-Review

- Emits only small JSON/text files under `.runtime/`
- Does not attempt to send a message into the chat UI
- Uses explicit boundary emission rather than parsing Codex internal logs
- Safe-mode behavior remains: notify + clipboard + text file only
