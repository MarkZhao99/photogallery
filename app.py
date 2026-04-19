from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
import secrets
import uuid
from datetime import datetime
from functools import lru_cache, wraps
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from country_descriptions import CountryDescriptionError, CountryPhotoSample
from storage import (
    PHOTO_PROCESSING_STATUS_DONE,
    PHOTO_PROCESSING_STATUS_PENDING,
    PHOTO_PROCESSING_STATUS_PROCESSING,
    PHOTO_PROCESSING_STATUS_REVIEW,
    PHOTO_TITLE_SOURCE_DEFAULT,
    PHOTO_TITLE_SOURCE_GENERATED,
    PHOTO_TITLE_SOURCE_MANUAL,
    create_storage,
    normalize_country_intro_payload,
    normalize_photo_ai_metadata,
)

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - Pillow is installed in this project
    Image = None
    ImageOps = None

PROJECT_ROOT = Path(__file__).resolve().parent


def load_simple_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def default_country_short_description(country: str, photo_count: int) -> str:
    if country == "未分类":
        return f"这组 {photo_count} 幅影像暂未细分国家，先以开放章节方式陈列。"
    return f"{country} 章节现收录 {photo_count} 幅影像，地点线索将随新作继续修订。"


def default_country_long_description(country: str, photo_count: int) -> str:
    if country == "未分类":
        return f"导览文字稍后补充。当前这一章节暂时收录了 {photo_count} 幅尚未细分国家的影像，后续整理后会补入更完整的地点与风景说明。"
    return f"导览文字稍后补充。当前章节已收录 {photo_count} 幅来自 {country} 的影像，后续在作品更新或手动刷新后会同步补全更完整的章节前言。"


def normalize_country_intro_descriptions(
    descriptions: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, str]]:
    normalized_descriptions: dict[str, dict[str, str]] = {}
    for raw_country, raw_description in (descriptions or {}).items():
        country = str(raw_country or "").strip()
        if not country:
            continue
        intro = normalize_country_intro_payload(raw_description)
        if intro["short_description"] or intro["long_description"]:
            normalized_descriptions[country] = intro
    return normalized_descriptions


def group_photos_by_country(photos: list[dict], descriptions: Optional[dict[str, Any]] = None) -> list[dict]:
    normalized_descriptions = normalize_country_intro_descriptions(descriptions)
    grouped: dict[str, list[dict]] = {}
    for photo in photos:
        country = photo.get("country") or "未分类"
        grouped.setdefault(country, []).append(photo)

    groups = []
    for country, items in grouped.items():
        intro = normalized_descriptions.get(country, {"short_description": "", "long_description": ""})
        short_description = intro["short_description"] or default_country_short_description(country, len(items))
        long_description = intro["long_description"] or default_country_long_description(country, len(items))
        groups.append(
            {
                "country": country,
                "count": len(items),
                "description": short_description,
                "short_description": short_description,
                "long_description": long_description,
                "photos": items,
            }
        )
    groups.sort(key=lambda group: (group["country"] == "未分类", group["country"]))
    return groups


COLLAGE_STANDARD_SLOT = "collage-tile-standard"
COLLAGE_WIDE_SLOT = "collage-tile-wide"
COLLAGE_TALL_SLOT = "collage-tile-tall"
COLLAGE_COLUMNS = 4
COLLAGE_LOOKAHEAD = 3


def normalize_layout_ratio(value: Any) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    if ratio <= 0:
        return 0.0
    return round(ratio, 4)


def collage_slot_dimensions(slot: str) -> tuple[int, int]:
    if slot == COLLAGE_WIDE_SLOT:
        return (2, 1)
    if slot == COLLAGE_TALL_SLOT:
        return (1, 2)
    return (1, 1)


def collage_slot_target_ratio(slot: str) -> float:
    if slot == COLLAGE_WIDE_SLOT:
        return 2.0
    if slot == COLLAGE_TALL_SLOT:
        return 0.5
    return 1.0


def collage_slot_candidates(photo: dict) -> list[str]:
    orientation = normalize_layout_orientation(photo.get("layout_orientation"))
    ratio = normalize_layout_ratio(photo.get("layout_ratio"))

    if orientation == "landscape" and ratio >= 1.35:
        return [COLLAGE_WIDE_SLOT, COLLAGE_STANDARD_SLOT]
    if orientation == "portrait" and ratio <= 0.8:
        return [COLLAGE_TALL_SLOT, COLLAGE_STANDARD_SLOT]
    return [COLLAGE_STANDARD_SLOT]


def clone_collage_grid(occupied: list[list[bool]]) -> list[list[bool]]:
    return [row[:] for row in occupied]


def find_first_collage_fit(occupied: list[list[bool]], width: int, height: int, columns: int = COLLAGE_COLUMNS) -> tuple[int, int]:
    row = 0
    while True:
        while len(occupied) < row + height:
            occupied.append([False] * columns)
        for column in range(columns - width + 1):
            fits = True
            for row_index in range(row, row + height):
                for column_index in range(column, column + width):
                    if occupied[row_index][column_index]:
                        fits = False
                        break
                if not fits:
                    break
            if fits:
                return row, column
        row += 1


def place_collage_slot(occupied: list[list[bool]], slot: str, columns: int = COLLAGE_COLUMNS) -> list[list[bool]]:
    width, height = collage_slot_dimensions(slot)
    next_grid = clone_collage_grid(occupied)
    row, column = find_first_collage_fit(next_grid, width, height, columns)
    for row_index in range(row, row + height):
        while len(next_grid) <= row_index:
            next_grid.append([False] * columns)
        for column_index in range(column, column + width):
            next_grid[row_index][column_index] = True
    return next_grid


def collage_column_heights(occupied: list[list[bool]], columns: int = COLLAGE_COLUMNS) -> list[int]:
    heights: list[int] = []
    for column in range(columns):
        max_height = 0
        for row_index, row in enumerate(occupied):
            if row[column]:
                max_height = row_index + 1
        heights.append(max_height)
    return heights


def collage_layout_score(occupied: list[list[bool]], photo: dict, slot: str, columns: int = COLLAGE_COLUMNS) -> float:
    heights = collage_column_heights(occupied, columns)
    max_height = max(heights) if heights else 0
    whitespace = sum(max_height - height for height in heights)
    roughness = sum(abs(left - right) for left, right in zip(heights, heights[1:]))
    ratio = normalize_layout_ratio(photo.get("layout_ratio")) or collage_slot_target_ratio(slot)
    crop_penalty = abs(ratio - collage_slot_target_ratio(slot))
    large_tile_penalty = 0.15 if slot != COLLAGE_STANDARD_SLOT else 0.0
    return whitespace * 25 + roughness * 18 + max_height * 8 + crop_penalty * 30 + large_tile_penalty * 10


