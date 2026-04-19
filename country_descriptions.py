from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import requests
from requests import RequestException

from storage import normalize_photo_ai_metadata

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageOps = None


GEMINI_PROVIDER = "gemini"
GROQ_PROVIDER = "groq"
GENERIC_TASK = "generic"
PHOTO_METADATA_TASK = "photo_metadata"
COUNTRY_INTRO_TASK = "country_intro"

GEMINI_GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
GROQ_DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
INTRO_COMPLETION_TOKENS = 420
INTRO_BUDGET_COMPLETION_TOKENS = 320
SUMMARY_COMPLETION_TOKENS = 220
PHOTO_METADATA_COMPLETION_TOKENS = 220
PHOTO_METADATA_BUDGET_COMPLETION_TOKENS = 140
DEFAULT_REQUEST_RETRIES = 4
DEFAULT_RETRY_DELAY_SECONDS = 2.0


class CountryDescriptionError(RuntimeError):
    pass


class CountryDescriptionUnavailable(CountryDescriptionError):
    pass


@dataclass
class CountryPhotoSample:
    name: str
    title: str
    content_type: str | None
    payload: bytes


class CountryDescriptionGenerator:
    def __init__(self, task: str = GENERIC_TASK) -> None:
        self.task = task
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

        if self.task == PHOTO_METADATA_TASK:
            requested_provider = os.getenv("PHOTO_METADATA_PROVIDER", "").strip().lower()
            if requested_provider in {GROQ_PROVIDER, GEMINI_PROVIDER}:
                self.provider = requested_provider
            elif gemini_key:
                self.provider = GEMINI_PROVIDER
            else:
                self.provider = GROQ_PROVIDER

            if self.provider == GEMINI_PROVIDER:
                self.api_key = gemini_key
                self.model = (
                    os.getenv("PHOTO_METADATA_GEMINI_MODEL", "").strip()
                    or os.getenv("GEMINI_VISION_MODEL", "").strip()
                    or GEMINI_DEFAULT_MODEL
                )
                self.timeout = int(
                    os.getenv(
                        "PHOTO_METADATA_TIMEOUT_SECONDS",
                        os.getenv("GEMINI_TIMEOUT_SECONDS", os.getenv("COUNTRY_DESCRIPTION_TIMEOUT_SECONDS", "60")),
                    )
                    or "60"
                )
            else:
                self.api_key = groq_key
                self.model = (
                    os.getenv("PHOTO_METADATA_GROQ_MODEL", "").strip()
                    or os.getenv("GROQ_VISION_MODEL", "").strip()
                    or GROQ_DEFAULT_MODEL
                )
                self.timeout = int(
                    os.getenv(
                        "PHOTO_METADATA_TIMEOUT_SECONDS",
                        os.getenv("GROQ_TIMEOUT_SECONDS", os.getenv("COUNTRY_DESCRIPTION_TIMEOUT_SECONDS", "60")),
                    )
                    or "60"
                )
            default_image_limit = 5
            default_image_edge = "640"
            default_image_bytes = "140000"
            self.intro_completion_tokens = INTRO_COMPLETION_TOKENS
            self.photo_metadata_completion_tokens = max(
                80,
                int(
                    os.getenv(
                        "PHOTO_METADATA_MAX_COMPLETION_TOKENS",
                        str(PHOTO_METADATA_BUDGET_COMPLETION_TOKENS),
                    )
                    or str(PHOTO_METADATA_BUDGET_COMPLETION_TOKENS)
                ),
            )
        elif self.task == COUNTRY_INTRO_TASK:
            self.provider = GEMINI_PROVIDER
            self.api_key = gemini_key
            self.model = (
                os.getenv("COUNTRY_INTRO_GEMINI_MODEL", "").strip()
                or os.getenv("GEMINI_TEXT_MODEL", "").strip()
                or os.getenv("GEMINI_VISION_MODEL", "").strip()
                or GEMINI_DEFAULT_MODEL
            )
            self.timeout = int(
                os.getenv(
                    "COUNTRY_INTRO_TIMEOUT_SECONDS",
                    os.getenv("GEMINI_TIMEOUT_SECONDS", os.getenv("COUNTRY_DESCRIPTION_TIMEOUT_SECONDS", "60")),
                )
                or "60"
            )
            default_image_limit = 1
            default_image_edge = "960"
            default_image_bytes = "260000"
            self.intro_completion_tokens = max(
                120,
                int(
                    os.getenv(
                        "COUNTRY_INTRO_MAX_COMPLETION_TOKENS",
                        str(INTRO_BUDGET_COMPLETION_TOKENS),
                    )
                    or str(INTRO_BUDGET_COMPLETION_TOKENS)
                ),
            )
            self.photo_metadata_completion_tokens = PHOTO_METADATA_COMPLETION_TOKENS
        else:
            requested_provider = os.getenv("COUNTRY_DESCRIPTION_PROVIDER", "").strip().lower()
            if requested_provider in {GROQ_PROVIDER, GEMINI_PROVIDER}:
                self.provider = requested_provider
            elif groq_key:
                self.provider = GROQ_PROVIDER
            else:
                self.provider = GEMINI_PROVIDER

            if self.provider == GROQ_PROVIDER:
                self.api_key = groq_key
                self.model = os.getenv("GROQ_VISION_MODEL", GROQ_DEFAULT_MODEL).strip() or GROQ_DEFAULT_MODEL
                self.timeout = int(
                    os.getenv("GROQ_TIMEOUT_SECONDS", os.getenv("COUNTRY_DESCRIPTION_TIMEOUT_SECONDS", "60")) or "60"
                )
                default_image_limit = 5
                default_image_edge = "768"
                default_image_bytes = "180000"
            else:
                self.api_key = gemini_key
                self.model = os.getenv("GEMINI_VISION_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL
                self.timeout = int(
                    os.getenv("GEMINI_TIMEOUT_SECONDS", os.getenv("COUNTRY_DESCRIPTION_TIMEOUT_SECONDS", "60")) or "60"
                )
                default_image_limit = 3
                default_image_edge = "960"
                default_image_bytes = "260000"

            self.intro_completion_tokens = INTRO_COMPLETION_TOKENS
            self.photo_metadata_completion_tokens = PHOTO_METADATA_COMPLETION_TOKENS

        self.image_limit = max(
            1,
            int(os.getenv("COUNTRY_DESCRIPTION_IMAGE_LIMIT", str(default_image_limit)) or str(default_image_limit)),
        )
        if self.provider == GROQ_PROVIDER:
            self.image_limit = min(5, self.image_limit)

        image_edge_env_name = "PHOTO_METADATA_MAX_EDGE" if self.task == PHOTO_METADATA_TASK else "COUNTRY_DESCRIPTION_MAX_EDGE"
        image_bytes_env_name = "PHOTO_METADATA_MAX_BYTES" if self.task == PHOTO_METADATA_TASK else "COUNTRY_DESCRIPTION_MAX_BYTES"
        self.max_image_edge = max(512, int(os.getenv(image_edge_env_name, default_image_edge) or default_image_edge))
        self.max_image_bytes = max(
            120_000 if self.task == PHOTO_METADATA_TASK else 180_000,
            int(os.getenv(image_bytes_env_name, default_image_bytes) or default_image_bytes),
        )

        retries_env_name = {
            PHOTO_METADATA_TASK: "PHOTO_METADATA_REQUEST_RETRIES",
            COUNTRY_INTRO_TASK: "COUNTRY_INTRO_REQUEST_RETRIES",
        }.get(self.task, "COUNTRY_DESCRIPTION_REQUEST_RETRIES")
        self.max_request_retries = max(
            1,
            int(os.getenv(retries_env_name, str(DEFAULT_REQUEST_RETRIES)) or str(DEFAULT_REQUEST_RETRIES)),
        )

        retry_delay_env_name = {
            PHOTO_METADATA_TASK: "PHOTO_METADATA_RETRY_DELAY_SECONDS",
            COUNTRY_INTRO_TASK: "COUNTRY_INTRO_RETRY_DELAY_SECONDS",
        }.get(self.task, "COUNTRY_DESCRIPTION_RETRY_DELAY_SECONDS")
        self.default_retry_delay_seconds = max(
            0.5,
            float(
                os.getenv(
                    retry_delay_env_name,
                    str(DEFAULT_RETRY_DELAY_SECONDS),
                )
                or str(DEFAULT_RETRY_DELAY_SECONDS)
            ),
        )

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def availability_message(self) -> str:
        if not self.api_key:
            missing_env = "GROQ_API_KEY" if self.provider == GROQ_PROVIDER else "GEMINI_API_KEY"
            return f"未配置 {missing_env}，暂时无法{self._task_action_label()}。"
        if self.task == PHOTO_METADATA_TASK and (Image is None or ImageOps is None):
            return "未安装 Pillow，暂时无法压缩图片并识别照片元数据。"
        return ""

    def describe_country(
        self,
        country: str,
        photos: list[CountryPhotoSample],
        *,
        previous_short_description: str = "",
        previous_long_description: str = "",
    ) -> dict[str, str]:
        availability_issue = self.availability_message()
        if availability_issue:
            raise CountryDescriptionUnavailable(availability_issue)

        if not photos:
            raise CountryDescriptionError("没有可用于生成介绍的照片。")

        if len(photos) <= self.image_limit:
            output_text = self._request_generation_text(
                self._build_intro_payload_from_images(
                    country,
                    photos,
                    previous_short_description=previous_short_description,
                    previous_long_description=previous_long_description,
                )
            )
            return self._parse_intro_response(output_text)

        batch_summaries = self._summarize_photo_batches(country, photos)
        output_text = self._request_generation_text(
            self._build_intro_payload_from_batch_summaries(
                country,
                photos,
                batch_summaries,
                previous_short_description=previous_short_description,
                previous_long_description=previous_long_description,
            )
        )
        return self._parse_intro_response(output_text)

    def describe_photo_metadata(self, country: str, photo: CountryPhotoSample) -> dict[str, str]:
        availability_issue = self.availability_message()
        if availability_issue:
            raise CountryDescriptionUnavailable(availability_issue)

        output_text = self._request_generation_text(
            self._build_photo_metadata_payload(
                country,
                photo,
            )
        )
        return self._parse_photo_metadata_response(output_text)

    def describe_country_from_metadata(
        self,
        country: str,
        photo_metadata_list: list[dict[str, Any]],
        *,
        previous_short_description: str = "",
        previous_long_description: str = "",
    ) -> dict[str, str]:
        availability_issue = self.availability_message()
        if availability_issue:
            raise CountryDescriptionUnavailable(availability_issue)

        normalized_metadata = [
            normalize_photo_ai_metadata(item)
            for item in photo_metadata_list
            if any(str((item or {}).get(field) or "").strip() for field in ("city", "place", "subject", "scene_summary"))
        ]
        if not normalized_metadata:
            raise CountryDescriptionError("没有可用于生成介绍的照片元数据。")

        output_text = self._request_generation_text(
            self._build_intro_payload_from_photo_metadata(
                country,
                normalized_metadata,
                previous_short_description=previous_short_description,
                previous_long_description=previous_long_description,
            )
        )
        return self._parse_intro_response(output_text)

    def _build_intro_payload_from_images(
        self,
        country: str,
        photos: list[CountryPhotoSample],
        *,
        previous_short_description: str,
        previous_long_description: str,
    ) -> dict[str, Any]:
        user_text = (
            f"国家章节名称：{country}\n"
            f"本次新增照片数量：{len(photos)} 张。\n"
            f"当前已有短介绍：{previous_short_description or '（无）'}\n"
            f"当前已有详细导览：{previous_long_description or '（无）'}\n"
            "请只根据这些照片可确认的内容增量修订文案，保留旧文案的整体气质与叙述主线；"
            "优先识别出可明确判断的城市、地标或景点，如果把握不足，就改用更稳妥的场景与建筑类型表述，不要硬猜，也不要复述文件名。"
        )
        system_prompt = (
            "你是摄影展览的中文文字编辑。你会根据同一国家的一组照片，"
            "为国家章节输出一条短题记和一段详细导览。"
            "要求："
            "1. 使用简体中文，语气优雅、克制，像展览前言，不像旅游攻略或宣传文案。"
            "2. 优先识别照片中能够高置信度判断的城市、地标或景点名称；如果无法高置信度确认，就不要硬猜，改写成旧城广场、峡湾湖岸、巴洛克立面、雪山谷地、海港街区之类的稳妥描述。"
            "3. 必须概括照片里出现了哪些地点类型与场景线索，例如山谷、湖岸、街巷、旧城、教堂、雪山、林地、河流、屋顶、广场、海湾、港口、桥梁、宫殿、修道院等。"
            "4. 除了单张照片的画面内容，还要从国家层面提炼建筑、自然与文化气质，例如立面风格、城市肌理、山海关系、生活秩序、历史感、宗教感、航海气质、王朝痕迹或度假气息。"
            "5. 文风要有展览导言的高级感与纵深感，用完整而有节奏的句子把地点、建筑、自然和文化线索串起来，避免空泛辞藻堆砌。"
            "6. 不要编造看不出来的事实，不要写拍摄器材、拍摄时间、作者心情，也不要出现“可能”“似乎”这类含糊判断。"
            "7. 必须只返回 JSON，并且包含 short_description 与 long_description 两个字段。"
            "8. short_description 要像章节题记，只写一句，不展开细节，控制在 14 到 24 个汉字之间。"
            "9. long_description 必须明显长于 short_description，写成一段完整、流动、可朗读的策展导览，控制在 220 到 360 个汉字之间。"
            "10. long_description 不要只是把 short_description 换一种说法扩写，必须补足地点层次、建筑或自然结构、文化气质与观看路径。"
        )
        return self._build_generation_payload(
            system_prompt=system_prompt,
            user_text=user_text,
            photos=photos,
            json_output=True,
            temperature=0.35,
            max_completion_tokens=INTRO_COMPLETION_TOKENS,
            response_schema_name="country_intro",
        )

    def _build_intro_payload_from_batch_summaries(
        self,
        country: str,
        photos: list[CountryPhotoSample],
        batch_summaries: list[str],
        *,
        previous_short_description: str,
        previous_long_description: str,
    ) -> dict[str, Any]:
        merged_summaries = "\n".join(
            f"第 {index + 1} 批新增照片摘要：{summary}"
            for index, summary in enumerate(batch_summaries)
            if summary.strip()
        )
        user_text = (
            f"国家章节名称：{country}\n"
            f"本次新增照片总数：{len(photos)} 张。\n"
            f"当前已有短介绍：{previous_short_description or '（无）'}\n"
            f"当前已有详细导览：{previous_long_description or '（无）'}\n"
            "下面是按批次整理后的新增照片视觉信息，请综合全部批次内容，并在保留旧文案叙述主线与气质的前提下，"
            "把这次新增照片里出现的地点、建筑、自然与文化线索都并入新的国家章节文案。\n"
            f"{merged_summaries}"
        )

        system_prompt = (
            "你是摄影展览的中文文字编辑。你会根据同一国家的一组照片摘要，"
            "为国家章节输出一条短题记和一段详细导览。"
            "要求："
            "1. 使用简体中文，语气优雅、克制，像展览前言，不像旅游攻略或宣传文案。"
            "2. 必须综合全部批次摘要，不要遗漏后面批次中的新地点、新景观或新建筑线索。"
            "3. 优先保留旧文案的叙述主线，再把这次新增照片中的城市、地标、街区、自然景观和文化特征准确并入。"
            "4. 如果某些城市或景点名称无法高置信度判断，就改用更稳妥的场景与建筑类型表述，不要硬猜。"
            "5. 必须只返回 JSON，并且包含 short_description 与 long_description 两个字段。"
            "6. short_description 要像章节题记，只写一句，不展开细节，控制在 14 到 24 个汉字之间。"
            "7. long_description 必须明显长于 short_description，写成一段完整、流动、可朗读的策展导览，控制在 220 到 360 个汉字之间。"
            "8. long_description 不要只是把 short_description 换一种说法扩写，必须补足地点层次、建筑或自然结构、文化气质与观看路径。"
        )
        return self._build_generation_payload(
            system_prompt=system_prompt,
            user_text=user_text,
            photos=[],
            json_output=True,
            temperature=0.3,
            max_completion_tokens=INTRO_COMPLETION_TOKENS,
            response_schema_name="country_intro",
        )

    def _build_intro_payload_from_photo_metadata(
        self,
        country: str,
        photo_metadata_list: list[dict[str, str]],
        *,
        previous_short_description: str,
        previous_long_description: str,
    ) -> dict[str, Any]:
        formatted_metadata_lines = []
        for index, item in enumerate(photo_metadata_list, start=1):
            parts = []
            if item.get("city"):
                parts.append(f"城市：{item['city']}")
            if item.get("place"):
                parts.append(f"地点：{item['place']}")
            if item.get("subject"):
                parts.append(f"主体：{item['subject']}")
            if item.get("scene_summary"):
                parts.append(f"摘要：{item['scene_summary']}")
            formatted_metadata_lines.append(
                f"{index}. " + "；".join(parts or ["线索缺失"])
            )

        user_text = (
            f"国家章节名称：{country}\n"
            f"本次纳入修订的照片元数据数量：{len(photo_metadata_list)} 条。\n"
            f"当前已有短介绍：{previous_short_description or '（无）'}\n"
            f"当前已有详细导览：{previous_long_description or '（无）'}\n"
            "下面是逐张照片整理出的城市、地点、主体与场景摘要，请基于这些元数据修订国家章节文案，"
            "保留旧文案的整体气质与叙述主线，并把新的城市、景点、建筑、自然与文化线索准确并入。\n"
            + "\n".join(formatted_metadata_lines)
        )
        system_prompt = (
            "你是摄影展览的中文文字编辑。你会根据同一国家的一组照片元数据，"
            "为国家章节输出一条短题记和一段详细导览。"
            "要求："
            "1. 使用简体中文，优先使用中国大陆用户更常见的中文译名。"
            "2. 只能根据给定元数据写作，不要编造画面外事实。"
            "3. 需要综合城市、景点、建筑、自然地貌与文化气质，把分散的地点线索串成一段完整叙述。"
            "4. 优先保留旧文案的叙述主线，再把本次新增线索自然并入。"
            "5. 语气优雅、克制，像展览导言，不像旅游攻略。"
            "6. 必须只返回 JSON，并且包含 short_description 与 long_description 两个字段。"
            "7. short_description 要像章节题记，只写一句，不展开细节，控制在 14 到 24 个汉字之间。"
            "8. long_description 必须明显长于 short_description，写成一段完整、流动、可朗读的策展导览，控制在 220 到 360 个汉字之间。"
            "9. long_description 不要只是把 short_description 换一种说法扩写，必须把城市、景点、建筑、地貌与气氛自然组织成完整段落。"
        )
        return self._build_generation_payload(
            system_prompt=system_prompt,
            user_text=user_text,
            photos=[],
            json_output=True,
            temperature=0.25,
            max_completion_tokens=self.intro_completion_tokens,
            response_schema_name="country_intro",
        )

    def _summarize_photo_batches(self, country: str, photos: list[CountryPhotoSample]) -> list[str]:
        summaries: list[str] = []
        batches = self._chunk_photos(photos)
        for index, batch in enumerate(batches):
            output_text = self._request_generation_text(
                self._build_photo_batch_summary_payload(country, batch, batch_index=index + 1, batch_total=len(batches))
            )
            summary = " ".join(output_text.split())
            if summary:
                summaries.append(summary)
        if not summaries:
            raise CountryDescriptionError("Gemini 没有返回可用的新增照片摘要。")
        return summaries

    def _chunk_photos(self, photos: list[CountryPhotoSample]) -> list[list[CountryPhotoSample]]:
        return [photos[index : index + self.image_limit] for index in range(0, len(photos), self.image_limit)]

    def _build_photo_batch_summary_payload(
        self,
        country: str,
        photos: list[CountryPhotoSample],
        *,
        batch_index: int,
        batch_total: int,
    ) -> dict[str, Any]:
        user_text = (
            f"国家章节名称：{country}\n"
            f"这是第 {batch_index} / {batch_total} 批新增照片，共 {len(photos)} 张。\n"
            "请只根据这一批照片，提炼出可确认的城市或景点名称，以及场景、建筑、自然与文化线索，"
            "为后续总文案合成提供一段高信息密度的中文摘要。"
        )
        system_prompt = (
            "你是摄影资料整理助手。请阅读这一批照片并输出一段中文摘要。"
            "要求："
            "1. 只写这一批照片里可确认的视觉线索，不要编造。"
            "2. 优先写可确认的城市、地标、街区或景点；没有把握时，改用旧城广场、海港街区、雪山谷地、教堂立面、河岸街巷等稳妥表述。"
            "3. 必须覆盖建筑、自然、文化与场景信息，尽量避免遗漏。"
            "4. 只返回一段简体中文，不要 JSON，不要项目符号，不要解释过程。"
            "5. 控制在 90 到 180 个汉字之间，信息密度高，方便后续合成国家章节导览。"
        )
        return self._build_generation_payload(
            system_prompt=system_prompt,
            user_text=user_text,
            photos=photos,
            json_output=False,
            temperature=0.2,
            max_completion_tokens=SUMMARY_COMPLETION_TOKENS,
        )

    def _build_photo_metadata_payload(
        self,
        country: str,
        photo: CountryPhotoSample,
    ) -> dict[str, Any]:
        user_text = (
            f"国家章节名称：{country}\n"
            f"照片文件名：{photo.name}\n"
            f"已有标题：{photo.title or '（无）'}\n"
            "请识别这张照片最可能对应的城市或地区、具体景点或地点、画面主体，以及一句高信息密度的场景摘要。"
        )
        system_prompt = (
            "你是摄影资料整理助手。请为单张旅行照片提取结构化元数据。"
            "要求："
            "1. 使用简体中文，且必须使用中国大陆用户更常见的中文译名。"
            "2. 优先识别可高置信度判断的城市、地区、景点或街区名称；没有把握时，不要硬猜，可以留空。"
            "3. subject 要概括画面主体，例如教堂立面、湖畔小镇、港口街区、雪山岸线、旧城广场。"
            "4. scene_summary 用一句 28 到 60 个汉字的完整中文句子，把地点与景观特征串起来。"
            "5. 只返回 JSON，字段必须包含 city、place、subject、scene_summary。"
        )
        return self._build_generation_payload(
            system_prompt=system_prompt,
            user_text=user_text,
            photos=[photo],
            json_output=True,
            temperature=0.1,
            max_completion_tokens=self.photo_metadata_completion_tokens,
            response_schema_name="photo_metadata",
        )

    def _build_generation_payload(
        self,
        *,
        system_prompt: str,
        user_text: str,
        photos: list[CountryPhotoSample],
        json_output: bool,
        temperature: float,
        max_completion_tokens: int,
        response_schema_name: str | None = None,
    ) -> dict[str, Any]:
        if self.provider == GROQ_PROVIDER:
            return self._build_groq_payload(
                system_prompt=system_prompt,
                user_text=user_text,
                photos=photos,
                json_output=json_output,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                response_schema_name=response_schema_name,
            )
        return self._build_gemini_payload(
            system_prompt=system_prompt,
            user_text=user_text,
            photos=photos,
            json_output=json_output,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            response_schema_name=response_schema_name,
        )

    def _build_gemini_payload(
        self,
        *,
        system_prompt: str,
        user_text: str,
        photos: list[CountryPhotoSample],
        json_output: bool,
        temperature: float,
        max_completion_tokens: int,
        response_schema_name: str | None,
    ) -> dict[str, Any]:
        user_parts: list[dict[str, Any]] = [{"text": user_text}]
        for photo in photos:
            user_parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": self._build_inline_image_data(photo),
                    }
                }
            )

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": user_parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_completion_tokens,
                # Disable Gemini thinking for this workflow so JSON mode has enough output budget
                # and country intro generation stays on the lowest practical cost profile.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if json_output:
            payload["generationConfig"].update(
                {
                    "responseMimeType": "application/json",
                    "responseSchema": self._schema_for_provider(response_schema_name or "country_intro"),
                }
            )
        return payload

    def _build_groq_payload(
        self,
        *,
        system_prompt: str,
        user_text: str,
        photos: list[CountryPhotoSample],
        json_output: bool,
        temperature: float,
        max_completion_tokens: int,
        response_schema_name: str | None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for photo in photos:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": self._build_image_data_url(photo),
                    },
                }
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
        }
        if json_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema_name or "country_intro",
                    "schema": self._schema_for_provider(response_schema_name or "country_intro"),
                },
            }
        return payload

    def _schema_for_provider(self, name: str) -> dict[str, Any]:
        if self.provider == GROQ_PROVIDER:
            if name == "photo_metadata":
                return self._groq_photo_metadata_response_schema()
            return self._groq_intro_response_schema()
        if name == "photo_metadata":
            return self._gemini_photo_metadata_response_schema()
        return self._gemini_intro_response_schema()

    def _gemini_intro_response_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "short_description": {
                    "type": "STRING",
                    "description": "主界面常驻显示的一句短题记。",
                },
                "long_description": {
                    "type": "STRING",
                    "description": "展开后显示的一段完整国家章节导览文字。",
                },
            },
            "required": ["short_description", "long_description"],
        }

    def _groq_intro_response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "short_description": {
                    "type": "string",
                    "description": "主界面常驻显示的一句短题记。",
                },
                "long_description": {
                    "type": "string",
                    "description": "展开后显示的一段完整国家章节导览文字。",
                },
            },
            "required": ["short_description", "long_description"],
        }

    def _gemini_photo_metadata_response_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING"},
                "place": {"type": "STRING"},
                "subject": {"type": "STRING"},
                "scene_summary": {"type": "STRING"},
            },
            "required": ["city", "place", "subject", "scene_summary"],
        }

    def _groq_photo_metadata_response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "city": {"type": "string"},
                "place": {"type": "string"},
                "subject": {"type": "string"},
                "scene_summary": {"type": "string"},
            },
            "required": ["city", "place", "subject", "scene_summary"],
        }

    def _request_generation_text(self, payload: dict[str, Any]) -> str:
        last_error_message = ""
        for attempt in range(1, self.max_request_retries + 1):
            try:
                if self.provider == GROQ_PROVIDER:
                    response = requests.post(
                        GROQ_CHAT_COMPLETIONS_URL,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=self.timeout,
                    )
                else:
                    response = requests.post(
                        GEMINI_GENERATE_CONTENT_URL.format(model=self.model),
                        headers={
                            "x-goog-api-key": self.api_key,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=self.timeout,
                    )
            except RequestException as exc:
                raise CountryDescriptionError(self._normalize_error_message(str(exc))) from exc

            try:
                response_payload = response.json()
            except ValueError as exc:
                raise CountryDescriptionError("AI 服务返回了无效数据。") from exc

            if response.ok:
                output_text = self._extract_response_text(response_payload).strip()
                if not output_text:
                    raise CountryDescriptionError(f"{self._provider_label()} 没有返回可用的{self._task_output_label()}。")
                return output_text

            error_message = self._extract_error_message(response_payload) or f"{self._provider_label()} 服务请求失败（{response.status_code}）。"
            last_error_message = error_message
            if self._should_retry(response.status_code, error_message) and attempt < self.max_request_retries:
                time.sleep(self._retry_delay_seconds(response, error_message))
                continue
            raise CountryDescriptionError(self._normalize_error_message(error_message))

        raise CountryDescriptionError(self._normalize_error_message(last_error_message))

    def _parse_intro_response(self, output_text: str) -> dict[str, str]:
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise CountryDescriptionError(f"{self._provider_label()} 返回的国家介绍格式不正确。") from exc

        short_description = self._normalize_intro_text(parsed.get("short_description"), limit=80)
        long_description = self._normalize_intro_text(parsed.get("long_description"), limit=420)
        if not short_description or not long_description:
            raise CountryDescriptionError(f"{self._provider_label()} 没有返回有效的国家介绍。")
        return {
            "short_description": short_description,
            "long_description": long_description,
        }

    def _parse_photo_metadata_response(self, output_text: str) -> dict[str, str]:
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise CountryDescriptionError(f"{self._provider_label()} 返回的照片元数据格式不正确。") from exc

        normalized = normalize_photo_ai_metadata(parsed)
        if not any(normalized.values()):
            raise CountryDescriptionError(f"{self._provider_label()} 没有返回可用的照片元数据。")
        return normalized

    def _build_inline_image_data(self, photo: CountryPhotoSample) -> str:
        if Image is None or ImageOps is None:
            raise CountryDescriptionUnavailable("未安装 Pillow，暂时无法压缩图片并生成国家介绍。")

        try:
            image = Image.open(BytesIO(photo.payload))
        except Exception as exc:
            raise CountryDescriptionError(f"读取图片失败：{photo.name}") from exc

        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        elif image.mode == "L":
            image = image.convert("RGB")

        image.thumbnail((self.max_image_edge, self.max_image_edge))

        encoded_payload = self._encode_jpeg(image)
        return base64.b64encode(encoded_payload).decode("ascii")

    def _build_image_data_url(self, photo: CountryPhotoSample) -> str:
        return f"data:image/jpeg;base64,{self._build_inline_image_data(photo)}"

    def _encode_jpeg(self, image: Any) -> bytes:
        for quality in (86, 80, 74, 68, 62):
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
            payload = buffer.getvalue()
            if len(payload) <= self.max_image_bytes or quality == 62:
                return payload
        raise CountryDescriptionError("图片压缩失败。")

    def _extract_error_message(self, payload: dict[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return ""

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                    if texts:
                        return "\n".join(texts)

        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return ""

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            texts = [str(part.get("text") or "").strip() for part in parts if isinstance(part, dict) and part.get("text")]
            if texts:
                return "\n".join(texts)

        return ""

    def _normalize_error_message(self, message: str) -> str:
        normalized = " ".join(str(message or "").split())
        lowered = normalized.lower()
        if any(token in lowered for token in ("resource_exhausted", "quota", "rate limit", "too many requests", "429")):
            if self.provider == GROQ_PROVIDER:
                return f"Groq 免费额度已用完或触发限流，已保留当前{self._task_preserved_label()}。"
            return f"Gemini 免费额度已用完，已保留当前{self._task_preserved_label()}。"
        if "timed out" in lowered or "read timeout" in lowered or "connect timeout" in lowered:
            return f"{self._provider_label()} 响应超时，已保留当前{self._task_preserved_label()}。"
        if any(token in lowered for token in ("unauthorized", "invalid api key", "incorrect api key", "authentication", "401")):
            return f"{self._provider_label()} API Key 无效，或当前模型没有访问权限。"
        return normalized or f"{self._provider_label()} 服务暂时不可用。"

    def _normalize_intro_text(self, value: Any, *, limit: int) -> str:
        return " ".join(str(value or "").split())[:limit]

    def _provider_label(self) -> str:
        return "Groq" if self.provider == GROQ_PROVIDER else "Gemini"

    def _task_action_label(self) -> str:
        if self.task == PHOTO_METADATA_TASK:
            return "识别照片元数据"
        return "自动生成国家介绍"

    def _task_output_label(self) -> str:
        if self.task == PHOTO_METADATA_TASK:
            return "照片元数据"
        return "国家介绍"

    def _task_preserved_label(self) -> str:
        if self.task == PHOTO_METADATA_TASK:
            return "照片元数据"
        return "国家介绍"

    def _should_retry(self, status_code: int, message: str) -> bool:
        lowered = " ".join(str(message or "").split()).lower()
        if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
            return True
        return any(token in lowered for token in ("rate limit", "try again in", "temporarily unavailable", "overloaded"))

    def _retry_delay_seconds(self, response: Any, message: str) -> float:
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.5, float(retry_after))
            except (TypeError, ValueError):
                pass

        match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", str(message or ""), flags=re.IGNORECASE)
        if match:
            try:
                return max(0.5, float(match.group(1)) + 0.5)
            except (TypeError, ValueError):
                pass

        return self.default_retry_delay_seconds
