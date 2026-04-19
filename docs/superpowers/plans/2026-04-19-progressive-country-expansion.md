# Progressive Country Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the public homepage from preview-only country cards with detail-page navigation into inline country expansion with preview-first image loading, deferred overflow loading, and country-priority hydration.

**Architecture:** Extend the existing `build_groups()` output so the homepage receives both `preview_photos` and `overflow_photos`, while country detail pages keep the full gallery behavior. Render both layers on the homepage, but only activate `preview_photos` immediately; `overflow_photos` ship as deferred image metadata and are promoted either after preview images settle or immediately when the user expands a country.

**Tech Stack:** Flask, Jinja2 templates, vanilla JavaScript, CSS, `unittest`

---

### Task 1: Lock the behavior with homepage regression tests

**Files:**
- Modify: `tests/test_local_public_share.py`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_public_homepage_renders_inline_country_expansion_with_deferred_overflow(self):
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
        self.assertEqual(len(self.collage_cards(gallery_html, card_kind="public-photo-card")), 6)
        self.assertIn('data-country-expand-toggle', html)
        self.assertIn('data-country-overflow-grid', html)
        self.assertIn('data-deferred-photo="true"', html)
        self.assertIn("展开本国家全部作品", html)
        self.assertIn("完整导览文字。", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_public_homepage_renders_inline_country_expansion_with_deferred_overflow -v`
Expected: FAIL because the homepage still renders only four cards and does not include inline overflow/deferred-loading markup.

- [ ] **Step 3: Add preview sizing regression coverage**

```python
    def test_preview_card_sizes_use_smaller_public_gallery_widths(self):
        with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
            self.assertEqual(app_module.preview_card_widths(), (360, 540, 720, 1080))
            self.assertEqual(app_module.preview_card_default_width(), 540)
            self.assertEqual(
                app_module.preview_card_sizes(),
                "(max-width: 640px) 46vw, (max-width: 1100px) 24vw, 18vw",
            )
```

- [ ] **Step 4: Run the preview sizing test**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_preview_card_sizes_use_smaller_public_gallery_widths -v`
Expected: FAIL because current widths still resolve to `(480, 720, 1080, 1600)` and the larger `sizes` string.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_local_public_share.py
git commit -m "test: cover inline country expansion homepage"
```

### Task 2: Return preview and overflow photo sets from the backend

**Files:**
- Modify: `app.py`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Update `build_groups()` to split preview and overflow photos**

```python
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
        preview_photos = list(all_photos)
        overflow_photos: list[dict] = []

        if preview_limit and len(all_photos) > preview_limit:
            preview_photos = select_country_preview_photos(all_photos, limit=preview_limit)
            preview_names = {str(photo.get("name") or "") for photo in preview_photos}
            overflow_photos = [photo for photo in all_photos if str(photo.get("name") or "") not in preview_names]

        group["count"] = len(all_photos)
        group["preview_photos"] = assign_collage_slots(preview_photos)
        group["overflow_photos"] = assign_collage_slots(overflow_photos)
        group["photos"] = assign_collage_slots(all_photos)
        group["visible_count"] = len(group["preview_photos"])
        group["overflow_count"] = len(group["overflow_photos"])
        group["has_overflow_photos"] = bool(group["overflow_photos"])
        group["is_preview"] = group["has_overflow_photos"]
        group["preview_note"] = "首页精选" if group["is_preview"] else ""
        group["detail_url"] = url_for(detail_endpoint, country=group["country"]) if detail_endpoint else ""
    return groups
```

- [ ] **Step 2: Shrink homepage card widths**

```python
def preview_card_widths() -> tuple[int, ...]:
    widths = (360, 540, 720, 1080)
    normalized = {normalize_preview_width(width) for width in widths}
    return tuple(sorted(normalized))


def preview_card_sizes() -> str:
    return "(max-width: 640px) 46vw, (max-width: 1100px) 24vw, 18vw"
```

- [ ] **Step 3: Run the two red tests**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_public_homepage_renders_inline_country_expansion_with_deferred_overflow tests.test_local_public_share.LocalPublicShareTests.test_preview_card_sizes_use_smaller_public_gallery_widths -v`
Expected: homepage test still fails on missing template markup, while preview sizing test passes once the helper values change.

- [ ] **Step 4: Commit backend changes**

```bash
git add app.py tests/test_local_public_share.py
git commit -m "feat: split public gallery preview and overflow photos"
```

### Task 3: Render inline expansion markup and deferred image metadata

**Files:**
- Modify: `templates/gallery.html`
- Modify: `templates/_photo_components.html`
- Modify: `static/style.css`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Extend photo card macro for deferred images**

```jinja2
{% macro photo_card(photo, editable=False, collage_slot="collage-tile-standard", deferred=False) -%}
<article class="photo-card collage-tile {{ collage_slot }}{% if editable %} editable-photo-card{% else %} public-photo-card{% endif %}{% if deferred %} deferred-photo-card{% endif %}">
  <button
    class="photo-view-button"
    type="button"
    data-action="open-lightbox"
    data-image-url="{{ photo.preview_url or photo.url }}"
    data-download-url="{{ photo.download_url or photo.url }}"
    data-image-alt="{{ photo.title or photo.name }}"
  >
    <img
      {% if deferred %}
      data-deferred-photo="true"
      data-src="{{ photo.card_image_url or photo.preview_url or photo.url }}"
      {% if photo.card_image_srcset %}data-srcset="{{ photo.card_image_srcset }}"{% endif %}
      {% if photo.card_image_sizes %}data-sizes="{{ photo.card_image_sizes }}"{% endif %}
      {% else %}
      src="{{ photo.card_image_url or photo.preview_url or photo.url }}"
      {% if photo.card_image_srcset %}srcset="{{ photo.card_image_srcset }}"{% endif %}
      {% if photo.card_image_sizes %}sizes="{{ photo.card_image_sizes }}"{% endif %}
      {% endif %}
      alt="{{ photo.title or photo.name }}"
      loading="lazy"
      decoding="async"
    >
```

- [ ] **Step 2: Render preview and overflow grids on the homepage**

```jinja2
          <section class="country-section" data-country-section data-country-name="{{ group.country }}">
            {{ country_intro(group, loop.index) }}

            <div class="gallery-grid collage-grid" data-country-preview-grid>
              {% for photo in group.preview_photos %}
              {{ photo_card(photo, collage_slot=photo.collage_slot or collage_slot(photo, loop.index0)) }}
              {% endfor %}
            </div>

            <div class="country-overflow-shell" data-country-overflow-shell hidden>
              <div class="gallery-grid collage-grid country-overflow-grid" data-country-overflow-grid>
                {% for photo in group.overflow_photos %}
                {{ photo_card(photo, collage_slot=photo.collage_slot or collage_slot(photo, loop.index0), deferred=True) }}
                {% endfor %}
              </div>
            </div>
          </section>
```

- [ ] **Step 3: Add inline control styling**

```css
.country-section[data-country-expanded="true"] .country-overflow-shell {
  display: block;
}

.country-overflow-shell[hidden] {
  display: none !important;
}

.deferred-photo-card img:not([src]) {
  background: linear-gradient(135deg, rgba(181, 93, 63, 0.12), rgba(255, 255, 255, 0.4));
}
```

- [ ] **Step 4: Run homepage regression test**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_public_homepage_renders_inline_country_expansion_with_deferred_overflow -v`
Expected: PASS once the homepage ships six cards, inline expansion controls, and deferred attributes.

- [ ] **Step 5: Commit template/style changes**

```bash
git add templates/gallery.html templates/_photo_components.html static/style.css tests/test_local_public_share.py
git commit -m "feat: render inline country expansion on public homepage"
```

### Task 4: Add priority deferred-loading behavior on the client

**Files:**
- Modify: `static/country-intros.js`
- Modify: `tests/test_local_public_share.py`

- [ ] **Step 1: Add a script regression test for the priority loader contract**

```python
    def test_country_intro_script_contains_priority_loader_hooks(self):
        script = (PROJECT_ROOT / "static" / "country-intros.js").read_text(encoding="utf-8")

        self.assertIn("data-country-expand-toggle", script)
        self.assertIn("requestIdleCallback", script)
        self.assertIn("data-country-priority", script)
        self.assertIn("activateDeferredImages", script)
```

- [ ] **Step 2: Run the script regression test**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_country_intro_script_contains_priority_loader_hooks -v`
Expected: FAIL because the current script only toggles the long description.

- [ ] **Step 3: Implement the priority loader**

```javascript
function activateDeferredImages(images) {
  images.forEach((image) => {
    if (image.dataset.activated === "true") {
      return;
    }
    image.src = image.dataset.src || "";
    if (image.dataset.srcset) image.srcset = image.dataset.srcset;
    if (image.dataset.sizes) image.sizes = image.dataset.sizes;
    image.dataset.activated = "true";
  });
}

function scheduleOverflowHydration(countrySections) {
  const queue = [...countrySections];
  const run = () => {
    const section = queue.shift();
    if (!section) return;
    activateDeferredImages(section.querySelectorAll('[data-deferred-photo="true"]'));
    window.setTimeout(run, 120);
  };
  (window.requestIdleCallback || window.setTimeout)(run, 120);
}
```

- [ ] **Step 4: Run the script regression test**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_country_intro_script_contains_priority_loader_hooks -v`
Expected: PASS

- [ ] **Step 5: Commit client behavior**

```bash
git add static/country-intros.js tests/test_local_public_share.py
git commit -m "feat: prioritize deferred public gallery image loading"
```

### Task 5: Final verification

**Files:**
- Modify: `app.py`
- Modify: `templates/gallery.html`
- Modify: `templates/_photo_components.html`
- Modify: `static/country-intros.js`
- Modify: `static/style.css`
- Modify: `tests/test_local_public_share.py`

- [ ] **Step 1: Run targeted public gallery tests**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_public_homepage_renders_inline_country_expansion_with_deferred_overflow tests.test_local_public_share.LocalPublicShareTests.test_public_country_detail_page_renders_full_country_gallery tests.test_local_public_share.LocalPublicShareTests.test_country_intro_script_contains_priority_loader_hooks tests.test_local_public_share.LocalPublicShareTests.test_preview_card_sizes_use_smaller_public_gallery_widths -v`
Expected: PASS

- [ ] **Step 2: Run the full suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests pass

- [ ] **Step 3: Inspect worktree**

Run: `git status --short`
Expected: only intended feature files remain modified or staged

- [ ] **Step 4: Final commit**

```bash
git add app.py templates/gallery.html templates/_photo_components.html static/country-intros.js static/style.css tests/test_local_public_share.py docs/superpowers/plans/2026-04-19-progressive-country-expansion.md
git commit -m "feat: inline public country expansion with progressive loading"
```
