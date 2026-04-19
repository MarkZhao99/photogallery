import importlib
import os
import sys
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from requests.exceptions import ReadTimeout


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = headers or {}

    def json(self):
        return self._payload


class CountryDescriptionsTests(unittest.TestCase):
    def test_photo_metadata_task_prefers_gemini_when_available_and_uses_budget_settings(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_VISION_MODEL": "gemini-2.5-flash",
                "GEMINI_TIMEOUT_SECONDS": "45",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator(task="photo_metadata")

            image_buffer = BytesIO()
            Image.new("RGB", (1400, 1000), "#8c725c").save(image_buffer, format="JPEG", quality=92)
            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": '{"city":"特罗姆瑟","place":"海港旧城","subject":"雪山与港口街区","scene_summary":"雪山、海港与木屋街区在冷光中交织。"}'
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
            ) as post_mock:
                metadata = generator.describe_photo_metadata("挪威", photo)

        self.assertEqual(generator.provider, "gemini")
        self.assertEqual(generator.task, "photo_metadata")
        self.assertEqual(metadata["city"], "特罗姆瑟")
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 140)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")

    def test_photo_metadata_task_falls_back_to_groq_when_gemini_unavailable(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GROQ_VISION_MODEL": "meta-llama/llama-4-scout-17b-16e-instruct",
                "GROQ_TIMEOUT_SECONDS": "30",
                "GEMINI_API_KEY": "",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator(task="photo_metadata")

        self.assertEqual(generator.provider, "groq")

    def test_country_intro_task_defaults_to_gemini_and_uses_text_only_payload(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_VISION_MODEL": "gemini-2.5-flash",
                "GEMINI_TIMEOUT_SECONDS": "45",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator(task="country_intro")

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": '{"short_description":"雪山港城与峡湾暮色连成一体。","long_description":"这组挪威影像把特罗姆瑟的海港街区、卑尔根的港口立面与峡湾暮色串联起来，让北方城市的木屋秩序、雪山岸线和海风气息在同一段叙述里缓慢展开。"}'
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
            ) as post_mock:
                description = generator.describe_country_from_metadata(
                    "挪威",
                    [
                        {"city": "特罗姆瑟", "place": "海港旧城", "subject": "雪山与港口街区", "scene_summary": "雪山、海港与木屋街区在冷光中交织。"},
                        {"city": "卑尔根", "place": "布吕根码头", "subject": "彩色港口建筑", "scene_summary": "彩色立面沿港口延展开来。"},
                    ],
                    previous_short_description="旧短介绍",
                    previous_long_description="旧长介绍",
                )

        self.assertEqual(generator.provider, "gemini")
        self.assertEqual(generator.task, "country_intro")
        self.assertEqual(description["short_description"], "雪山港城与峡湾暮色连成一体。")
        call = post_mock.call_args
        self.assertEqual(
            call.args[0],
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        )
        payload = call.kwargs["json"]
        self.assertEqual(len(payload["contents"][0]["parts"]), 1)
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 320)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0)
        self.assertIn("systemInstruction", payload)

    def test_groq_generator_extracts_photo_metadata_with_json_schema(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GROQ_VISION_MODEL": "meta-llama/llama-4-scout-17b-16e-instruct",
                "GROQ_TIMEOUT_SECONDS": "30",
                "GEMINI_API_KEY": "",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            image_buffer = BytesIO()
            Image.new("RGB", (1400, 1000), "#8c725c").save(image_buffer, format="JPEG", quality=92)
            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"city":"特罗姆瑟","place":"海港旧城","subject":"雪山与港口街区","scene_summary":"雪山、海港与木屋街区在冷光中交织。"}'
                                }
                            }
                        ]
                    }
                ),
            ) as post_mock:
                metadata = generator.describe_photo_metadata("挪威", photo)

        self.assertEqual(
            metadata,
            {
                "city": "特罗姆瑟",
                "place": "海港旧城",
                "subject": "雪山与港口街区",
                "scene_summary": "雪山、海港与木屋街区在冷光中交织。",
            },
        )
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertIn("使用中国大陆用户更常见的中文译名", payload["messages"][0]["content"])

    def test_groq_generator_builds_country_intro_from_photo_metadata(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GROQ_VISION_MODEL": "meta-llama/llama-4-scout-17b-16e-instruct",
                "GROQ_TIMEOUT_SECONDS": "30",
                "GEMINI_API_KEY": "",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"short_description":"雪山港城与峡湾暮色连成一体。","long_description":"这组挪威影像把特罗姆瑟的海港街区、卑尔根的港口立面与峡湾暮色串联起来，让北方城市的木屋秩序、雪山岸线和海风气息在同一段叙述里缓慢展开。"}'
                                }
                            }
                        ]
                    }
                ),
            ) as post_mock:
                description = generator.describe_country_from_metadata(
                    "挪威",
                    [
                        {"city": "特罗姆瑟", "place": "海港旧城", "subject": "雪山与港口街区", "scene_summary": "雪山、海港与木屋街区在冷光中交织。"},
                        {"city": "卑尔根", "place": "布吕根码头", "subject": "彩色港口建筑", "scene_summary": "彩色立面沿港口延展开来。"},
                    ],
                    previous_short_description="旧短介绍",
                    previous_long_description="旧长介绍",
                )

        self.assertEqual(description["short_description"], "雪山港城与峡湾暮色连成一体。")
        payload = post_mock.call_args.kwargs["json"]
        self.assertIn("特罗姆瑟", payload["messages"][1]["content"][0]["text"])
        self.assertIn("卑尔根", payload["messages"][1]["content"][0]["text"])
        self.assertIn("旧短介绍", payload["messages"][1]["content"][0]["text"])

    def test_groq_generator_retries_after_rate_limit_delay(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GROQ_VISION_MODEL": "meta-llama/llama-4-scout-17b-16e-instruct",
                "GROQ_TIMEOUT_SECONDS": "30",
                "GEMINI_API_KEY": "",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            image_buffer = BytesIO()
            Image.new("RGB", (1200, 900), "#8c725c").save(image_buffer, format="JPEG", quality=92)
            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                side_effect=[
                    FakeResponse(
                        {
                            "error": {
                                "message": "Rate limit reached for model `meta-llama/llama-4-scout-17b-16e-instruct` on tokens per minute (TPM): Limit 30000, Used 21904, Requested 12316. Please try again in 0.01s.",
                                "type": "tokens",
                                "code": "rate_limit_exceeded",
                            }
                        },
                        status_code=429,
                    ),
                    FakeResponse(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": '{"short_description":"海港山线与北方光色彼此衔接。","long_description":"港口岸线、山体轮廓与城市立面在清冷光线里缓慢展开，新的街区与海湾线索被自然并入旧有叙述，使章节气质保持克制而完整。"}'
                                    }
                                }
                            ]
                        }
                    ),
                ],
            ) as post_mock, patch.object(module.time, "sleep") as sleep_mock:
                description = generator.describe_country(
                    "挪威",
                    [photo],
                    previous_short_description="旧短介绍",
                    previous_long_description="旧长介绍",
                )

        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once()
        self.assertEqual(
            description,
            {
                "short_description": "海港山线与北方光色彼此衔接。",
                "long_description": "港口岸线、山体轮廓与城市立面在清冷光线里缓慢展开，新的街区与海湾线索被自然并入旧有叙述，使章节气质保持克制而完整。",
            },
        )

    def test_groq_generator_uses_openai_compatible_vision_payload(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-groq-key",
                "GROQ_VISION_MODEL": "meta-llama/llama-4-scout-17b-16e-instruct",
                "GROQ_TIMEOUT_SECONDS": "30",
                "GEMINI_API_KEY": "",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            image_buffer = BytesIO()
            Image.new("RGB", (1600, 1200), "#8c725c").save(image_buffer, format="JPEG", quality=92)
            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"short_description":"海港山线与北方光色彼此衔接。","long_description":"港口岸线、山体轮廓与城市立面在清冷光线里缓慢展开，新的街区与海湾线索被自然并入旧有叙述，使章节气质保持克制而完整。"}'
                                }
                            }
                        ]
                    }
                ),
            ) as post_mock:
                description = generator.describe_country(
                    "挪威",
                    [photo],
                    previous_short_description="旧短介绍",
                    previous_long_description="旧长介绍",
                )

        self.assertEqual(generator.provider, "groq")
        self.assertEqual(generator.image_limit, 5)
        self.assertEqual(
            description,
            {
                "short_description": "海港山线与北方光色彼此衔接。",
                "long_description": "港口岸线、山体轮廓与城市立面在清冷光线里缓慢展开，新的街区与海湾线索被自然并入旧有叙述，使章节气质保持克制而完整。",
            },
        )
        call = post_mock.call_args
        self.assertEqual(call.args[0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-groq-key")
        self.assertEqual(call.kwargs["timeout"], 30)
        payload = call.kwargs["json"]
        self.assertEqual(payload["model"], "meta-llama/llama-4-scout-17b-16e-instruct")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["max_completion_tokens"], 420)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(payload["messages"][1]["content"][0]["type"], "text")
        self.assertEqual(payload["messages"][1]["content"][1]["type"], "image_url")
        self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_gemini_generator_batches_all_photos_instead_of_truncating_to_first_few(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_VISION_MODEL": "gemini-2.5-flash",
                "GEMINI_TIMEOUT_SECONDS": "45",
                "COUNTRY_DESCRIPTION_IMAGE_LIMIT": "2",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            photos = []
            for index in range(5):
                image_buffer = BytesIO()
                Image.new("RGB", (1200 + index * 10, 900), "#8c725c").save(image_buffer, format="JPEG", quality=90)
                photos.append(
                    module.CountryPhotoSample(
                        name=f"demo-{index + 1}.jpg",
                        title=f"demo-{index + 1}",
                        content_type="image/jpeg",
                        payload=image_buffer.getvalue(),
                    )
                )

            with patch.object(
                module.requests,
                "post",
                side_effect=[
                    FakeResponse({"candidates": [{"content": {"parts": [{"text": "第一批：峡湾、雪山、港口城镇。"}]}}]}),
                    FakeResponse({"candidates": [{"content": {"parts": [{"text": "第二批：现代海港、木屋聚落、山谷道路。"}]}}]}),
                    FakeResponse({"candidates": [{"content": {"parts": [{"text": "第三批：教堂立面与河岸街区。"}]}}]}),
                    FakeResponse(
                        {
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [
                                            {
                                                "text": '{"short_description":"峡湾、城镇与北境秩序连成一体。","long_description":"这一章节把峡湾岸线、港口城镇、雪山谷地与教堂街区串联起来，既保留了旧导览的整体气质，也把新上传照片中的海港、木屋、河岸与山路线索纳入同一段北境叙事。"}'
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ),
                ],
            ) as post_mock:
                description = generator.describe_country(
                    "挪威",
                    photos,
                    previous_short_description="旧短介绍",
                    previous_long_description="旧长介绍",
                )

        self.assertEqual(
            description,
            {
                "short_description": "峡湾、城镇与北境秩序连成一体。",
                "long_description": "这一章节把峡湾岸线、港口城镇、雪山谷地与教堂街区串联起来，既保留了旧导览的整体气质，也把新上传照片中的海港、木屋、河岸与山路线索纳入同一段北境叙事。",
            },
        )
        self.assertEqual(post_mock.call_count, 4)
        first_payload = post_mock.call_args_list[0].kwargs["json"]
        second_payload = post_mock.call_args_list[1].kwargs["json"]
        third_payload = post_mock.call_args_list[2].kwargs["json"]
        final_payload = post_mock.call_args_list[3].kwargs["json"]
        self.assertEqual(len(first_payload["contents"][0]["parts"]) - 1, 2)
        self.assertEqual(len(second_payload["contents"][0]["parts"]) - 1, 2)
        self.assertEqual(len(third_payload["contents"][0]["parts"]) - 1, 1)
        self.assertIn("第一批：峡湾、雪山、港口城镇。", final_payload["contents"][0]["parts"][0]["text"])
        self.assertIn("第二批：现代海港、木屋聚落、山谷道路。", final_payload["contents"][0]["parts"][0]["text"])
        self.assertIn("第三批：教堂立面与河岸街区。", final_payload["contents"][0]["parts"][0]["text"])

    def test_gemini_generator_uses_dual_intro_schema_and_parses_json_response(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_VISION_MODEL": "gemini-2.5-flash",
                "GEMINI_TIMEOUT_SECONDS": "45",
            },
            clear=False,
        ):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            image_buffer = BytesIO()
            Image.new("RGB", (1600, 1200), "#8c725c").save(image_buffer, format="JPEG", quality=92)

            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": '{"short_description":"湖山与旧镇在静光中相互映照。","long_description":"山地、湖岸与旧城街巷交替出现，画面在冷冽空气与安静建筑之间建立出清透、克制的节奏。"}'
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
            ) as post_mock:
                description = generator.describe_country(
                    "奥地利",
                    [photo],
                    previous_short_description="旧短介绍",
                    previous_long_description="旧长介绍",
                )

        self.assertEqual(
            description,
            {
                "short_description": "湖山与旧镇在静光中相互映照。",
                "long_description": "山地、湖岸与旧城街巷交替出现，画面在冷冽空气与安静建筑之间建立出清透、克制的节奏。",
            },
        )
        self.assertEqual(post_mock.call_count, 1)
        call = post_mock.call_args
        self.assertEqual(
            call.args[0],
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        )
        self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], "test-gemini-key")
        self.assertEqual(call.kwargs["timeout"], 45)
        payload = call.kwargs["json"]
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["responseSchema"]["type"], "OBJECT")
        self.assertEqual(payload["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0)
        self.assertEqual(payload["contents"][0]["parts"][1]["inlineData"]["mimeType"], "image/jpeg")
        system_prompt = payload["systemInstruction"]["parts"][0]["text"]
        user_prompt = payload["contents"][0]["parts"][0]["text"]
        self.assertIn("优先识别照片中能够高置信度判断的城市、地标或景点名称", system_prompt)
        self.assertIn("建筑、自然与文化气质", system_prompt)
        self.assertIn("short_description", system_prompt)
        self.assertIn("long_description", system_prompt)
        self.assertIn("当前已有短介绍：旧短介绍", user_prompt)
        self.assertIn("当前已有详细导览：旧长介绍", user_prompt)

    def test_gemini_generator_translates_quota_exhausted_error(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}, clear=False):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            image_buffer = BytesIO()
            Image.new("RGB", (800, 600), "#8c725c").save(image_buffer, format="JPEG", quality=90)
            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                return_value=FakeResponse(
                    {"error": {"message": "RESOURCE_EXHAUSTED: Quota exceeded for quota metric"}},
                    status_code=429,
                ),
            ):
                with self.assertRaises(module.CountryDescriptionError) as exc_info:
                    generator.describe_country("奥地利", [photo])

        self.assertIn("免费额度已用完", str(exc_info.exception))

    def test_gemini_generator_translates_timeout_error(self):
        sys.modules.pop("country_descriptions", None)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}, clear=False):
            module = importlib.import_module("country_descriptions")
            module = importlib.reload(module)
            generator = module.CountryDescriptionGenerator()

            image_buffer = BytesIO()
            Image.new("RGB", (800, 600), "#8c725c").save(image_buffer, format="JPEG", quality=90)
            photo = module.CountryPhotoSample(
                name="demo.jpg",
                title="demo",
                content_type="image/jpeg",
                payload=image_buffer.getvalue(),
            )

            with patch.object(
                module.requests,
                "post",
                side_effect=ReadTimeout("HTTPSConnectionPool(host='generativelanguage.googleapis.com', port=443): Read timed out."),
            ):
                with self.assertRaises(module.CountryDescriptionError) as exc_info:
                    generator.describe_country("奥地利", [photo])

        self.assertIn("Gemini 响应超时", str(exc_info.exception))

    def test_refresh_country_descriptions_keeps_existing_text_and_returns_manual_workflow_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "icloud",
                    "ICLOUD_PHOTO_DIR": temp_dir,
                    "ADMIN_USERNAME": "admin",
                    "ADMIN_PASSWORD": "test-password",
                    "ADMIN_SESSION_SECRET": "test-session-secret",
                    "PORT": "5001",
                    "PUBLIC_SITE_ONLY": "false",
                    "GEMINI_API_KEY": "",
                },
                clear=False,
            ):
                sys.modules.pop("app", None)
                app_module = importlib.import_module("app")
                app_module = importlib.reload(app_module)

                class FakeStorage:
                    def __init__(self):
                        self.descriptions = {
                            "奥地利": {
                                "short_description": "现有短介绍",
                                "long_description": "现有详细导览",
                            }
                        }
                        self.updated = []

                    def list_country_descriptions(self):
                        return dict(self.descriptions)

                    def update_country_description(self, country, description):
                        self.updated.append((country, description))
                        self.descriptions[country] = description

                    def delete_country_description(self, country):
                        self.descriptions.pop(country, None)

                fake_storage = FakeStorage()
                app_module.storage = fake_storage

                result = app_module.refresh_country_descriptions(
                    [{"country": "奥地利", "name": "demo.jpg"}],
                    ["奥地利"],
                    force=True,
                )

        self.assertEqual(
            fake_storage.descriptions["奥地利"],
            {
                "short_description": "现有短介绍",
                "long_description": "现有详细导览",
            },
        )
        self.assertEqual(fake_storage.updated, [])
        self.assertEqual(result["updated"], [])
        self.assertEqual(
            result["failed"],
            [
                {
                    "country": "奥地利",
                    "error": "当前实现不再自动调用 groq 和 gemini。需要 AI 的步骤只通过当前对话里的模型分 5 张一批处理，再把结果回写到图库元数据。",
                }
            ],
        )
        self.assertIn("当前实现不再自动调用 groq 和 gemini", result["message"])

    def test_refresh_country_descriptions_marks_uploaded_country_for_manual_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "icloud",
                    "ICLOUD_PHOTO_DIR": temp_dir,
                    "ADMIN_USERNAME": "admin",
                    "ADMIN_PASSWORD": "test-password",
                    "ADMIN_SESSION_SECRET": "test-session-secret",
                    "PORT": "5001",
                    "PUBLIC_SITE_ONLY": "false",
                    "GEMINI_API_KEY": "test-gemini-key",
                },
                clear=False,
            ):
                sys.modules.pop("app", None)
                app_module = importlib.import_module("app")
                app_module = importlib.reload(app_module)

                class FakeStorage:
                    def __init__(self):
                        self.descriptions = {
                            "挪威": {
                                "short_description": "旧短介绍",
                                "long_description": "旧长介绍",
                            }
                        }

                    def list_country_descriptions(self):
                        return dict(self.descriptions)

                    def update_country_description(self, country, description):
                        self.descriptions[country] = description

                    def delete_country_description(self, country):
                        self.descriptions.pop(country, None)

                fake_storage = FakeStorage()
                app_module.storage = fake_storage

                photos = [
                    {"country": "挪威", "name": "old-1.jpg"},
                    {"country": "挪威", "name": "old-2.jpg"},
                    {"country": "挪威", "name": "new-1.jpg"},
                    {"country": "挪威", "name": "new-2.jpg"},
                    {"country": "挪威", "name": "new-3.jpg"},
                ]
                imported = [
                    {"country": "挪威", "name": "new-1.jpg"},
                    {"country": "挪威", "name": "new-2.jpg"},
                    {"country": "挪威", "name": "new-3.jpg"},
                ]

                result = app_module.refresh_country_descriptions(
                    photos,
                    ["挪威"],
                    force=True,
                    sample_source_photos=imported,
                )

        self.assertEqual(result["updated"], [])
        self.assertEqual(
            result["failed"],
            [
                {
                    "country": "挪威",
                    "error": "当前实现不再自动调用 groq 和 gemini。需要 AI 的步骤只通过当前对话里的模型分 5 张一批处理，再把结果回写到图库元数据。",
                }
            ],
        )
        self.assertIn("挪威", result["message"])

    def test_refresh_country_descriptions_can_flag_full_collection_for_manual_rebuild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "icloud",
                    "ICLOUD_PHOTO_DIR": temp_dir,
                    "ADMIN_USERNAME": "admin",
                    "ADMIN_PASSWORD": "test-password",
                    "ADMIN_SESSION_SECRET": "test-session-secret",
                    "PORT": "5001",
                    "PUBLIC_SITE_ONLY": "false",
                    "GEMINI_API_KEY": "test-gemini-key",
                },
                clear=False,
            ):
                sys.modules.pop("app", None)
                app_module = importlib.import_module("app")
                app_module = importlib.reload(app_module)

                class FakeStorage:
                    def __init__(self):
                        self.descriptions = {}

                    def list_country_descriptions(self):
                        return dict(self.descriptions)

                    def update_country_description(self, country, description):
                        self.descriptions[country] = description

                    def delete_country_description(self, country):
                        self.descriptions.pop(country, None)

                fake_storage = FakeStorage()
                app_module.storage = fake_storage

                photos = [
                    {"country": "法国", "name": "fr-1.jpg"},
                    {"country": "法国", "name": "fr-2.jpg"},
                    {"country": "法国", "name": "fr-3.jpg"},
                    {"country": "法国", "name": "fr-4.jpg"},
                ]

                result = app_module.refresh_country_descriptions(
                    photos,
                    ["法国"],
                    force=True,
                )

        self.assertEqual(result["updated"], [])
        self.assertEqual(result["failed"][0]["country"], "法国")
        self.assertIn("法国", result["message"])

    def test_refresh_country_descriptions_does_not_attempt_direct_image_intro_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "icloud",
                    "ICLOUD_PHOTO_DIR": temp_dir,
                    "ADMIN_USERNAME": "admin",
                    "ADMIN_PASSWORD": "test-password",
                    "ADMIN_SESSION_SECRET": "test-session-secret",
                    "PORT": "5001",
                    "PUBLIC_SITE_ONLY": "false",
                    "GEMINI_API_KEY": "test-gemini-key",
                    "GROQ_API_KEY": "test-groq-key",
                },
                clear=False,
            ):
                sys.modules.pop("app", None)
                app_module = importlib.import_module("app")
                app_module = importlib.reload(app_module)

                class FakeStorage:
                    def __init__(self):
                        self.descriptions = {
                            "捷克": {
                                "short_description": "旧短介绍",
                                "long_description": "旧长介绍",
                            }
                        }

                    def list_country_descriptions(self):
                        return dict(self.descriptions)

                    def update_country_description(self, country, description):
                        self.descriptions[country] = description

                    def delete_country_description(self, country):
                        self.descriptions.pop(country, None)

                app_module.storage = FakeStorage()

                with patch.object(
                    app_module,
                    "refresh_photo_ai_metadata",
                    side_effect=AssertionError("不应再调用图片元数据自动刷新"),
                ):
                    result = app_module.refresh_country_descriptions(
                        [{"country": "捷克", "name": "cz-1.jpg"}],
                        ["捷克"],
                        force=True,
                        sample_source_photos=[{"country": "捷克", "name": "cz-1.jpg"}],
                    )

        self.assertEqual(
            result["failed"],
            [
                {
                    "country": "捷克",
                    "error": "当前实现不再自动调用 groq 和 gemini。需要 AI 的步骤只通过当前对话里的模型分 5 张一批处理，再把结果回写到图库元数据。",
                }
            ],
        )

    def test_build_country_photo_samples_returns_all_photos_for_country(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PHOTO_STORAGE": "icloud",
                    "ICLOUD_PHOTO_DIR": temp_dir,
                    "ADMIN_USERNAME": "admin",
                    "ADMIN_PASSWORD": "test-password",
                    "ADMIN_SESSION_SECRET": "test-session-secret",
                    "PORT": "5001",
                    "PUBLIC_SITE_ONLY": "false",
                    "GEMINI_API_KEY": "test-gemini-key",
                    "COUNTRY_DESCRIPTION_IMAGE_LIMIT": "2",
                },
                clear=False,
            ):
                sys.modules.pop("app", None)
                app_module = importlib.import_module("app")
                app_module = importlib.reload(app_module)

                class FakeStorage:
                    def open_photo(self, photo_name):
                        return BytesIO(f"payload:{photo_name}".encode("utf-8")), "image/jpeg"

                app_module.storage = FakeStorage()

                photos = [
                    {"country": "西班牙", "name": "es-1.jpg", "title": ""},
                    {"country": "西班牙", "name": "es-2.jpg", "title": ""},
                    {"country": "西班牙", "name": "es-3.jpg", "title": ""},
                    {"country": "西班牙", "name": "es-4.jpg", "title": ""},
                ]

                samples = app_module.build_country_photo_samples(photos, "西班牙")

        self.assertEqual([sample.name for sample in samples], ["es-1.jpg", "es-2.jpg", "es-3.jpg", "es-4.jpg"])


if __name__ == "__main__":
    unittest.main()
