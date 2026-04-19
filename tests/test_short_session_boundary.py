import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts import short_session_boundary


class ShortSessionBoundaryTests(unittest.TestCase):
    def test_emit_boundary_writes_payload_with_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            handoff_path = project_root / "docs" / "superpowers" / "handoffs" / "resume.md"
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("# handoff\n", encoding="utf-8")

            payload = short_session_boundary.emit_boundary(
                project_root=project_root,
                handoff_path=handoff_path,
                resume_command="继续短会话：读取 handoff",
                reason="image_batch_limit",
                created_at="2026-04-19T03:00:00+08:00",
            )

            paths = short_session_boundary.runtime_paths(project_root)
            boundary_payload = json.loads(paths["boundary"].read_text(encoding="utf-8"))

        self.assertEqual(payload["reason"], "image_batch_limit")
        self.assertEqual(boundary_payload["created_at"], "2026-04-19T03:00:00+08:00")
        self.assertEqual(boundary_payload["handoff_path"], str(handoff_path.resolve()))
        self.assertEqual(boundary_payload["resume_command"], "继续短会话：读取 handoff")
        self.assertEqual(boundary_payload["resume_text_path"], str(paths["resume_text"].resolve()))

    def test_process_boundary_if_new_notifies_copies_and_writes_resume_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            handoff_path = project_root / "docs" / "superpowers" / "handoffs" / "resume.md"
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("# handoff\n", encoding="utf-8")

            short_session_boundary.emit_boundary(
                project_root=project_root,
                handoff_path=handoff_path,
                resume_command="继续短会话：读取 handoff",
                reason="image_batch_limit",
                created_at="2026-04-19T03:00:00+08:00",
            )

            runner = Mock()
            processed = short_session_boundary.process_boundary_if_new(
                project_root=project_root,
                runner=runner,
            )
            resume_text = short_session_boundary.runtime_paths(project_root)["resume_text"].read_text(encoding="utf-8")

        self.assertTrue(processed)
        self.assertEqual(runner.call_count, 2)
        notify_call = runner.call_args_list[0]
        clipboard_call = runner.call_args_list[1]
        self.assertEqual(notify_call.args[0][0], "osascript")
        self.assertEqual(clipboard_call.args[0][0], "pbcopy")
        self.assertEqual(clipboard_call.kwargs["input"], "继续短会话：读取 handoff")
        self.assertEqual(resume_text, "继续短会话：读取 handoff\n")

    def test_process_boundary_if_new_suppresses_duplicate_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            handoff_path = project_root / "docs" / "superpowers" / "handoffs" / "resume.md"
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("# handoff\n", encoding="utf-8")

            short_session_boundary.emit_boundary(
                project_root=project_root,
                handoff_path=handoff_path,
                resume_command="继续短会话：读取 handoff",
                reason="image_batch_limit",
                created_at="2026-04-19T03:00:00+08:00",
            )

            runner = Mock()
            first = short_session_boundary.process_boundary_if_new(project_root=project_root, runner=runner)
            second = short_session_boundary.process_boundary_if_new(project_root=project_root, runner=runner)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(runner.call_count, 2)

    def test_process_boundary_if_new_writes_text_even_if_notification_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            handoff_path = project_root / "docs" / "superpowers" / "handoffs" / "resume.md"
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("# handoff\n", encoding="utf-8")

            short_session_boundary.emit_boundary(
                project_root=project_root,
                handoff_path=handoff_path,
                resume_command="继续短会话：读取 handoff",
                reason="image_batch_limit",
                created_at="2026-04-19T03:00:00+08:00",
            )

            def fake_runner(command, **kwargs):
                if command[0] == "osascript":
                    raise RuntimeError("notification failed")
                return None

            processed = short_session_boundary.process_boundary_if_new(
                project_root=project_root,
                runner=fake_runner,
            )
            resume_text = short_session_boundary.runtime_paths(project_root)["resume_text"].read_text(encoding="utf-8")

        self.assertTrue(processed)
        self.assertEqual(resume_text, "继续短会话：读取 handoff\n")


if __name__ == "__main__":
    unittest.main()
