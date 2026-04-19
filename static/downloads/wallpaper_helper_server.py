#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_NAME = "Wallpaper Helper"
APP_VERSION = "1.1.5"
HOST = "127.0.0.1"
PORT = 38941
CACHE_DIR = Path.home() / "Library/Application Support/WallpaperHelper/cache"
WALLPAPER_STORE_INDEX = Path.home() / "Library/Application Support/com.apple.wallpaper/Store/Index.plist"
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True

    try:
        parsed = urllib.parse.urlparse(origin)
    except ValueError:
        return False

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in ALLOWED_HOSTS:
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    return ip.is_loopback or ip.is_private


def guess_extension(image_url: str, content_type: str | None) -> str:
    parsed = urllib.parse.urlparse(image_url)
    ext = Path(urllib.parse.unquote(parsed.path)).suffix.lower()
    if ext:
        return ext

    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return guessed or ".jpg"


def safe_name(name: str | None, fallback_stem: str = "wallpaper") -> str:
    cleaned = (name or "").strip()
    if cleaned:
        cleaned = Path(cleaned).stem
    if not cleaned:
        cleaned = fallback_stem
    cleaned = re.sub(r"[^\w\-. ]+", "-", cleaned, flags=re.UNICODE).strip(" .-_")
    return cleaned or fallback_stem


def build_target_path(image_url: str, image_name: str | None, content_type: str | None) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext = guess_extension(image_url, content_type)
    return CACHE_DIR / f"{safe_name(image_name)}{ext}"


