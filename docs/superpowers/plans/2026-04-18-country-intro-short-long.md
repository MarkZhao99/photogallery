# Country Intro Short/Long Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split each country section intro into a short summary plus an expandable long guide, migrate existing single-string country descriptions safely, and update Gemini generation so uploads incrementally revise only affected countries using old copy plus newly uploaded photos.

**Architecture:** Keep the current Flask + Jinja structure and extend the existing storage metadata model instead of introducing a new persistence layer. Use a backward-compatible country-description object in `storage.py`, update grouping/rendering in `app.py`, render the new short/long intro structure in both public and admin templates, and change Gemini generation to return dual fields while preserving old values on any failure.

**Tech Stack:** Python 3.9, Flask, Jinja templates, vanilla JavaScript, Pillow, requests, unittest

---

## File Structure

**Modify**
- `storage.py`
  - Extend country-description metadata from string-only values to backward-compatible objects with `short_description` and `long_description`
  - Add normalization helpers and fallback logic for old data
- `app.py`
  - Update country grouping to expose both intro fields and safe fallbacks
  - Pass previous intro text and affected/new photo samples into Gemini refresh logic
- `country_descriptions.py`
  - Change Gemini output schema from single `description` to `short_description` + `long_description`
  - Support incremental rewriting using existing text plus newly uploaded photos
- `templates/gallery.html`
  - Render short intro by default and expandable long intro in each country header
- `templates/index.html`
  - Mirror the same short/long country intro structure in admin and update dynamic client-side rendering
- `static/style.css`
  - Add styles for compact short intro, expandable long guide block, and toggle button states
- `tests/test_country_descriptions.py`
  - Cover dual-field Gemini output, incremental prompt content, and failure preservation behavior
- `tests/test_local_public_share.py`
  - Cover short/long intro rendering and toggle markup in public output

**Create**
- `tests/test_country_intro_storage.py`
  - Focused storage compatibility coverage for old string values and new object values

**No Commit Note**
- This workspace currently has no `.git` directory. Any “commit” step below becomes a progress checkpoint rather than an actual git commit.

---

### Task 1: Lock Down Storage Compatibility With Failing Tests

**Files:**
- Create: `tests/test_country_intro_storage.py`
- Test: `tests/test_country_intro_storage.py`

- [ ] **Step 1: Write the failing storage compatibility tests**

```python
import tempfile
import unittest
from pathlib import Path

from storage import COUNTRY_DESCRIPTIONS_KEY, MetadataStore


class CountryIntroStorageTests(unittest.TestCase):
    def test_old_string_description_maps_to_long_description(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")
            store.save(
                {
                    COUNTRY_DESCRIPTIONS_KEY: {
                        "奥地利": "旧的国家长介绍"
                    }
                }
            )

            descriptions = store.list_country_descriptions()

        self.assertEqual(
            descriptions["奥地利"],
            {
                "short_description": "",
                "long_description": "旧的国家长介绍",
            },
        )

    def test_new_object_description_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")

            store.update_country_description(
                "挪威",
                {
                    "short_description": "山海冷光中的北境秩序。",
                    "long_description": "完整导览文字。",
                },
            )
            descriptions = store.list_country_descriptions()

        self.assertEqual(
            descriptions["挪威"]["short_description"],
            "山海冷光中的北境秩序。",
        )
        self.assertEqual(
            descriptions["挪威"]["long_description"],
            "完整导览文字。",
        )

    def test_empty_short_description_is_preserved_for_backfill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MetadataStore(Path(temp_dir) / "meta.json")
            store.save(
                {
                    COUNTRY_DESCRIPTIONS_KEY: {
                        "西班牙": {
                            "short_description": "",
                            "long_description": "旧长介绍",
                        }
                    }
                }
            )

            descriptions = store.list_country_descriptions()

        self.assertEqual(descriptions["西班牙"]["short_description"], "")
        self.assertEqual(descriptions["西班牙"]["long_description"], "旧长介绍")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the storage tests to verify they fail**

Run: `python3 -m unittest tests/test_country_intro_storage.py -v`

Expected: `FAIL` or `ERROR` because `MetadataStore.list_country_descriptions()` currently returns `dict[str, str]` and `update_country_description()` only accepts a string.

- [ ] **Step 3: Implement backward-compatible country-intro storage**

```python
# storage.py
def normalize_country_intro_payload(payload: Any) -> dict[str, str]:
    if isinstance(payload, dict):
        short_description = normalize_country_description(payload.get("short_description"))
        long_description = normalize_country_description(payload.get("long_description"))
        return {
            "short_description": short_description,
            "long_description": long_description,
        }

    return {
        "short_description": "",
        "long_description": normalize_country_description(payload),
    }


