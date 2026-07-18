#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令: $1"
}

load_env() {
  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    fail "已创建 .env，请先编辑以下变量后再重新运行：DEMO_USERNAME、DEMO_PASSWORD、SESSION_SECRET"
  fi

  set -a
  source "$ROOT_DIR/.env"
  set +a

  [[ -n "${DEMO_USERNAME:-}" ]] || fail ".env 中缺少 DEMO_USERNAME"
  [[ -n "${DEMO_PASSWORD:-}" ]] || fail ".env 中缺少 DEMO_PASSWORD"
  [[ -n "${SESSION_SECRET:-}" ]] || fail ".env 中缺少 SESSION_SECRET"
  [[ "${SESSION_SECRET}" != "replace-with-a-long-random-string" ]] || fail "请将 SESSION_SECRET 替换为随机长字符串"
}

create_venv() {
  require_cmd "$PYTHON_BIN"
  log "创建虚拟环境并安装依赖"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  source "$VENV_DIR/bin/activate"
  pip install --upgrade pip
  pip install -r requirements.txt
}

main() {
  log "开始初始化应用环境，项目目录：$ROOT_DIR"
  load_env
  create_venv
  log "完成"
}

main "$@"
