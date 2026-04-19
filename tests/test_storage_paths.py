import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storage import resolve_storage_runtime_info


class StorageRuntimeInfoTests(unittest.TestCase):
    def test_resolve_storage_runtime_info_for_icloud_uses_configured_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()

            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "icloud",
                    "ICLOUD_PHOTO_DIR": str(Path(temp_dir) / "icloud-library"),
                },
                clear=False,
            ):
                runtime = resolve_storage_runtime_info(project_root)

        expected_root = (Path(temp_dir) / "icloud-library").resolve()
        self.assertEqual(runtime["provider"], "icloud")
        self.assertEqual(runtime["root"], str(expected_root))
        self.assertEqual(runtime["metadata_path"], str(expected_root / "photo-metadata.json"))

    def test_resolve_storage_runtime_info_for_local_uses_project_uploads_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()

            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "local",
                },
                clear=False,
            ):
                runtime = resolve_storage_runtime_info(project_root)

        expected_root = (project_root / "uploads").resolve()
        self.assertEqual(runtime["provider"], "local")
        self.assertEqual(runtime["root"], str(expected_root))
        self.assertEqual(runtime["metadata_path"], str(expected_root / "photo-metadata.json"))

    def test_resolve_storage_runtime_info_normalizes_relative_project_root_to_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                project_root = Path("project")
                project_root.mkdir()

                with patch.dict(
                    os.environ,
                    {
                        "PHOTO_STORAGE": "local",
                    },
                    clear=False,
                ):
                    runtime = resolve_storage_runtime_info(project_root)
            finally:
                os.chdir(previous_cwd)

        expected_root = (Path(temp_dir) / "project" / "uploads").resolve()
        self.assertEqual(runtime["provider"], "local")
        self.assertTrue(Path(runtime["root"]).is_absolute())
        self.assertTrue(Path(runtime["metadata_path"]).is_absolute())
        self.assertEqual(runtime["root"], str(expected_root))
        self.assertEqual(runtime["metadata_path"], str(expected_root / "photo-metadata.json"))


if __name__ == "__main__":
    unittest.main()
