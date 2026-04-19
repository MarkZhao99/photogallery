from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import requests
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is available on macOS/Linux
    fcntl = None


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
UNCATEGORIZED_LABEL = "未分类"
COUNTRY_DESCRIPTIONS_KEY = "__country_descriptions__"
COUNTRY_SHORT_DESCRIPTION_LIMIT = 80
COUNTRY_LONG_DESCRIPTION_LIMIT = 420
PHOTO_AI_METADATA_FIELDS = ("city", "place", "subject", "scene_summary")
PHOTO_PROCESSING_STATUS_PENDING = "pending"
PHOTO_PROCESSING_STATUS_PROCESSING = "processing"
PHOTO_PROCESSING_STATUS_DONE = "done"
PHOTO_PROCESSING_STATUS_REVIEW = "review"
PHOTO_PROCESSING_STATUSES = {
    PHOTO_PROCESSING_STATUS_PENDING,
    PHOTO_PROCESSING_STATUS_PROCESSING,
    PHOTO_PROCESSING_STATUS_DONE,
    PHOTO_PROCESSING_STATUS_REVIEW,
}
PHOTO_TITLE_SOURCE_DEFAULT = "default"
PHOTO_TITLE_SOURCE_GENERATED = "generated"
PHOTO_TITLE_SOURCE_MANUAL = "manual"
PHOTO_TITLE_SOURCES = {
    PHOTO_TITLE_SOURCE_DEFAULT,
    PHOTO_TITLE_SOURCE_GENERATED,
    PHOTO_TITLE_SOURCE_MANUAL,
}
PHOTO_AI_METADATA_LIMITS = {
    "city": 60,
    "place": 80,
    "subject": 80,
    "scene_summary": 220,
}
COMMON_CHINESE_TRANSLATIONS = {
    "托洛姆瑟": "特罗姆瑟",
    "神圣家族圣殿": "圣家堂",
    "神圣家族大教堂": "圣家堂",
    "神圣家族教堂": "圣家堂",
    "神圣家族赎罪堂": "圣家堂",
    "巴塞隆纳": "巴塞罗那",
    "佛罗伦斯": "佛罗伦萨",
}


@dataclass
class PhotoRecord:
    name: str
    url: str
    country: str
    title: str
    size: int | None = None
    modified_at: str | None = None
    city: str | None = None
    place: str | None = None
    subject: str | None = None
    scene_summary: str | None = None
    processing_status: str | None = None
    processing_reason: str | None = None
    processing_error: str | None = None
    processing_attempts: int | None = None
    processing_owner: str | None = None
    processing_batch_id: str | None = None
    processing_started_at: str | None = None
    title_source: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "country": self.country,
            "title": self.title,
            "size": self.size,
            "modified_at": self.modified_at,
            "city": self.city,
            "place": self.place,
            "subject": self.subject,
            "scene_summary": self.scene_summary,
            "processing_status": self.processing_status,
            "processing_reason": self.processing_reason,
            "processing_error": self.processing_error,
            "processing_attempts": self.processing_attempts,
            "processing_owner": self.processing_owner,
            "processing_batch_id": self.processing_batch_id,
            "processing_started_at": self.processing_started_at,
            "title_source": self.title_source,
        }


