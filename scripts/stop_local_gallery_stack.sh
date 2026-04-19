#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="${RUNTIME_DIR_OVERRIDE:-$ROOT_DIR/.runtime}"

stop_service() {
  local name="$1"
  local pid_file="$RUNTIME_DIR/${name}.pid"

  if [[ ! -f "$pid_file" ]]; then
    echo "${name} 未运行"
    return
  fi

  local pid
  pid="$(<"$pid_file")"

  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..10}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "${name} 已停止"
  else
    echo "${name} 进程已不存在"
  fi

  rm -f "$pid_file"
}

stop_service "admin"
stop_service "public"
