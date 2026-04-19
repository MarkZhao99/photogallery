#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="${RUNTIME_DIR_OVERRIDE:-$ROOT_DIR/.runtime}"
mkdir -p "$RUNTIME_DIR"
APP_HOST="${APP_HOST:-127.0.0.1}"
ADMIN_PORT="${ADMIN_PORT:-5001}"
PUBLIC_PORT="${PUBLIC_PORT:-5002}"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

start_service() {
  local name="$1"
  local port="$2"
  local public_site_only="$3"
  local pid_file="$RUNTIME_DIR/${name}.pid"
  local log_file="$RUNTIME_DIR/${name}.log"

  if curl -fsS "http://${APP_HOST}:${port}/healthz" >/dev/null 2>&1; then
    echo "${name} 已在端口 ${port} 提供服务：http://${APP_HOST}:${port}"
    return
  fi

  if [[ -f "$pid_file" ]]; then
    local existing_pid
    existing_pid="$(<"$pid_file")"
    if kill -0 "$existing_pid" 2>/dev/null; then
      echo "${name} 已在运行，PID=${existing_pid}"
      return
    fi
    rm -f "$pid_file"
  fi

  : > "$log_file"
  (
    cd "$ROOT_DIR"
    nohup env APP_HOST="$APP_HOST" \
      PORT="$port" \
      PUBLIC_SITE_ONLY="$public_site_only" \
      FLASK_DEBUG=false \
      "$PYTHON_BIN" app.py >> "$log_file" 2>&1 < /dev/null &
    echo $! > "$pid_file"
  )

  sleep 2
  if ! curl -fsS "http://${APP_HOST}:${port}/healthz" >/dev/null; then
    echo "${name} 启动失败，请检查日志：$log_file"
    tail -n 40 "$log_file" || true
    exit 1
  fi

  echo "${name} 已启动：http://${APP_HOST}:${port}"
}

start_service "admin" "$ADMIN_PORT" "false"
start_service "public" "$PUBLIC_PORT" "true"

echo ""
echo "后台管理页：http://${APP_HOST}:${ADMIN_PORT}/admin"
echo "公共展示页：http://${APP_HOST}:${PUBLIC_PORT}/gallery"
echo "运行日志目录：$RUNTIME_DIR"
