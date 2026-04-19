#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

./scripts/stop_local_gallery_stack.sh

pkill -f "$ROOT_DIR/tools/cloudflared tunnel --url http://127.0.0.1:5002" 2>/dev/null || true

echo "本地服务已停止。"
echo "如果还有 Tunnel 终端窗口开着，直接关闭即可。"