def search_best_collage_sequence(
    occupied: list[list[bool]],
    photos: list[dict],
    start_index: int,
    *,
    depth: int = COLLAGE_LOOKAHEAD,
    columns: int = COLLAGE_COLUMNS,
) -> tuple[float, list[str]]:
    if start_index >= len(photos) or depth <= 0:
        return 0.0, []

    best_score: Optional[float] = None
    best_sequence: list[str] = []

    for slot in collage_slot_candidates(photos[start_index]):
        next_grid = place_collage_slot(occupied, slot, columns)
        score = collage_layout_score(next_grid, photos[start_index], slot, columns)
        if depth > 1 and start_index + 1 < len(photos):
            next_score, next_sequence = search_best_collage_sequence(
                next_grid,
                photos,
                start_index + 1,
                depth=depth - 1,
                columns=columns,
            )
            score += next_score * 0.7
        else:
            next_sequence = []

        if best_score is None or score < best_score:
            best_score = score
            best_sequence = [slot, *next_sequence]

    return best_score or 0.0, best_sequence


def assign_collage_slots(photos: list[dict], columns: int = COLLAGE_COLUMNS) -> list[dict]:
    occupied: list[list[bool]] = []
    assigned: list[dict] = []

    for index, photo in enumerate(photos):
        _, best_sequence = search_best_collage_sequence(
            occupied,
            photos,
            index,
            depth=min(COLLAGE_LOOKAHEAD, len(photos) - index),
            columns=columns,
        )
        slot = best_sequence[0] if best_sequence else COLLAGE_STANDARD_SLOT
        occupied = place_collage_slot(occupied, slot, columns)
        record = dict(photo)
        record["collage_slot"] = slot
        assigned.append(record)

    return assigned


def admin_username() -> str:
    return os.getenv("ADMIN_USERNAME", "zxxk").strip() or "zxxk"


def admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "").strip()


