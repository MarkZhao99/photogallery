#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

./scripts/install_cloudflared_local.sh
./scripts/start_local_gallery_stack.sh

echo ""
echo "本地服务已经启动。"
echo "后台管理页：http://127.0.0.1:5001/admin"
echo "公共展示页：http://127.0.0.1:5002/gallery"
echo "下面开始创建临时公网地址。请保持这个终端窗口开启。"
echo ""

./scripts/share_public_quick_tunnel.sh