def normalize_country_description_value(value: Any) -> str:
    return " ".join(str(value or "").split())[:420]


class MetadataStore:
    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        payload = self.load().get(COUNTRY_DESCRIPTIONS_KEY, {})
        if not isinstance(payload, dict):
            return {}

        descriptions: dict[str, dict[str, str]] = {}
        for raw_country, raw_intro in payload.items():
            country = (str(raw_country or "")).strip()
            if not country:
                continue
            intro = normalize_country_intro_payload(raw_intro)
            if intro["short_description"] or intro["long_description"]:
                descriptions[country] = intro
        return descriptions

    def update_country_description(self, country: str, description: Any) -> dict[str, str]:
        normalized_country = normalize_country(country)
        normalized_intro = normalize_country_intro_payload(description)
        data = self.load()
        descriptions = data.get(COUNTRY_DESCRIPTIONS_KEY, {})
        if not isinstance(descriptions, dict):
            descriptions = {}

        if normalized_intro["short_description"] or normalized_intro["long_description"]:
            descriptions[normalized_country] = normalized_intro
            data[COUNTRY_DESCRIPTIONS_KEY] = descriptions
        else:
            descriptions.pop(normalized_country, None)
            if descriptions:
                data[COUNTRY_DESCRIPTIONS_KEY] = descriptions
            else:
                data.pop(COUNTRY_DESCRIPTIONS_KEY, None)

        self.save(data)
        return normalized_intro
```

- [ ] **Step 4: Run the storage tests to verify they pass**

Run: `python3 -m unittest tests/test_country_intro_storage.py -v`

Expected: `OK`

- [ ] **Step 5: Record progress checkpoint**

Because this workspace has no git repository, record progress by re-reading the diff target files instead of committing:

Run: `sed -n '1,220p' storage.py`

Expected: New normalization helper and object-based storage logic are visible.

---

### Task 2: Red-Green the Dual-Field Gemini Output and Incremental Rewrite Inputs

**Files:**
- Modify: `tests/test_country_descriptions.py`
- Modify: `country_descriptions.py`
- Test: `tests/test_country_descriptions.py`

- [ ] **Step 1: Extend the failing Gemini tests for dual-field output**

```python
# tests/test_country_descriptions.py
def test_gemini_generator_uses_dual_intro_schema_and_old_copy_context(self):
    sys.modules.pop("country_descriptions", None)
    with patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_VISION_MODEL": "gemini-2.5-flash",
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
                                        "text": '{"short_description":"湖山与旧镇在静光中相互映照。","long_description":"完整导览文字。"}'
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
        ) as post_mock:
            result = generator.describe_country(
                "奥地利",
                [photo],
                previous_short_description="旧短介绍",
                previous_long_description="旧长介绍",
            )

    self.assertEqual(
        result,
        {
            "short_description": "湖山与旧镇在静光中相互映照。",
            "long_description": "完整导览文字。",
        },
    )
    payload = post_mock.call_args.kwargs["json"]
    system_prompt = payload["system_instruction"]["parts"][0]["text"]
    user_prompt = payload["contents"][0]["parts"][0]["text"]
    self.assertIn("short_description", system_prompt)
    self.assertIn("long_description", system_prompt)
    self.assertIn("当前已有短介绍：旧短介绍", user_prompt)
    self.assertIn("当前已有详细导览：旧长介绍", user_prompt)
