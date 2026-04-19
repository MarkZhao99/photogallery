# Country Intro And 413 Handoff

## Current Status

- The `country intro short/long` work appears complete in the application code.
- Full regression verification passed on `2026-04-19` with:

```bash
python3 -m unittest discover -s tests -v
```

- Result: `Ran 64 tests in 16.883s` and `OK`.
- Data curation resumed on `2026-04-19` in small manual batches:
  - Norway batch 1: `5` photos updated
  - Norway batch 2: `5` photos updated
  - Norway batch 3: `3` photos updated
  - Norway country description now has both `short_description` and `long_description`
  - Spain batch 1: `5` photos updated
  - Spain batch 2: `5` photos updated
  - Spain batch 3: `1` photo updated
  - Spain country description now has both `short_description` and `long_description`
  - Italy batch 1: `5` photos updated
  - Italy batch 2: `5` photos updated
  - Italy batch 3: `5` photos updated
  - Italy batch 4: `2` photos updated
  - Italy country description now has both `short_description` and `long_description`
  - France batch 1: `5` photos updated
  - France batch 2: `5` photos updated
  - France country description now has both `short_description` and `long_description`
  - Czech batch 1: `4` photos updated
  - Czech country description now has both `short_description` and `long_description`
  - Austria batch 1: `5` photos updated
  - Austria batch 2: `1` photo updated
  - Austria country description now has both `short_description` and `long_description`

## What Was Completed

- Country descriptions now support backward-compatible `short_description` and `long_description` storage.
- Public and admin galleries render the short intro by default and expose an expandable long guide.
- Incremental country-intro refresh flow preserves existing text and routes larger review work through the manual workflow.
- Square collage gallery and related admin/public rendering tests are already passing.
- New async auto-metadata infrastructure now exists for newly uploaded `pending` photos:
  - upload still returns immediately and queues work
  - batches can be atomically claimed into `processing`
  - stale `processing` batches can be recovered
  - valid short Codex subprocess output can be validated and applied through the existing manual-review write path
  - admin now shows a lightweight auto-metadata queue status panel
  - launchd worker support exists for periodic local background processing

## 413 Root Cause

- The earlier `413 Payload Too Large` issue was not caused by this Flask app's upload endpoints.
- The failure came from the Codex conversation/request layer hitting the proxy limit at `https://crs.us.bestony.com/openai/responses`.
- Evidence in the archived Codex session shows large `view_image` outputs being stored as `data:image/...;base64,...` payloads, after which the proxy returned:

```text
unexpected status 413 Payload Too Large: {"error":"Payload Too Large","message":"Request body size exceeds limit","limit":"60MB"}
```

## Evidence Paths

- Proxy/model config: `~/.codex/config.toml`
- Archived error session:
  `~/.codex/sessions/2026/04/17/rollout-2026-04-17T10-36-37-019d994c-2319-7253-bb38-daec106ba30a.jsonl`
- Follow-up diagnosis sessions:
  `~/.codex/sessions/2026/04/19/rollout-2026-04-19T00-36-16-019da173-36d2-7011-a740-6a58c47a8e22.jsonl`
  `~/.codex/sessions/2026/04/19/rollout-2026-04-19T00-53-27-019da182-f090-7761-bc48-e9196f895042.jsonl`

## Resume Guidance

- Start from this handoff instead of replaying old chat history.
- Avoid embedding full-resolution local images into the conversation unless absolutely necessary.
- Prefer reading files locally and summarizing findings in a few lines.
- If a thread grows large again, open a new thread and carry forward only a short summary plus exact file paths.
- User preference: for future image-heavy work, proactively switch to short fresh sessions after each tiny batch instead of continuing in a long-lived thread.
- Local notifier support now exists:
  - Start watcher in foreground: `python3 scripts/watch_short_session_boundary.py`
  - Install background LaunchAgent: `python3 scripts/install_short_session_boundary_launchd.py`
  - Emit boundary: `python3 scripts/emit_short_session_boundary.py --handoff /abs/path/to/handoff.md --resume-command "继续短会话：读取 ..." --reason image_batch_limit`
  - LaunchAgent plist path: `~/Library/LaunchAgents/com.mark.vscode1.short-session-boundary-watcher.plist`
  - LaunchAgent logs: `.runtime/launchd/`
- Auto metadata worker support now exists:
  - Run one batch manually: `python3 scripts/auto_metadata_worker.py`
  - Install background LaunchAgent: `python3 scripts/install_auto_metadata_worker_launchd.py`
  - LaunchAgent plist path: `~/Library/LaunchAgents/com.mark.vscode1.auto-metadata-worker.plist`
  - Worker logs: `.runtime/launchd/`
- Worker bridge files:
  - `scripts/auto_metadata_worker.py`
  - `scripts/auto_metadata_worker_support.py`
  - `scripts/auto_metadata_worker_launchd.py`
  - `scripts/install_auto_metadata_worker_launchd.py`
  - `scripts/prompts/gallery_auto_metadata_worker.md`
- Manual review payloads used for the Norway run were saved under:
  - `.runtime/manual-review/norway-batch-01.json`
  - `.runtime/manual-review/norway-batch-02.json`
  - `.runtime/manual-review/norway-batch-03.json`
- Additional payloads saved in this run:
  - `.runtime/manual-review/spain-batch-01.json`
  - `.runtime/manual-review/spain-batch-02.json`
  - `.runtime/manual-review/spain-batch-03.json`
  - `.runtime/manual-review/italy-batch-01.json`
  - `.runtime/manual-review/italy-batch-02.json`
  - `.runtime/manual-review/italy-batch-03.json`
  - `.runtime/manual-review/italy-batch-04.json`
  - `.runtime/manual-review/france-batch-01.json`
  - `.runtime/manual-review/france-batch-02.json`
  - `.runtime/manual-review/czech-batch-01.json`
  - `.runtime/manual-review/austria-batch-01.json`
  - `.runtime/manual-review/austria-batch-02.json`

## No Known App-Side Gaps

- With the current test suite green, there is no clear unfinished app task left from the previous implementation cycle.
- If new work resumes on this feature, the next step should come from new requirements rather than backlog recovery.

## Data-Side Status

- The real iCloud gallery data is fully processed for the currently uploaded library snapshot.
- Fresh checks on `2026-04-19` show:
  - `pending_total = 0`
  - `review_total = 0`
  - `done_total = 61`
- Country completion counts:
  - Norway: `13 / 13` done
  - Spain: `11 / 11` done
  - Italy: `17 / 17` done
  - France: `10 / 10` done
  - Czech: `4 / 4` done
  - Austria: `6 / 6` done
- France, Czech, and Austria now all have stored `short_description` and `long_description`.
- The latest export from:

```bash
python3 scripts/process_gallery_metadata.py pending-batch --limit 5
```

returns an empty batch with `photo_count: 0`, so there is no remaining pending manual-review work at this time.

## Verification

- Full regression suite passed on `2026-04-19` with:

```bash
python3 -m unittest discover -s tests -v
```

- Result: `Ran 84 tests in 17.004s` and `OK`.
