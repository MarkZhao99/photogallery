# Photo Shelf

本地优先的照片图库，支持 `iCloud Drive`、本地目录和 `WebDAV` 三种存储方式。项目提供公开图库和后台管理页，并且可以对新上传、状态为 `pending` 的照片做异步识图，自动补充标题和元数据。

## 现在这个项目能做什么

- 按国家上传和整理照片
- 在公开页按国家分组展示照片
- 为国家章节生成短版和长版导语
- 对新上传的 `pending` 照片异步补全标题、城市、地点、主体和场景摘要
- 用后台队列追踪 `pending / processing / done / review` 状态
- 在 macOS 上通过 `launchd` 常驻运行后台 worker
- 在 iCloud 模式下启动本地双实例，并用 `cloudflared` 临时对外分享公开图库

## 项目结构

- `app.py`: Flask 应用入口，上传、公开页、后台页、队列接口都在这里
- `storage.py`: 照片与元数据存储抽象，支持 `local / icloud / webdav`
- `scripts/auto_metadata_worker.py`: 运行一次异步元数据处理
- `scripts/install_auto_metadata_worker_launchd.py`: 安装或移除后台 worker 的 `launchd` LaunchAgent
- `scripts/process_gallery_metadata.py`: 手动导出和回填小批量待处理照片
- `templates/`: 页面模板
- `tests/`: 回归测试
- `docs/superpowers/`: 设计、计划和交接文档

## 快速启动

1. 创建虚拟环境并激活：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 复制环境变量模板：

```bash
cp .env.example .env
```

4. 最少要配置这些字段：

```bash
PHOTO_STORAGE=icloud
ICLOUD_PHOTO_DIR=~/Library/Mobile\ Documents/com~apple~CloudDocs/web图库
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this-admin-password
ADMIN_SESSION_SECRET=change-this-session-secret
MAX_UPLOAD_MB=50
```

5. 启动应用：

```bash
python3 app.py
```

6. 打开页面：

- 公开图库：`http://127.0.0.1:5001`
- 后台登录：`http://127.0.0.1:5001/admin/login`

## 存储模式

### iCloud

默认推荐：

```bash
PHOTO_STORAGE=icloud
ICLOUD_PHOTO_DIR=~/Library/Mobile\ Documents/com~apple~CloudDocs/web图库
```

照片文件和 `photo-metadata.json` 会保存在本机 iCloud Drive 目录，并跟随 iCloud 同步。

### Local

```bash
PHOTO_STORAGE=local
```

照片会保存到仓库内的 `uploads/` 目录，适合纯本地开发。

### WebDAV

```bash
PHOTO_STORAGE=webdav
WEBDAV_BASE_URL=https://your-webdav-host/dav/
WEBDAV_USERNAME=your-username
WEBDAV_PASSWORD=your-password
WEBDAV_REMOTE_DIR=photo-wall
WEBDAV_METADATA_REMOTE_NAME=.photo-metadata.json
```

适合挂到自建网盘或对象存储网关。

## 自动元数据流程

上传系统已经改成“快上传、慢处理”的异步模式：

1. 后台上传照片时，先只保存文件和基础国家信息
2. 新照片会被标记成 `pending`
3. 后台 worker 再去认图并补全：
   `title`、`city`、`place`、`subject`、`scene_summary`
4. 处理完成后，状态会进入 `done`；需要人工复核时进入 `review`

### 为什么这样设计

这样做是为了同时解决两个问题：

- 上传请求不再被识图流程阻塞，后台响应更快
- 每次只处理很小的一批照片，并且每批都走一个新的短 `codex exec` 子进程，避免请求体和上下文膨胀，降低 `413` 和长会话失控风险

### 批处理约束

- 单批最多 5 张
- 单次只处理同一个国家
- `pending -> processing -> done/review`
- 超时或失败会按重试规则回退

### 手动执行一次 worker

```bash
python3 scripts/auto_metadata_worker.py
```

### 安装后台常驻 worker

```bash
python3 scripts/install_auto_metadata_worker_launchd.py install
```

移除：

```bash
python3 scripts/install_auto_metadata_worker_launchd.py uninstall
```

### 手动导出一批待处理照片

```bash
python3 scripts/process_gallery_metadata.py pending-batch --limit 5
```

### 手动回填模型结果

```bash
python3 scripts/process_gallery_metadata.py apply-batch --input /absolute/path/to/result.json
```

## 本地公开分享

如果你使用 iCloud 模式，本仓库自带本地双实例启动脚本：

- 后台实例：`127.0.0.1:5001`
- 公开实例：`127.0.0.1:5002`

常用命令：

```bash
./scripts/start_local_gallery_stack.sh
./scripts/status_local_gallery_stack.sh
./scripts/stop_local_gallery_stack.sh
```

macOS 一键分享：

- [start_public_gallery_share.command](start_public_gallery_share.command)
- [stop_public_gallery_share.command](stop_public_gallery_share.command)

手动临时公网分享：

```bash
./scripts/install_cloudflared_local.sh
./scripts/share_public_quick_tunnel.sh
```

详细说明见 [LOCAL_PUBLIC_SHARE_ICLOUD.md](LOCAL_PUBLIC_SHARE_ICLOUD.md)。

## 413 和上下文膨胀规避

这个仓库针对“图片任务把请求体撑大”的问题已经做了明确约束：

- 不把大批量图片直接塞进一个长对话
- 优先从本地文件读取，而不是把大块内容贴进聊天上下文
- 用交接文档承接状态，而不是依赖超长会话历史
- 图片识图一律切成小批次
- 每批都启动新的短进程，不复用超长模型上下文

如果你继续做图片整理，优先看最新 handoff，再用短会话逐批处理。

## 测试

运行完整测试：

```bash
python3 -m unittest discover -s tests -v
```

## 日常 Git 工作流

以后最常用的 4 条命令就是：

```bash
git status -sb
git add -A
git commit -m "feat: your change summary"
git push
```

推荐习惯：

- 每次只做一小类改动后再提交
- 提交信息写成 `feat:`、`fix:`、`docs:`、`chore:` 这种短前缀
- 不要把临时日志、缓存、上传目录和本地密钥提交进 Git

第一次在新机器上推送 `GitHub` 时，如果需要认证：

- Username: 你的 GitHub 用户名
- Password: 你的 GitHub PAT

## 相关文档

- [自动 pending 图片元数据设计](docs/superpowers/specs/2026-04-19-auto-pending-photo-metadata-design.md)
- [短会话边界提醒设计](docs/superpowers/specs/2026-04-19-short-session-boundary-notifier-design.md)
- [最近的交接说明](docs/superpowers/handoffs/2026-04-19-country-intro-and-413.md)

## 备注

- 支持的图片格式：`jpg`、`jpeg`、`png`、`gif`、`webp`
- 公开访客只能访问 `/` 和 `/gallery`
- 图片读取通过 `/photos/<filename>` 代理，存储凭据不会暴露给浏览器
- 如果 WebDAV 使用自签名证书，可能需要额外处理 `requests` 的 SSL 配置