```

- [ ] **Step 2: Run the Gemini tests to verify they fail**

Run: `python3 -m unittest tests/test_country_descriptions.py -v`

Expected: `FAIL` because `describe_country()` currently returns a single string and does not accept previous intro fields.

- [ ] **Step 3: Implement dual-field Gemini generation plus incremental input context**

```python
# country_descriptions.py
def describe_country(
    self,
    country: str,
    photos: list[CountryPhotoSample],
    *,
    previous_short_description: str = "",
    previous_long_description: str = "",
) -> dict[str, str]:
    ...
    user_parts: list[dict[str, Any]] = [
        {
            "text": (
                f"国家章节名称：{country}\n"
                f"本次新增照片数量：{len(selected_photos)} 张。\n"
                f"当前已有短介绍：{previous_short_description or '（无）'}\n"
                f"当前已有详细导览：{previous_long_description or '（无）'}\n"
                "请在保留原文案主气质的前提下，根据这次新增照片增量修订两段文案。"
            ),
        }
    ]
    ...
    payload["generationConfig"]["response_schema"] = {
        "type": "OBJECT",
        "properties": {
            "short_description": {"type": "STRING"},
            "long_description": {"type": "STRING"},
        },
        "required": ["short_description", "long_description"],
    }
    ...
    parsed = json.loads(output_text)
    short_description = normalize_country_description_value(parsed.get("short_description"))
    long_description = normalize_country_description_value(parsed.get("long_description"))
    if not short_description and not long_description:
        raise CountryDescriptionError("Gemini 没有返回有效的国家介绍。")
    return {
        "short_description": short_description,
        "long_description": long_description,
    }
```

- [ ] **Step 4: Run the Gemini tests to verify they pass**

Run: `python3 -m unittest tests/test_country_descriptions.py -v`

Expected: `OK`

- [ ] **Step 5: Record progress checkpoint**

Run: `sed -n '1,260p' country_descriptions.py`

Expected: `describe_country()` accepts previous intro fields and returns a dict with `short_description` and `long_description`.

---

### Task 3: Wire Intro Objects Through Grouping, Upload Refresh, and Safe Fallbacks

**Files:**
- Modify: `app.py`
- Test: `tests/test_local_public_share.py`
- Test: `tests/test_country_descriptions.py`

- [ ] **Step 1: Add failing grouping/render tests for short vs. long intro fields**

```python
# tests/test_local_public_share.py
def test_public_gallery_renders_short_intro_and_expandable_long_intro(self):
    with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
        app_module.storage = FakeStorage()
        with patch.object(
            app_module.storage,
            "list_country_descriptions",
            return_value={
                "奥地利": {
                    "short_description": "湖山与旧镇在静光中相互映照。",
                    "long_description": "完整导览文字。",
                }
            },
        ):
            response = app_module.app.test_client().get("/")

    html = response.get_data(as_text=True)
    self.assertIn("湖山与旧镇在静光中相互映照。", html)
    self.assertIn("完整导览文字。", html)
    self.assertIn("展开导览", html)
```

```python
# tests/test_country_descriptions.py
def test_refresh_country_descriptions_passes_old_copy_and_new_photos_only(self):
    ...
    with patch.object(
        app_module.country_describer,
        "describe_country",
        return_value={
            "short_description": "新短介绍",
            "long_description": "新长介绍",
        },
    ) as describe_mock, patch.object(
        app_module,
        "build_country_photo_samples",
        return_value=["new-photo-a", "new-photo-b"],
    ):
        result = app_module.refresh_country_descriptions(
            photos,
            ["奥地利"],
            force=True,
            photo_samples_by_country={"奥地利": ["new-photo-a", "new-photo-b"]},
        )

    self.assertEqual(
        describe_mock.call_args.kwargs["previous_short_description"],
        "旧短介绍",
    )
    self.assertEqual(
        describe_mock.call_args.kwargs["previous_long_description"],
        "旧长介绍",
    )
```

- [ ] **Step 2: Run the affected tests to verify they fail**

Run: `python3 -m unittest tests/test_local_public_share.py tests/test_country_descriptions.py -v`

Expected: `FAIL` because group objects only expose `description`, and refresh logic does not pass previous intro fields or photo subsets.

- [ ] **Step 3: Implement grouped intro fields, fallbacks, and incremental refresh plumbing**

```python
# app.py
def default_country_intro(country: str, photo_count: int) -> dict[str, str]:
    if country == "未分类":
        return {
            "short_description": "尚未整理成章节题记。",
            "long_description": f"这一章节暂时收录了 {photo_count} 幅尚未细分归档的影像，导览文字会在后续整理后补齐。",
        }
    return {
        "short_description": f"{country}章节的导览正在整理中。",
        "long_description": f"这一章节收录了 {photo_count} 幅来自 {country} 的影像，新的国家导览会在作品更新后同步整理。",
    }


def group_photos_by_country(photos: list[dict], descriptions: Optional[dict[str, dict[str, str]]] = None) -> list[dict]:
    ...
    intro = descriptions.get(country) or default_country_intro(country, len(items))
    short_description = intro.get("short_description") or build_short_intro_fallback(intro.get("long_description", ""))
    long_description = intro.get("long_description") or build_long_intro_fallback(country, len(items))
    groups.append(
        {
            "country": country,
            "count": len(items),
            "short_description": short_description,
            "long_description": long_description,
            "photos": items,
        }
    )


