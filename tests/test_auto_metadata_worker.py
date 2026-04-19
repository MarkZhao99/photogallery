import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts import auto_metadata_worker_support


class AutoMetadataWorkerTests(unittest.TestCase):
    def create_prompt_template(self, project_root: Path) -> None:
        prompt_path = project_root / "scripts" / "prompts" / "gallery_auto_metadata_worker.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text("只返回 JSON。", encoding="utf-8")

    def test_build_codex_exec_command_uses_output_file_images_and_project_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_path = project_root / ".runtime" / "codex-output.json"
            command = auto_metadata_worker_support.build_codex_exec_command(
                project_root=project_root,
                output_path=output_path,
                image_paths=[
                    project_root / "a.jpg",
                    project_root / "b.jpg",
                ],
                codex_binary=Path("/usr/bin/codex"),
            )

        self.assertEqual(command[0], "/usr/bin/codex")
        self.assertIn("exec", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--output-last-message", command)
        self.assertIn(str(output_path.resolve()), command)
        self.assertIn("--image", command)
        self.assertIn(str(project_root.resolve()), command)

    def test_process_once_claims_batch_runs_codex_and_completes_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            self.create_prompt_template(project_root)
            image_path = project_root / "sample.jpg"
            image_path.write_bytes(b"jpeg")
            calls: dict[str, object] = {}

            def fake_complete(batch_id, payload):
                calls["batch_id"] = batch_id
                calls["payload"] = payload
                return {"updated_count": 1}

            fake_app = SimpleNamespace(
                MAX_METADATA_BATCH_SIZE=5,
                recover_stale_processing_batches=lambda timeout_seconds: {"requeued_count": 0, "review_count": 0},
                auto_metadata_processing_timeout_seconds=lambda: 900,
                claim_pending_review_batch=lambda limit, owner: {
                    "batch_id": "batch-1",
                    "country": "意大利",
                    "photo_count": 1,
                    "photos": [
                        {
                            "name": "意大利/sample.jpg",
                            "absolute_path": str(image_path),
                            "country": "意大利",
                        }
                    ],
                    "country_description": {"short_description": "", "long_description": ""},
                },
                complete_processing_batch=fake_complete,
                release_processing_batch=lambda batch_id, error, retryable: {"released_count": 1},
            )

            def fake_runner(command, **kwargs):
                output_index = command.index("--output-last-message") + 1
                Path(command[output_index]).write_text(
                    json.dumps(
                        {
                            "country": "意大利",
                            "photos": [
                                {
                                    "name": "意大利/sample.jpg",
                                    "city": "威尼斯",
                                    "place": "圣马可广场",
                                    "subject": "广场立面",
                                    "scene_summary": "威尼斯广场与钟楼在冷光中展开。",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0)

            result = auto_metadata_worker_support.process_once(
                project_root=project_root,
                app_module=fake_app,
                runner=fake_runner,
                codex_binary=Path("/usr/bin/codex"),
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(calls["batch_id"], "batch-1")
        self.assertEqual(calls["payload"]["photos"][0]["place"], "圣马可广场")

    def test_process_once_releases_batch_when_codex_runner_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            self.create_prompt_template(project_root)
            image_path = project_root / "sample.jpg"
            image_path.write_bytes(b"jpeg")
            released: dict[str, object] = {}

            def fake_release(batch_id, error, retryable):
                released["batch_id"] = batch_id
                released["error"] = error
                released["retryable"] = retryable
                return {"released_count": 1}

            fake_app = SimpleNamespace(
                MAX_METADATA_BATCH_SIZE=5,
                recover_stale_processing_batches=lambda timeout_seconds: {"requeued_count": 0, "review_count": 0},
                auto_metadata_processing_timeout_seconds=lambda: 900,
                claim_pending_review_batch=lambda limit, owner: {
                    "batch_id": "batch-2",
                    "country": "法国",
                    "photo_count": 1,
                    "photos": [
                        {
                            "name": "法国/sample.jpg",
                            "absolute_path": str(image_path),
                            "country": "法国",
                        }
                    ],
                    "country_description": {"short_description": "", "long_description": ""},
                },
                complete_processing_batch=lambda batch_id, payload: {"updated_count": 1},
                release_processing_batch=fake_release,
            )

            def fake_runner(command, **kwargs):
                raise RuntimeError("codex failed")

            result = auto_metadata_worker_support.process_once(
                project_root=project_root,
                app_module=fake_app,
                runner=fake_runner,
                codex_binary=Path("/usr/bin/codex"),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(released["batch_id"], "batch-2")
        self.assertIn("codex failed", str(released["error"]))
        self.assertTrue(released["retryable"])


if __name__ == "__main__":
    unittest.main()