class MetadataStore:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] | None = None
        self._cache_mtime_ns: int | None = None

    def _read_from_disk(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _refresh_cache(self, data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        self._cache = data
        try:
            self._cache_mtime_ns = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._cache_mtime_ns = None
        return data

    @contextmanager
    def _exclusive_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _write_locked(self, data: dict[str, dict[str, Any]]) -> None:
        temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, self.path)
        self._refresh_cache(data)

    def _mutate(self, callback):
        with self._exclusive_lock():
            data = self._read_from_disk()
            result = callback(data)
            self._write_locked(data)
            return result

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            self._cache = {}
            self._cache_mtime_ns = None
            return {}
        mtime_ns = self.path.stat().st_mtime_ns
        if self._cache is not None and self._cache_mtime_ns == mtime_ns:
            return self._cache
        data = self._read_from_disk()
        return self._refresh_cache(data)

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        with self._exclusive_lock():
            self._write_locked(data)

    def get_record(self, filename: str) -> dict[str, Any]:
        return self.load().get(filename, {})

    def get_country(self, filename: str) -> str:
        return self.get_record(filename).get("country", UNCATEGORIZED_LABEL) or UNCATEGORIZED_LABEL

    def get_optional_country(self, filename: str) -> str | None:
        country = self.get_record(filename).get("country")
        if country is None:
            return None
        cleaned = str(country).strip()
        return cleaned or None

    def get_title(self, filename: str) -> str:
        return self.get_record(filename).get("title", "") or ""

    def get_title_source(self, filename: str) -> str:
        record = self.get_record(filename)
        explicit_source = normalize_title_source(record.get("title_source"))
        if explicit_source:
            return explicit_source
        title = normalize_title(record.get("title"))
        if not title or title == default_title(filename):
            return PHOTO_TITLE_SOURCE_DEFAULT
        return PHOTO_TITLE_SOURCE_MANUAL

    def get_photo_ai_metadata(self, filename: str) -> dict[str, str]:
        record = self.get_record(filename)
        return normalize_photo_ai_metadata({field: record.get(field) for field in PHOTO_AI_METADATA_FIELDS})

    def get_photo_processing_info(self, filename: str) -> dict[str, Any]:
        record = self.get_record(filename)
        return {
            "processing_status": normalize_processing_status(record.get("processing_status")),
            "processing_reason": normalize_processing_text(record.get("processing_reason"), limit=40),
            "processing_error": normalize_processing_text(record.get("processing_error"), limit=240),
            "processing_attempts": normalize_processing_attempts(record.get("processing_attempts")),
            "processing_owner": normalize_processing_text(record.get("processing_owner"), limit=120),
            "processing_batch_id": normalize_processing_text(record.get("processing_batch_id"), limit=120),
            "processing_started_at": normalize_processing_text(record.get("processing_started_at"), limit=40),
        }

    def update_photo_ai_metadata(self, filename: str, payload: Any) -> dict[str, str]:
        normalized_metadata = normalize_photo_ai_metadata(payload)
        
        def apply(data: dict[str, dict[str, Any]]) -> dict[str, str]:
            record = data.get(filename, {})
            for field, value in normalized_metadata.items():
                if value:
                    record[field] = value
                else:
                    record.pop(field, None)
            data[filename] = record
            return normalized_metadata

        self._mutate(apply)
        return normalized_metadata

    def update_photo_processing_info(self, filename: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}

        status = normalize_processing_status(payload.get("processing_status", payload.get("status")))
        reason = normalize_processing_text(payload.get("processing_reason", payload.get("reason")), limit=40)
        error = normalize_processing_text(payload.get("processing_error", payload.get("error")), limit=240)
        attempts = normalize_processing_attempts(payload.get("processing_attempts", payload.get("attempts")))
        owner = normalize_processing_text(payload.get("processing_owner", payload.get("owner")), limit=120)
        batch_id = normalize_processing_text(payload.get("processing_batch_id", payload.get("batch_id")), limit=120)
        started_at = normalize_processing_text(payload.get("processing_started_at", payload.get("started_at")), limit=40)

        def apply(data: dict[str, dict[str, Any]]) -> dict[str, Any]:
            record = data.get(filename, {})

            if status:
                record["processing_status"] = status
            else:
                record.pop("processing_status", None)

            if reason:
                record["processing_reason"] = reason
            else:
                record.pop("processing_reason", None)

            if error:
                record["processing_error"] = error
            else:
                record.pop("processing_error", None)

            if attempts:
                record["processing_attempts"] = attempts
            else:
                record.pop("processing_attempts", None)

            if owner:
                record["processing_owner"] = owner
            else:
                record.pop("processing_owner", None)

            if batch_id:
                record["processing_batch_id"] = batch_id
            else:
                record.pop("processing_batch_id", None)

            if started_at:
                record["processing_started_at"] = started_at
            else:
                record.pop("processing_started_at", None)

            data[filename] = record
            return {
                "processing_status": normalize_processing_status(record.get("processing_status")),
                "processing_reason": normalize_processing_text(record.get("processing_reason"), limit=40),
                "processing_error": normalize_processing_text(record.get("processing_error"), limit=240),
                "processing_attempts": normalize_processing_attempts(record.get("processing_attempts")),
                "processing_owner": normalize_processing_text(record.get("processing_owner"), limit=120),
                "processing_batch_id": normalize_processing_text(record.get("processing_batch_id"), limit=120),
                "processing_started_at": normalize_processing_text(record.get("processing_started_at"), limit=40),
            }

        return self._mutate(apply)

    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        payload = self.load().get(COUNTRY_DESCRIPTIONS_KEY, {})
        if not isinstance(payload, dict):
            return {}

        descriptions: dict[str, dict[str, str]] = {}
        for raw_country, raw_description in payload.items():
            country = (str(raw_country or "")).strip()
            description = normalize_country_intro_payload(raw_description)
            if country and (description["short_description"] or description["long_description"]):
                descriptions[country] = description
        return descriptions

    def get_country_description(self, country: str) -> dict[str, str]:
        return self.list_country_descriptions().get(
            (country or "").strip(),
            {"short_description": "", "long_description": ""},
        )

    def update_country_description(self, country: str, description: Any) -> dict[str, str]:
        normalized_country = normalize_country(country)
        normalized_description = normalize_country_intro_payload(description)
        
        def apply(data: dict[str, dict[str, Any]]) -> dict[str, str]:
            descriptions = data.get(COUNTRY_DESCRIPTIONS_KEY, {})
            if not isinstance(descriptions, dict):
                descriptions = {}

            if normalized_description["short_description"] or normalized_description["long_description"]:
                descriptions[normalized_country] = normalized_description
                data[COUNTRY_DESCRIPTIONS_KEY] = descriptions
            else:
                descriptions.pop(normalized_country, None)
                if descriptions:
                    data[COUNTRY_DESCRIPTIONS_KEY] = descriptions
                else:
                    data.pop(COUNTRY_DESCRIPTIONS_KEY, None)
            return normalized_description

        self._mutate(apply)
        return normalized_description

    def delete_country_description(self, country: str) -> None:
        cleaned_country = (country or "").strip()
        if not cleaned_country:
            return

        def apply(data: dict[str, dict[str, Any]]) -> None:
            descriptions = data.get(COUNTRY_DESCRIPTIONS_KEY, {})
            if not isinstance(descriptions, dict):
                return

            descriptions.pop(cleaned_country, None)
            if descriptions:
                data[COUNTRY_DESCRIPTIONS_KEY] = descriptions
            else:
                data.pop(COUNTRY_DESCRIPTIONS_KEY, None)

        self._mutate(apply)

    def update_info(
        self,
        filename: str,
        *,
        country: str | None = None,
        title: str | None = None,
        title_source: str | None = None,
    ) -> dict[str, Any]:
        updated_record: dict[str, Any] = {}

        def apply(data: dict[str, dict[str, Any]]) -> dict[str, Any]:
            record = data.get(filename, {})
            if country is not None:
                record["country"] = normalize_country(country)
            if title is not None:
                record["title"] = normalize_title(title)
            if title_source is not None:
                normalized_title_source = normalize_title_source(title_source)
                if normalized_title_source:
                    record["title_source"] = normalized_title_source
                else:
                    record.pop("title_source", None)
            data[filename] = record
            return dict(record)

        updated_record = self._mutate(apply)
        return updated_record

    def rename_key(self, old_name: str, new_name: str) -> None:
        if old_name == new_name:
            return

        def apply(data: dict[str, dict[str, Any]]) -> None:
            if old_name not in data:
                return
            data[new_name] = data.pop(old_name)

        self._mutate(apply)

    def delete_info(self, filename: str) -> None:
        def apply(data: dict[str, dict[str, Any]]) -> None:
            if filename not in data:
                return
            data.pop(filename, None)

        self._mutate(apply)

    def set_country(self, filename: str, country: str) -> None:
        self.update_info(filename, country=country)


def normalize_country(country: str | None) -> str:
    cleaned = (country or "").strip()
    if not cleaned:
        raise ValueError("请填写照片拍摄国家。")
    return cleaned.replace("/", "-").replace("\\", "-")[:60]


def normalize_title(title: str | None) -> str:
    return (title or "").strip()[:120]


def normalize_title_source(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in PHOTO_TITLE_SOURCES else ""


def normalize_processing_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in PHOTO_PROCESSING_STATUSES else ""


def normalize_processing_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_processing_attempts(value: Any) -> int:
    try:
        attempts = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, attempts)


def normalize_common_chinese_text(value: Any, *, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    for source, target in COMMON_CHINESE_TRANSLATIONS.items():
        normalized = normalized.replace(source, target)
    return normalized[:limit]


def normalize_country_description(description: Any, *, limit: int = COUNTRY_LONG_DESCRIPTION_LIMIT) -> str:
    return normalize_common_chinese_text(description, limit=limit)


def normalize_country_intro_payload(payload: Any) -> dict[str, str]:
    if isinstance(payload, dict):
        short_description = normalize_country_description(
            payload.get("short_description"),
            limit=COUNTRY_SHORT_DESCRIPTION_LIMIT,
        )
        long_description = normalize_country_description(
            payload.get("long_description"),
            limit=COUNTRY_LONG_DESCRIPTION_LIMIT,
        )
        return {
            "short_description": short_description,
            "long_description": long_description,
        }

    return {
        "short_description": "",
        "long_description": normalize_country_description(
            payload,
            limit=COUNTRY_LONG_DESCRIPTION_LIMIT,
        ),
    }


def normalize_photo_ai_metadata(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        payload = {}
    return {
        field: normalize_common_chinese_text(payload.get(field), limit=PHOTO_AI_METADATA_LIMITS[field])
        for field in PHOTO_AI_METADATA_FIELDS
    }


def default_title(filename: str) -> str:
    return Path(filename).stem


class BasePhotoStorage:
    def list_photos(self) -> list[dict]:
        raise NotImplementedError

    def sync_storage_structure(self) -> dict[str, int]:
        return {"moved": 0}

    def save_photo(self, upload: FileStorage, country: str) -> dict:
        raise NotImplementedError

    def update_photo_info(self, name: str, country: str, title: str, *, title_source: str | None = None) -> dict:
        raise NotImplementedError

    def open_photo(self, name: str) -> tuple[BytesIO, str | None]:
        raise NotImplementedError

    def delete_photo(self, name: str) -> None:
        raise NotImplementedError

    def get_photo_ai_metadata(self, filename: str) -> dict[str, str]:
        return normalize_photo_ai_metadata({})

    def update_photo_ai_metadata(self, filename: str, payload: Any) -> dict[str, str]:
        return normalize_photo_ai_metadata(payload)

    def get_photo_processing_info(self, filename: str) -> dict[str, Any]:
        return {
            "processing_status": "",
            "processing_reason": "",
            "processing_error": "",
            "processing_attempts": 0,
        }

    def update_photo_processing_info(self, filename: str, payload: Any) -> dict[str, Any]:
        return self.get_photo_processing_info(filename)

    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        return {}

    def update_country_description(self, country: str, description: Any) -> dict[str, str]:
        return normalize_country_intro_payload(description)

    def delete_country_description(self, country: str) -> None:
        return None

    def _normalize_filename(self, filename: str) -> str:
        safe_name = secure_filename(filename)
        ext = Path(safe_name).suffix.lower()
        if not safe_name or ext not in ALLOWED_EXTENSIONS:
            raise ValueError("仅支持 jpg、jpeg、png、gif、webp 格式。")
        return f"{uuid.uuid4().hex[:12]}-{safe_name}"


class FileSystemPhotoStorage(BasePhotoStorage):
    def __init__(self, root: Path, metadata_path: Path | None = None):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata = MetadataStore(metadata_path or self.root / "photo-metadata.json")
        self._organize_existing_files()

    def _country_dir(self, country: str) -> Path:
        return self.root / normalize_country(country)

    def _relative_name(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def _resolve_photo_path(self, name: str) -> Path:
        target = (self.root / Path(name)).resolve()
        root_resolved = self.root.resolve()
        if root_resolved not in target.parents and target != root_resolved:
            raise FileNotFoundError(name)
        return target

    def _infer_country_for_path(self, path: Path) -> str:
        relative = path.relative_to(self.root)
        if len(relative.parts) > 1:
            return relative.parts[0]
        return self.metadata.get_optional_country(relative.as_posix()) or UNCATEGORIZED_LABEL

    def _organize_existing_files(self) -> dict[str, int]:
        moved = 0
        for path in list(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path == self.metadata.path or path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            relative_name = self._relative_name(path)
            country = self.metadata.get_optional_country(relative_name) or self._infer_country_for_path(path)
            target_dir = self._country_dir(country)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name
            if target == path:
                self.metadata.update_info(relative_name, country=country)
                continue
            if not target.exists():
                path.rename(target)
                moved += 1
            new_relative = self._relative_name(target)
            self.metadata.rename_key(relative_name, new_relative)
            self.metadata.update_info(new_relative, country=country)
        return {"moved": moved}

    def sync_storage_structure(self) -> dict[str, int]:
        return self._organize_existing_files()

    def list_photos(self) -> list[dict]:
        self.sync_storage_structure()
        photos = []
        for path in sorted(self.root.rglob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path == self.metadata.path or path.suffix.lower() not in ALLOWED_EXTENSIONS or not path.is_file():
                continue
            relative_name = self._relative_name(path)
            stat = path.stat()
            metadata = self.metadata.get_photo_ai_metadata(relative_name)
            processing_info = self.metadata.get_photo_processing_info(relative_name)
            photos.append(
                PhotoRecord(
                    name=relative_name,
                    url=f"/photos/{quote(relative_name, safe='/')}",
                    country=self.metadata.get_optional_country(relative_name) or self._infer_country_for_path(path),
                    title=self.metadata.get_title(relative_name) or default_title(path.name),
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    city=metadata["city"] or None,
                    place=metadata["place"] or None,
                    subject=metadata["subject"] or None,
                    scene_summary=metadata["scene_summary"] or None,
                    processing_status=processing_info["processing_status"] or None,
                    processing_reason=processing_info["processing_reason"] or None,
                    processing_error=processing_info["processing_error"] or None,
                    processing_attempts=processing_info["processing_attempts"],
                    processing_owner=processing_info["processing_owner"] or None,
                    processing_batch_id=processing_info["processing_batch_id"] or None,
                    processing_started_at=processing_info["processing_started_at"] or None,
                    title_source=self.metadata.get_title_source(relative_name) or None,
                ).to_dict()
            )
        return photos

    def save_photo(self, upload: FileStorage, country: str) -> dict:
        filename = self._normalize_filename(upload.filename or "photo")
        normalized_country = normalize_country(country)
        target_dir = self._country_dir(normalized_country)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        upload.save(target)
        relative_name = self._relative_name(target)
        normalized_title = default_title(filename)
        self.metadata.update_info(
            relative_name,
            country=normalized_country,
            title=normalized_title,
            title_source=PHOTO_TITLE_SOURCE_DEFAULT,
        )
        self.metadata.update_photo_processing_info(
            relative_name,
            {
                "processing_status": PHOTO_PROCESSING_STATUS_PENDING,
                "processing_reason": "upload",
                "processing_error": "",
                "processing_attempts": 0,
            },
        )
        stat = target.stat()
        processing_info = self.metadata.get_photo_processing_info(relative_name)
        return PhotoRecord(
            name=relative_name,
            url=f"/photos/{quote(relative_name, safe='/')}",
            country=normalized_country,
            title=normalized_title,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            processing_status=processing_info["processing_status"] or None,
            processing_reason=processing_info["processing_reason"] or None,
            processing_error=processing_info["processing_error"] or None,
            processing_attempts=processing_info["processing_attempts"],
            processing_owner=processing_info["processing_owner"] or None,
            processing_batch_id=processing_info["processing_batch_id"] or None,
            processing_started_at=processing_info["processing_started_at"] or None,
            title_source=self.metadata.get_title_source(relative_name) or None,
        ).to_dict()

    def update_photo_info(self, name: str, country: str, title: str, *, title_source: str | None = None) -> dict:
        safe_name = Path(name).as_posix()
        target = self._resolve_photo_path(safe_name)
        if not target.exists():
            raise FileNotFoundError(name)
        normalized_country = normalize_country(country)
        normalized_title = normalize_title(title) or default_title(target.name)
        current_relative = self._relative_name(target)
        target_dir = self._country_dir(normalized_country)
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / target.name
        if destination != target:
            if not destination.exists():
                target.rename(destination)
            target = destination
        new_relative = self._relative_name(target)
        self.metadata.rename_key(current_relative, new_relative)
        self.metadata.update_info(
            new_relative,
            country=normalized_country,
            title=normalized_title,
            title_source=title_source,
        )
        stat = target.stat()
        processing_info = self.metadata.get_photo_processing_info(new_relative)
        return PhotoRecord(
            name=new_relative,
            url=f"/photos/{quote(new_relative, safe='/')}",
            country=normalized_country,
            title=normalized_title,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            processing_status=processing_info["processing_status"] or None,
            processing_reason=processing_info["processing_reason"] or None,
            processing_error=processing_info["processing_error"] or None,
            processing_attempts=processing_info["processing_attempts"],
            processing_owner=processing_info["processing_owner"] or None,
            processing_batch_id=processing_info["processing_batch_id"] or None,
            processing_started_at=processing_info["processing_started_at"] or None,
            title_source=self.metadata.get_title_source(new_relative) or None,
        ).to_dict()

    def open_photo(self, name: str) -> tuple[BytesIO, str | None]:
        target = self._resolve_photo_path(name)
        if not target.exists():
            raise FileNotFoundError(name)
        return BytesIO(target.read_bytes()), mimetypes.guess_type(target.name)[0]

    def delete_photo(self, name: str) -> None:
        safe_name = Path(name).as_posix()
        target = self._resolve_photo_path(safe_name)
        if not target.exists():
            raise FileNotFoundError(name)
        relative_name = self._relative_name(target)
        target.unlink()
        self.metadata.delete_info(relative_name)

        parent = target.parent
        root_resolved = self.root.resolve()
        while parent.resolve() != root_resolved:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def get_photo_ai_metadata(self, filename: str) -> dict[str, str]:
        return self.metadata.get_photo_ai_metadata(Path(filename).as_posix())

    def update_photo_ai_metadata(self, filename: str, payload: Any) -> dict[str, str]:
        return self.metadata.update_photo_ai_metadata(Path(filename).as_posix(), payload)

    def get_photo_processing_info(self, filename: str) -> dict[str, Any]:
        return self.metadata.get_photo_processing_info(Path(filename).as_posix())

    def update_photo_processing_info(self, filename: str, payload: Any) -> dict[str, Any]:
        return self.metadata.update_photo_processing_info(Path(filename).as_posix(), payload)

    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        return self.metadata.list_country_descriptions()

    def update_country_description(self, country: str, description: Any) -> dict[str, str]:
        return self.metadata.update_country_description(country, description)

    def delete_country_description(self, country: str) -> None:
        self.metadata.delete_country_description(country)


class LocalPhotoStorage(FileSystemPhotoStorage):
    def __init__(self, project_root: Path):
        super().__init__(project_root / "uploads")


class ICloudPhotoStorage(FileSystemPhotoStorage):
    def __init__(self, root: Path):
        super().__init__(root)


class WebDAVMetadataStore(MetadataStore):
    def __init__(self, session: requests.Session, file_url: str, timeout: int, cache_ttl_seconds: float = 2.0):
        self.session = session
        self.file_url = file_url
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, dict[str, Any]] | None = None
        self._cache_loaded_at = 0.0

    def load(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None and (time.time() - self._cache_loaded_at) < self.cache_ttl_seconds:
            return self._cache

        response = self.session.get(self.file_url, timeout=self.timeout)
        if response.status_code == 404:
            data: dict[str, dict[str, Any]] = {}
        else:
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            data = payload if isinstance(payload, dict) else {}

        self._cache = data
        self._cache_loaded_at = time.time()
        return data

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        response = self.session.put(
            self.file_url,
            data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        self._cache = data
        self._cache_loaded_at = time.time()


class WebDAVPhotoStorage(BasePhotoStorage):
    def __init__(self, base_url: str, username: str, password: str, remote_dir: str, metadata_path: Path, metadata_remote_name: str):
        self.base_url = base_url.rstrip("/") + "/"
        self.remote_dir = remote_dir.strip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.timeout = 30
        self._ensure_collection()
        self.local_metadata_path = metadata_path
        self.metadata = WebDAVMetadataStore(
            self.session,
            self._file_url(metadata_remote_name),
            self.timeout,
            cache_ttl_seconds=float(os.getenv("WEBDAV_METADATA_CACHE_SECONDS", "2") or "2"),
        )
        self._migrate_local_metadata_if_needed()

    def _folder_url(self) -> str:
        if not self.remote_dir:
            return self.base_url
        return urljoin(self.base_url, quote(self.remote_dir) + "/")

    def _file_url(self, name: str) -> str:
        parts = [segment for segment in [self.remote_dir, name] if segment]
        relative = "/".join(quote(segment) for segment in parts)
        return urljoin(self.base_url, relative)

    def _ensure_collection(self) -> None:
        if not self.remote_dir:
            return

        current = ""
        for segment in self.remote_dir.split("/"):
            current = posixpath.join(current, segment) if current else segment
            url = urljoin(self.base_url, quote(current) + "/")
            response = self.session.request("MKCOL", url, timeout=self.timeout)
            if response.status_code not in (201, 405):
                response.raise_for_status()

    def _migrate_local_metadata_if_needed(self) -> None:
        if not self.local_metadata_path.exists():
            return

        remote_data = self.metadata.load()
        if remote_data:
            return

        try:
            local_data = json.loads(self.local_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if isinstance(local_data, dict) and local_data:
            self.metadata.save(local_data)

    def list_photos(self) -> list[dict]:
        headers = {"Depth": "1"}
        response = self.session.request("PROPFIND", self._folder_url(), headers=headers, timeout=self.timeout)
        response.raise_for_status()

        ns = {"d": "DAV:"}
        root = ET.fromstring(response.text)
        photos = []

        for item in root.findall("d:response", ns):
            href = item.findtext("d:href", default="", namespaces=ns)
            filename = Path(href.rstrip("/")).name
            if not filename:
                continue

            propstat = item.find("d:propstat", ns)
            if propstat is None:
                continue
            prop = propstat.find("d:prop", ns)
            if prop is None:
                continue

            resource_type = prop.find("d:resourcetype", ns)
            if resource_type is not None and resource_type.find("d:collection", ns) is not None:
                continue
            if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
                continue

            size_text = prop.findtext("d:getcontentlength", default=None, namespaces=ns)
            modified_text = prop.findtext("d:getlastmodified", default=None, namespaces=ns)
            modified_at = None
            if modified_text:
                try:
                    modified_at = parsedate_to_datetime(modified_text).isoformat(timespec="seconds")
                except (TypeError, ValueError, IndexError):
                    modified_at = modified_text
            metadata = self.metadata.get_photo_ai_metadata(filename)
            processing_info = self.metadata.get_photo_processing_info(filename)

            photos.append(
                PhotoRecord(
                    name=filename,
                    url=f"/photos/{quote(filename)}",
                    country=self.metadata.get_country(filename),
                    title=self.metadata.get_title(filename) or default_title(filename),
                    size=int(size_text) if size_text and size_text.isdigit() else None,
                    modified_at=modified_at,
                    city=metadata["city"] or None,
                    place=metadata["place"] or None,
                    subject=metadata["subject"] or None,
                    scene_summary=metadata["scene_summary"] or None,
                    processing_status=processing_info["processing_status"] or None,
                    processing_reason=processing_info["processing_reason"] or None,
                    processing_error=processing_info["processing_error"] or None,
                    processing_attempts=processing_info["processing_attempts"],
                    title_source=self.metadata.get_title_source(filename) or None,
                ).to_dict()
            )

        photos.sort(key=lambda item: item.get("modified_at") or "", reverse=True)
        return photos

    def save_photo(self, upload: FileStorage, country: str) -> dict:
        filename = self._normalize_filename(upload.filename or "photo")
        normalized_country = normalize_country(country)
        normalized_title = default_title(filename)
        content = upload.stream.read()
        content_type = upload.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        response = self.session.put(
            self._file_url(filename),
            data=content,
            headers={"Content-Type": content_type},
            timeout=self.timeout,
        )
        response.raise_for_status()
        self.metadata.update_info(
            filename,
            country=normalized_country,
            title=normalized_title,
            title_source=PHOTO_TITLE_SOURCE_DEFAULT,
        )
        self.metadata.update_photo_processing_info(
            filename,
            {
                "processing_status": PHOTO_PROCESSING_STATUS_PENDING,
                "processing_reason": "upload",
                "processing_error": "",
                "processing_attempts": 0,
            },
        )
        processing_info = self.metadata.get_photo_processing_info(filename)

        return PhotoRecord(
            name=filename,
            url=f"/photos/{quote(filename)}",
            country=normalized_country,
            title=normalized_title,
            size=len(content),
            modified_at=datetime.utcnow().isoformat(timespec="seconds"),
            processing_status=processing_info["processing_status"] or None,
            processing_reason=processing_info["processing_reason"] or None,
            processing_error=processing_info["processing_error"] or None,
            processing_attempts=processing_info["processing_attempts"],
            title_source=self.metadata.get_title_source(filename) or None,
        ).to_dict()

    def update_photo_info(self, name: str, country: str, title: str, *, title_source: str | None = None) -> dict:
        safe_name = Path(name).name
        normalized_country = normalize_country(country)
        normalized_title = normalize_title(title) or default_title(safe_name)
        self.metadata.update_info(
            safe_name,
            country=normalized_country,
            title=normalized_title,
            title_source=title_source,
        )
        response = self.session.request("PROPFIND", self._file_url(safe_name), headers={"Depth": "0"}, timeout=self.timeout)
        if response.status_code == 404:
            raise FileNotFoundError(safe_name)
        response.raise_for_status()
        modified_at = datetime.utcnow().isoformat(timespec="seconds")
        size = None
        ns = {"d": "DAV:"}
        root = ET.fromstring(response.text)
        item = root.find("d:response", ns)
        if item is not None:
            prop = item.find("d:propstat/d:prop", ns)
            if prop is not None:
                size_text = prop.findtext("d:getcontentlength", default=None, namespaces=ns)
                modified_text = prop.findtext("d:getlastmodified", default=None, namespaces=ns)
                size = int(size_text) if size_text and size_text.isdigit() else None
                if modified_text:
                    try:
                        modified_at = parsedate_to_datetime(modified_text).isoformat(timespec="seconds")
                    except (TypeError, ValueError, IndexError):
                        modified_at = modified_text
        return PhotoRecord(
            name=safe_name,
            url=f"/photos/{quote(safe_name)}",
            country=normalized_country,
            title=normalized_title,
            size=size,
            modified_at=modified_at,
            processing_status=self.metadata.get_photo_processing_info(safe_name)["processing_status"] or None,
            processing_reason=self.metadata.get_photo_processing_info(safe_name)["processing_reason"] or None,
            processing_error=self.metadata.get_photo_processing_info(safe_name)["processing_error"] or None,
            processing_attempts=self.metadata.get_photo_processing_info(safe_name)["processing_attempts"],
            title_source=self.metadata.get_title_source(safe_name) or None,
        ).to_dict()

    def open_photo(self, name: str) -> tuple[BytesIO, str | None]:
        safe_name = Path(name).name
        response = self.session.get(self._file_url(safe_name), timeout=self.timeout)
        if response.status_code == 404:
            raise FileNotFoundError(safe_name)
        response.raise_for_status()
        return BytesIO(response.content), response.headers.get("Content-Type")

    def delete_photo(self, name: str) -> None:
        safe_name = Path(name).name
        response = self.session.delete(self._file_url(safe_name), timeout=self.timeout)
        if response.status_code == 404:
            raise FileNotFoundError(safe_name)
        response.raise_for_status()
        self.metadata.delete_info(safe_name)

    def get_photo_ai_metadata(self, filename: str) -> dict[str, str]:
        return self.metadata.get_photo_ai_metadata(Path(filename).name)

    def update_photo_ai_metadata(self, filename: str, payload: Any) -> dict[str, str]:
        return self.metadata.update_photo_ai_metadata(Path(filename).name, payload)

    def get_photo_processing_info(self, filename: str) -> dict[str, Any]:
        return self.metadata.get_photo_processing_info(Path(filename).name)

    def update_photo_processing_info(self, filename: str, payload: Any) -> dict[str, Any]:
        return self.metadata.update_photo_processing_info(Path(filename).name, payload)

    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        return self.metadata.list_country_descriptions()

    def update_country_description(self, country: str, description: Any) -> dict[str, str]:
        return self.metadata.update_country_description(country, description)

    def delete_country_description(self, country: str) -> None:
        self.metadata.delete_country_description(country)


def resolve_storage_runtime_info(project_root: Path) -> dict[str, str]:
    project_root = project_root.expanduser().resolve()
    provider = os.getenv("PHOTO_STORAGE", "local").lower().strip() or "local"
    if provider == "webdav":
        base_url = os.getenv("WEBDAV_BASE_URL", "").strip()
        remote_dir = os.getenv("WEBDAV_REMOTE_DIR", "photo-wall").strip()
        metadata_remote_name = os.getenv("WEBDAV_METADATA_REMOTE_NAME", ".photo-metadata.json").strip() or ".photo-metadata.json"
        remote_root = urljoin(base_url.rstrip("/") + "/", remote_dir.strip("/") + "/") if base_url else remote_dir
        return {
            "provider": provider,
            "root": remote_root,
            "metadata_path": str((project_root / ".webdav-photo-metadata.json").resolve()),
            "metadata_remote_name": metadata_remote_name,
        }

    if provider == "icloud":
        default_dir = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/web图库"
        root = Path(os.path.expanduser(os.getenv("ICLOUD_PHOTO_DIR", str(default_dir)))).expanduser().resolve()
    else:
        root = (project_root / "uploads").resolve()

    return {
        "provider": provider,
        "root": str(root),
        "metadata_path": str((root / "photo-metadata.json").resolve()),
    }


def create_storage(project_root: Path) -> BasePhotoStorage:
    project_root = project_root.expanduser().resolve()
    runtime = resolve_storage_runtime_info(project_root)
    provider = runtime["provider"]
    if provider == "webdav":
        base_url = os.getenv("WEBDAV_BASE_URL", "").strip()
        username = os.getenv("WEBDAV_USERNAME", "").strip()
        password = os.getenv("WEBDAV_PASSWORD", "").strip()
        remote_dir = os.getenv("WEBDAV_REMOTE_DIR", "photo-wall").strip()
        metadata_remote_name = runtime["metadata_remote_name"]
        if not all([base_url, username, password]):
            raise RuntimeError(
                "WEBDAV_BASE_URL、WEBDAV_USERNAME 和 WEBDAV_PASSWORD 在 PHOTO_STORAGE=webdav 时必须填写。"
            )
        return WebDAVPhotoStorage(
            base_url,
            username,
            password,
            remote_dir,
            Path(runtime["metadata_path"]),
            metadata_remote_name,
        )
    if provider == "icloud":
        return ICloudPhotoStorage(Path(runtime["root"]))
    return LocalPhotoStorage(project_root)
