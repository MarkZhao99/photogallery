# 本地 iCloud 存储 + 公网分享操作说明

这套配置适用于当前项目继续使用 iCloud Drive 目录存图，同时把公共展示页分享给别人看。

## 我已经替你做好的部分

- 应用默认改为仅监听 `127.0.0.1`
- 应用默认关闭 Flask debug
- 公共展示实例启用 `PUBLIC_SITE_ONLY=true` 时，后台和 API 会返回 `404`
- 公共展示实例不再在页面请求中自动补写国家描述
- 新增了本地双实例启动、停止、状态检查、Quick Tunnel 分享脚本
- 新增了固定 Tunnel 配置模板
- 新增了一键双击启动和停止的 `.command` 文件
- 新增了项目内自动安装 `cloudflared` 的脚本

## 当前默认结构

- 后台管理：`http://127.0.0.1:5001/admin`
- 公共展示：`http://127.0.0.1:5002/gallery`
- 图片存储：`~/Library/Mobile Documents/com~apple~CloudDocs/web图库`

## 先决条件

1. 你已经安装项目依赖

```bash
cd /path/to/photogallery
pip install -r requirements.txt
```

2. 你的 `.env` 中继续保持 iCloud 存储

```env
PHOTO_STORAGE=icloud
ICLOUD_PHOTO_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/web图库
```

## 最简单的用法

如果你只是想尽快分享给别人看，现在最简单的步骤只有这一个：

1. 在 Finder 里双击 [start_public_gallery_share.command](start_public_gallery_share.command)

双击后它会自动完成这些事情：

- 自动下载并安装项目内的 `cloudflared`
- 自动启动后台实例和公共展示实例
- 自动建立一个临时公网地址
- 在终端窗口里直接显示那个公网地址

你只需要：

- 保持这个终端窗口不要关
- 把里面显示的 `https://xxxx.trycloudflare.com` 发给别人

停止时，双击 [stop_public_gallery_share.command](stop_public_gallery_share.command) 即可。

## 1. 启动本地后台和展示页

```bash
cd /path/to/photogallery
./scripts/start_local_gallery_stack.sh
```

启动后：

- 后台管理页：`http://127.0.0.1:5001/admin`
- 公共展示页：`http://127.0.0.1:5002/gallery`

## 2. 查看运行状态

```bash
./scripts/status_local_gallery_stack.sh
```

日志会写到：

```text
.runtime/
```

## 3. 停止本地服务

```bash
./scripts/stop_local_gallery_stack.sh
```

## 4. 临时分享给别人看

如果你不想双击 `.command`，也可以手动执行：

```bash
./scripts/install_cloudflared_local.sh
./scripts/start_local_gallery_stack.sh
./scripts/share_public_quick_tunnel.sh
```

终端里会出现一个类似下面的地址：

```text
https://xxxx.trycloudflare.com
```

把这个地址发给别人即可。这个地址是临时的，停止脚本后会失效。

## 5. 配置固定域名长期分享

### 你需要手动做的事情

1. 准备一个自己的域名
2. 把域名接入 Cloudflare
3. 安装 `cloudflared`
4. 执行 Cloudflare 登录

```bash
cloudflared tunnel login
```

5. 创建固定 Tunnel

```bash
cloudflared tunnel create gallery-public
```

6. 把仓库里的模板复制到 Cloudflare 默认配置目录

模板文件：

[cloudflared/gallery-public.example.yml](cloudflared/gallery-public.example.yml)

把里面这几项改掉：

- `REPLACE_WITH_YOUR_TUNNEL_UUID`
- `gallery.example.com`
- `credentials-file` 路径中的 UUID

7. 把改好的配置保存到：

```text
~/.cloudflared/config.yml
```

8. 给域名绑定 Tunnel

```bash
cloudflared tunnel route dns gallery-public gallery.你的域名.com
```

9. 启动 Tunnel

```bash
cloudflared tunnel run gallery-public
```

成功后，别人访问你的固定域名就能看到展示页。

## 6. 常见问题

### 为什么别人有时打不开

因为站点仍运行在你的电脑上。下面任何一个条件不满足，别人都打不开：

- 你的电脑开机
- 你的电脑联网
- 本地 Flask 进程还在运行
- Cloudflare Tunnel 还在运行
- 电脑没有睡眠断网

### 为什么后台没有公网地址

这是故意的。公网只应该暴露 `5002` 展示实例，后台继续只在本机使用。

### 为什么我在 iPhone 上能看但不能直接设壁纸

当前“桌面壁纸助手”是给 macOS 用的，不适用于 iPhone 系统壁纸设置。
