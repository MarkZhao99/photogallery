from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from storage import (
    COUNTRY_DESCRIPTIONS_KEY,
    FileSystemPhotoStorage,
    MetadataStore,
    normalize_photo_ai_metadata,
    PHOTO_PROCESSING_STATUS_PENDING,
    PHOTO_TITLE_SOURCE_DEFAULT,
)


class CountryIntroStorageTests(unittest.TestCase):
    def test_old_string_description_maps_to_long_description(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")
            store.save(
                {
                    COUNTRY_DESCRIPTIONS_KEY: {
                        "奥地利": "旧的国家长介绍",
                    }
                }
            )

            descriptions = store.list_country_descriptions()

        self.assertEqual(
            descriptions["奥地利"],
            {
                "short_description": "",
                "long_description": "旧的国家长介绍",
            },
        )

    def test_new_object_description_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")

            store.update_country_description(
                "挪威",
                {
                    "short_description": "山海冷光中的北境秩序。",
                    "long_description": "完整导览文字。",
                },
            )
            descriptions = store.list_country_descriptions()

        self.assertEqual(
            descriptions["挪威"]["short_description"],
            "山海冷光中的北境秩序。",
        )
        self.assertEqual(
            descriptions["挪威"]["long_description"],
            "完整导览文字。",
        )

    def test_empty_short_description_is_preserved_for_backfill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")
            store.save(
                {
                    COUNTRY_DESCRIPTIONS_KEY: {
                        "西班牙": {
                            "short_description": "",
                            "long_description": "旧长介绍",
                        }
                    }
                }
            )

            descriptions = store.list_country_descriptions()

        self.assertEqual(descriptions["西班牙"]["short_description"], "")
        self.assertEqual(descriptions["西班牙"]["long_description"], "旧长介绍")

    def test_filesystem_storage_delete_photo_removes_file_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemPhotoStorage(Path(temp_dir) / "uploads")
            store.update_country_description(
                "奥地利",
                {
                    "short_description": "湖山与旧镇在静光里缓慢展开。",
                    "long_description": "完整导览文字。",
                },
            )
            photo = store.save_photo(
                FileStorage(
                    stream=BytesIO(b"demo-image-bytes"),
                    filename="demo.jpg",
                    content_type="image/jpeg",
                ),
                "奥地利",
            )
            photo_path = Path(temp_dir) / "uploads" / photo["name"]

            self.assertTrue(photo_path.exists())
            self.assertIn(photo["name"], store.metadata.load())

            store.delete_photo(photo["name"])

            self.assertFalse(photo_path.exists())
            self.assertNotIn(photo["name"], store.metadata.load())
            self.assertEqual(
                store.list_country_descriptions()["奥地利"],
                {
                    "short_description": "湖山与旧镇在静光里缓慢展开。",
                    "long_description": "完整导览文字。",
                },
            )

    def test_normalize_photo_ai_metadata_uses_common_chinese_translations(self):
        metadata = normalize_photo_ai_metadata(
            {
                "city": "托洛姆瑟",
                "place": "神圣家族圣殿",
                "subject": "海港街区与教堂",
                "scene_summary": "托洛姆瑟的海港与神圣家族圣殿形成鲜明对照。",
            }
        )

        self.assertEqual(metadata["city"], "特罗姆瑟")
        self.assertEqual(metadata["place"], "圣家堂")
        self.assertIn("特罗姆瑟", metadata["scene_summary"])
        self.assertIn("圣家堂", metadata["scene_summary"])

    def test_metadata_store_round_trips_photo_ai_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")

            store.update_photo_ai_metadata(
                "奥地利/demo.jpg",
                {
                    "city": "哈尔施塔特",
                    "place": "哈尔施塔特湖",
                    "subject": "湖畔小镇夜景",
                    "scene_summary": "灯光与湖面反射构成安静的夜景。",
                },
            )
            metadata = store.get_photo_ai_metadata("奥地利/demo.jpg")

        self.assertEqual(metadata["city"], "哈尔施塔特")
        self.assertEqual(metadata["place"], "哈尔施塔特湖")
        self.assertEqual(metadata["subject"], "湖畔小镇夜景")
        self.assertEqual(metadata["scene_summary"], "灯光与湖面反射构成安静的夜景。")

    def test_metadata_store_load_tolerates_invalid_utf8_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "meta.json"
            path.write_bytes(b"{\n  \"broken\": \"\xa9\"\n}")
            store = MetadataStore(path)

            data = store.load()

        self.assertEqual(data, {})

    def test_metadata_store_mutations_reload_latest_disk_state_even_with_stale_mtime_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = (Path(temp_dir) / "meta.json").resolve()
            primary = MetadataStore(path)
            secondary = MetadataStore(path)
            photo_name = "奥地利/demo.jpg"
            primary.update_info(photo_name, country="奥地利", title="demo")

            original_stat = Path.stat

            def fake_stat(path_obj, *args, **kwargs):
                result = original_stat(path_obj, *args, **kwargs)
                if Path(path_obj).resolve() == path:
                    return SimpleNamespace(st_mtime_ns=1)
                return result

            with patch("storage.Path.stat", new=fake_stat):
                secondary.load()
                primary.update_photo_ai_metadata(
                    photo_name,
                    {
                        "city": "哈尔施塔特",
                        "place": "哈尔施塔特湖",
                    },
                )
                secondary.update_photo_processing_info(
                    photo_name,
                    {
                        "processing_status": PHOTO_PROCESSING_STATUS_PENDING,
                        "processing_reason": "upload",
                    },
                )

            record = primary.get_record(photo_name)

        self.assertEqual(record["city"], "哈尔施塔特")
        self.assertEqual(record["place"], "哈尔施塔特湖")
        self.assertEqual(record["processing_status"], PHOTO_PROCESSING_STATUS_PENDING)
        self.assertEqual(record["processing_reason"], "upload")

    def test_save_photo_marks_new_upload_as_pending_with_default_title_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileSystemPhotoStorage(Path(temp_dir) / "uploads")

            photo = store.save_photo(
                FileStorage(
                    stream=BytesIO(b"demo-image-bytes"),
                    filename="demo.jpg",
                    content_type="image/jpeg",
                ),
                "奥地利",
            )
            record = store.metadata.get_record(photo["name"])

        self.assertEqual(record["processing_status"], PHOTO_PROCESSING_STATUS_PENDING)
        self.assertEqual(record["processing_reason"], "upload")
        self.assertEqual(record["title_source"], PHOTO_TITLE_SOURCE_DEFAULT)


if __name__ == "__main__":
    unittest.main()
