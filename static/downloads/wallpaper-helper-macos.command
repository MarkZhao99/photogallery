#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
HOST="127.0.0.1"
PORT="38941"

show_exit_hint() {
  if [[ -t 0 ]]; then
    echo ""
    read -r -p "按回车键关闭窗口..." _ || true
  fi
}

existing_pid="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
if [[ -n "$existing_pid" ]]; then
  health_json="$(curl -s --max-time 2 "http://${HOST}:${PORT}/health" 2>/dev/null || true)"

  if [[ "$health_json" == *"Wallpaper Helper"* ]]; then
    echo "桌面助手已经在运行，无需重复启动。"
    echo "运行地址：http://${HOST}:${PORT}"
    echo "进程 PID：${existing_pid}"
    show_exit_hint
    exit 0
  fi

  echo "端口 ${PORT} 已被其他程序占用，无法启动桌面助手。"
  echo "占用进程 PID：${existing_pid}"
  echo "请先关闭该进程后再重试。"
  show_exit_hint
  exit 1
fi

echo "Wallpaper Helper 正在启动..."
echo "启动后请保持这个窗口开启。"
echo ""

/usr/bin/python3 "$SCRIPT_DIR/wallpaper_helper_server.py"
