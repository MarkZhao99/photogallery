# 公网展示页部署到 Render

这个项目现在支持两套同时工作的形态：

- 本地后台：继续只在你自己的电脑上运行，负责上传、改国家、维护图片
- 公网展示页：部署到 Render，只开放公开展厅，不暴露后台和 API

实现方式：

- 本地和云端都改为 `PHOTO_STORAGE=webdav`
- 图片文件和元数据都共用同一个 WebDAV 目录
- 云端通过 `PUBLIC_SITE_ONLY=true` 自动关闭 `/admin`、`/admin/login`、`/api/*`

## 1. 准备 WebDAV

你需要一个外网可访问的 WebDAV 服务，用来同时存：

- 图片文件
- 远程元数据文件 `.photo-metadata.json`

需要准备这些变量：

- `WEBDAV_BASE_URL`
- `WEBDAV_USERNAME`
- `WEBDAV_PASSWORD`
- `WEBDAV_REMOTE_DIR`

## 2. 先迁移现有图片到 WebDAV

当前你的项目是 `PHOTO_STORAGE=icloud`。如果要部署到 Render，必须先把现有图片迁到 WebDAV。

先在本地 `.env` 里填好 WebDAV 变量，然后执行：

```bash
python3 scripts/migrate_to_webdav.py
```

默认会把当前 iCloud 目录中的图片、国家分类、标题和国家介绍迁移到 WebDAV。

如果你想从 `uploads/` 本地目录迁移，可以先设置：

```bash
MIGRATE_SOURCE=local python3 scripts/migrate_to_webdav.py
```

## 3. 本地后台切到 WebDAV

迁移完成后，把你本机 `.env` 改成：

```env
PHOTO_STORAGE=webdav
PUBLIC_SITE_ONLY=false
WEBDAV_BASE_URL=你的地址
WEBDAV_USERNAME=你的用户名
WEBDAV_PASSWORD=你的密码
WEBDAV_REMOTE_DIR=photo-wall
WEBDAV_METADATA_REMOTE_NAME=.photo-metadata.json
```

然后本地继续运行：

```bash
python3 app.py
```

这样你本地后台还是可用，但数据已经改成直接读写 WebDAV。

## 4. 部署公网展示页到 Render

Render 官方 Flask 部署文档：

- https://render.com/docs/deploy-flask

项目里已经附带了 [render.yaml](./render.yaml)，可以直接用 Blueprint 部署。

### Render 上的关键环境变量

公网展示页必须使用：

```env
PHOTO_STORAGE=webdav
PUBLIC_SITE_ONLY=true
WEBDAV_BASE_URL=你的地址
WEBDAV_USERNAME=你的用户名
WEBDAV_PASSWORD=你的密码
WEBDAV_REMOTE_DIR=photo-wall
WEBDAV_METADATA_REMOTE_NAME=.photo-metadata.json
```

可选：

```env
GEMINI_API_KEY=你的 Gemini API Key
GEMINI_VISION_MODEL=gemini-2.5-flash
```

如果配置了 `GEMINI_API_KEY`，你本地后台上传新图后，国家介绍会自动按图片内容更新；公网展示页会读取同一份远程元数据。Gemini 免费额度用完时，系统会保留当前已有的中文国家介绍，不会把它清空。

## 5. 为什么公网不会暴露后台

当 Render 环境里设置：

```env
PUBLIC_SITE_ONLY=true
```

应用会直接关闭这些路径：

- `/admin`
- `/admin/login`
- `/admin/logout`
- `/api/*`

也就是说，公网实例只保留：

- `/`
- `/gallery`
- `/photos/...`
- `/healthz`

这样别人只能看展示页，不能看到后台登录页。

## 6. 部署完成后

Render 会给你一个默认公网地址，通常类似：

```text
https://你的服务名.onrender.com
```

后续如果要换成你自己的域名，可以再在 Render 后台绑定自定义域名。
