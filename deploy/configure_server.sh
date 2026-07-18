#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
SERVICE_NAME="${SERVICE_NAME:-thss-rag}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
INSTALL_SYSTEMD="${INSTALL_SYSTEMD:-1}"
WRITE_NGINX_SNIPPET="${WRITE_NGINX_SNIPPET:-1}"
DEPLOY_DIR="${DEPLOY_DIR:-$ROOT_DIR/deploy}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$DEPLOY_DIR/generated}"
SYSTEMD_UNIT_PREVIEW_PATH="$ARTIFACTS_DIR/${SERVICE_NAME}.service"
NGINX_SNIPPET_PATH="$ARTIFACTS_DIR/nginx-${SERVICE_NAME}.conf.snippet"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

ensure_venv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    fail "未找到虚拟环境：${VENV_DIR}/bin/python。请先运行 deploy/setup_app.sh"
  fi
}

write_systemd_unit() {
  mkdir -p "$ARTIFACTS_DIR"
  log "生成 systemd service 文件预览: $SYSTEMD_UNIT_PREVIEW_PATH"

  cat >"$SYSTEMD_UNIT_PREVIEW_PATH" <<EOF
[Unit]
Description=THSS RAG Chatbot (FastAPI)
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${ROOT_DIR}
EnvironmentFile=${ROOT_DIR}/.env
ExecStart=${VENV_DIR}/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

  if [[ "$INSTALL_SYSTEMD" != "1" ]]; then
    log "跳过 systemd 安装（INSTALL_SYSTEMD=${INSTALL_SYSTEMD}）"
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
    log "跳过 Nginx 配置片段生成（WRITE_NGINX_SNIPPET=${WRITE_NGINX_SNIPPET}）"
    return
  fi

  mkdir -p "$ARTIFACTS_DIR"
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

main() {
  log "开始生成/安装 systemd 与 Nginx 配置，项目目录：$ROOT_DIR"
  ensure_venv
  write_systemd_unit
  write_nginx_snippet
  log "完成"
}

main "$@"
