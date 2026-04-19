import contextlib
import importlib
import os
import re
import runpy
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_LAYOUT_ORIENTATIONS = [
    "landscape",
    "portrait",
    "landscape",
    "square",
    "portrait",
    "landscape",
]
EXPECTED_COLLAGE_SLOTS = [
    "collage-tile-wide",
    "collage-tile-standard",
    "collage-tile-standard",
    "collage-tile-standard",
    "collage-tile-standard",
    "collage-tile-wide",
]


def base_env(temp_dir: str, **overrides: str) -> dict[str, str]:
    values = {
        "PHOTO_STORAGE": "icloud",
        "ICLOUD_PHOTO_DIR": temp_dir,
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "test-password",
        "ADMIN_SESSION_SECRET": "test-session-secret",
        "PORT": "5001",
        "PUBLIC_SITE_ONLY": "false",
        "GEMINI_API_KEY": "",
    }
    values.update(overrides)
    return values


@contextlib.contextmanager
def loaded_app_module(**overrides: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, base_env(temp_dir, **overrides), clear=False):
            sys.modules.pop("app", None)
            module = importlib.import_module("app")
            module = importlib.reload(module)
            try:
                yield module
            finally:
                sys.modules.pop("app", None)


def run_app_as_main(**overrides: str) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, base_env(temp_dir, **overrides), clear=False):
            with patch("flask.app.Flask.run", autospec=True) as run_mock:
                runpy.run_path(str(PROJECT_ROOT / "app.py"), run_name="__main__")
    return run_mock.call_args.kwargs


def pick_free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def build_fake_photo(index: int, *, country: str = "奥地利") -> dict:
    suffix = "" if index == 1 else f"-{index}"
    title_suffix = "" if index == 1 else f" {index}"
    minute = index - 1
    encoded_country = "%E5%A5%A5%E5%9C%B0%E5%88%A9"
    layout_orientation = FAKE_LAYOUT_ORIENTATIONS[index - 1]
    layout_ratio = {
        "landscape": 1.8,
        "portrait": 0.67,
        "square": 1.0,
    }[layout_orientation]
    return {
        "name": f"{country}/demo{suffix}.jpg",
        "url": f"/photos/{encoded_country}/demo{suffix}.jpg",
        "country": country,
        "title": f"demo{title_suffix}",
        "size": 111 * index + 12,
        "modified_at": f"2026-04-17T18:{minute:02d}:00",
        "layout_orientation": layout_orientation,
        "layout_ratio": layout_ratio,
    }


def build_city_photo(index: int, *, country: str = "意大利", city: str, place: str) -> dict:
    photo = build_fake_photo(((index - 1) % 6) + 1, country=country)
    photo["name"] = f"{country}/city-{index}.jpg"
    photo["url"] = f"/photos/{urllib.parse.quote(country)}/city-{index}.jpg"
    photo["title"] = f"{city} {place}"
    photo["modified_at"] = f"2026-04-18T1{index % 10}:00:00"
    photo["city"] = city
    photo["place"] = place
    photo["subject"] = f"{place} 风景"
    photo["scene_summary"] = f"{city} 的 {place} 与周边街区。"
    return photo


class FakeStorage:
    def list_photos(self) -> list[dict]:
        return [build_fake_photo(index) for index in range(1, 7)]

    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        return {
            "奥地利": {
                "short_description": "湖山与旧镇在静光里缓慢展开。",
                "long_description": "奥地利的影像沿着湖岸、小镇与山体层层展开，冷冽空气中的尖顶、屋脊与水面反光共同勾勒出一种克制而古典的秩序。",
            }
        }