def refresh_country_descriptions(..., photo_samples_by_country: Optional[dict[str, list[CountryPhotoSample]]] = None):
    ...
    existing_intro = existing_descriptions.get(country, {})
    samples = (
        photo_samples_by_country.get(country)
        if photo_samples_by_country and country in photo_samples_by_country
        else build_country_photo_samples(photos, country)
    )
    intro = country_describer.describe_country(
        country,
        samples,
        previous_short_description=str(existing_intro.get("short_description") or ""),
        previous_long_description=str(existing_intro.get("long_description") or ""),
    )
    storage.update_country_description(country, intro)
```

Also update upload code to build `photo_samples_by_country` from the newly imported photos rather than all current country photos.

- [ ] **Step 4: Run the affected tests to verify they pass**

Run: `python3 -m unittest tests/test_local_public_share.py tests/test_country_descriptions.py tests/test_country_intro_storage.py -v`

Expected: `OK`

- [ ] **Step 5: Record progress checkpoint**

Run: `sed -n '1,260p' app.py`

Expected: Group payloads now expose `short_description` and `long_description`, with refresh logic passing previous text into Gemini.

---

### Task 4: Render Short Intro + Expandable Long Guide in Public and Admin

**Files:**
- Modify: `templates/gallery.html`
- Modify: `templates/index.html`
- Modify: `static/style.css`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Add failing markup tests for short/long country intro UI**

```python
# tests/test_local_public_share.py
def test_public_gallery_renders_country_guide_toggle_markup(self):
    with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
        app_module.storage = FakeStorage()
        with patch.object(
            app_module.storage,
            "list_country_descriptions",
            return_value={
                "奥地利": {
                    "short_description": "湖山与旧镇在静光中相互映照。",
                    "long_description": "完整导览文字。",
                }
            },
        ):
            response = app_module.app.test_client().get("/")

    html = response.get_data(as_text=True)
    self.assertIn('class="country-short-description"', html)
    self.assertIn('class="country-guide-toggle"', html)
    self.assertIn('class="country-long-description" hidden', html)
    self.assertIn("展开导览", html)


def test_admin_gallery_renders_country_guide_toggle_markup(self):
    with loaded_app_module() as app_module:
        app_module.storage = FakeStorage()
        with app_module.app.test_client() as client:
            with client.session_transaction() as session:
                session["admin_authenticated"] = True
                session["admin_password_sig"] = app_module.current_password_signature()
                session["admin_username"] = app_module.admin_username()
            response = client.get("/admin")

    html = response.get_data(as_text=True)
    self.assertIn('class="country-short-description"', html)
    self.assertIn('class="country-guide-toggle"', html)
```

- [ ] **Step 2: Run the rendering tests to verify they fail**

Run: `python3 -m unittest tests/test_local_public_share.py -v`

Expected: `FAIL` because templates still render a single `.country-summary` paragraph.

- [ ] **Step 3: Implement the expandable intro structure in both templates and dynamic admin rendering**

```html
<!-- templates/gallery.html and templates/index.html -->
<div class="country-heading">
  <p class="country-label">Collection</p>
  <h3>{{ group.country }}</h3>
  <p class="country-short-description">{{ group.short_description }}</p>
  <button
    class="country-guide-toggle"
    type="button"
    data-action="toggle-country-guide"
    aria-expanded="false"
  >
    展开导览
  </button>
  <div class="country-long-description" hidden>
    <p>{{ group.long_description }}</p>
  </div>
</div>
```

```javascript
// templates/index.html inline script update
sectionElement.querySelector(".country-short-description").textContent = group.short_description || "";
sectionElement.querySelector(".country-long-description p").textContent = group.long_description || "";
```

```css
/* static/style.css */
.country-short-description {
  margin: 10px 0 0;
  color: var(--ink-soft);
}

.country-guide-toggle {
  width: fit-content;
  margin-top: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent-deep);
}

.country-long-description[hidden] {
  display: none;
}

