import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts import short_session_boundary_launchd


class ShortSessionBoundaryLaunchdTests(unittest.TestCase):
    def create_watcher_script(self, project_root: Path) -> None:
        watcher_path = project_root / "scripts" / "watch_short_session_boundary.py"
        watcher_path.parent.mkdir(parents=True, exist_ok=True)
        watcher_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def test_build_launch_agent_plist_points_at_watcher_and_runtime_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            home_dir = project_root / "home"
            self.create_watcher_script(project_root)

            payload = short_session_boundary_launchd.build_launch_agent_plist(
                project_root=project_root,
                home_dir=home_dir,
                python_binary=Path("/usr/bin/python3"),
                interval_seconds=2.5,
            )
            paths = short_session_boundary_launchd.launch_agent_paths(project_root, home_dir=home_dir)

        self.assertEqual(payload["Label"], short_session_boundary_launchd.DEFAULT_LABEL)
        self.assertEqual(
            payload["ProgramArguments"],
            [
                "/usr/bin/python3",
                str((project_root / "scripts" / "watch_short_session_boundary.py").resolve()),
                "--interval",
                "2.5",
            ],
        )
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertEqual(payload["WorkingDirectory"], str(project_root.resolve()))
        self.assertEqual(payload["StandardOutPath"], str(paths["stdout_log"].resolve()))
        self.assertEqual(payload["StandardErrorPath"], str(paths["stderr_log"].resolve()))
        self.assertEqual(payload["EnvironmentVariables"]["PYTHONUNBUFFERED"], "1")

    def test_write_launch_agent_plist_creates_loadable_xml_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            home_dir = project_root / "home"
            self.create_watcher_script(project_root)

            plist_path = short_session_boundary_launchd.write_launch_agent_plist(
                project_root=project_root,
                home_dir=home_dir,
                python_binary=Path("/usr/bin/python3"),
            )

            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)

        self.assertEqual(plist_path.name, f"{short_session_boundary_launchd.DEFAULT_LABEL}.plist")
        self.assertEqual(payload["Label"], short_session_boundary_launchd.DEFAULT_LABEL)
        self.assertEqual(payload["ProgramArguments"][1], str((project_root / "scripts" / "watch_short_session_boundary.py").resolve()))

    def test_install_launch_agent_writes_plist_and_reloads_service(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            home_dir = project_root / "home"
            self.create_watcher_script(project_root)
            runner = Mock()

            install_result = short_session_boundary_launchd.install_launch_agent(
                project_root=project_root,
                home_dir=home_dir,
                python_binary=Path("/usr/bin/python3"),
                uid=501,
                runner=runner,
            )
            paths = short_session_boundary_launchd.launch_agent_paths(project_root, home_dir=home_dir)
            self.assertEqual(install_result["plist_path"], paths["plist"])
            self.assertTrue(paths["plist"].exists())
            self.assertEqual(runner.call_count, 3)
            self.assertEqual(
                runner.call_args_list[0].args[0],
                ["/bin/launchctl", "bootout", "gui/501", str(paths["plist"])],
            )
            self.assertFalse(runner.call_args_list[0].kwargs["check"])
            self.assertEqual(
                runner.call_args_list[1].args[0],
                ["/bin/launchctl", "bootstrap", "gui/501", str(paths["plist"])],
            )
            self.assertTrue(runner.call_args_list[1].kwargs["check"])
            self.assertEqual(
                runner.call_args_list[2].args[0],
                [
                    "/bin/launchctl",
                    "kickstart",
                    "-k",
                    f"gui/501/{short_session_boundary_launchd.DEFAULT_LABEL}",
                ],
            )


if __name__ == "__main__":
    unittest.main()
