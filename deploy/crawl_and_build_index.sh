#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
CRAWL_FULL_SITE="${CRAWL_FULL_SITE:-1}"
CRAWL_LIMIT="${CRAWL_LIMIT:-850}"
CRAWL_RATE_LIMIT="${CRAWL_RATE_LIMIT:-0.75}"
BUILD_VECTOR_INDEX="${BUILD_VECTOR_INDEX:-0}"
DATABASE_PATH="${DATABASE_PATH:-data/rag.sqlite3}"
INDEX_DIR="${INDEX_DIR:-data/index}"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

run_with_progress() {
  local label="$1"
  shift
  local start_ts
  start_ts="$(date +%s)"

  "$@" &
  local pid=$!

  if [[ -t 1 ]]; then
    while kill -0 "$pid" >/dev/null 2>&1; do
      local now_ts elapsed
      now_ts="$(date +%s)"
      elapsed=$((now_ts - start_ts))
      printf "\r[%s] %s... (%ds)" "$(date '+%F %T')" "$label" "$elapsed"
      sleep 2
    done
    echo
  else
    while kill -0 "$pid" >/dev/null 2>&1; do
      local now_ts elapsed
      now_ts="$(date +%s)"
      elapsed=$((now_ts - start_ts))
      log "${label}... (${elapsed}s)"
      sleep 15
    done
  fi

  wait "$pid"
}

load_env_optional() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
  fi
}

ensure_venv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    fail "未找到虚拟环境：${VENV_DIR}/bin/python。请先运行 deploy/setup_app.sh"
  fi
}

crawl_and_build_index() {
  mkdir -p "$(dirname "$DATABASE_PATH")"
  mkdir -p "$INDEX_DIR"

  if [[ "$CRAWL_FULL_SITE" == "1" ]]; then
    log "执行全站爬取 (需要等待十几分钟)"
    run_with_progress \
      "正在爬取数据（crawl.py --full-site）" \
      "$VENV_DIR/bin/python" scripts/crawl.py --full-site --limit "$CRAWL_LIMIT" --rate-limit "$CRAWL_RATE_LIMIT" --database "$DATABASE_PATH"
  else
    log "跳过全站爬取（CRAWL_FULL_SITE=${CRAWL_FULL_SITE}）"
  fi

  log "构建索引"
  if [[ "$BUILD_VECTOR_INDEX" == "1" ]]; then
    [[ -n "${OPENAI_API_KEY:-}" ]] || fail "BUILD_VECTOR_INDEX=1 时必须配置 OPENAI_API_KEY"
    run_with_progress \
      "正在构建索引（build_index.py --with-vector）" \
      "$VENV_DIR/bin/python" scripts/build_index.py --with-vector --database "$DATABASE_PATH" --index-dir "$INDEX_DIR"
  else
    run_with_progress \
      "正在构建索引（build_index.py）" \
      "$VENV_DIR/bin/python" scripts/build_index.py --database "$DATABASE_PATH" --index-dir "$INDEX_DIR"
  fi
}

main() {
  log "开始爬取与建索引，项目目录：$ROOT_DIR"
  load_env_optional
  ensure_venv
  crawl_and_build_index
  log "完成"
}

main "$@"