.country-long-description {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid rgba(38, 27, 21, 0.08);
}
```

- [ ] **Step 4: Add and implement the toggle behavior**

```javascript
// create or inline small shared script block
document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-action='toggle-country-guide']");
  if (!trigger) return;

  const container = trigger.closest(".country-heading");
  const longDescription = container?.querySelector(".country-long-description");
  if (!longDescription) return;

  const expanded = trigger.getAttribute("aria-expanded") === "true";
  trigger.setAttribute("aria-expanded", expanded ? "false" : "true");
  trigger.textContent = expanded ? "展开导览" : "收起导览";
  longDescription.hidden = expanded;
});
```

- [ ] **Step 5: Run the rendering tests to verify they pass**

Run: `python3 -m unittest tests/test_local_public_share.py -v`

Expected: `OK`

- [ ] **Step 6: Record progress checkpoint**

Run: `curl -fsS http://127.0.0.1:5002/gallery | rg -n "country-short-description|country-guide-toggle|country-long-description|展开导览"`

Expected: Matching markup appears in the page output.

---

### Task 5: Finish End-to-End Verification and Safe Defaults

**Files:**
- Modify: `app.py`
- Modify: `storage.py`
- Modify: `tests/test_local_public_share.py`
- Modify: `tests/test_country_descriptions.py`
- Modify: `tests/test_country_intro_storage.py`

- [ ] **Step 1: Add failing tests for empty-intro fallback behavior**

```python
# tests/test_local_public_share.py
def test_public_gallery_uses_safe_fallback_intro_when_country_has_no_copy(self):
    with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
        app_module.storage = FakeStorage()
        with patch.object(app_module.storage, "list_country_descriptions", return_value={"奥地利": {"short_description": "", "long_description": ""}}):
            response = app_module.app.test_client().get("/")

    html = response.get_data(as_text=True)
    self.assertIn("章节题记正在整理中", html)
    self.assertIn("导览文字稍后补充", html)
```

- [ ] **Step 2: Run the full suite to verify the new fallback test fails**

Run: `python3 -m unittest tests/test_country_descriptions.py tests/test_country_intro_storage.py tests/test_local_public_share.py -v`

Expected: `FAIL` until fallback helpers and template rendering cover empty intro values.

- [ ] **Step 3: Implement fallback helpers and ensure upload flow preserves old values on any AI error**

```python
# app.py
def build_short_intro_fallback(long_description: str) -> str:
    normalized = " ".join(str(long_description or "").split())
    if normalized:
        return normalized[:40]
    return "章节题记正在整理中。"


def build_long_intro_fallback(country: str, photo_count: int) -> str:
    return f"这一章节目前收录了 {photo_count} 幅来自 {country} 的影像，导览文字稍后补充。"
```

Keep `refresh_country_descriptions()` behavior strict:

```python
except CountryDescriptionError as exc:
    cast_list = result["failed"]
    assert isinstance(cast_list, list)
    cast_list.append({"country": country, "error": str(exc)})
    # Do not update storage here.
```

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `python3 -m unittest tests/test_country_descriptions.py tests/test_country_intro_storage.py tests/test_local_public_share.py -v`

Expected: `OK`

- [ ] **Step 5: Final verification against the spec**

Run these commands:

```bash
python3 -m unittest tests/test_country_descriptions.py tests/test_country_intro_storage.py tests/test_local_public_share.py -v
curl -fsS http://127.0.0.1:5002/gallery | rg -n "country-short-description|country-guide-toggle|country-long-description|展开导览"
curl -fsS http://127.0.0.1:5001/admin | rg -n "country-short-description|country-guide-toggle|country-long-description"
```

Expected:
- Test suite passes
- Public page contains short intro + toggle + hidden long intro markup
- Admin page contains the same intro structure

- [ ] **Step 6: Record progress checkpoint**

Because git is unavailable, record completion by saving the test output or re-running the verification commands above and noting the successful result in the final task summary.

---

## Self-Review

### Spec Coverage

- Short intro + expandable long guide: covered in Task 4
- Dual-field Gemini output: covered in Task 2
- Incremental rewriting from old copy + new images: covered in Task 3
- Old-data compatibility: covered in Task 1
- Failure preservation and empty fallbacks: covered in Task 5
- Public/admin consistency and mobile-safe folded default: covered in Task 4 and Task 5

### Placeholder Scan

- No `TODO` / `TBD` placeholders remain
- Every task includes exact files, code blocks, test commands, and expected results
- No “similar to above” references are used as substitutes for actual steps

### Type Consistency

- Storage shape is consistently `{"short_description": str, "long_description": str}`
- App grouping uses `group.short_description` and `group.long_description`
- Gemini output schema uses the same field names
- Fallback helpers produce the same two fields consumed by templates
