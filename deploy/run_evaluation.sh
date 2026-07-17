#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

EVAL_FILE="${EVAL_FILE:-$ROOT_DIR/data/evaluation_questions.csv}"
EVAL_OUTPUT_DIR="${EVAL_OUTPUT_DIR:-$ROOT_DIR/data/eval}"
EVAL_LIMIT="${EVAL_LIMIT:-50}"
EVAL_OFFSET="${EVAL_OFFSET:-0}"
EVAL_LANGUAGE="${EVAL_LANGUAGE:-zh}"
EVAL_METHOD="${EVAL_METHOD:-pipeline}"
EVAL_TOP_K="${EVAL_TOP_K:-5}"
EVAL_NO_LLM="${EVAL_NO_LLM:-1}"
EVAL_USE_VECTOR="${EVAL_USE_VECTOR:-0}"
EVAL_API_URL="${EVAL_API_URL:-http://127.0.0.1:8000/api/chat}"
EVAL_LOGIN_URL="${EVAL_LOGIN_URL:-}"
EVAL_HTTP_TIMEOUT="${EVAL_HTTP_TIMEOUT:-60}"

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

  [[ -f "$EVAL_FILE" ]] || fail "缺少评测数据集：$EVAL_FILE（可先运行 ./deploy/fetch_eval_dataset.sh）"
  mkdir -p "$EVAL_OUTPUT_DIR"

  log "开始评测（method=${EVAL_METHOD}, limit=${EVAL_LIMIT}, offset=${EVAL_OFFSET}, lang=${EVAL_LANGUAGE}）"

  args=(
    "$VENV_DIR/bin/python" scripts/eval_questions.py
    --eval-file "$EVAL_FILE"
    --output-dir "$EVAL_OUTPUT_DIR"
    --limit "$EVAL_LIMIT"
    --offset "$EVAL_OFFSET"
    --language "$EVAL_LANGUAGE"
    --method "$EVAL_METHOD"
    --top-k "$EVAL_TOP_K"
    --timeout "$EVAL_HTTP_TIMEOUT"
  )

  if [[ "$EVAL_NO_LLM" == "1" ]]; then
    args+=(--no-llm)
  fi

  if [[ "$EVAL_USE_VECTOR" == "1" ]]; then
    args+=(--use-vector)
  else
    args+=(--no-vector)
  fi

  if [[ "$EVAL_METHOD" == "http" ]]; then
    args+=(--api-url "$EVAL_API_URL")
    if [[ -n "$EVAL_LOGIN_URL" ]]; then
      args+=(--login-url "$EVAL_LOGIN_URL")
    fi
    if [[ -n "${DEMO_USERNAME:-}" && -n "${DEMO_PASSWORD:-}" ]]; then
      args+=(--username "$DEMO_USERNAME" --password "$DEMO_PASSWORD")
    fi
  fi

  "${args[@]}"

  log "完成：$EVAL_OUTPUT_DIR"
}

main "$@"
