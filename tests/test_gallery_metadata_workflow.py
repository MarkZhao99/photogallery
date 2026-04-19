import contextlib
import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def base_env(temp_dir: str, **overrides: str) -> dict[str, str]:
    values = {
        "PHOTO_STORAGE": "icloud",
        "ICLOUD_PHOTO_DIR": temp_dir,
        "ADMIN_USERNAME": "zxxk",
        "ADMIN_PASSWORD": "test-password",
        "ADMIN_SESSION_SECRET": "test-session-secret",
        "PORT": "5001",
        "PUBLIC_SITE_ONLY": "false",
    }
    values.update(overrides)
    return values


@contextlib.contextmanager
def loaded_app_module(**overrides: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, base_env(temp_dir, **overrides), clear=False):
            sys.modules.pop("app", None)
            module = importlib.import_module("app")
            module = importlib.reload(module)
            try:
                yield module
            finally:
                sys.modules.pop("app", None)


class GalleryMetadataWorkflowTests(unittest.TestCase):
    def login(self, app_module):
        client = app_module.app.test_client()
        with client.session_transaction() as session:
            session["admin_authenticated"] = True
            session["admin_password_sig"] = app_module.current_password_signature()
            session["admin_username"] = app_module.admin_username()
        return client

    def test_upload_marks_photo_pending_without_running_country_intro_generation(self):
        with loaded_app_module() as app_module:
            client = self.login(app_module)
            with patch.object(
                app_module,
                "refresh_country_descriptions",
                side_effect=AssertionError("上传时不应直接刷新国家介绍"),
            ):
                response = client.post(
                    "/api/upload",
                    data={
                        "photos": (BytesIO(b"queued-image"), "queued.jpg"),
                        "photo_keys": "queued-1",
                        "photo_countries": "意大利",
                        "refresh_country_descriptions": "1",
                    },
                    content_type="multipart/form-data",
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["photo"]["processing_status"], "pending")
        self.assertEqual(response.json["photo"]["processing_reason"], "upload")
        self.assertEqual(response.json["photo"]["title_source"], "default")
        self.assertIn("自动识别队列", response.json["description_updates"]["message"])

    def test_build_auto_metadata_status_summary_counts_processing_states(self):
        with loaded_app_module() as app_module:
            pending_photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"pending-photo"),
                    filename="pending.jpg",
                    content_type="image/jpeg",
                ),
                "法国",
            )
            processing_photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"processing-photo"),
                    filename="processing.jpg",
                    content_type="image/jpeg",
                ),
                "法国",
            )
            review_photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"review-photo"),
                    filename="review.jpg",
                    content_type="image/jpeg",
                ),
                "法国",
            )
            app_module.storage.update_photo_processing_info(
                processing_photo["name"],
                {
                    "processing_status": "processing",
                    "processing_reason": "auto_worker",
                    "processing_error": "",
                    "processing_attempts": 1,
                    "processing_owner": "worker-1",
                    "processing_batch_id": "batch-1",
                    "processing_started_at": "2026-04-19T12:00:00",
                },
            )
            app_module.storage.update_photo_processing_info(
                review_photo["name"],
                {
                    "processing_status": "review",
                    "processing_reason": "auto_worker",
                    "processing_error": "bad json",
                    "processing_attempts": 3,
                },
            )

            summary = app_module.build_auto_metadata_status_summary(app_module.load_photos())

        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["processing_count"], 1)
        self.assertEqual(summary["review_count"], 1)
        self.assertEqual(summary["last_error"], "bad json")
        self.assertEqual(summary["processing_countries"], ["法国"])
        self.assertEqual(pending_photo["processing_status"], "pending")

    def test_build_pending_review_batch_returns_one_country_max_five_photos_with_absolute_paths(self):
        with loaded_app_module() as app_module:
            for index in range(3):
                app_module.storage.save_photo(
                    FileStorage(
                        stream=BytesIO(f"fr-{index}".encode("utf-8")),
                        filename=f"fr-{index}.jpg",
                        content_type="image/jpeg",
                    ),
                    "法国",
                )
            for index in range(6):
                app_module.storage.save_photo(
                    FileStorage(
                        stream=BytesIO(f"it-{index}".encode("utf-8")),
                        filename=f"it-{index}.jpg",
                        content_type="image/jpeg",
                    ),
                    "意大利",
                )

            result = app_module.build_pending_review_batch(limit=5)

            photos_after = {photo["name"]: photo for photo in app_module.load_photos()}

        self.assertEqual(result["country"], "意大利")
        self.assertEqual(len(result["photos"]), 5)
        self.assertTrue(all(item["country"] == "意大利" for item in result["photos"]))
        self.assertTrue(all(item["absolute_path"] for item in result["photos"]))
        self.assertTrue(all(Path(item["absolute_path"]).is_absolute() for item in result["photos"]))
        pending_italy = [
            photo for photo in photos_after.values()
            if photo["country"] == "意大利" and photo["processing_status"] == "pending"
        ]
        pending_france = [
            photo for photo in photos_after.values()
            if photo["country"] == "法国" and photo["processing_status"] == "pending"
        ]
        self.assertEqual(len(pending_italy), 6)
        self.assertEqual(len(pending_france), 3)

    def test_claim_pending_review_batch_marks_single_country_processing(self):
        with loaded_app_module() as app_module:
            for index in range(2):
                app_module.storage.save_photo(
                    FileStorage(
                        stream=BytesIO(f"fr-{index}".encode("utf-8")),
                        filename=f"fr-{index}.jpg",
                        content_type="image/jpeg",
                    ),
                    "法国",
                )
            for index in range(5):
                app_module.storage.save_photo(
                    FileStorage(
                        stream=BytesIO(f"it-{index}".encode("utf-8")),
                        filename=f"it-{index}.jpg",
                        content_type="image/jpeg",
                    ),
                    "意大利",
                )

            batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")
            second = app_module.claim_pending_review_batch(limit=5, owner="worker-2")
            photos = app_module.load_photos()

        self.assertEqual(batch["country"], "意大利")
        self.assertEqual(batch["photo_count"], 5)
        self.assertTrue(batch["batch_id"])
        self.assertTrue(all(item["country"] == "意大利" for item in batch["photos"]))
        processing_photos = [
            photo for photo in photos
            if photo["country"] == "意大利" and photo["processing_status"] == "processing"
        ]
        self.assertEqual(len(processing_photos), 5)
        self.assertEqual(second["photo_count"], 2)
        self.assertEqual(second["country"], "法国")

    def test_release_processing_batch_returns_to_pending_before_max_attempts(self):
        with loaded_app_module() as app_module:
            photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"fr"),
                    filename="fr.jpg",
                    content_type="image/jpeg",
                ),
                "法国",
            )

            batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")
            app_module.release_processing_batch(batch["batch_id"], error="bad json", retryable=True)
            updated = next(item for item in app_module.load_photos() if item["name"] == photo["name"])

        self.assertEqual(updated["processing_status"], "pending")
        self.assertEqual(updated["processing_reason"], "auto_retry")
        self.assertEqual(updated["processing_error"], "bad json")
        self.assertEqual(updated["processing_attempts"], 1)

    def test_recover_stale_processing_batches_returns_timed_out_items_to_pending(self):
        with loaded_app_module() as app_module:
            photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"stale"),
                    filename="stale.jpg",
                    content_type="image/jpeg",
                ),
                "奥地利",
            )
            batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")
            stale_started_at = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
            app_module.storage.update_photo_processing_info(
                photo["name"],
                {
                    "processing_status": "processing",
                    "processing_reason": "auto_worker",
                    "processing_error": "",
                    "processing_attempts": 1,
                    "processing_owner": "worker-1",
                    "processing_batch_id": batch["batch_id"],
                    "processing_started_at": stale_started_at,
                },
            )

            result = app_module.recover_stale_processing_batches(timeout_seconds=10)
            updated = next(item for item in app_module.load_photos() if item["name"] == photo["name"])

        self.assertEqual(result["requeued_count"], 1)
        self.assertEqual(updated["processing_status"], "pending")
        self.assertEqual(updated["processing_reason"], "auto_recover")

    def test_complete_processing_batch_applies_valid_result(self):
        with loaded_app_module() as app_module:
            photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"it-photo"),
                    filename="it-photo.jpg",
                    content_type="image/jpeg",
                ),
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
                    "country_description": {
                        "short_description": "水城广场与石墙在晨光里相遇。",
                        "long_description": "意大利这一组影像沿着威尼斯的广场、钟楼与石质立面缓慢展开，让水巷附近的秩序和人流气息在同一段导览里收束起来。",
                    },
                },
            )

            updated = next(item for item in app_module.load_photos() if item["name"] == photo["name"])

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(updated["processing_status"], "done")
        self.assertEqual(updated["title"], "圣马可广场")
        self.assertEqual(updated["city"], "威尼斯")
        self.assertEqual(updated["place"], "圣马可广场")

    def test_complete_processing_batch_rejects_name_mismatch(self):
        with loaded_app_module() as app_module:
            app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"cz-photo"),
                    filename="cz-photo.jpg",
                    content_type="image/jpeg",
                ),
                "捷克",
            )
            batch = app_module.claim_pending_review_batch(limit=5, owner="worker-1")

            with self.assertRaises(ValueError):
                app_module.complete_processing_batch(
                    batch["batch_id"],
                    {
                        "country": "捷克",
                        "photos": [
                            {
                                "name": "other.jpg",
                                "city": "布拉格",
                                "place": "老城广场",
                                "subject": "旧城",
                                "scene_summary": "错误照片名。",
                            }
                        ],
                    },
                )

    def test_apply_manual_review_batch_updates_metadata_title_and_country_intro(self):
        with loaded_app_module() as app_module:
            photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"it-photo"),
                    filename="it-photo.jpg",
                    content_type="image/jpeg",
                ),
                "意大利",
            )

            result = app_module.apply_manual_review_batch(
                {
                    "country": "意大利",
                    "photos": [
                        {
                            "name": photo["name"],
                            "city": "威尼斯",
                            "place": "圣马可广场",
                            "subject": "广场立面",
                            "scene_summary": "威尼斯广场与钟楼在冷光中展开。",
                            "title": "圣马可广场",
                        }
                    ],
                    "country_description": {
                        "short_description": "水城广场与石墙在晨光里相遇。",
                        "long_description": "意大利这一组影像沿着威尼斯的广场、钟楼与石质立面缓慢展开，让水巷附近的秩序和人流气息在同一段导览里收束起来。",
                    },
                }
            )

            updated_photo = next(item for item in app_module.load_photos() if item["name"] == photo["name"])
            updated_metadata = app_module.storage.get_photo_ai_metadata(photo["name"])
            updated_description = app_module.storage.list_country_descriptions()["意大利"]

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(updated_photo["title"], "圣马可广场")
        self.assertEqual(updated_photo["title_source"], "generated")
        self.assertEqual(updated_photo["processing_status"], "done")
        self.assertEqual(updated_metadata["city"], "威尼斯")
        self.assertEqual(updated_metadata["place"], "圣马可广场")
        self.assertEqual(updated_description["short_description"], "水城广场与石墙在晨光里相遇。")

    def test_manual_title_edit_updates_place_and_city_from_known_place_mapping(self):
        with loaded_app_module() as app_module:
            target_photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"target-photo"),
                    filename="target.jpg",
                    content_type="image/jpeg",
                ),
                "意大利",
            )
            reference_photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"reference-photo"),
                    filename="reference.jpg",
                    content_type="image/jpeg",
                ),
                "意大利",
            )
            app_module.storage.update_photo_ai_metadata(
                reference_photo["name"],
                {
                    "city": "威尼斯",
                    "place": "圣马可广场",
                    "subject": "广场立面",
                    "scene_summary": "威尼斯广场与钟楼。",
                },
            )

            client = self.login(app_module)
            with patch.object(
                app_module,
                "refresh_country_descriptions",
                return_value={
                    "enabled": True,
                    "message": "",
                    "updated": [],
                    "deleted": [],
                    "failed": [],
                },
            ) as refresh_mock:
                response = client.patch(
                    f"/api/photos/{target_photo['name']}",
                    json={"title": "圣马可广场", "country": "意大利"},
                )

            updated_metadata = app_module.storage.get_photo_ai_metadata(target_photo["name"])
            updated_photo = next(
                photo for photo in app_module.load_photos()
                if photo["name"] == target_photo["name"]
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(updated_metadata["place"], "圣马可广场")
        self.assertEqual(updated_metadata["city"], "威尼斯")
        self.assertEqual(updated_photo["title"], "圣马可广场")
        self.assertEqual(updated_photo["title_source"], "manual")
        refresh_mock.assert_called_once()

    def test_workflow_prompt_contains_request_size_and_batch_constraints(self):
        prompt_path = PROJECT_ROOT / "scripts" / "prompts" / "gallery_metadata_workflow.md"
        prompt = prompt_path.read_text(encoding="utf-8")

        self.assertIn("不要请求体过大", prompt)
        self.assertIn("单批最多 5 张", prompt)
        self.assertIn("先读取当前激活存储路径", prompt)
        self.assertIn("不要调用 groq 和 gemini", prompt)


if __name__ == "__main__":
    unittest.main()
