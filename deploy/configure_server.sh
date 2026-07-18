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

NGINX_SITE_NAME="${NGINX_SITE_NAME:-thss-rag}"
NGINX_CONF_D_PATH="${NGINX_CONF_D_PATH:-/etc/nginx/conf.d/${NGINX_SITE_NAME}.conf}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"
NGINX_LISTEN_PORT="${NGINX_LISTEN_PORT:-8443}"
NGINX_SSL_CERT="${NGINX_SSL_CERT:-/etc/nginx/ssl/fullchain.crt}"
NGINX_SSL_KEY="${NGINX_SSL_KEY:-/etc/nginx/ssl/server.key}"
NGINX_STATIC_ROOT="${NGINX_STATIC_ROOT:-/var/www/html}"
UPSTREAM_URL="${UPSTREAM_URL:-http://127.0.0.1:8000}"

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

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令: $1"
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

  require_cmd nginx
  require_cmd sudo

  mkdir -p "$ARTIFACTS_DIR"
  log "生成 Nginx 配置片段: $NGINX_SNIPPET_PATH"

  cat >"$NGINX_SNIPPET_PATH" <<EOF
location = /chat {
    return 302 /chat/;
}

location ^~ /api/ {
    proxy_pass ${UPSTREAM_URL};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}

location ^~ /static/ {
    proxy_pass ${UPSTREAM_URL};
    proxy_set_header Host \$host;
}
EOF

  local tmp_path
  tmp_path="/tmp/${NGINX_SITE_NAME}.conf.$$"

  cat >"$tmp_path" <<EOF
# Reuse the existing 8443 SSL entry (cert + SSL params should match the default site).
server {
    listen ${NGINX_LISTEN_PORT} ssl http2;
    listen [::]:${NGINX_LISTEN_PORT} ssl http2;
    server_name ${NGINX_SERVER_NAME};

    ssl_certificate ${NGINX_SSL_CERT};
    ssl_certificate_key ${NGINX_SSL_KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1h;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location /chat/ {
        proxy_pass ${UPSTREAM_URL}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /chat-vue/ {
        proxy_pass ${UPSTREAM_URL}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    include ${NGINX_SNIPPET_PATH};

    location / {
        root ${NGINX_STATIC_ROOT};
        index index.html;
        try_files \$uri \$uri/ =404;
    }
}
EOF

  log "写入 Nginx 配置: ${NGINX_CONF_D_PATH}"
  sudo mkdir -p "$(dirname "$NGINX_CONF_D_PATH")"
  sudo mv "$tmp_path" "$NGINX_CONF_D_PATH"
  sudo chmod 0644 "$NGINX_CONF_D_PATH"

  log "校验 Nginx 配置"
  sudo nginx -t

  log "重载 Nginx"
  sudo systemctl reload nginx
}

main() {
  log "开始生成/安装 systemd 与 Nginx 配置，项目目录：$ROOT_DIR"
  ensure_venv
  write_systemd_unit
  write_nginx_snippet
  log "完成"
}

main "$@"
