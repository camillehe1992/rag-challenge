#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_NAME="${SERVICE_NAME:-thss-rag}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
FETCH_EVAL_DATASET="${FETCH_EVAL_DATASET:-1}"
EVAL_URL="${EVAL_URL:-}"
CRAWL_FULL_SITE="${CRAWL_FULL_SITE:-1}"
CRAWL_LIMIT="${CRAWL_LIMIT:-850}"
BUILD_VECTOR_INDEX="${BUILD_VECTOR_INDEX:-0}"
INSTALL_SYSTEMD="${INSTALL_SYSTEMD:-1}"
WRITE_NGINX_SNIPPET="${WRITE_NGINX_SNIPPET:-1}"
DEPLOY_DIR="${DEPLOY_DIR:-$PROJECT_DIR/deploy}"
SYSTEMD_UNIT_PREVIEW_PATH="$DEPLOY_DIR/${SERVICE_NAME}.service"
NGINX_SNIPPET_PATH="$DEPLOY_DIR/nginx-${SERVICE_NAME}.conf.snippet"

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
  if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    fail "已创建 .env，请先编辑以下变量后再重新运行：DEMO_USERNAME、DEMO_PASSWORD、SESSION_SECRET、SERVER_HOST"
  fi

  set -a
  source "$PROJECT_DIR/.env"
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

fetch_eval_dataset() {
  if [[ "$FETCH_EVAL_DATASET" != "1" ]]; then
    log "跳过评测集抓取（FETCH_EVAL_DATASET=$FETCH_EVAL_DATASET）"
    return
  fi

  if [[ -z "${SERVER_HOST:-}" || "${SERVER_HOST}" == "xxx.xxx.xxx.xxx" ]]; then
    log "跳过评测集抓取：.env 中 SERVER_HOST 未设置为真实服务器地址"
    return
  fi

  local url
  url="${EVAL_URL:-https://${SERVER_HOST}:8443/questions.html}"

  log "抓取评测数据集"
  if ! "$VENV_DIR/bin/python" scripts/fetch_eval_questions.py \
    --url "$url" \
    --output data/evaluation_questions.csv \
    --insecure; then
    log "评测集抓取失败（可忽略），继续后续步骤。你也可以设置 FETCH_EVAL_DATASET=0 跳过。"
  fi
}

crawl_and_build_index() {
  if [[ "$CRAWL_FULL_SITE" == "1" ]]; then
    log "执行全站爬取"
    "$VENV_DIR/bin/python" scripts/crawl.py --full-site --limit "$CRAWL_LIMIT"
  else
    log "跳过全站爬取（CRAWL_FULL_SITE=$CRAWL_FULL_SITE）"
  fi

  log "构建索引"
  if [[ "$BUILD_VECTOR_INDEX" == "1" ]]; then
    [[ -n "${OPENAI_API_KEY:-}" ]] || fail "BUILD_VECTOR_INDEX=1 时必须配置 OPENAI_API_KEY"
    "$VENV_DIR/bin/python" scripts/build_index.py --with-vector
  else
    "$VENV_DIR/bin/python" scripts/build_index.py
  fi
}

write_systemd_unit() {
  mkdir -p "$DEPLOY_DIR"
  log "生成 systemd service 文件预览: $SYSTEMD_UNIT_PREVIEW_PATH"

  cat >"$SYSTEMD_UNIT_PREVIEW_PATH" <<EOF
[Unit]
Description=THSS RAG Chatbot (FastAPI)
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${VENV_DIR}/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

  if [[ "$INSTALL_SYSTEMD" != "1" ]]; then
    log "跳过 systemd 安装（INSTALL_SYSTEMD=$INSTALL_SYSTEMD）"
    return
  fi

  if [[ "$(uname -s)" != "Linux" || ! -d /etc/systemd/system ]]; then
    log "当前环境不是 Linux/systemd，仅生成了预览文件"
    return
  fi

  log "安装并启动 systemd 服务"
  sudo cp "$SYSTEMD_UNIT_PREVIEW_PATH" "/etc/systemd/system/${SERVICE_NAME}.service"
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager || true

  log "查看日志命令"
  echo "sudo journalctl -u ${SERVICE_NAME} -n 200 --no-pager"
}

write_nginx_snippet() {
  if [[ "$WRITE_NGINX_SNIPPET" != "1" ]]; then
    log "跳过 Nginx 配置片段生成（WRITE_NGINX_SNIPPET=$WRITE_NGINX_SNIPPET）"
    return
  fi

  mkdir -p "$DEPLOY_DIR"
  log "生成 Nginx 配置片段: $NGINX_SNIPPET_PATH"

  cat >"$NGINX_SNIPPET_PATH" <<EOF
location = / {
    return 302 /chat;
}

location = /chat {
    proxy_pass http://127.0.0.1:8000/chat;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location ^~ /chat/ {
    proxy_pass http://127.0.0.1:8000/chat/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location ^~ /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location ^~ /static/ {
    proxy_pass http://127.0.0.1:8000/static/;
    proxy_set_header Host \$host;
}
EOF

  log "请将上述片段合并到现有的 8443 server 块中，然后执行："
  echo "sudo nginx -t"
  echo "sudo systemctl reload nginx"
}

print_validate_commands() {
  if [[ -n "${SERVER_HOST:-}" && "${SERVER_HOST}" != "xxx.xxx.xxx.xxx" ]]; then
    log "部署验证命令"
    echo "curl -k -I \"https://${SERVER_HOST}:8443/\" | head -n 5"
    echo "curl -k \"https://${SERVER_HOST}:8443/api/health\""
  else
    log "SERVER_HOST 未配置为真实地址，跳过验证命令输出"
  fi
}

main() {
  log "开始部署，项目目录：$PROJECT_DIR"
  load_env
  create_venv
  fetch_eval_dataset
  crawl_and_build_index
  write_systemd_unit
  write_nginx_snippet
  print_validate_commands
  log "完成"
}

main "$@"