def public_site_only() -> bool:
    return os.getenv("PUBLIC_SITE_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def server_host() -> str:
    return os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"


def server_port() -> int:
    return int(os.getenv("PORT", "5001"))


def debug_enabled() -> bool:
    return os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def current_password_signature() -> str:
    password = admin_password()
    if not password:
        return ""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def is_admin_authenticated() -> bool:
    signature = current_password_signature()
    return (
        bool(signature)
        and session.get("admin_authenticated") is True
        and session.get("admin_password_sig") == signature
        and session.get("admin_username") == admin_username()
    )


def normalize_next_url(target: Optional[str]) -> str:
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("admin_dashboard")
    return target


def admin_required(api: bool = False):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if public_site_only():
                abort(404)

            if is_admin_authenticated():
                return view_func(*args, **kwargs)

            if api:
                return jsonify({"error": "请先登录后台管理页。", "login_url": url_for("admin_login")}), 401

            next_url = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
            return redirect(url_for("admin_login", next=normalize_next_url(next_url)))

        return wrapped

    return decorator


def normalize_countries(countries: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_country in countries:
        country = str(raw_country or "").strip()
        if not country or country in seen:
            continue
        seen.add(country)
        normalized.append(country)
    return normalized


PHOTO_AI_METADATA_FIELDS = ("city", "place", "subject", "scene_summary")
DEFAULT_COUNTRY_PREVIEW_LIMIT = 4
MAX_METADATA_BATCH_SIZE = 5
DEFAULT_AUTO_METADATA_MAX_ATTEMPTS = 3
DEFAULT_AUTO_METADATA_PROCESSING_TIMEOUT_SECONDS = 15 * 60
MANUAL_AI_WORKFLOW_MESSAGE = (
    "当前实现不再自动调用 groq 和 gemini。"
    "需要 AI 的步骤只通过当前对话里的模型分 5 张一批处理，再把结果回写到图库元数据。"
)


class ManualWorkflowDescriber:
    def is_enabled(self) -> bool:
        return False

    def availability_message(self) -> str:
        return MANUAL_AI_WORKFLOW_MESSAGE

    def describe_photo_metadata(self, country: str, photo: CountryPhotoSample) -> dict[str, str]:
        raise CountryDescriptionError(MANUAL_AI_WORKFLOW_MESSAGE)

    def describe_country_from_metadata(
        self,
        country: str,
        photo_metadata_list: list[dict[str, Any]],
        *,
        previous_short_description: str = "",
        previous_long_description: str = "",
    ) -> dict[str, str]:
        raise CountryDescriptionError(MANUAL_AI_WORKFLOW_MESSAGE)


def country_preview_limit() -> int:
    try:
        return max(1, int(os.getenv("COUNTRY_PREVIEW_LIMIT", str(DEFAULT_COUNTRY_PREVIEW_LIMIT)) or str(DEFAULT_COUNTRY_PREVIEW_LIMIT)))
    except ValueError:
        return DEFAULT_COUNTRY_PREVIEW_LIMIT


def photo_metadata_richness(photo: dict) -> int:
    return sum(1 for field in PHOTO_AI_METADATA_FIELDS if str(photo.get(field) or "").strip())


def photo_metadata_complete(photo: dict) -> bool:
    return all(str(photo.get(field) or "").strip() for field in PHOTO_AI_METADATA_FIELDS)


def photo_diversity_key(photo: dict) -> str:
    for prefix, field in (("city", "city"), ("place", "place"), ("subject", "subject"), ("title", "title"), ("name", "name")):
        value = str(photo.get(field) or "").strip()
        if value:
            return f"{prefix}:{value}"
    return ""


def photo_curator_sort_key(photo: dict) -> tuple[int, str, int, str]:
    return (
        photo_metadata_richness(photo),
        str(photo.get("modified_at") or ""),
        int(photo.get("size") or 0),
        str(photo.get("name") or ""),
    )


def metadata_batch_limit(limit: int | None = None) -> int:
    try:
        normalized_limit = int(limit or MAX_METADATA_BATCH_SIZE)
    except (TypeError, ValueError):
        normalized_limit = MAX_METADATA_BATCH_SIZE
    return max(1, min(MAX_METADATA_BATCH_SIZE, normalized_limit))


def empty_description_update_result(message: str = "") -> dict[str, list[dict] | bool | str]:
    return {
        "enabled": False,
        "message": message or MANUAL_AI_WORKFLOW_MESSAGE,
        "updated": [],
        "deleted": [],
        "failed": [],
    }


def manual_country_review_message(countries: Iterable[str] | None = None) -> str:
    normalized_countries = normalize_countries(countries or [])
    if not normalized_countries:
        return MANUAL_AI_WORKFLOW_MESSAGE
    return (
        f"{MANUAL_AI_WORKFLOW_MESSAGE}"
        f" 当前待当前对话处理的国家：{'、'.join(normalized_countries)}。"
    )


def auto_metadata_queue_message(countries: Iterable[str] | None = None) -> str:
    normalized_countries = normalize_countries(countries or [])
    suffix = f"：{'、'.join(normalized_countries)}" if normalized_countries else ""
    return f"已加入自动识别队列{suffix}。系统会异步补全图片元数据、生成标题，并在结果稳定后更新国家介绍。"


def auto_metadata_max_attempts() -> int:
    try:
        value = int(os.getenv("AUTO_METADATA_MAX_ATTEMPTS", str(DEFAULT_AUTO_METADATA_MAX_ATTEMPTS)))
    except ValueError:
        value = DEFAULT_AUTO_METADATA_MAX_ATTEMPTS
    return max(1, value)


def auto_metadata_processing_timeout_seconds() -> int:
    try:
        value = int(
            os.getenv(
                "AUTO_METADATA_PROCESSING_TIMEOUT_SECONDS",
                str(DEFAULT_AUTO_METADATA_PROCESSING_TIMEOUT_SECONDS),
            )
        )
    except ValueError:
        value = DEFAULT_AUTO_METADATA_PROCESSING_TIMEOUT_SECONDS
    return max(60, value)


def now_isoformat() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def metadata_store():
    return getattr(storage, "metadata", None)


def build_auto_metadata_status_summary(photos: list[dict]) -> dict[str, Any]:
    pending = [photo for photo in photos if str(photo.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_PENDING]
    processing = [photo for photo in photos if str(photo.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_PROCESSING]
    review = [photo for photo in photos if str(photo.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_REVIEW]
    done = [photo for photo in photos if str(photo.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_DONE]

    errored = sorted(
        [photo for photo in photos if str(photo.get("processing_error") or "").strip()],
        key=lambda photo: (
            str(photo.get("processing_started_at") or ""),
            str(photo.get("modified_at") or ""),
            str(photo.get("name") or ""),
        ),
        reverse=True,
    )
    latest_activity = sorted(
        [
            str(photo.get("processing_started_at") or "").strip() or str(photo.get("modified_at") or "").strip()
            for photo in photos
            if str(photo.get("processing_started_at") or "").strip() or str(photo.get("modified_at") or "").strip()
        ],
        reverse=True,
    )

    return {
        "pending_count": len(pending),
        "processing_count": len(processing),
        "review_count": len(review),
        "done_count": len(done),
        "processing_countries": sorted({str(photo.get("country") or "").strip() for photo in processing if str(photo.get("country") or "").strip()}),
        "last_error": str((errored[0].get("processing_error") if errored else "") or "").strip(),
        "last_activity_at": latest_activity[0] if latest_activity else "",
    }


def build_generated_photo_title(photo: dict) -> str:
    for field in ("place", "city"):
        value = str(photo.get(field) or "").strip()
        if value:
            return value[:120]
    fallback = str(photo.get("title") or "").strip()
    if fallback:
        return fallback[:120]
    return Path(str(photo.get("name") or "photo")).stem[:120]


def resolve_city_from_place(place: str, *, country: str, photos: list[dict], exclude_name: str = "") -> str:
    normalized_place = str(place or "").strip()
    normalized_country = str(country or "").strip()
    if not normalized_place or not normalized_country:
        return ""

    known_places: dict[str, str] = {}
    known_cities: list[str] = []
    for photo in photos:
        if str(photo.get("country") or "").strip() != normalized_country:
            continue
        if str(photo.get("name") or "") == exclude_name:
            continue
        city = str(photo.get("city") or "").strip()
        place_name = str(photo.get("place") or "").strip()
        if city and city not in known_cities:
            known_cities.append(city)
        if city and place_name and place_name not in known_places:
            known_places[place_name] = city

    if normalized_place in known_places:
        return known_places[normalized_place]

    for city in known_cities:
        if city == normalized_place or city in normalized_place:
            return city

    for place_name, city in known_places.items():
        if normalized_place in place_name or place_name in normalized_place:
            return city

    return ""


def select_pending_photo_batch(photos: list[dict], limit: int = MAX_METADATA_BATCH_SIZE) -> list[dict]:
    pending = [
        photo
        for photo in photos
        if str(photo.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_PENDING
    ]
    if not pending:
        return []
    target_country = str(pending[0].get("country") or "").strip()
    return [photo for photo in pending if str(photo.get("country") or "").strip() == target_country][:metadata_batch_limit(limit)]


def absolute_photo_path(photo_name: str) -> str:
    resolver = getattr(storage, "_resolve_photo_path", None)
    if callable(resolver):
        try:
            return str(resolver(photo_name))
        except Exception:
            return ""
    return ""


def build_pending_review_batch(limit: int = MAX_METADATA_BATCH_SIZE) -> dict[str, Any]:
    photos = load_photos()
    batch = select_pending_photo_batch(photos, limit=limit)
    if not batch:
        return {
            "country": "",
            "photos": [],
            "photo_count": 0,
            "country_description": {"short_description": "", "long_description": ""},
            "workflow_message": MANUAL_AI_WORKFLOW_MESSAGE,
            "apply_command": "python3 scripts/process_gallery_metadata.py apply-batch --input <json-file>",
        }

    country = str(batch[0].get("country") or "").strip()
    descriptions = normalize_country_intro_descriptions(storage.list_country_descriptions())
    return {
        "country": country,
        "photo_count": len(batch),
        "photos": [
            {
                "name": str(photo.get("name") or ""),
                "country": str(photo.get("country") or ""),
                "title": str(photo.get("title") or ""),
                "city": str(photo.get("city") or ""),
                "place": str(photo.get("place") or ""),
                "subject": str(photo.get("subject") or ""),
                "scene_summary": str(photo.get("scene_summary") or ""),
                "processing_status": str(photo.get("processing_status") or ""),
                "title_source": str(photo.get("title_source") or ""),
                "absolute_path": absolute_photo_path(str(photo.get("name") or "")),
            }
            for photo in batch
        ],
        "country_description": descriptions.get(country, {"short_description": "", "long_description": ""}),
        "workflow_message": manual_country_review_message([country]),
        "apply_command": "python3 scripts/process_gallery_metadata.py apply-batch --input <json-file>",
    }


def empty_claimed_review_batch() -> dict[str, Any]:
    return {
        "batch_id": "",
        "owner": "",
        "country": "",
        "photos": [],
        "photo_count": 0,
        "country_description": {"short_description": "", "long_description": ""},
    }


def build_claimed_batch_payload(
    *,
    batch_id: str,
    owner: str,
    photo_names: list[str],
) -> dict[str, Any]:
    if not photo_names:
        return empty_claimed_review_batch()

    photos = load_photos()
    descriptions = normalize_country_intro_descriptions(storage.list_country_descriptions())
    photo_index = {str(photo.get("name") or ""): photo for photo in photos}
    claimed_photos = [photo_index[name] for name in photo_names if name in photo_index]
    if not claimed_photos:
        return empty_claimed_review_batch()
    country = str(claimed_photos[0].get("country") or "").strip()
    return {
        "batch_id": batch_id,
        "owner": owner,
        "country": country,
        "photo_count": len(claimed_photos),
        "photos": [
            {
                "name": str(photo.get("name") or ""),
                "country": str(photo.get("country") or ""),
                "title": str(photo.get("title") or ""),
                "city": str(photo.get("city") or ""),
                "place": str(photo.get("place") or ""),
                "subject": str(photo.get("subject") or ""),
                "scene_summary": str(photo.get("scene_summary") or ""),
                "processing_status": str(photo.get("processing_status") or ""),
                "title_source": str(photo.get("title_source") or ""),
                "absolute_path": absolute_photo_path(str(photo.get("name") or "")),
            }
            for photo in claimed_photos
        ],
        "country_description": descriptions.get(country, {"short_description": "", "long_description": ""}),
    }


def claim_pending_review_batch(limit: int = MAX_METADATA_BATCH_SIZE, owner: str = "") -> dict[str, Any]:
    batch = select_pending_photo_batch(load_photos(), limit=limit)
    if not batch:
        return empty_claimed_review_batch()

    target_names = [str(photo.get("name") or "") for photo in batch]
    batch_id = uuid.uuid4().hex
    claim_owner = str(owner or "auto-worker").strip() or "auto-worker"
    claimed_at = now_isoformat()

    store = metadata_store()
    claimed_names: list[str] = []
    if store is not None and hasattr(store, "_mutate"):
        def apply(data: dict[str, dict[str, Any]]) -> list[str]:
            names: list[str] = []
            for name in target_names:
                record = data.get(name)
                if not isinstance(record, dict):
                    continue
                if str(record.get("processing_status") or "").strip() != PHOTO_PROCESSING_STATUS_PENDING:
                    continue
                attempts = int(record.get("processing_attempts") or 0)
                record["processing_status"] = PHOTO_PROCESSING_STATUS_PROCESSING
                record["processing_reason"] = "auto_worker"
                record["processing_error"] = ""
                record["processing_attempts"] = attempts + 1
                record["processing_owner"] = claim_owner
                record["processing_batch_id"] = batch_id
                record["processing_started_at"] = claimed_at
                data[name] = record
                names.append(name)
            return names

        claimed_names = list(store._mutate(apply))
    else:
        for name in target_names:
            current = storage.get_photo_processing_info(name)
            if str(current.get("processing_status") or "").strip() != PHOTO_PROCESSING_STATUS_PENDING:
                continue
            updated = storage.update_photo_processing_info(
                name,
                {
                    "processing_status": PHOTO_PROCESSING_STATUS_PROCESSING,
                    "processing_reason": "auto_worker",
                    "processing_error": "",
                    "processing_attempts": int(current.get("processing_attempts") or 0) + 1,
                    "processing_owner": claim_owner,
                    "processing_batch_id": batch_id,
                    "processing_started_at": claimed_at,
                },
            )
            if str(updated.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_PROCESSING:
                claimed_names.append(name)

    return build_claimed_batch_payload(batch_id=batch_id, owner=claim_owner, photo_names=claimed_names)


def processing_batch_photo_names(batch_id: str) -> list[str]:
    normalized_batch_id = str(batch_id or "").strip()
    if not normalized_batch_id:
        return []
    store = metadata_store()
    if store is None or not hasattr(store, "load"):
        return []
    data = store.load()
    names: list[str] = []
    for name, record in data.items():
        if name == "__country_descriptions__" or not isinstance(record, dict):
            continue
        if str(record.get("processing_batch_id") or "").strip() != normalized_batch_id:
            continue
        if str(record.get("processing_status") or "").strip() != PHOTO_PROCESSING_STATUS_PROCESSING:
            continue
        names.append(str(name))
    return names


def release_processing_batch(batch_id: str, *, error: str, retryable: bool) -> dict[str, Any]:
    normalized_batch_id = str(batch_id or "").strip()
    if not normalized_batch_id:
        return {"released_count": 0, "requeued_count": 0, "review_count": 0}

    max_attempts = auto_metadata_max_attempts()
    store = metadata_store()
    released_count = 0
    requeued_count = 0
    review_count = 0

    if store is not None and hasattr(store, "_mutate"):
        def apply(data: dict[str, dict[str, Any]]) -> dict[str, int]:
            released = 0
            requeued = 0
            review = 0
            for name, record in data.items():
                if name == "__country_descriptions__" or not isinstance(record, dict):
                    continue
                if str(record.get("processing_batch_id") or "").strip() != normalized_batch_id:
                    continue
                if str(record.get("processing_status") or "").strip() != PHOTO_PROCESSING_STATUS_PROCESSING:
                    continue
                attempts = int(record.get("processing_attempts") or 0)
                should_retry = retryable and attempts < max_attempts
                record["processing_status"] = PHOTO_PROCESSING_STATUS_PENDING if should_retry else PHOTO_PROCESSING_STATUS_REVIEW
                record["processing_reason"] = "auto_retry" if should_retry else "auto_review"
                record["processing_error"] = str(error or "").strip()[:240]
                record.pop("processing_owner", None)
                record.pop("processing_batch_id", None)
                record.pop("processing_started_at", None)
                data[name] = record
                released += 1
                if should_retry:
                    requeued += 1
                else:
                    review += 1
            return {"released_count": released, "requeued_count": requeued, "review_count": review}

        result = apply(data := None) if False else store._mutate(apply)
        released_count = int(result["released_count"])
        requeued_count = int(result["requeued_count"])
        review_count = int(result["review_count"])
    else:
        for name in processing_batch_photo_names(normalized_batch_id):
            current = storage.get_photo_processing_info(name)
            attempts = int(current.get("processing_attempts") or 0)
            should_retry = retryable and attempts < max_attempts
            storage.update_photo_processing_info(
                name,
                {
                    "processing_status": PHOTO_PROCESSING_STATUS_PENDING if should_retry else PHOTO_PROCESSING_STATUS_REVIEW,
                    "processing_reason": "auto_retry" if should_retry else "auto_review",
                    "processing_error": error,
                    "processing_attempts": attempts,
                    "processing_owner": "",
                    "processing_batch_id": "",
                    "processing_started_at": "",
                },
            )
            released_count += 1
            if should_retry:
                requeued_count += 1
            else:
                review_count += 1

    return {
        "released_count": released_count,
        "requeued_count": requeued_count,
        "review_count": review_count,
    }


def recover_stale_processing_batches(timeout_seconds: int | None = None) -> dict[str, int]:
    normalized_timeout = max(1, int(timeout_seconds or auto_metadata_processing_timeout_seconds()))
    now = datetime.now()
    max_attempts = auto_metadata_max_attempts()
    store = metadata_store()
    if store is None or not hasattr(store, "_mutate"):
        return {"requeued_count": 0, "review_count": 0}

    def apply(data: dict[str, dict[str, Any]]) -> dict[str, int]:
        requeued = 0
        review = 0
        for name, record in data.items():
            if name == "__country_descriptions__" or not isinstance(record, dict):
                continue
            if str(record.get("processing_status") or "").strip() != PHOTO_PROCESSING_STATUS_PROCESSING:
                continue
            started_at = parse_iso_datetime(record.get("processing_started_at"))
            if started_at is None:
                continue
            if (now - started_at).total_seconds() < normalized_timeout:
                continue
            attempts = int(record.get("processing_attempts") or 0)
            should_retry = attempts < max_attempts
            record["processing_status"] = PHOTO_PROCESSING_STATUS_PENDING if should_retry else PHOTO_PROCESSING_STATUS_REVIEW
            record["processing_reason"] = "auto_recover" if should_retry else "auto_review"
            record["processing_error"] = "auto worker timeout"
            record.pop("processing_owner", None)
            record.pop("processing_batch_id", None)
            record.pop("processing_started_at", None)
            data[name] = record
            if should_retry:
                requeued += 1
            else:
                review += 1
        return {"requeued_count": requeued, "review_count": review}

    return store._mutate(apply)


def validate_processing_batch_payload(batch_id: str, payload: dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("自动处理结果格式不正确。")

    expected_names = processing_batch_photo_names(batch_id)
    if not expected_names:
        raise ValueError("没有找到正在处理的批次。")

    raw_updates = payload.get("photos")
    if not isinstance(raw_updates, list) or not raw_updates:
        raise ValueError("自动处理结果里缺少照片列表。")

    returned_names = [str(item.get("name") or "").strip() for item in raw_updates if isinstance(item, dict)]
    if len(returned_names) != len(expected_names):
        raise ValueError("自动处理结果的照片数量与认领批次不一致。")
    if set(returned_names) != set(expected_names):
        raise ValueError("自动处理结果的照片名称与认领批次不一致。")
    return expected_names


def complete_processing_batch(batch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    validate_processing_batch_payload(batch_id, payload)
    result = apply_manual_review_batch(payload)
    return result


def apply_generated_metadata_to_photo(photo: dict, metadata: dict[str, str], photos: list[dict]) -> dict:
    photo_name = str(photo.get("name") or "")
    country = str(photo.get("country") or "")
    current_title = str(photo.get("title") or "").strip()
    title_source = str(photo.get("title_source") or "").strip() or PHOTO_TITLE_SOURCE_DEFAULT
    normalized_metadata = normalize_photo_ai_metadata(metadata)

    if title_source == PHOTO_TITLE_SOURCE_MANUAL and current_title:
        normalized_metadata["place"] = current_title
        resolved_city = resolve_city_from_place(current_title, country=country, photos=photos, exclude_name=photo_name)
        if resolved_city:
            normalized_metadata["city"] = resolved_city

    storage.update_photo_ai_metadata(photo_name, normalized_metadata)

    if title_source == PHOTO_TITLE_SOURCE_MANUAL and current_title:
        return storage.update_photo_info(
            photo_name,
            country,
            current_title,
            title_source=PHOTO_TITLE_SOURCE_MANUAL,
        )

    generated_title = build_generated_photo_title(
        {
            **normalized_metadata,
            "title": current_title,
            "name": photo_name,
        }
    )
    generated_source = PHOTO_TITLE_SOURCE_GENERATED if generated_title != Path(photo_name).stem else PHOTO_TITLE_SOURCE_DEFAULT
    return storage.update_photo_info(
        photo_name,
        country,
        generated_title,
        title_source=generated_source,
    )


def apply_manual_review_batch(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("批处理结果格式不正确。")

    photos = load_photos()
    photo_index = {str(photo.get("name") or ""): photo for photo in photos}
    raw_updates = payload.get("photos", [])
    if not isinstance(raw_updates, list) or not raw_updates:
        raise ValueError("批处理结果里缺少照片列表。")

    country = str(payload.get("country") or "").strip()
    updated_records: list[dict[str, Any]] = []
    updated_names: list[str] = []

    for raw_item in raw_updates:
        if not isinstance(raw_item, dict):
            raise ValueError("照片结果格式不正确。")
        photo_name = str(raw_item.get("name") or "").strip()
        if not photo_name:
            raise ValueError("照片结果缺少 name。")
        existing_photo = photo_index.get(photo_name)
        if existing_photo is None:
            raise FileNotFoundError(photo_name)

        target_country = str(raw_item.get("country") or existing_photo.get("country") or country).strip()
        normalized_metadata = normalize_photo_ai_metadata(raw_item)
        explicit_title = str(raw_item.get("title") or "").strip()
        if explicit_title:
            title = explicit_title
            title_source = PHOTO_TITLE_SOURCE_GENERATED
        else:
            title = build_generated_photo_title({**existing_photo, **normalized_metadata})
            title_source = PHOTO_TITLE_SOURCE_GENERATED if title else PHOTO_TITLE_SOURCE_DEFAULT

        storage.update_photo_ai_metadata(photo_name, normalized_metadata)
        updated_record = storage.update_photo_info(
            photo_name,
            target_country,
            title,
            title_source=title_source,
        )
        storage.update_photo_processing_info(
            str(updated_record.get("name") or photo_name),
            {
                "processing_status": PHOTO_PROCESSING_STATUS_DONE if photo_metadata_complete(normalized_metadata) else PHOTO_PROCESSING_STATUS_REVIEW,
                "processing_reason": "",
                "processing_error": "",
                "processing_owner": "",
                "processing_batch_id": "",
                "processing_started_at": "",
            },
        )
        updated_names.append(str(updated_record.get("name") or photo_name))
        updated_records.append(with_photo_urls(updated_record))

    description_updates = empty_description_update_result(manual_country_review_message([country] if country else []))
    raw_description = payload.get("country_description")
    if country and isinstance(raw_description, dict):
        description = storage.update_country_description(country, raw_description)
        description_updates = {
            "enabled": False,
            "message": "已回写当前对话生成的国家介绍。",
            "updated": [{"country": country, **description}],
            "deleted": [],
            "failed": [],
        }

    refreshed_photos = load_photos()
    return {
        "country": country,
        "updated_count": len(updated_records),
        "updated_photos": [
            photo for photo in refreshed_photos
            if str(photo.get("name") or "") in updated_names
        ],
        "description_updates": description_updates,
    }


def queue_photos_for_metadata_audit(
    *,
    countries: Iterable[str] | None = None,
    force_all: bool = False,
    reason: str = "library_audit",
) -> dict[str, int | list[str]]:
    photos = load_photos()
    normalized_countries = set(normalize_countries(countries or []))
    queued_names: list[str] = []
    for photo in photos:
        photo_country = str(photo.get("country") or "").strip()
        if normalized_countries and photo_country not in normalized_countries:
            continue
        should_queue = force_all or not photo_metadata_complete(photo)
        if not should_queue:
            continue
        storage.update_photo_processing_info(
            str(photo.get("name") or ""),
            {
                "processing_status": PHOTO_PROCESSING_STATUS_PENDING,
                "processing_reason": reason,
                "processing_error": "",
            },
        )
        queued_names.append(str(photo.get("name") or ""))
    return {"queued_count": len(queued_names), "queued": queued_names}


def process_pending_photo_batch(limit: int = MAX_METADATA_BATCH_SIZE) -> dict[str, Any]:
    batch = build_pending_review_batch(limit=limit)
    batch["remaining_pending_count"] = len(
        [
            photo
            for photo in load_photos()
            if str(photo.get("processing_status") or "").strip() == PHOTO_PROCESSING_STATUS_PENDING
        ]
    )
    return batch


def select_country_preview_photos(photos: list[dict], limit: int = DEFAULT_COUNTRY_PREVIEW_LIMIT) -> list[dict]:
    if limit <= 0 or len(photos) <= limit:
        return list(photos)

    ordered_photos = list(photos)
    selected: list[dict] = []
    selected_names: set[str] = set()
    seen_diversity_keys: set[str] = set()

    for photo in ordered_photos:
        diversity_key = photo_diversity_key(photo)
        if not diversity_key or diversity_key in seen_diversity_keys:
            continue
        selected.append(photo)
        seen_diversity_keys.add(diversity_key)
        selected_names.add(str(photo.get("name") or ""))
        if len(selected) >= limit:
            return selected

    for photo in ordered_photos:
        photo_name = str(photo.get("name") or "")
        if photo_name in selected_names:
            continue
        selected.append(photo)
        selected_names.add(photo_name)
        if len(selected) >= limit:
            break

    return selected


def can_generate_photo_metadata() -> bool:
    return False


def refresh_photo_ai_metadata(photos: list[dict], country: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    metadata_records: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    for photo in photos:
        if photo.get("country") != country:
            continue

        existing_metadata = normalize_photo_ai_metadata(photo)
        if photo_metadata_complete(existing_metadata):
            metadata_records.append(existing_metadata)
            continue

        if any(existing_metadata.values()):
            metadata_records.append(existing_metadata)
            continue

        failures.append(
            {
                "name": str(photo.get("name") or ""),
                "error": MANUAL_AI_WORKFLOW_MESSAGE,
            }
        )

    return metadata_records, failures


def build_country_photo_samples(photos: list[dict], country: str) -> list[CountryPhotoSample]:
    samples: list[CountryPhotoSample] = []
    for photo in photos:
        if photo.get("country") != country:
            continue
        try:
            stream, content_type = storage.open_photo(photo["name"])
        except FileNotFoundError:
            continue
        samples.append(
            CountryPhotoSample(
                name=photo["name"],
                title=str(photo.get("title") or ""),
                content_type=content_type,
                payload=stream.getvalue(),
            )
        )
    return samples


def refresh_country_descriptions(
    photos: list[dict],
    countries: Iterable[str],
    *,
    force: bool,
    sample_source_photos: Optional[list[dict]] = None,
) -> dict[str, list[dict] | bool | str]:
    normalized_countries = normalize_countries(countries)
    existing_descriptions = normalize_country_intro_descriptions(storage.list_country_descriptions())
    result = empty_description_update_result(manual_country_review_message(normalized_countries))

    if not normalized_countries:
        return result

    photos_by_country: dict[str, list[dict]] = {}
    for photo in photos:
        country = str(photo.get("country") or "").strip()
        if country:
            photos_by_country.setdefault(country, []).append(photo)

    sample_photos = sample_source_photos if sample_source_photos is not None else photos

    for country in normalized_countries:
        country_photos = photos_by_country.get(country, [])
        if not country_photos:
            if existing_descriptions.get(country):
                storage.delete_country_description(country)
                cast_list = result["deleted"]
                assert isinstance(cast_list, list)
                cast_list.append(country)
            continue

        if not force and existing_descriptions.get(country):
            continue

        cast_list = result["failed"]
        assert isinstance(cast_list, list)
        cast_list.append({"country": country, "error": MANUAL_AI_WORKFLOW_MESSAGE})

    return result


def build_groups(
    photos: list[dict],
    *,
    ensure_missing_descriptions: bool = False,
    preview_limit: int | None = None,
    detail_endpoint: str | None = None,
) -> list[dict]:
    descriptions = normalize_country_intro_descriptions(storage.list_country_descriptions())
    groups = group_photos_by_country(photos, descriptions)
    for group in groups:
        all_photos = list(group["photos"])
        display_photos = list(all_photos)
        if preview_limit and len(all_photos) > preview_limit:
            display_photos = select_country_preview_photos(all_photos, limit=preview_limit)

        group["count"] = len(all_photos)
        group["visible_count"] = len(display_photos)
        group["is_preview"] = len(display_photos) < len(all_photos)
        group["preview_note"] = "首页精选" if group["is_preview"] else ""
        group["detail_url"] = url_for(detail_endpoint, country=group["country"]) if detail_endpoint else ""
        group["photos"] = assign_collage_slots(display_photos)
    return groups


def preview_max_edge() -> int:
    try:
        return max(640, int(os.getenv("PREVIEW_MAX_EDGE", "1600")))
    except ValueError:
        return 1600


def preview_quality() -> int:
    try:
        value = int(os.getenv("PREVIEW_QUALITY", "82"))
    except ValueError:
        value = 82
    return min(95, max(55, value))


def normalize_preview_width(raw_width: Optional[int]) -> int:
    if raw_width is None:
        return preview_max_edge()

    return min(preview_max_edge(), max(320, int(raw_width)))


def preview_card_widths() -> tuple[int, ...]:
    widths = (480, 720, 1080, preview_max_edge())
    normalized = {normalize_preview_width(width) for width in widths}
    return tuple(sorted(normalized))


def preview_card_default_width() -> int:
    widths = preview_card_widths()
    return widths[min(1, len(widths) - 1)]


def preview_card_sizes() -> str:
    return "(max-width: 380px) 100vw, (max-width: 960px) 50vw, 33vw"


def preview_cache_seconds() -> int:
    try:
        return max(3600, int(os.getenv("PREVIEW_CACHE_SECONDS", str(7 * 24 * 60 * 60))))
    except ValueError:
        return 7 * 24 * 60 * 60


def preview_cache_dir() -> Path:
    cache_dir = PROJECT_ROOT / ".preview-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def preview_cache_path(photo_name: str, max_edge: Optional[int] = None) -> Path:
    target_edge = normalize_preview_width(max_edge)
    digest = hashlib.sha256(
        f"{photo_name}|{target_edge}|{preview_quality()}".encode("utf-8")
    ).hexdigest()
    return preview_cache_dir() / f"{digest}.jpg"


def clear_photo_runtime_caches(photo_name: str) -> None:
    cache_paths = {preview_cache_path(photo_name)}
    cache_paths.update(preview_cache_path(photo_name, width) for width in preview_card_widths())
    for cache_path in cache_paths:
        cache_path.unlink(missing_ok=True)
    infer_photo_layout_metrics.cache_clear()


def normalize_layout_orientation(value: Any) -> str:
    orientation = str(value or "").strip().lower()
    if orientation in {"landscape", "portrait", "square"}:
        return orientation
    return ""


@lru_cache(maxsize=1024)
def infer_photo_layout_metrics(photo_name: str, modified_at: str = "", size: int = 0) -> tuple[str, float]:
    if Image is None or ImageOps is None:
        return "square", 1.0

    try:
        stream, _ = storage.open_photo(photo_name)
    except Exception:
        return "square", 1.0

    try:
        image = Image.open(stream)
        image = ImageOps.exif_transpose(image)
        width, height = image.size
    except Exception:
        return "square", 1.0

    if not width or not height:
        return "square", 1.0

    ratio = round(width / height, 4)

    if width > height:
        return "landscape", ratio
    if height > width:
        return "portrait", ratio
    return "square", 1.0


def build_preview_image(photo_name: str, max_edge: Optional[int] = None) -> tuple[BytesIO, str]:
    target_edge = normalize_preview_width(max_edge)
    cache_path = preview_cache_path(photo_name, target_edge)
    if cache_path.exists():
        return BytesIO(cache_path.read_bytes()), "image/jpeg"

    stream, content_type = storage.open_photo(photo_name)
    original_payload = stream.getvalue()

    if Image is None or ImageOps is None:
        return BytesIO(original_payload), content_type or mimetypes.guess_type(photo_name)[0] or "application/octet-stream"

    try:
        image = Image.open(BytesIO(original_payload))
        image = ImageOps.exif_transpose(image)
        image.load()
        alpha_image = image.convert("RGBA")
        flattened = Image.new("RGB", alpha_image.size, "#f4ebdc")
        flattened.paste(alpha_image, mask=alpha_image.getchannel("A"))
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        flattened.thumbnail((target_edge, target_edge), resampling)
        output = BytesIO()
        flattened.save(output, format="JPEG", quality=preview_quality(), optimize=True, progressive=True)
        preview_bytes = output.getvalue()
        cache_path.write_bytes(preview_bytes)
        return BytesIO(preview_bytes), "image/jpeg"
    except Exception:
        return BytesIO(original_payload), content_type or mimetypes.guess_type(photo_name)[0] or "application/octet-stream"


def with_photo_urls(photo: dict) -> dict:
    record = dict(photo)
    safe_name = str(record.get("name") or "")
    encoded_name = quote(safe_name, safe="/")
    layout_orientation = normalize_layout_orientation(record.get("layout_orientation"))
    layout_ratio = normalize_layout_ratio(record.get("layout_ratio"))
    if safe_name and (not layout_orientation or not layout_ratio):
        inferred_orientation, inferred_ratio = infer_photo_layout_metrics(
            safe_name,
            str(record.get("modified_at") or ""),
            int(record.get("size") or 0),
        )
        layout_orientation = layout_orientation or inferred_orientation
        layout_ratio = layout_ratio or inferred_ratio
    record["preview_url"] = f"/photos-preview/{encoded_name}"
    record["download_url"] = f"/photos/{encoded_name}"
    record["card_image_url"] = f"/photos-preview/{encoded_name}?w={preview_card_default_width()}"
    record["card_image_srcset"] = ", ".join(
        f"/photos-preview/{encoded_name}?w={width} {width}w" for width in preview_card_widths()
    )
    record["card_image_sizes"] = preview_card_sizes()
    record["layout_orientation"] = layout_orientation or "square"
    record["layout_ratio"] = layout_ratio or 1.0
    return record


def load_photos() -> list[dict]:
    return [with_photo_urls(photo) for photo in storage.list_photos()]


def render_public_gallery():
    photos = load_photos()
    return render_template(
        "gallery.html",
        photos=photos,
        groups=build_groups(
            photos,
            ensure_missing_descriptions=not public_site_only(),
            preview_limit=country_preview_limit(),
            detail_endpoint="public_country_detail",
        ),
    )


def render_public_country_detail(country: str):
    photos = load_photos()
    groups = build_groups(
        photos,
        ensure_missing_descriptions=not public_site_only(),
    )
    normalized_country = str(country or "").strip()
    group = next((item for item in groups if item.get("country") == normalized_country), None)
    if group is None:
        abort(404)

    return render_template(
        "country_detail.html",
        country=normalized_country,
        group=group,
    )


load_simple_env(PROJECT_ROOT / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("ADMIN_SESSION_SECRET") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}

storage = create_storage(PROJECT_ROOT)
photo_metadata_describer = ManualWorkflowDescriber()
country_describer = ManualWorkflowDescriber()


def static_asset_version(filename: str) -> int:
    asset_root = Path(app.static_folder) if app.static_folder else PROJECT_ROOT / "static"
    asset_path = asset_root / filename
    try:
        return int(asset_path.stat().st_mtime)
    except FileNotFoundError:
        return 0


@app.context_processor
def inject_asset_versions():
    return {"static_asset_version": static_asset_version}


@app.route("/")
def public_home():
    return render_public_gallery()


@app.route("/gallery")
def public_gallery():
    return render_public_gallery()


@app.route("/gallery/country/<path:country>")
def public_country_detail(country: str):
    return render_public_country_detail(country)


@app.get("/healthz")
def healthcheck():
    return jsonify({"ok": True, "public_site_only": public_site_only()})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if public_site_only():
        abort(404)

    if is_admin_authenticated():
        return redirect(url_for("admin_dashboard"))

    next_url = normalize_next_url(request.values.get("next"))
    if not admin_password():
        return render_template(
            "login.html",
            next_url=next_url,
            password_missing=True,
            error=None,
            admin_username=admin_username(),
        ), 503

    error = None
    if request.method == "POST":
        submitted_username = request.form.get("username", "").strip()
        submitted_password = request.form.get("password", "")
        if hmac.compare_digest(submitted_username, admin_username()) and hmac.compare_digest(submitted_password, admin_password()):
            session.clear()
            session["admin_authenticated"] = True
            session["admin_username"] = admin_username()
            session["admin_password_sig"] = current_password_signature()
            return redirect(next_url)
        error = "用户名或密码错误，请重试。"

    return render_template(
        "login.html",
        next_url=next_url,
        password_missing=False,
        error=error,
        admin_username=admin_username(),
    )


@app.post("/admin/logout")
@admin_required()
def admin_logout():
    session.clear()
    return redirect(url_for("public_home"))


@app.route("/admin")
@admin_required()
def admin_dashboard():
    photos = load_photos()
    return render_template(
        "index.html",
        photos=photos,
        groups=build_groups(photos, ensure_missing_descriptions=True),
        auto_metadata_status=build_auto_metadata_status_summary(photos),
        admin_username=admin_username(),
        max_upload_mb=app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
    )


@app.get("/api/photos")
@admin_required(api=True)
def list_photos():
    photos = load_photos()
    return jsonify(
        {
            "photos": photos,
            "groups": build_groups(photos, ensure_missing_descriptions=True),
            "auto_metadata_status": build_auto_metadata_status_summary(photos),
        }
    )


@app.post("/api/sync-storage")
@admin_required(api=True)
def sync_storage():
    result = storage.sync_storage_structure()
    photos = load_photos()
    description_result = build_groups(photos, ensure_missing_descriptions=True)
    return jsonify(
        {
            "synced": result,
            "photos": photos,
            "groups": description_result,
            "auto_metadata_status": build_auto_metadata_status_summary(photos),
        }
    )


@app.post("/api/upload")
@admin_required(api=True)
def upload_photo():
    uploads = [item for item in request.files.getlist("photos") if item and item.filename]
    if not uploads:
        fallback_photo = request.files.get("photo")
        if fallback_photo and fallback_photo.filename:
            uploads = [fallback_photo]

    if not uploads:
        return jsonify({"error": "请至少选择一张图片。"}), 400

    photo_keys = request.form.getlist("photo_keys")
    photo_countries = request.form.getlist("photo_countries")

    if photo_countries:
        if len(photo_countries) != len(uploads):
            return jsonify({"error": "批量导入数据不完整，请重新选择照片后再试。"}), 400
        if photo_keys and len(photo_keys) != len(uploads):
            return jsonify({"error": "批量导入文件映射异常，请重新选择照片后再试。"}), 400
        upload_entries = list(zip(uploads, photo_keys or [""] * len(uploads), photo_countries))
        missing_countries = [
            {
                "filename": upload.filename or "photo",
                "photo_key": photo_key,
                "error": "请填写这张照片的拍摄国家。",
            }
            for upload, photo_key, country in upload_entries
            if not (country or "").strip()
        ]
        if missing_countries:
            return jsonify({"error": "请为每张照片填写拍摄国家。", "failed": missing_countries}), 400
    else:
        country = request.form.get("country", "")
        if not country.strip():
            return jsonify({"error": "请填写拍摄国家。"}), 400
        upload_entries = [(upload, "", country) for upload in uploads]

    imported = []
    failed = []

    for upload, photo_key, country in upload_entries:
        try:
            imported.append(with_photo_urls(storage.save_photo(upload, country)))
        except ValueError as exc:
            failed.append({"filename": upload.filename or "photo", "photo_key": photo_key, "error": str(exc)})
        except Exception as exc:
            failed.append({"filename": upload.filename or "photo", "photo_key": photo_key, "error": f"上传失败：{exc}"})

    if not imported:
        first_error = failed[0]["error"] if failed else "上传失败。"
        return jsonify({"error": first_error, "imported": [], "failed": failed}), 400

    photos = load_photos()
    queued_countries = normalize_countries(photo.get("country") or "" for photo in imported)
    queued_country_text = "、".join(queued_countries)
    description_updates = empty_description_update_result(
        auto_metadata_queue_message(queued_countries or ([queued_country_text] if queued_country_text else []))
    )
    groups = build_groups(photos)

    status_code = 201 if not failed else 207
    return (
        jsonify(
            {
                "photo": imported[0],
                "photos": imported,
                "imported_count": len(imported),
                "failed_count": len(failed),
                "failed": failed,
                "description_updates": description_updates,
                "groups": groups,
                "auto_metadata_status": build_auto_metadata_status_summary(photos),
            }
        ),
        status_code,
    )


@app.post("/api/country-descriptions/refresh")
@admin_required(api=True)
def refresh_country_description_sections():
    payload = request.get_json(silent=True) or {}
    raw_countries = payload.get("countries", [])
    raw_photo_names = payload.get("photo_names", [])
    if raw_countries is None:
        raw_countries = []
    if not isinstance(raw_countries, list):
        return jsonify({"error": "国家列表格式不正确。"}), 400
    if raw_photo_names is None:
        raw_photo_names = []
    if not isinstance(raw_photo_names, list):
        return jsonify({"error": "照片列表格式不正确。"}), 400

    photos = load_photos()
    countries = normalize_countries(raw_countries) or normalize_countries(photo.get("country") or "" for photo in photos)
    photo_name_set = {str(name or "").strip() for name in raw_photo_names if str(name or "").strip()}
    sample_source_photos = [photo for photo in photos if str(photo.get("name") or "") in photo_name_set] if photo_name_set else None
    description_updates = refresh_country_descriptions(
        photos,
        countries,
        force=True,
        sample_source_photos=sample_source_photos,
    )

    return jsonify(
        {
            "groups": build_groups(photos),
            "description_updates": description_updates,
            "auto_metadata_status": build_auto_metadata_status_summary(photos),
        }
    )


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(error):
    max_bytes = app.config.get("MAX_CONTENT_LENGTH")
    max_upload_mb = max(1, int(max_bytes / (1024 * 1024))) if max_bytes else None
    message = (
        f"单张照片或单次请求不能超过 {max_upload_mb} MB，请压缩图片后重试。"
        if max_upload_mb
        else "上传内容过大，请压缩图片后重试。"
    )

    if request.path.startswith("/api/"):
        return jsonify({"error": message}), 413

    return message, 413


@app.patch("/api/photos/<path:photo_name>")
@admin_required(api=True)
def update_photo_info(photo_name: str):
    payload = request.get_json(silent=True) or {}
    country = payload.get("country", "")
    title = payload.get("title", "")
    current_photos = load_photos()
    original_photo = next((photo for photo in current_photos if photo.get("name") == photo_name), None)
    previous_country = (original_photo or {}).get("country", "")

    normalized_title = str(title or "").strip()

    try:
        photo_record = with_photo_urls(
            storage.update_photo_info(
                photo_name,
                country,
                title,
                title_source=PHOTO_TITLE_SOURCE_MANUAL if normalized_title else PHOTO_TITLE_SOURCE_DEFAULT,
            )
        )
    except FileNotFoundError:
        return jsonify({"error": "照片不存在。"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"更新失败：{exc}"}), 500

    photos = load_photos()
    if normalized_title:
        existing_metadata = storage.get_photo_ai_metadata(str(photo_record.get("name") or ""))
        updated_metadata = dict(existing_metadata)
        updated_metadata["place"] = normalized_title
        resolved_city = resolve_city_from_place(
            normalized_title,
            country=str(photo_record.get("country") or ""),
            photos=photos,
            exclude_name=str(photo_record.get("name") or ""),
        )
        updated_metadata["city"] = resolved_city
        storage.update_photo_ai_metadata(str(photo_record.get("name") or ""), updated_metadata)
        storage.update_photo_processing_info(
            str(photo_record.get("name") or ""),
            {
                "processing_status": PHOTO_PROCESSING_STATUS_DONE if resolved_city else PHOTO_PROCESSING_STATUS_PENDING,
                "processing_reason": "" if resolved_city else "title_override",
                "processing_error": "",
            },
        )
        photos = load_photos()
        photo_record = with_photo_urls(
            next(
                photo
                for photo in photos
                if str(photo.get("name") or "") == str(photo_record.get("name") or "")
            )
        )

    description_updates = refresh_country_descriptions(
        photos,
        [str(previous_country or ""), str(photo_record.get("country") or "")],
        force=True,
    )
    return jsonify(
        {
            "photo": photo_record,
            "photos": photos,
            "groups": build_groups(photos),
            "description_updates": description_updates,
            "auto_metadata_status": build_auto_metadata_status_summary(photos),
        }
    )


@app.delete("/api/photos/<path:photo_name>")
@admin_required(api=True)
def delete_photo(photo_name: str):
    current_photos = load_photos()
    original_photo = next((photo for photo in current_photos if photo.get("name") == photo_name), None)
    if original_photo is None:
        return jsonify({"error": "照片不存在。"}), 404

    previous_country = str((original_photo or {}).get("country") or "")

    try:
        storage.delete_photo(photo_name)
    except FileNotFoundError:
        return jsonify({"error": "照片不存在。"}), 404
    except Exception as exc:
        return jsonify({"error": f"删除失败：{exc}"}), 500

    clear_photo_runtime_caches(photo_name)
    photos = load_photos()
    description_updates = refresh_country_descriptions(
        photos,
        [previous_country],
        force=True,
    )
    return jsonify(
        {
            "deleted_photo_name": photo_name,
            "photos": photos,
            "groups": build_groups(photos),
            "description_updates": description_updates,
            "auto_metadata_status": build_auto_metadata_status_summary(photos),
        }
    )


@app.get("/photos/<path:photo_name>")
def get_photo(photo_name: str):
    try:
        stream, content_type = storage.open_photo(photo_name)
    except FileNotFoundError:
        return jsonify({"error": "照片不存在。"}), 404

    guessed_type = content_type or mimetypes.guess_type(photo_name)[0] or "application/octet-stream"
    return send_file(stream, mimetype=guessed_type, download_name=photo_name)


@app.get("/photos-preview/<path:photo_name>")
def get_photo_preview(photo_name: str):
    try:
        stream, content_type = build_preview_image(photo_name, request.args.get("w", type=int))
    except FileNotFoundError:
        return jsonify({"error": "照片不存在。"}), 404

    response = send_file(
        stream,
        mimetype=content_type or "image/jpeg",
        download_name=Path(photo_name).name,
    )
    response.cache_control.public = True
    response.cache_control.max_age = preview_cache_seconds()
    response.cache_control.no_cache = None
    return response


if __name__ == "__main__":
    app.run(debug=debug_enabled(), host=server_host(), port=server_port())
