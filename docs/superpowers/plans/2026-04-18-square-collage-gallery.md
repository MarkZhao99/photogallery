# Square Collage Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current loose waterfall gallery with a tight square collage layout that uses mixed tile sizes, minimal gaps, and the same visual structure on both the public gallery and the admin gallery.

**Architecture:** Keep the existing Flask + Jinja rendering flow and change the gallery at the template/CSS layer instead of adding a new layout engine. Server-rendered pages will emit deterministic collage tile classes from the photo index, and the admin page’s client-side `renderGroups()` path will mirror the same tile cycle so post-upload refreshes match the initial server render.

**Tech Stack:** Python 3.9, Flask, Jinja templates, vanilla JavaScript, CSS Grid, unittest

---

## File Structure

**Modify**
- `tests/test_local_public_share.py`
  - Extend the fake gallery fixture to cover multi-photo collage output
  - Add HTML and stylesheet regression tests for the square collage layout
- `templates/_photo_components.html`
  - Add a `collage_slot` input to the shared photo-card macro and emit deterministic tile classes
- `templates/gallery.html`
  - Pass the per-photo collage slot into public gallery cards
- `templates/index.html`
  - Pass the per-photo collage slot into admin cards
  - Update the admin-side `photo-card-template` and `renderGroups()` logic so live refreshes use the same collage classes
- `static/style.css`
  - Replace the current `column-count` waterfall rules with a dense CSS Grid collage
  - Make every tile square-cropped with minimal gaps and reduced frame whitespace

**No Commit Note**
- This workspace currently has no `.git` directory. Any “commit” step below becomes a progress checkpoint using `sed`, `rg`, or the test output instead of an actual git commit.

---

### Task 1: Lock Down Collage Markup With Failing Tests

**Files:**
- Modify: `tests/test_local_public_share.py:67-184`
- Modify: `templates/_photo_components.html:1-42`
- Modify: `templates/gallery.html:135-143`
- Modify: `templates/index.html:214-221`
- Modify: `templates/index.html:578-614`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Write the failing collage markup tests**

Replace the single-photo fake fixture with a five-photo country fixture so the markup can exercise multiple tile sizes, then add these tests to `tests/test_local_public_share.py`:

```python
class FakeStorage:
    def list_photos(self) -> list[dict]:
        return [
            {
                "name": "奥地利/demo-1.jpg",
                "url": "/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo-1.jpg",
                "country": "奥地利",
                "title": "demo-1",
                "size": 123,
                "modified_at": "2026-04-17T18:00:00",
            },
            {
                "name": "奥地利/demo-2.jpg",
                "url": "/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo-2.jpg",
                "country": "奥地利",
                "title": "demo-2",
                "size": 124,
                "modified_at": "2026-04-17T18:00:01",
            },
            {
                "name": "奥地利/demo-3.jpg",
                "url": "/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo-3.jpg",
                "country": "奥地利",
                "title": "demo-3",
                "size": 125,
                "modified_at": "2026-04-17T18:00:02",
            },
            {
                "name": "奥地利/demo-4.jpg",
                "url": "/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo-4.jpg",
                "country": "奥地利",
                "title": "demo-4",
                "size": 126,
                "modified_at": "2026-04-17T18:00:03",
            },
            {
                "name": "奥地利/demo-5.jpg",
                "url": "/photos/%E5%A5%A5%E5%9C%B0%E5%88%A9/demo-5.jpg",
                "country": "奥地利",
                "title": "demo-5",
                "size": 127,
                "modified_at": "2026-04-17T18:00:04",
            },
        ]

    def list_country_descriptions(self) -> dict[str, dict[str, str]]:
        return {
            "奥地利": {
                "short_description": "湖山与旧镇在静光里缓慢展开。",
                "long_description": "奥地利的影像沿着湖岸、小镇与山体层层展开，冷冽空气中的尖顶、屋脊与水面反光共同勾勒出一种克制而古典的秩序。",
            }
        }


def test_public_gallery_uses_square_collage_tile_markup(self):
    with loaded_app_module(PUBLIC_SITE_ONLY="true") as app_module:
        app_module.storage = FakeStorage()
        response = app_module.app.test_client().get("/")

    html = response.get_data(as_text=True)
    self.assertEqual(response.status_code, 200)
    self.assertIn('class="gallery-grid collage-grid"', html)
    self.assertIn("collage-tile-hero", html)
    self.assertIn("collage-tile-wide", html)
    self.assertIn("collage-tile-standard", html)


def test_admin_gallery_uses_square_collage_tile_markup(self):
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
    self.assertIn('class="gallery-grid collage-grid"', html)
    self.assertIn("collage-tile-hero", html)
    self.assertIn("collage-tile-wide", html)
    self.assertIn('const collageCycle = ["collage-tile-hero"', html)
```

