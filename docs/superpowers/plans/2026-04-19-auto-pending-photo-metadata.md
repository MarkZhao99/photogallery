# Auto Pending Photo Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically process newly uploaded `pending` photos with short local Codex subprocesses so metadata, generated titles, and optional country descriptions are written back asynchronously without blocking uploads.

**Architecture:** Keep the upload path synchronous only for storage and queueing. Add a worker-oriented queue layer around existing metadata records so one batch can be atomically claimed, processed, retried, and recovered. Reuse the existing manual review schema and `apply_manual_review_batch()` as the write path so automatic and manual flows stay compatible.

**Tech Stack:** Flask, Python `unittest`, existing metadata store/file lock flow, local subprocess execution, launchd-compatible worker scripts.

---

### Task 1: Lock The Upload And Queue Contract

**Files:**
- Modify: `tests/test_gallery_metadata_workflow.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing tests for upload and status summary**

```python
def test_upload_keeps_photo_pending_and_returns_auto_queue_message(self):
    with loaded_app_module() as app_module:
        client = self.login(app_module)
        response = client.post(
            "/api/upload",
            data={
                "photos": (BytesIO(b"queued-image"), "queued.jpg"),
                "photo_keys": "queued-1",
                "photo_countries": "意大利",
            },
            content_type="multipart/form-data",
        )

    self.assertEqual(response.status_code, 201)
    self.assertEqual(response.json["photo"]["processing_status"], "pending")
    self.assertIn("自动识别队列", response.json["description_updates"]["message"])


def test_auto_metadata_status_summary_counts_processing_states(self):
    with loaded_app_module() as app_module:
        photo = app_module.storage.save_photo(
            FileStorage(stream=BytesIO(b"queued"), filename="queued.jpg", content_type="image/jpeg"),
            "法国",
        )
        app_module.storage.update_photo_processing_info(
            photo["name"],
            {
                "processing_status": "processing",
                "processing_reason": "auto_worker",
                "processing_error": "",
                "processing_attempts": 1,
            },
        )

        summary = app_module.build_auto_metadata_status_summary(app_module.load_photos())

    self.assertEqual(summary["processing_count"], 1)
    self.assertEqual(summary["pending_count"], 0)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python3 -m unittest tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_upload_keeps_photo_pending_and_returns_auto_queue_message tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_auto_metadata_status_summary_counts_processing_states -v`

Expected: failure because the upload message still says “待处理队列” and there is no `build_auto_metadata_status_summary()`.

- [ ] **Step 3: Implement the minimal app-side behavior**

```python
def build_auto_metadata_status_summary(photos: list[dict]) -> dict[str, Any]:
    pending = [photo for photo in photos if str(photo.get("processing_status") or "") == PHOTO_PROCESSING_STATUS_PENDING]
    processing = [photo for photo in photos if str(photo.get("processing_status") or "") == PHOTO_PROCESSING_STATUS_PROCESSING]
    review = [photo for photo in photos if str(photo.get("processing_status") or "") == PHOTO_PROCESSING_STATUS_REVIEW]
    return {
        "pending_count": len(pending),
        "processing_count": len(processing),
        "review_count": len(review),
        "last_error": "",
        "last_activity_at": "",
    }
```

Update the upload response message so it explicitly promises asynchronous auto-processing rather than only a manual queue.

- [ ] **Step 4: Re-run the focused tests**

Run: `python3 -m unittest tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_upload_keeps_photo_pending_and_returns_auto_queue_message tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_auto_metadata_status_summary_counts_processing_states -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gallery_metadata_workflow.py app.py
git commit -m "feat: expose async auto-metadata queue status"
```

### Task 2: Add Atomic Batch Claiming, Release, And Recovery

**Files:**
- Modify: `tests/test_gallery_metadata_workflow.py`
- Modify: `storage.py`
- Modify: `app.py`

- [ ] **Step 1: Write failing tests for claim/release/recovery**

```python
def test_claim_pending_review_batch_marks_single_country_processing(self):
    with loaded_app_module() as app_module:
        for index in range(6):
            app_module.storage.save_photo(
                FileStorage(stream=BytesIO(f"it-{index}".encode()), filename=f"it-{index}.jpg", content_type="image/jpeg"),
                "意大利",
            )

        batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")
        photos = app_module.load_photos()

    self.assertEqual(batch["country"], "意大利")
    self.assertEqual(batch["photo_count"], 5)
    self.assertTrue(all(item["processing_status"] == "processing" for item in photos[:5]))


def test_release_processing_batch_returns_to_pending_before_max_attempts(self):
    with loaded_app_module() as app_module:
        photo = app_module.storage.save_photo(
            FileStorage(stream=BytesIO(b"fr"), filename="fr.jpg", content_type="image/jpeg"),
            "法国",
        )
        batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")

        app_module.release_processing_batch(batch["batch_id"], error="bad json", retryable=True)
        updated = next(item for item in app_module.load_photos() if item["name"] == photo["name"])

    self.assertEqual(updated["processing_status"], "pending")
    self.assertEqual(updated["processing_error"], "bad json")
```

- [ ] **Step 2: Run the claim/release tests and verify red**

Run: `python3 -m unittest tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_claim_pending_review_batch_marks_single_country_processing tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_release_processing_batch_returns_to_pending_before_max_attempts -v`

Expected: failure because claim/release helpers do not exist.

- [ ] **Step 3: Implement queue mutation helpers**

```python
def claim_pending_review_batch(limit: int = MAX_METADATA_BATCH_SIZE, owner: str = "") -> dict[str, Any]:
    ...


def release_processing_batch(batch_id: str, *, error: str, retryable: bool) -> dict[str, Any]:
    ...