class LocalPublicShareTests(unittest.TestCase):
    def render_public_gallery_html(self) -> str:
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            response = app_module.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def render_admin_gallery_html(self) -> str:
        with loaded_app_module(PUBLIC_SITE_ONLY="false") as app_module:
            app_module.storage = FakeStorage()
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["admin_authenticated"] = True
                session["admin_password_sig"] = app_module.current_password_signature()
                session["admin_username"] = app_module.admin_username()
            response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def template_source(self, relative_path: str) -> str:
        return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

    def stylesheet_source(self) -> str:
        return (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")

    def parse_tag_attributes(self, opening_tag: str) -> dict[str, str]:
        return dict(re.findall(r'([:\w-]+)="([^"]*)"', opening_tag))

    def collage_cards(self, html: str, *, card_kind: Optional[str] = None) -> list[dict[str, object]]:
        cards: list[dict[str, object]] = []
        for match in re.finditer(r"<article\b([^>]*)>", html):
            attrs = self.parse_tag_attributes(match.group(1))
            class_names = set(attrs.get("class", "").split())
            if {"photo-card", "collage-tile"} - class_names:
                continue
            if card_kind and card_kind not in class_names:
                continue
            cards.append(
                {
                    "attrs": attrs,
                    "classes": class_names,
                    "slot": attrs.get("data-collage-slot"),
                }
            )
        return cards

    def template_fragment(self, html: str, template_id: str) -> str:
        match = re.search(
            rf'<template id="{re.escape(template_id)}">\s*(.*?)\s*</template>',
            html,
            re.S,
        )
        self.assertIsNotNone(match, msg=f"template {template_id} not found")
        assert match is not None
        return match.group(1)

    def extract_braced_block(self, source: str, start_index: int) -> tuple[str, int]:
        self.assertLess(start_index, len(source))
        self.assertEqual(source[start_index], "{")
        depth = 0
        for index in range(start_index, len(source)):
            char = source[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[start_index + 1 : index], index
        self.fail("unbalanced braces in stylesheet")

    def selector_block(self, source: str, selector: str) -> str:
        match = re.search(rf"{re.escape(selector)}\s*\{{", source)
        self.assertIsNotNone(match, msg=f"selector {selector} not found")
        assert match is not None
        block, _ = self.extract_braced_block(source, match.end() - 1)
        return block

    def media_query_block(self, css: str, media_query: str) -> str:
        match = re.search(rf"{re.escape(media_query)}\s*\{{", css)
        self.assertIsNotNone(match, msg=f"media query {media_query} not found")
        assert match is not None
        block, _ = self.extract_braced_block(css, match.end() - 1)
        return block

    def assert_collage_slots(self, html: str, card_kind: str) -> None:
        cards = self.collage_cards(html, card_kind=card_kind)
        self.assertEqual(len(cards), len(EXPECTED_COLLAGE_SLOTS))
        self.assertEqual([card["slot"] for card in cards], EXPECTED_COLLAGE_SLOTS)
        self.assertEqual(
            [card["attrs"].get("data-layout-orientation") for card in cards],
            FAKE_LAYOUT_ORIENTATIONS,
        )
        for card, expected_slot, expected_orientation in zip(cards, EXPECTED_COLLAGE_SLOTS, FAKE_LAYOUT_ORIENTATIONS):
            self.assertEqual(card["slot"], expected_slot)
            self.assertIn(expected_slot, card["classes"])
            self.assertEqual(card["attrs"].get("data-layout-orientation"), expected_orientation)
            if expected_orientation == "landscape":
                self.assertIn(expected_slot, {"collage-tile-standard", "collage-tile-wide"})
            elif expected_orientation == "portrait":
                self.assertIn(expected_slot, {"collage-tile-standard", "collage-tile-tall"})
            else:
                self.assertEqual(expected_slot, "collage-tile-standard")

    def test_main_defaults_bind_to_localhost_and_disable_debug(self):
        run_kwargs = run_app_as_main()

        self.assertEqual(run_kwargs["host"], "127.0.0.1")
        self.assertEqual(run_kwargs["port"], 5001)
        self.assertFalse(run_kwargs["debug"])

    def test_main_respects_app_host_override(self):
        run_kwargs = run_app_as_main(APP_HOST="0.0.0.0", PORT="5050")

        self.assertEqual(run_kwargs["host"], "0.0.0.0")
        self.assertEqual(run_kwargs["port"], 5050)

    def test_public_only_gallery_does_not_refresh_descriptions(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            with patch.object(app_module, "refresh_country_descriptions") as refresh_mock:
                response = app_module.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        refresh_mock.assert_not_called()

    def test_public_only_hides_admin_and_api_routes(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            client = app_module.app.test_client()

            self.assertEqual(client.get("/admin").status_code, 404)
            self.assertEqual(client.get("/admin/login").status_code, 404)
            self.assertEqual(client.get("/api/photos").status_code, 404)
            self.assertEqual(client.get("/healthz").json["public_site_only"], True)

    def test_public_gallery_includes_mobile_lightweight_sections(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            response = app_module.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="mobile-curation-sheet panel-surface"', html)
        self.assertIn('class="helper-guide-mobile"', html)
        self.assertIn('class="intro intro-mobile"', html)

    def test_public_gallery_uses_preview_urls_and_original_download_urls(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            response = app_module.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg", html)
        self.assertIn('data-download-url="/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg"', html)

    def test_public_gallery_uses_responsive_thumbnail_sources(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            response = app_module.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('src="/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg?w=720"', html)
        self.assertIn("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg?w=480 480w", html)
        self.assertIn("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg?w=720 720w", html)
        self.assertIn("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg?w=1080 1080w", html)
        self.assertIn('sizes="(max-width: 380px) 100vw, (max-width: 960px) 50vw, 33vw"', html)

    def test_public_gallery_uses_square_collage_tile_markup(self):
        html = self.render_public_gallery_html()
        self.assertIn('class="gallery-grid collage-grid"', html)
        self.assertNotIn("collage-tile-hero", html)
        cards = self.collage_cards(html, card_kind="public-photo-card")
        self.assertEqual(len(cards), 4)
        for card in cards:
            self.assertIn(card["slot"], {"collage-tile-standard", "collage-tile-wide", "collage-tile-tall"})

    def test_public_gallery_renders_photo_caption_under_each_image(self):
        html = self.render_public_gallery_html()

        self.assertIn('class="photo-subtitle photo-card-caption"', html)
        self.assertIn("demo", html)

    def test_with_photo_urls_infers_layout_orientation_from_image_payload(self):
        buffer = BytesIO()
        Image.new("RGB", (900, 1400), "#b55d3f").save(buffer, format="JPEG", quality=92)

        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            with patch.object(app_module.storage, "open_photo", return_value=(BytesIO(buffer.getvalue()), "image/jpeg")):
                photo = app_module.with_photo_urls(
                    {
                        "name": "奥地利/demo.jpg",
                        "url": "/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg",
                        "country": "奥地利",
                        "title": "demo",
                    }
                )

        self.assertEqual(photo["layout_orientation"], "portrait")
        self.assertAlmostEqual(photo["layout_ratio"], round(900 / 1400, 4))

    def test_public_gallery_renders_short_intro_and_expandable_long_intro(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            response = app_module.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("湖山与旧镇在静光里缓慢展开。", html)
        self.assertIn("奥地利的影像沿着湖岸、小镇与山体层层展开", html)
        self.assertIn("展开导览", html)
        self.assertIn('class="country-detail"', html)
        self.assertIn('aria-expanded="false"', html)

    def test_admin_gallery_uses_same_intro_structure_as_public_page(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="false") as app_module:
            app_module.storage = FakeStorage()
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["admin_authenticated"] = True
                session["admin_password_sig"] = app_module.current_password_signature()
                session["admin_username"] = app_module.admin_username()
            response = client.get("/admin")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("湖山与旧镇在静光里缓慢展开。", html)
        self.assertIn("奥地利的影像沿着湖岸、小镇与山体层层展开", html)
        self.assertIn("展开导览", html)
        self.assertIn('class="country-detail"', html)

    def test_admin_dashboard_renders_auto_metadata_status_summary(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="false") as app_module:
            class QueueStorage(FakeStorage):
                def list_photos(self):
                    photos = super().list_photos()
                    photos[0]["processing_status"] = "pending"
                    photos[0]["processing_reason"] = "upload"
                    photos[1]["processing_status"] = "processing"
                    photos[1]["processing_reason"] = "auto_worker"
                    photos[1]["processing_owner"] = "worker-1"
                    photos[1]["processing_batch_id"] = "batch-1"
                    photos[1]["processing_started_at"] = "2026-04-19T12:00:00"
                    photos[2]["processing_status"] = "review"
                    photos[2]["processing_reason"] = "auto_review"
                    photos[2]["processing_error"] = "bad json"
                    photos[2]["processing_attempts"] = 3
                    return photos

            app_module.storage = QueueStorage()
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["admin_authenticated"] = True
                session["admin_password_sig"] = app_module.current_password_signature()
                session["admin_username"] = app_module.admin_username()
            response = client.get("/admin")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("自动识别队列", html)
        self.assertIn("待处理", html)
        self.assertIn("处理中", html)
        self.assertIn("需复核", html)
        self.assertIn("bad json", html)

    def test_admin_gallery_uses_square_collage_tile_markup(self):
        html = self.render_admin_gallery_html()
        self.assertIn('class="gallery-grid collage-grid"', html)
        self.assertNotIn("collage-tile-hero", html)
        gallery_html = html.split('<template id="country-section-template">', 1)[0]
        self.assert_collage_slots(gallery_html, "editable-photo-card")
        template_cards = self.collage_cards(self.template_fragment(html, "photo-card-template"))
        self.assertEqual(len(template_cards), 1)
        template_card = template_cards[0]
        self.assertIn("editable-photo-card", template_card["classes"])
        self.assertIn("collage-tile-standard", template_card["classes"])
        self.assertEqual(template_card["slot"], "collage-tile-standard")
        self.assertEqual(template_card["attrs"].get("data-layout-orientation"), "square")
        self.assertRegex(html, r"dataset\.layoutOrientation\s*=")
        self.assertRegex(html, r"classList\.add\(\s*collageSlot\s*\)")

        self.assertNotIn("{% set collage_cycle =", self.template_source("templates/gallery.html"))
        self.assertNotIn("{% set collage_cycle =", self.template_source("templates/index.html"))
        self.assertRegex(
            self.template_source("templates/index.html"),
            r'<template id="photo-card-template">\s*\{\{\s*photo_card\(',
        )

    def test_admin_template_updates_photo_caption_text_in_dynamic_cards(self):
        html = self.render_admin_gallery_html()
        template_source = self.template_source("templates/index.html")

        self.assertIn('data-photo-caption', html)
        self.assertRegex(template_source, r"captionElement\.textContent\s*=\s*title")

    def test_admin_gallery_includes_delete_action_in_edit_dialog(self):
        html = self.render_admin_gallery_html()
        template_source = self.template_source("templates/index.html")

        self.assertIn('id="delete-photo-button"', html)
        self.assertIn("彻底删除", html)
        self.assertIn('method: "DELETE"', template_source)
        self.assertIn("确认删除这张照片", template_source)

    def test_admin_delete_api_requires_login(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="false") as app_module:
            client = app_module.app.test_client()
            response = client.delete("/api/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "请先登录后台管理页。")

    def test_admin_delete_api_removes_photo_and_country_intro_when_country_becomes_empty(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="false") as app_module:
            class FakeDeleteStorage:
                def __init__(self):
                    self.photos = [build_fake_photo(1)]
                    self.descriptions = {
                        "奥地利": {
                            "short_description": "湖山与旧镇在静光里缓慢展开。",
                            "long_description": "完整导览文字。",
                        }
                    }

                def list_photos(self):
                    return list(self.photos)

                def list_country_descriptions(self):
                    return dict(self.descriptions)

                def delete_country_description(self, country):
                    self.descriptions.pop(country, None)

                def delete_photo(self, name):
                    for index, photo in enumerate(self.photos):
                        if photo["name"] == name:
                            self.photos.pop(index)
                            return
                    raise FileNotFoundError(name)

            app_module.storage = FakeDeleteStorage()
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["admin_authenticated"] = True
                session["admin_password_sig"] = app_module.current_password_signature()
                session["admin_username"] = app_module.admin_username()

            response = client.delete("/api/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["deleted_photo_name"], "奥地利/demo.jpg")
        self.assertEqual(response.json["groups"], [])
        self.assertEqual(response.json["description_updates"]["deleted"], ["奥地利"])

    def test_public_homepage_limits_country_preview_and_links_to_detail_page(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            class CityStorage:
                def list_photos(self):
                    return [
                        build_city_photo(1, city="罗马", place="圣彼得大教堂"),
                        build_city_photo(2, city="罗马", place="斗兽场"),
                        build_city_photo(3, city="威尼斯", place="大运河"),
                        build_city_photo(4, city="威尼斯", place="圣马可广场"),
                        build_city_photo(5, city="佛罗伦萨", place="圣母百花大教堂"),
                        build_city_photo(6, city="米兰", place="米兰大教堂"),
                    ]

                def list_country_descriptions(self):
                    return {
                        "意大利": {
                            "short_description": "意大利城市与教堂穹顶在光线里彼此呼应。",
                            "long_description": "完整导览文字。",
                        }
                    }

            app_module.storage = CityStorage()
            response = app_module.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        gallery_html = html.split('<section id="wallpaper-helper-guide"', 1)[0]
        self.assertEqual(len(self.collage_cards(gallery_html, card_kind="public-photo-card")), 4)
        self.assertIn("/gallery/country/%E6%84%8F%E5%A4%A7%E5%88%A9", html)
        self.assertIn("首页精选", html)

    def test_public_country_detail_page_renders_full_country_gallery(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            class CityStorage:
                def list_photos(self):
                    return [
                        build_city_photo(1, city="罗马", place="圣彼得大教堂"),
                        build_city_photo(2, city="罗马", place="斗兽场"),
                        build_city_photo(3, city="威尼斯", place="大运河"),
                        build_city_photo(4, city="威尼斯", place="圣马可广场"),
                        build_city_photo(5, city="佛罗伦萨", place="圣母百花大教堂"),
                        build_city_photo(6, city="米兰", place="米兰大教堂"),
                    ]

                def list_country_descriptions(self):
                    return {
                        "意大利": {
                            "short_description": "意大利城市与教堂穹顶在光线里彼此呼应。",
                            "long_description": "完整导览文字。",
                        }
                    }

            app_module.storage = CityStorage()
            response = app_module.app.test_client().get("/gallery/country/%E6%84%8F%E5%A4%A7%E5%88%A9")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.collage_cards(html, card_kind="public-photo-card")), 6)
        self.assertIn("返回公开展厅", html)
        self.assertIn("意大利", html)

    def test_country_preview_selection_prefers_distinct_cities(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            photos = [
                build_city_photo(1, city="罗马", place="圣彼得大教堂"),
                build_city_photo(2, city="罗马", place="斗兽场"),
                build_city_photo(3, city="威尼斯", place="大运河"),
                build_city_photo(4, city="威尼斯", place="圣马可广场"),
                build_city_photo(5, city="佛罗伦萨", place="圣母百花大教堂"),
                build_city_photo(6, city="米兰", place="米兰大教堂"),
            ]

            preview = app_module.select_country_preview_photos(photos, limit=4)

        self.assertEqual(len(preview), 4)
        self.assertEqual({photo["city"] for photo in preview}, {"罗马", "威尼斯", "佛罗伦萨", "米兰"})

    def test_delete_api_clears_preview_cache_and_preview_route_returns_404(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="false") as app_module:
            photo = app_module.storage.save_photo(
                FileStorage(
                    stream=BytesIO(b"preview-cache-demo"),
                    filename="delete-demo.jpg",
                    content_type="image/jpeg",
                ),
                "奥地利",
            )
            cache_path = app_module.preview_cache_path(photo["name"])
            cache_path.write_bytes(b"cached-preview")
            self.assertTrue(cache_path.exists())

            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["admin_authenticated"] = True
                session["admin_password_sig"] = app_module.current_password_signature()
                session["admin_username"] = app_module.admin_username()

            delete_response = client.delete(f"/api/photos/{urllib.parse.quote(photo['name'], safe='')}")
            preview_response = client.get(f"/photos-preview/{urllib.parse.quote(photo['name'], safe='')}")

        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(cache_path.exists())
        self.assertEqual(preview_response.status_code, 404)

    def test_stylesheet_uses_dense_square_collage_rules(self):
        css = self.stylesheet_source()
        collage_grid_block = self.selector_block(css, ".gallery-grid.collage-grid")
        self.assertIn("display: grid", collage_grid_block)
        self.assertIn("grid-auto-flow: dense", collage_grid_block)
        self.assertIn("gap: 2px", collage_grid_block)

        collage_tile_block = self.selector_block(css, ".photo-card.collage-tile")
        self.assertIn("aspect-ratio: 1 / 1", collage_tile_block)

        collage_image_block = self.selector_block(
            css,
            ".photo-card.collage-tile > .photo-view-button > img",
        )
        self.assertIn("width: 100%", collage_image_block)
        self.assertIn("height: 100%", collage_image_block)
        self.assertIn("object-fit: cover", collage_image_block)

        self.assertIn(".gallery-grid:not(.collage-grid)", css)
        self.assertNotIn(".collage-tile-hero", css)

        wide_block = self.selector_block(
            css,
            ".gallery-grid.collage-grid > .photo-card.collage-tile.collage-tile-wide",
        )
        self.assertIn("grid-column: span 2", wide_block)
        self.assertIn("grid-row: span 1", wide_block)
        self.assertIn("aspect-ratio: 2 / 1", wide_block)

        tall_block = self.selector_block(
            css,
            ".gallery-grid.collage-grid > .photo-card.collage-tile.collage-tile-tall",
        )
        self.assertIn("grid-column: span 1", tall_block)
        self.assertIn("grid-row: span 2", tall_block)
        self.assertIn("aspect-ratio: 1 / 2", tall_block)

        mobile_720 = self.media_query_block(css, "@media (max-width: 720px)")
        mobile_720_collage_block = self.selector_block(mobile_720, ".gallery-grid.collage-grid")
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile_720_collage_block)
        self.assertNotIn("column-count", mobile_720_collage_block)

        mobile_560 = self.media_query_block(css, "@media (max-width: 560px)")
        mobile_560_collage_block = self.selector_block(mobile_560, ".gallery-grid.collage-grid")
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile_560_collage_block)
        self.assertNotIn("column-count", mobile_560_collage_block)

        mobile_380 = self.media_query_block(css, "@media (max-width: 380px)")
        mobile_380_collage_block = self.selector_block(mobile_380, ".gallery-grid.collage-grid")
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile_380_collage_block)
        self.assertNotIn("column-count", mobile_380_collage_block)

    def test_stylesheet_centers_translucent_photo_caption(self):
        css = self.stylesheet_source()
        caption_block = self.selector_block(css, ".photo-card-caption")

        self.assertIn("text-align: center", caption_block)
        self.assertIn("opacity:", caption_block)
        self.assertIn("justify-self: center", caption_block)

    def test_preview_route_returns_compressed_image(self):
        buffer = BytesIO()
        Image.new("RGB", (2400, 1600), "#b55d3f").save(buffer, format="JPEG", quality=97)
        original_payload = buffer.getvalue()

        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            with patch.object(app_module.storage, "open_photo", return_value=(BytesIO(original_payload), "image/jpeg")):
                response = app_module.app.test_client().get("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg")

        self.assertEqual(response.status_code, 200)
        self.assertIn("image/jpeg", response.content_type)
        self.assertLess(len(response.data), len(original_payload))

    def test_preview_route_respects_width_query(self):
        buffer = BytesIO()
        Image.new("RGB", (2400, 1600), "#b55d3f").save(buffer, format="JPEG", quality=97)
        original_payload = buffer.getvalue()

        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            with patch.object(app_module.storage, "open_photo", return_value=(BytesIO(original_payload), "image/jpeg")):
                response = app_module.app.test_client().get("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg?w=720")

        self.assertEqual(response.status_code, 200)
        preview_image = Image.open(BytesIO(response.data))
        self.assertLessEqual(max(preview_image.size), 720)
        self.assertLess(len(response.data), len(original_payload))

    def test_preview_route_sets_public_cache_header(self):
        buffer = BytesIO()
        Image.new("RGB", (2400, 1600), "#b55d3f").save(buffer, format="JPEG", quality=97)
        original_payload = buffer.getvalue()

        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            with patch.object(app_module.storage, "open_photo", return_value=(BytesIO(original_payload), "image/jpeg")):
                response = app_module.app.test_client().get("/photos-preview/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo.jpg")

        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("public", cache_control)
        self.assertRegex(cache_control, r"max-age=\d+")

    def test_mobile_helper_sheet_mentions_download_only(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            app_module.storage = FakeStorage()
            response = app_module.app.test_client().get("/")

        html = response.get_data(as_text=True)
        mobile_section = re.search(r'<details class="helper-guide-mobile">(.+?)</details>', html, re.S)
        self.assertIsNotNone(mobile_section)
        assert mobile_section is not None
        section_html = mobile_section.group(1)
        self.assertIn("下载原图", section_html)
        self.assertNotIn("一键设为当前电脑壁纸", section_html)

    def test_start_script_keeps_both_services_running_after_exit(self):
        admin_port = pick_free_port()
        public_port = pick_free_port()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            env = os.environ.copy()
            env.update(
                base_env(
                    temp_dir,
                    APP_HOST="127.0.0.1",
                    FLASK_DEBUG="false",
                    ADMIN_PORT=str(admin_port),
                    PUBLIC_PORT=str(public_port),
                    RUNTIME_DIR_OVERRIDE=str(runtime_dir),
                    PYTHON_BIN=sys.executable,
                )
            )

            try:
                result = subprocess.run(
                    ["./scripts/start_local_gallery_stack.sh"],
                    cwd=PROJECT_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

                time.sleep(4)
                admin_health = urllib.request.urlopen(f"http://127.0.0.1:{admin_port}/healthz", timeout=5).read().decode("utf-8")
                public_health = urllib.request.urlopen(f"http://127.0.0.1:{public_port}/healthz", timeout=5).read().decode("utf-8")
            finally:
                subprocess.run(
                    ["./scripts/stop_local_gallery_stack.sh"],
                    cwd=PROJECT_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )

        self.assertIn('"ok":true', admin_health)
        self.assertIn('"ok":true', public_health)

    def test_one_click_public_share_launchers_exist(self):
        start_launcher = (PROJECT_ROOT / "start_public_gallery_share.command").read_text(encoding="utf-8")
        stop_launcher = (PROJECT_ROOT / "stop_public_gallery_share.command").read_text(encoding="utf-8")

        self.assertIn("./scripts/install_cloudflared_local.sh", start_launcher)
        self.assertIn("./scripts/start_local_gallery_stack.sh", start_launcher)
        self.assertIn("./scripts/share_public_quick_tunnel.sh", start_launcher)
        self.assertIn("./scripts/stop_local_gallery_stack.sh", stop_launcher)

    def test_quick_tunnel_script_supports_local_cloudflared_binary(self):
        share_script = (PROJECT_ROOT / "scripts" / "share_public_quick_tunnel.sh").read_text(encoding="utf-8")
        installer_script = (PROJECT_ROOT / "scripts" / "install_cloudflared_local.sh").read_text(encoding="utf-8")

        self.assertIn('LOCAL_CLOUDFLARED_BIN="$ROOT_DIR/tools/cloudflared"', share_script)
        self.assertIn("github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin", installer_script)

    def test_lightbox_script_hides_wallpaper_button_on_mobile(self):
        script = (PROJECT_ROOT / "static" / "photo-lightbox.js").read_text(encoding="utf-8")

        self.assertIn('window.matchMedia("(max-width: 720px)")', script)
        self.assertIn("lightboxWallpaperButton.hidden = isMobileLightbox", script)
        self.assertIn("downloadUrl", script)


if __name__ == "__main__":
    unittest.main()
