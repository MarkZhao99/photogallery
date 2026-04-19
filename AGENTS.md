# Repository Instructions

## Context Discipline

- Keep requests small. Do not paste large logs, JSON blobs, stack traces, or generated HTML into the conversation when the same data can be read from local files.
- Prefer reading files from disk with shell tools over quoting their contents back into the chat.
- When continuing prior work, read the latest handoff note under `docs/superpowers/handoffs/` before scanning archived session logs.

## Image Handling

- Do not use full-resolution image embedding unless exact pixel-level inspection is necessary.
- Avoid workflows that serialize local images into `data:image/...;base64,...` payloads inside the conversation context.
- If an image must be inspected, keep the result short and do not repeat image payloads or large OCR dumps in later turns.

## Session Handoffs

- After substantial work, save a compact state summary under `docs/superpowers/handoffs/`.
- Handoffs should include: goal, current status, verification command, open risks, and the minimum context needed to resume work.
- Use the handoff file as the primary resume artifact so new sessions do not depend on long chat history.
- For image-heavy review, metadata curation, or other context-expanding tasks, stop after one small batch and continue in a fresh short session using the latest handoff.
- To trigger the local safe-mode notifier, emit a boundary with `python3 scripts/emit_short_session_boundary.py --handoff <abs-handoff-path> --resume-command "<resume text>" --reason <short-label>`.
- The watcher itself is `python3 scripts/watch_short_session_boundary.py`; it only sends a macOS notification, copies the resume text to the clipboard, and updates `.runtime/last-resume-command.txt`.
- To keep that watcher running in the background via macOS `launchd`, use `python3 scripts/install_short_session_boundary_launchd.py`. It installs `~/Library/LaunchAgents/com.mark.vscode1.short-session-boundary-watcher.plist` and writes logs under `.runtime/launchd/`.