def recover_stale_processing_batches(*, timeout_seconds: int) -> dict[str, int]:
    ...
```

Back these helpers with `MetadataStore._mutate()` so selection and status transition happen under the existing file lock.

- [ ] **Step 4: Re-run the focused tests**

Run: `python3 -m unittest tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_claim_pending_review_batch_marks_single_country_processing tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_release_processing_batch_returns_to_pending_before_max_attempts -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gallery_metadata_workflow.py storage.py app.py
git commit -m "feat: add auto-metadata batch claiming and recovery"
```

### Task 3: Implement The Short Codex Worker Bridge

**Files:**
- Create: `scripts/auto_metadata_worker.py`
- Create: `scripts/prompts/gallery_auto_metadata_worker.md`
- Modify: `tests/test_gallery_metadata_workflow.py`
- Modify: `app.py`

- [ ] **Step 1: Write failing tests for worker result validation and apply flow**

```python
def test_process_claimed_batch_applies_valid_result(self):
    with loaded_app_module() as app_module:
        photo = app_module.storage.save_photo(
            FileStorage(stream=BytesIO(b"it-photo"), filename="it-photo.jpg", content_type="image/jpeg"),
            "意大利",
        )
        batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")

        result = app_module.complete_processing_batch(
            batch["batch_id"],
            {
                "country": "意大利",
                "photos": [
                    {
                        "name": photo["name"],
                        "city": "威尼斯",
                        "place": "圣马可广场",
                        "subject": "广场立面",
                        "scene_summary": "威尼斯广场与钟楼在冷光中展开。",
                    }
                ],
            },
        )

        updated = next(item for item in app_module.load_photos() if item["name"] == photo["name"])

    self.assertEqual(result["updated_count"], 1)
    self.assertEqual(updated["processing_status"], "done")
    self.assertEqual(updated["title"], "圣马可广场")


def test_complete_processing_batch_rejects_name_mismatch(self):
    with loaded_app_module() as app_module:
        app_module.storage.save_photo(
            FileStorage(stream=BytesIO(b"cz-photo"), filename="cz-photo.jpg", content_type="image/jpeg"),
            "捷克",
        )
        batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")

        with self.assertRaises(ValueError):
            app_module.complete_processing_batch(
                batch["batch_id"],
                {"country": "捷克", "photos": [{"name": "other.jpg", "city": "布拉格", "place": "老城广场"}]},
            )
```

- [ ] **Step 2: Run the worker completion tests**

Run: `python3 -m unittest tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_process_claimed_batch_applies_valid_result tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_complete_processing_batch_rejects_name_mismatch -v`

Expected: failure because `complete_processing_batch()` does not exist.

- [ ] **Step 3: Implement completion helpers and worker script**

```python
def complete_processing_batch(batch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ...


def build_codex_worker_prompt(batch: dict[str, Any]) -> str:
    ...
```

Add `scripts/auto_metadata_worker.py` with:

```python
def main() -> int:
    recovery = recover_stale_processing_batches(timeout_seconds=processing_timeout_seconds())
    batch = claim_pending_review_batch(limit=5, owner=worker_id())
    if not batch["photos"]:
        return 0
    payload = run_codex_subprocess(batch)
    complete_processing_batch(batch["batch_id"], payload)
    return 0
```

Keep the subprocess contract strict: batch JSON in, strict JSON out, no long logs.

- [ ] **Step 4: Re-run the focused tests**

Run: `python3 -m unittest tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_process_claimed_batch_applies_valid_result tests.test_gallery_metadata_workflow.GalleryMetadataWorkflowTests.test_complete_processing_batch_rejects_name_mismatch -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gallery_metadata_workflow.py app.py scripts/auto_metadata_worker.py scripts/prompts/gallery_auto_metadata_worker.md
git commit -m "feat: add auto metadata worker bridge"
```

### Task 4: Surface Queue State In The Admin UI

**Files:**
- Modify: `templates/index.html`
- Modify: `tests/test_local_public_share.py`
- Modify: `app.py`

- [ ] **Step 1: Write failing tests for admin queue visibility**

```python
def test_admin_dashboard_renders_auto_metadata_status_summary(self):
    ...
    self.assertIn("自动识别队列", html)
    self.assertIn("处理中", html)
```

- [ ] **Step 2: Run the admin template test**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_admin_dashboard_renders_auto_metadata_status_summary -v`

Expected: FAIL because the admin page has no queue panel yet.

- [ ] **Step 3: Add the minimal queue panel and optional trigger endpoint**

```python
return render_template(
    "index.html",
    photos=photos,
    groups=build_groups(photos, ensure_missing_descriptions=True),
    auto_metadata_status=build_auto_metadata_status_summary(photos),
    ...
)
```

In `templates/index.html`, render one compact panel with pending, processing, review, last activity, and recent error.

- [ ] **Step 4: Re-run the admin template test**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_admin_dashboard_renders_auto_metadata_status_summary -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_local_public_share.py app.py
git commit -m "feat: show auto metadata queue status in admin"
```

### Task 5: Full Verification

**Files:**
- Modify: `docs/superpowers/handoffs/2026-04-19-country-intro-and-413.md`

- [ ] **Step 1: Run targeted worker and upload tests**

Run: `python3 -m unittest tests/test_gallery_metadata_workflow.py tests/test_local_public_share.py -v`

Expected: all targeted tests pass.

- [ ] **Step 2: Run the full regression suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: full suite passes with `OK`.

- [ ] **Step 3: Update the handoff**

Record:
- new auto-metadata worker files
- launchd/worker expectations
- verification command outputs
- any residual risks around local Codex subprocess execution

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/handoffs/2026-04-19-country-intro-and-413.md
git commit -m "docs: hand off auto pending metadata worker"
```