- [ ] **Step 2: Run the collage markup tests to verify they fail**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_public_gallery_uses_square_collage_tile_markup tests.test_local_public_share.LocalPublicShareTests.test_admin_gallery_uses_square_collage_tile_markup -v`

Expected: `FAIL` because the current templates still render plain `.gallery-grid` and `.photo-card` without any collage tile classes or admin-side collage cycle logic.

- [ ] **Step 3: Write the minimal server and admin markup implementation**

Update the shared macro in `templates/_photo_components.html` so it can receive a per-photo collage slot:

```jinja2
{% macro photo_card(photo, editable=False, collage_slot="collage-tile-standard") -%}
<article
  class="photo-card collage-tile {{ collage_slot }}{% if editable %} editable-photo-card{% else %} public-photo-card{% endif %}"
  data-collage-slot="{{ collage_slot }}"
  {% if editable %}
  data-photo-name="{{ photo.name }}"
  data-photo-country="{{ photo.country }}"
  data-photo-title="{{ photo.title }}"
  {% endif %}
>
```

Pass a deterministic slot cycle from the public template:

```jinja2
{% set collage_cycle = [
  "collage-tile-hero",
  "collage-tile-tall",
  "collage-tile-wide",
  "collage-tile-standard",
  "collage-tile-wide",
  "collage-tile-standard"
] %}

<div class="gallery-grid collage-grid">
  {% for photo in group.photos %}
  {{ photo_card(photo, collage_slot=collage_cycle[loop.index0 % (collage_cycle|length)]) }}
  {% endfor %}
</div>
```

Mirror the same cycle in `templates/index.html` for both the server-rendered loop and the client-side refresh path:

```jinja2
{% set collage_cycle = [
  "collage-tile-hero",
  "collage-tile-tall",
  "collage-tile-wide",
  "collage-tile-standard",
  "collage-tile-wide",
  "collage-tile-standard"
] %}

<div class="gallery-grid collage-grid">
  {% for photo in group.photos %}
  {{ photo_card(photo, editable=True, collage_slot=collage_cycle[loop.index0 % (collage_cycle|length)]) }}
  {% endfor %}
</div>
```

```html
<template id="photo-card-template">
  <article class="photo-card collage-tile collage-tile-standard editable-photo-card" data-collage-slot="collage-tile-standard">
    <button class="edit-photo-button" type="button" data-action="edit-photo">编辑资料</button>
    <button class="photo-view-button" type="button" data-action="open-lightbox">
      <img alt="" loading="lazy">
      <span class="photo-view-hint">查看大图</span>
    </button>
  </article>
</template>
```

```javascript
const collageCycle = [
  "collage-tile-hero",
  "collage-tile-tall",
  "collage-tile-wide",
  "collage-tile-standard",
  "collage-tile-wide",
  "collage-tile-standard",
];

function collageSlotForIndex(photoIndex) {
  return collageCycle[photoIndex % collageCycle.length];
}

function applyCollageSlot(cardElement, photoIndex) {
  const slot = collageSlotForIndex(photoIndex);
  cardElement.classList.remove(...collageCycle);
  cardElement.classList.add(slot);
  cardElement.dataset.collageSlot = slot;
}
```

Call `applyCollageSlot(cardElement, photoIndex)` inside `renderGroups()` before appending each card, and change each gallery wrapper there to `.gallery-grid.collage-grid`.

- [ ] **Step 4: Run the collage markup tests to verify they pass**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_public_gallery_uses_square_collage_tile_markup tests.test_local_public_share.LocalPublicShareTests.test_admin_gallery_uses_square_collage_tile_markup -v`

Expected: both tests `OK`.

- [ ] **Step 5: Record the progress checkpoint**

Run: `rg -n "collage-grid|collage-tile-hero|const collageCycle" templates/_photo_components.html templates/gallery.html templates/index.html`

Expected: the macro, public template, and admin template all show the new collage class hooks.

---

### Task 2: Red-Green the Tight Square Collage Styles

**Files:**
- Modify: `tests/test_local_public_share.py:185-220`
- Modify: `static/style.css:879-980`
- Modify: `static/style.css:1792-1854`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Write the failing stylesheet regression test**

Add this test to `tests/test_local_public_share.py`:

