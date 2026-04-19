from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from storage import ICloudPhotoStorage, LocalPhotoStorage, WebDAVPhotoStorage


def load_simple_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line or line.startswith("GEMINI_"):
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_source_storage(project_root: Path):
    source = os.getenv("MIGRATE_SOURCE", "icloud").strip().lower()
    if source == "local":
        return LocalPhotoStorage(project_root)

    icloud_dir = Path(
        os.path.expanduser(
            os.getenv(
                "ICLOUD_PHOTO_DIR",
                str(Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/web图库"),
            )
        )
    ).expanduser()
    return ICloudPhotoStorage(icloud_dir)


def build_target_storage(project_root: Path) -> WebDAVPhotoStorage:
    base_url = os.getenv("WEBDAV_BASE_URL", "").strip()
    username = os.getenv("WEBDAV_USERNAME", "").strip()
    password = os.getenv("WEBDAV_PASSWORD", "").strip()
    remote_dir = os.getenv("WEBDAV_REMOTE_DIR", "photo-wall").strip()
    metadata_remote_name = os.getenv("WEBDAV_METADATA_REMOTE_NAME", ".photo-metadata.json").strip() or ".photo-metadata.json"

    if not all([base_url, username, password]):
        raise RuntimeError("请先在 .env 中填写 WEBDAV_BASE_URL、WEBDAV_USERNAME、WEBDAV_PASSWORD。")

    return WebDAVPhotoStorage(
        base_url,
        username,
        password,
        remote_dir,
        project_root / ".webdav-photo-metadata.json",
        metadata_remote_name,
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_simple_env(project_root / ".env")

    source_storage = build_source_storage(project_root)
    target_storage = build_target_storage(project_root)

    photos = source_storage.list_photos()
    if not photos:
        print("没有找到可迁移的照片。")
        return

    print(f"开始迁移 {len(photos)} 张照片到 WebDAV ...")

    migrated = 0
    for photo in photos:
        stream, content_type = source_storage.open_photo(photo["name"])
        payload = stream.getvalue()
        filename = Path(photo["name"]).name
        response = target_storage.session.put(
            target_storage._file_url(filename),
            data=payload,
            headers={"Content-Type": content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"},
            timeout=target_storage.timeout,
        )
        response.raise_for_status()
        target_storage.metadata.update_info(
            filename,
            country=str(photo.get("country") or ""),
            title=str(photo.get("title") or ""),
        )
        migrated += 1
        print(f"[{migrated}/{len(photos)}] 已迁移 {filename}")

    for country, description in source_storage.list_country_descriptions().items():
        target_storage.update_country_description(country, description)

    print("迁移完成。你现在可以把本地和 Render 都切换到 PHOTO_STORAGE=webdav。")


if __name__ == "__main__":
    main()
