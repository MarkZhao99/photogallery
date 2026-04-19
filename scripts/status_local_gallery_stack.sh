#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="${RUNTIME_DIR_OVERRIDE:-$ROOT_DIR/.runtime}"
APP_HOST="${APP_HOST:-127.0.0.1}"
ADMIN_PORT="${ADMIN_PORT:-5001}"
PUBLIC_PORT="${PUBLIC_PORT:-5002}"

print_service_status() {
  local name="$1"
  local port="$2"
  local pid_file="$RUNTIME_DIR/${name}.pid"
  local log_file="$RUNTIME_DIR/${name}.log"

  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(<"$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      if curl -fsS "http://${APP_HOST}:${port}/healthz" >/dev/null; then
        echo "${name}: 运行中，PID=${pid}，URL=http://${APP_HOST}:${port}"
      else
        echo "${name}: 进程存在但健康检查失败，PID=${pid}"
      fi
      echo "日志：$log_file"
      return
    fi
  fi

  echo "${name}: 未运行"
  echo "日志：$log_file"
}

print_service_status "admin" "$ADMIN_PORT"
print_service_status "public" "$PUBLIC_PORT"