```python
def test_stylesheet_uses_dense_square_collage_rules(self):
    style_text = (PROJECT_ROOT / "static/style.css").read_text(encoding="utf-8")

    self.assertIn(".gallery-grid.collage-grid", style_text)
    self.assertIn("grid-auto-flow: dense", style_text)
    self.assertRegex(style_text, r"gap:\\s*2px;")
    self.assertIn("aspect-ratio: 1 / 1", style_text)
    self.assertIn("object-fit: cover", style_text)
    self.assertIn(".collage-tile-hero", style_text)
    self.assertIn(".collage-tile-wide", style_text)
```

- [ ] **Step 2: Run the stylesheet test to verify it fails**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_stylesheet_uses_dense_square_collage_rules -v`

Expected: `FAIL` because the current stylesheet still uses `column-count`, `column-gap: 10px`, `height: auto`, and `object-fit: contain`.

- [ ] **Step 3: Write the minimal collage CSS implementation**

Replace the current gallery waterfall rules in `static/style.css` with a dense collage grid:

```css
.gallery-grid.collage-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-auto-flow: dense;
  gap: 2px;
  margin-top: 2px;
}

.photo-card.collage-tile {
  margin: 0;
  aspect-ratio: 1 / 1;
  overflow: hidden;
  transform: none;
}

.collage-tile-hero {
  grid-column: span 2;
  grid-row: span 2;
}

.collage-tile-wide {
  grid-column: span 2;
  grid-row: span 1;
}

.collage-tile-tall {
  grid-column: span 1;
  grid-row: span 2;
}

.photo-card.collage-tile img,
.photo-card.collage-tile .photo-view-button,
.photo-card.collage-tile .photo-view-button img {
  width: 100%;
  height: 100%;
  border-radius: 0;
}

.photo-card.collage-tile img {
  object-fit: cover;
}
```

Tighten the frame spacing and mobile behavior:

```css
.country-section {
  gap: 14px;
  padding: 18px 12px 12px;
}

@media (max-width: 720px) {
  .gallery-grid.collage-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 2px;
  }

  .country-section {
    gap: 12px;
    padding: 14px 8px 8px;
  }

  .edit-photo-button {
    top: 8px;
    right: 8px;
    min-height: 32px;
    padding: 0 10px;
  }
}
```

Also remove or override the current `hover` lift and `border-radius: 8px` rules for collage tiles so the grid reads like one continuous wall instead of separated cards.

- [ ] **Step 4: Run the stylesheet test to verify it passes**

Run: `python3 -m unittest tests.test_local_public_share.LocalPublicShareTests.test_stylesheet_uses_dense_square_collage_rules -v`

Expected: `OK`

- [ ] **Step 5: Record the progress checkpoint**

Run: `rg -n "gallery-grid\\.collage-grid|aspect-ratio: 1 / 1|object-fit: cover|collage-tile-hero|gap: 2px" static/style.css`

Expected: the stylesheet now contains the dense square collage rules and tile size variants.

---

### Task 3: Verify Full Behavior and Runtime Output

**Files:**
- Test: `tests/test_local_public_share.py`
- Test: `tests/test_country_descriptions.py`
- Test: `tests/test_country_intro_storage.py`

- [ ] **Step 1: Run the full public-share test module**

Run: `python3 -m unittest tests/test_local_public_share.py -v`

Expected: `OK`

- [ ] **Step 2: Run the complete test suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: `Ran 24 tests` or more with `OK`

- [ ] **Step 3: Restart the local admin and public services**

Run:

```bash
lsof -nP -iTCP:5001 -sTCP:LISTEN
lsof -nP -iTCP:5002 -sTCP:LISTEN
kill <admin-pid>
kill <public-pid>
python3 app.py
PUBLIC_SITE_ONLY=true PORT=5002 python3 app.py
```

Expected: fresh Flask processes listening on `127.0.0.1:5001` and `127.0.0.1:5002`

- [ ] **Step 4: Verify the rendered public page exposes the collage markup**

Run: `curl -s http://127.0.0.1:5002 | rg -n "gallery-grid collage-grid|collage-tile-hero|collage-tile-wide|data-collage-slot"`

Expected: HTML output includes the collage grid wrapper and multiple tile classes or slot attributes

- [ ] **Step 5: Record the final checkpoint**

Because there is no git repository, record completion by capturing the final verification output:

Run:

```bash
python3 -m unittest discover -s tests -v
curl -s http://127.0.0.1:5002 | rg -n "gallery-grid collage-grid|collage-tile-hero|collage-tile-wide"
```

Expected: tests pass and the public page shows the collage hooks in live HTML.
