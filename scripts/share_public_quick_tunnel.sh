#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_HOST="${APP_HOST:-127.0.0.1}"
PUBLIC_PORT="${PUBLIC_PORT:-5002}"
LOCAL_CLOUDFLARED_BIN="$ROOT_DIR/tools/cloudflared"

CLOUDFLARED_BIN=""
if [[ -x "$LOCAL_CLOUDFLARED_BIN" ]]; then
  CLOUDFLARED_BIN="$LOCAL_CLOUDFLARED_BIN"
elif command -v cloudflared >/dev/null 2>&1; then
  CLOUDFLARED_BIN="$(command -v cloudflared)"
fi

if [[ -z "$CLOUDFLARED_BIN" ]]; then
  echo "未检测到 cloudflared。"
  echo "可以先执行：./scripts/install_cloudflared_local.sh"
  exit 1
fi

if ! curl -fsS "http://${APP_HOST}:${PUBLIC_PORT}/healthz" >/dev/null; then
  echo "公共展示实例未运行，请先执行：./scripts/start_local_gallery_stack.sh"
  exit 1
fi

echo "正在把公共展示页分享为临时公网地址。按 Ctrl+C 可停止分享。"
exec "$CLOUDFLARED_BIN" tunnel --url "http://${APP_HOST}:${PUBLIC_PORT}"
