# iCloud 本地存储公网分享 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让项目在继续使用 iCloud 目录存图的前提下，能本地跑后台与展示双实例，并能把展示页安全地分享到公网。

**Architecture:** 应用通过 `APP_HOST`、`PORT` 与 `PUBLIC_SITE_ONLY` 区分后台实例和展示实例。脚本层负责启动、停止与检查两个本地实例，并为 Cloudflare Tunnel 提供临时分享和固定域名配置样板。公共实例在页面请求中保持只读，不补写国家描述。

**Tech Stack:** Python, Flask, unittest, zsh shell scripts, Cloudflare Tunnel

---

### Task 1: 运行模式回归测试

**Files:**
- Create: `tests/test_local_public_share.py`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Write the failing test**

```python
def test_main_defaults_bind_to_localhost(self):
    kwargs = run_app_as_main({})
    self.assertEqual(kwargs["host"], "127.0.0.1")
    self.assertEqual(kwargs["port"], 5001)
    self.assertFalse(kwargs["debug"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_local_public_share.py -v`
Expected: FAIL because the app currently binds to `0.0.0.0` with `debug=True`.

- [ ] **Step 3: Write minimal implementation**

```python
def server_host() -> str:
    return os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"

def server_port() -> int:
    return int(os.getenv("PORT", "5001"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_local_public_share.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_local_public_share.py app.py
git commit -m "test: cover local public share run mode"
```

### Task 2: 公共实例只读化

**Files:**
- Modify: `app.py`
- Test: `tests/test_local_public_share.py`

- [ ] **Step 1: Write the failing test**

```python
def test_public_only_home_does_not_refresh_country_descriptions(self):
    response = client.get("/")
    self.assertEqual(response.status_code, 200)
    refresh_mock.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_local_public_share.py -v`
Expected: FAIL because the public page still triggers description refresh.

- [ ] **Step 3: Write minimal implementation**

```python
def render_public_gallery():
    photos = storage.list_photos()
    ensure_missing_descriptions = not public_site_only()
    return render_template("gallery.html", photos=photos, groups=build_groups(photos, ensure_missing_descriptions=ensure_missing_descriptions))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_local_public_share.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_local_public_share.py app.py
git commit -m "fix: keep public-only gallery read-only"
```

### Task 3: 本地双实例脚本

**Files:**
- Create: `scripts/start_local_gallery_stack.sh`
- Create: `scripts/stop_local_gallery_stack.sh`
- Create: `scripts/status_local_gallery_stack.sh`
- Create: `scripts/share_public_quick_tunnel.sh`

- [ ] **Step 1: Write the failing test**

```bash
bash -n scripts/start_local_gallery_stack.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash -n scripts/start_local_gallery_stack.sh`
Expected: FAIL because the file does not exist.

- [ ] **Step 3: Write minimal implementation**

```bash
env APP_HOST=127.0.0.1 PORT=5001 PUBLIC_SITE_ONLY=false "$PYTHON_BIN" app.py
env APP_HOST=127.0.0.1 PORT=5002 PUBLIC_SITE_ONLY=true "$PYTHON_BIN" app.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash -n scripts/start_local_gallery_stack.sh scripts/stop_local_gallery_stack.sh scripts/status_local_gallery_stack.sh scripts/share_public_quick_tunnel.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/start_local_gallery_stack.sh scripts/stop_local_gallery_stack.sh scripts/status_local_gallery_stack.sh scripts/share_public_quick_tunnel.sh
git commit -m "feat: add local gallery share scripts"
```

### Task 4: 配置样板与中文文档

**Files:**
- Create: `cloudflared/gallery-public.example.yml`
- Create: `LOCAL_PUBLIC_SHARE_ICLOUD.md`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```bash
test -f cloudflared/gallery-public.example.yml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `test -f cloudflared/gallery-public.example.yml`
Expected: exit status 1 because the template file does not exist.

- [ ] **Step 3: Write minimal implementation**

```yaml
ingress:
  - hostname: gallery.example.com
    service: http://127.0.0.1:5002
```

- [ ] **Step 4: Run test to verify it passes**

Run: `test -f cloudflared/gallery-public.example.yml && test -f LOCAL_PUBLIC_SHARE_ICLOUD.md`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cloudflared/gallery-public.example.yml LOCAL_PUBLIC_SHARE_ICLOUD.md .env.example README.md
git commit -m "docs: add icloud public share guide"
```
