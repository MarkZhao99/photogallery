import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts import auto_metadata_worker_launchd


class AutoMetadataWorkerLaunchdTests(unittest.TestCase):
    def create_worker_script(self, project_root: Path) -> None:
        worker_path = project_root / "scripts" / "auto_metadata_worker.py"
        worker_path.parent.mkdir(parents=True, exist_ok=True)
        worker_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def test_build_launch_agent_plist_points_at_worker_and_runtime_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            home_dir = project_root / "home"
            self.create_worker_script(project_root)

            payload = auto_metadata_worker_launchd.build_launch_agent_plist(
                project_root=project_root,
                home_dir=home_dir,
                python_binary=Path("/usr/bin/python3"),
                interval_seconds=12,
            )
            paths = auto_metadata_worker_launchd.launch_agent_paths(project_root, home_dir=home_dir)

        self.assertEqual(payload["Label"], auto_metadata_worker_launchd.DEFAULT_LABEL)
        self.assertEqual(
            payload["ProgramArguments"],
            [
                "/usr/bin/python3",
                str((project_root / "scripts" / "auto_metadata_worker.py").resolve()),
            ],
        )
        self.assertTrue(payload["RunAtLoad"])
        self.assertEqual(payload["StartInterval"], 12)
        self.assertEqual(payload["WorkingDirectory"], str(project_root.resolve()))
        self.assertEqual(payload["StandardOutPath"], str(paths["stdout_log"].resolve()))
        self.assertEqual(payload["StandardErrorPath"], str(paths["stderr_log"].resolve()))

    def test_write_launch_agent_plist_creates_loadable_xml_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            home_dir = project_root / "home"
            self.create_worker_script(project_root)

            plist_path = auto_metadata_worker_launchd.write_launch_agent_plist(
                project_root=project_root,
                home_dir=home_dir,
                python_binary=Path("/usr/bin/python3"),
                interval_seconds=9,
            )

            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)

        self.assertEqual(plist_path.name, f"{auto_metadata_worker_launchd.DEFAULT_LABEL}.plist")
        self.assertEqual(payload["Label"], auto_metadata_worker_launchd.DEFAULT_LABEL)
        self.assertEqual(payload["StartInterval"], 9)

    def test_install_launch_agent_writes_plist_and_reloads_service(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            home_dir = project_root / "home"
            self.create_worker_script(project_root)
            runner = Mock()

            result = auto_metadata_worker_launchd.install_launch_agent(
                project_root=project_root,
                home_dir=home_dir,
                python_binary=Path("/usr/bin/python3"),
                interval_seconds=15,
                uid=501,
                runner=runner,
            )
            paths = auto_metadata_worker_launchd.launch_agent_paths(project_root, home_dir=home_dir)
            self.assertEqual(result["plist_path"], paths["plist"])
            self.assertTrue(paths["plist"].exists())
            self.assertEqual(runner.call_count, 3)
            self.assertEqual(
                runner.call_args_list[0].args[0],
                ["/bin/launchctl", "bootout", "gui/501", str(paths["plist"])],
            )
            self.assertEqual(
                runner.call_args_list[1].args[0],
                ["/bin/launchctl", "bootstrap", "gui/501", str(paths["plist"])],
            )
            self.assertEqual(
                runner.call_args_list[2].args[0],
                [
                    "/bin/launchctl",
                    "kickstart",
                    "-k",
                    f"gui/501/{auto_metadata_worker_launchd.DEFAULT_LABEL}",
                ],
            )


if __name__ == "__main__":
    unittest.main()
