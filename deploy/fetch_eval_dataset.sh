#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

EVAL_URL="${EVAL_URL:-}"
EVAL_HTML_PATH="${EVAL_HTML_PATH:-$ROOT_DIR/data/evaluation_questions.html}"
EVAL_CSV_PATH="${EVAL_CSV_PATH:-$ROOT_DIR/data/evaluation_questions.csv}"

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
  if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
  fi
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
  load_env
  create_venv

  local url
  if [[ -n "$EVAL_URL" ]]; then
    url="$EVAL_URL"
  else
    [[ -n "${SSH_HOST:-}" && "${SSH_HOST}" != "xxx.xxx.xxx.xxx" ]] || fail "请在 .env 中设置 SSH_HOST，或通过 EVAL_URL 传入完整 URL"
    url="https://${SSH_HOST}:8443/questions.html"
  fi

  require_cmd curl
  mkdir -p "$(dirname "$EVAL_HTML_PATH")"
  mkdir -p "$(dirname "$EVAL_CSV_PATH")"

  log "下载评测集 HTML 到：$EVAL_HTML_PATH"
  curl -k -L "$url" -o "$EVAL_HTML_PATH"

  log "解析本地 HTML 并生成 CSV：$EVAL_CSV_PATH"
  "$VENV_DIR/bin/python" scripts/fetch_eval_questions.py \
    --input-html "$EVAL_HTML_PATH" \
    --output "$EVAL_CSV_PATH"

  log "完成"
}

main "$@"
