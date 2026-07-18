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

CURL_CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-10}"
CURL_MAX_TIME="${CURL_MAX_TIME:-120}"
CURL_RETRY="${CURL_RETRY:-2}"

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

ensure_venv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    fail "未找到虚拟环境：${VENV_DIR}/bin/python。请先运行 deploy/setup_app.sh"
  fi
}

ensure_python_deps() {
  if ! "$VENV_DIR/bin/python" - <<'PY'
import httpx  # noqa: F401
from bs4 import BeautifulSoup  # noqa: F401
PY
  then
    fail "虚拟环境缺少依赖（httpx/bs4）。请先运行 deploy/setup_app.sh 安装 requirements.txt"
  fi
}

main() {
  load_env
  ensure_venv
  ensure_python_deps

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

  log "下载 URL：$url"
  log "下载评测集 HTML 到：$EVAL_HTML_PATH"
  local http_code effective_url
  local curl_flags
  curl_flags=(-k -L --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" --retry "$CURL_RETRY" --retry-delay 1)
  if [[ -t 1 ]]; then
    curl_flags+=(--progress-bar)
  else
    curl_flags+=(-sS)
  fi

  local tmp_html
  tmp_html="${EVAL_HTML_PATH}.tmp.$$"
  local meta
  if ! meta="$(curl "${curl_flags[@]}" "$url" -o "$tmp_html" -w "%{http_code} %{url_effective}")"; then
    rm -f "$tmp_html" || true
    fail "下载失败：curl 执行出错（可尝试增大 CURL_MAX_TIME 或检查 Nginx/网络）"
  fi

  http_code="${meta%% *}"
  effective_url="${meta#* }"
  if [[ -z "${http_code:-}" || -z "${effective_url:-}" || "${http_code}" == "${meta}" ]]; then
    rm -f "$tmp_html" || true
    fail "下载失败：无法解析 curl 返回的 http_code/effective_url（meta=${meta})"
  fi

  log "下载完成：http_code=${http_code} effective_url=${effective_url}"

  if [[ ! -s "$tmp_html" ]]; then
    rm -f "$tmp_html" || true
    fail "下载的 HTML 为空：$EVAL_HTML_PATH"
  fi

  if [[ "$http_code" != "200" ]]; then
    log "HTML 预览（前 40 行）："
    sed -n '1,40p' "$tmp_html" || true
    rm -f "$tmp_html" || true
    fail "下载失败：http_code=${http_code}（请检查 URL/网络/Nginx 路由）"
  fi

  mv "$tmp_html" "$EVAL_HTML_PATH"

  if ! grep -q "QUESTIONS_DATA" "$EVAL_HTML_PATH"; then
    log "未在 HTML 中发现 QUESTIONS_DATA，通常表示拿到的不是题库页"
    log "HTML 预览（前 60 行）："
    sed -n '1,60p' "$EVAL_HTML_PATH" || true
  fi

  log "解析本地 HTML 并生成 CSV：$EVAL_CSV_PATH"
  if ! "$VENV_DIR/bin/python" scripts/fetch_eval_questions.py \
    --input-html "$EVAL_HTML_PATH" \
    --output "$EVAL_CSV_PATH"; then
    log "解析失败：通常是因为下载到的页面不是题库页（例如被重定向到 /chat，或页面使用 JS 动态渲染）"
    log "HTML 预览（前 60 行）："
    sed -n '1,60p' "$EVAL_HTML_PATH" || true
    fail "未能从 HTML 解析出题目，请检查 effective_url 与 HTML 内容"
  fi

  if [[ ! -s "$EVAL_CSV_PATH" ]]; then
    fail "CSV 生成失败或为空：$EVAL_CSV_PATH"
  fi

  log "CSV 预览（前 5 行）："
  sed -n '1,5p' "$EVAL_CSV_PATH" || true

  log "完成"
}

main "$@"
