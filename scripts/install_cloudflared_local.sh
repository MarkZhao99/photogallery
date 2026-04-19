#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_BIN="$ROOT_DIR/tools/cloudflared"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$(dirname "$TARGET_BIN")"

if [[ -x "$TARGET_BIN" ]]; then
  echo "已存在本地 cloudflared：$TARGET_BIN"
  "$TARGET_BIN" --version
  exit 0
fi

platform="$(uname -s)"
arch="$(uname -m)"

case "${platform}-${arch}" in
  Darwin-arm64)
    download_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz"
    ;;
  Darwin-x86_64)
    download_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
    ;;
  Linux-x86_64)
    download_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
    ;;
  Linux-arm64|Linux-aarch64)
    download_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
    ;;
  *)
    echo "暂不支持自动安装当前平台：${platform}-${arch}"
    exit 1
    ;;
esac

echo "正在下载 cloudflared..."
echo "来源：$download_url"

if [[ "$download_url" == *.tgz ]]; then
  archive_path="$TMP_DIR/cloudflared.tgz"
  curl -fL "$download_url" -o "$archive_path"
  tar -xzf "$archive_path" -C "$TMP_DIR"
  mv "$TMP_DIR/cloudflared" "$TARGET_BIN"
else
  curl -fL "$download_url" -o "$TARGET_BIN"
fi

chmod +x "$TARGET_BIN"

echo "cloudflared 已安装到：$TARGET_BIN"
"$TARGET_BIN" --version