def download_image(image_url: str, image_name: str | None) -> Path:
    request = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            "Accept": "image/*,*/*;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"下载图片失败：服务器返回 {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("下载图片失败：无法连接展示页。") from exc

    if not payload:
        raise RuntimeError("下载图片失败：图片内容为空。")

    target = build_target_path(image_url, image_name, content_type)
    target.write_bytes(payload)
    return target


def applescript_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def swift_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def set_wallpaper_with_swift(path: Path) -> None:
    swift_binary = Path("/usr/bin/swift")
    if not swift_binary.exists():
        raise RuntimeError("未找到 Swift 运行环境。")

    swift_source = f"""
import AppKit
import Foundation

let imagePath = "{swift_escape(str(path))}"
let imageURL = URL(fileURLWithPath: imagePath)

do {{
    for screen in NSScreen.screens {{
        try NSWorkspace.shared.setDesktopImageURL(imageURL, for: screen, options: [:])
    }}
    print("OK")
}} catch {{
    fputs(String(describing: error), stderr)
    exit(1)
}}
"""

    with tempfile.NamedTemporaryFile("w", suffix=".swift", delete=False, encoding="utf-8") as handle:
        handle.write(swift_source)
        swift_script_path = Path(handle.name)

    try:
        subprocess.run(
            [str(swift_binary), str(swift_script_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if stderr:
            raise RuntimeError(f"设置壁纸失败：{stderr}") from exc
        raise RuntimeError("设置壁纸失败：Swift 桌面接口返回异常。") from exc
    finally:
        swift_script_path.unlink(missing_ok=True)


def current_wallpaper_paths_with_swift() -> list[Path]:
    swift_binary = Path("/usr/bin/swift")
    if not swift_binary.exists():
        raise RuntimeError("未找到 Swift 运行环境。")

    swift_source = """
import AppKit
import Foundation

for screen in NSScreen.screens {
    if let url = NSWorkspace.shared.desktopImageURL(for: screen) {
        print(url.path)
    }
}
"""

    with tempfile.NamedTemporaryFile("w", suffix=".swift", delete=False, encoding="utf-8") as handle:
        handle.write(swift_source)
        swift_script_path = Path(handle.name)

    try:
        result = subprocess.run(
            [str(swift_binary), str(swift_script_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if stderr:
            raise RuntimeError(f"读取当前壁纸失败：{stderr}") from exc
        raise RuntimeError("读取当前壁纸失败：Swift 桌面接口返回异常。") from exc
    finally:
        swift_script_path.unlink(missing_ok=True)

    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def set_wallpaper_with_applescript(path: Path) -> None:
    script_lines = [
        'tell application "System Events"',
        f'  tell every desktop to set picture to POSIX file "{applescript_escape(str(path))}"',
        "end tell",
    ]

    command: list[str] = ["/usr/bin/osascript"]
    for line in script_lines:
        command.extend(["-e", line])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if stderr:
            raise RuntimeError(f"设置壁纸失败：{stderr}") from exc
        raise RuntimeError("设置壁纸失败：请允许终端控制桌面后重试。") from exc


def refresh_desktop_services() -> None:
    killall_binary = Path("/usr/bin/killall")
    if killall_binary.exists():
        for process_name in ["WallpaperImageExtension", "WallpaperAgent", "Dock"]:
            subprocess.run(
                [str(killall_binary), process_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

    launchctl_binary = Path("/bin/launchctl")
    if launchctl_binary.exists():
        user_id = os.getuid()
        subprocess.run(
            [str(launchctl_binary), "kickstart", "-k", f"gui/{user_id}/com.apple.wallpaper.agent"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    time.sleep(1.5)


def current_paths_match_target(current_paths: list[Path], target: Path) -> bool:
    normalized_target = target.resolve()
    return any(current.resolve() == normalized_target for current in current_paths)


def wait_for_target_stable(target: Path, attempts: int, delay: float, required_streak: int) -> list[Path]:
    streak = 0
    last_paths: list[Path] = []

    for _ in range(attempts):
        try:
            current_paths = current_wallpaper_paths_with_swift()
        except RuntimeError:
            current_paths = []

        last_paths = current_paths
        if current_paths_match_target(current_paths, target):
            streak += 1
            if streak >= required_streak:
                return current_paths
        else:
            streak = 0

        time.sleep(delay)

    return last_paths


def update_desktop_payload(payload: dict[str, Any], file_url: str) -> bool:
    content = payload.get("Content")
    if not isinstance(content, dict):
        return False

    choices = content.get("Choices")
    if not isinstance(choices, list):
        return False

    updated = False
    for choice in choices:
        if not isinstance(choice, dict):
            continue

        files = choice.get("Files")
        if not isinstance(files, list):
            continue

        if not files:
            files.append({"relative": file_url})
        else:
            for file_entry in files:
                if isinstance(file_entry, dict):
                    file_entry["relative"] = file_url

        provider = str(choice.get("Provider") or "").strip()
        if provider == "default":
            choice["Provider"] = "com.apple.wallpaper.choice.image"
        updated = True

    return updated


def rewrite_wallpaper_store_tree(node: Any, file_url: str) -> bool:
    updated = False

    if isinstance(node, dict):
        desktop_payload = node.get("Desktop")
        if isinstance(desktop_payload, dict):
            updated = update_desktop_payload(desktop_payload, file_url) or updated

        for value in node.values():
            updated = rewrite_wallpaper_store_tree(value, file_url) or updated
        return updated

    if isinstance(node, list):
        for item in node:
            updated = rewrite_wallpaper_store_tree(item, file_url) or updated

    return updated


def update_wallpaper_store(path: Path) -> None:
    if not WALLPAPER_STORE_INDEX.exists():
        return

    try:
        with WALLPAPER_STORE_INDEX.open("rb") as handle:
            store = plistlib.load(handle)
    except Exception as exc:
        raise RuntimeError(f"读取系统壁纸配置失败：{exc}") from exc

    file_url = path.resolve().as_uri()
    updated = rewrite_wallpaper_store_tree(store, file_url)
    if not updated:
        return

    temp_path = WALLPAPER_STORE_INDEX.with_suffix(".tmp")
    try:
        with temp_path.open("wb") as handle:
            plistlib.dump(store, handle, fmt=plistlib.FMT_BINARY, sort_keys=False)
        temp_path.replace(WALLPAPER_STORE_INDEX)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"写入系统壁纸配置失败：{exc}") from exc


def set_wallpaper(path: Path) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("当前桌面助手只支持 macOS。")

    swift_error: RuntimeError | None = None
    applescript_error: RuntimeError | None = None
    store_error: RuntimeError | None = None

    try:
        set_wallpaper_with_swift(path)
    except RuntimeError as exc:
        swift_error = exc

    try:
        set_wallpaper_with_applescript(path)
    except RuntimeError as exc:
        applescript_error = exc

    try:
        update_wallpaper_store(path)
    except RuntimeError as exc:
        store_error = exc

    normalized_target = path.resolve()
    current_paths = wait_for_target_stable(normalized_target, attempts=8, delay=0.4, required_streak=2)
    if current_paths_match_target(current_paths, normalized_target):
        refresh_desktop_services()
        current_paths = wait_for_target_stable(normalized_target, attempts=8, delay=0.5, required_streak=3)
        if current_paths_match_target(current_paths, normalized_target):
            return

    refresh_desktop_services()

    try:
        set_wallpaper_with_swift(path)
    except RuntimeError as exc:
        if swift_error is None:
            swift_error = exc

    try:
        set_wallpaper_with_applescript(path)
    except RuntimeError as exc:
        if applescript_error is None:
            applescript_error = exc

    try:
        update_wallpaper_store(path)
    except RuntimeError as exc:
        if store_error is None:
            store_error = exc

    current_paths = wait_for_target_stable(normalized_target, attempts=10, delay=0.5, required_streak=4)
    if current_paths_match_target(current_paths, normalized_target):
        return

    if swift_error or applescript_error or store_error:
        raise RuntimeError(
            "设置壁纸失败：桌面服务没有切换到目标图片。\n"
            f"Swift 接口：{swift_error or '成功但未生效'}\n"
            f"AppleScript：{applescript_error or '成功但未生效'}\n"
            f"系统配置：{store_error or '已同步所有 Space'}"
        )

    raise RuntimeError("设置壁纸失败：系统没有切换到目标图片。")


def read_current_wallpaper_paths() -> list[str]:
    try:
        return [str(path) for path in current_wallpaper_paths_with_swift()]
    except RuntimeError:
        return []


class WallpaperHandler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{APP_VERSION}"

    def end_headers(self) -> None:
        origin = self.headers.get("Origin")
        if is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def write_json(self, payload: dict[str, Any], status_code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def reject_origin_if_needed(self) -> bool:
        origin = self.headers.get("Origin")
        if is_allowed_origin(origin):
            return False
        self.write_json({"ok": False, "error": "未授权的页面来源。"}, 403)
        return True

    def do_OPTIONS(self) -> None:
        if self.reject_origin_if_needed():
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self.write_json(
                {
                    "ok": True,
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "platform": "macOS" if sys.platform == "darwin" else sys.platform,
                    "supports_set_wallpaper": sys.platform == "darwin",
                }
            )
            return

        if self.path.rstrip("/") == "/current-wallpaper":
            self.write_json(
                {
                    "ok": True,
                    "current_paths": read_current_wallpaper_paths(),
                }
            )
            return

        self.write_json({"ok": False, "error": "接口不存在。"}, 404)

    def do_POST(self) -> None:
        if self.reject_origin_if_needed():
            return

        if self.path.rstrip("/") != "/set-wallpaper":
            self.write_json({"ok": False, "error": "接口不存在。"}, 404)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length)

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.write_json({"ok": False, "error": "请求数据格式不正确。"}, 400)
            return

        image_url = str(payload.get("image_url") or "").strip()
        image_name = str(payload.get("image_name") or "").strip()
        if not image_url:
            self.write_json({"ok": False, "error": "缺少图片地址。"}, 400)
            return

        parsed = urllib.parse.urlparse(image_url)
        if parsed.scheme not in {"http", "https"}:
            self.write_json({"ok": False, "error": "仅支持 http 或 https 图片地址。"}, 400)
            return

        try:
            print(f"收到设壁纸请求：image_name={image_name or '(empty)'} image_url={image_url}")
            saved_path = download_image(image_url, image_name)
            set_wallpaper(saved_path)
            print(f"壁纸设置完成：saved_path={saved_path}")
        except RuntimeError as exc:
            self.write_json({"ok": False, "error": str(exc)}, 500)
            return

        self.write_json(
            {
                "ok": True,
                "message": "已把当前图片设置为桌面壁纸。",
                "saved_path": str(saved_path),
                "current_paths": read_current_wallpaper_paths(),
            }
        )


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), WallpaperHandler)
    print(f"{APP_NAME} 已启动：http://{HOST}:{PORT}")
    print("保持这个终端窗口开启，即可让展示页一键设置桌面壁纸。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n桌面助手已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
