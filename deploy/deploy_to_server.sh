#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

SSH_HOST="${SSH_HOST:-}"
SSH_USER="${SSH_USER:-root}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"

REMOTE_DIR="${REMOTE_DIR:-}"
REMOTE_VENV_DIR="${REMOTE_VENV_DIR:-}"
REMOTE_SERVICE_NAME="${REMOTE_SERVICE_NAME:-}"

RSYNC_DELETE="${RSYNC_DELETE:-0}"
REMOTE_PIP_INSTALL="${REMOTE_PIP_INSTALL:-1}"
REMOTE_SYSTEMD_RESTART="${REMOTE_SYSTEMD_RESTART:-1}"

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

infer_remote_defaults() {
  local docs_path
  docs_path="$ROOT_DIR/docs/Deployment-Manual.md"

  if [[ -z "$REMOTE_DIR" && -f "$docs_path" ]]; then
    REMOTE_DIR="$(
      grep -E '^WorkingDirectory=' -m1 "$docs_path" \
        | cut -d= -f2- \
        | tr -d '\r' \
        | xargs
    )"
  fi
  REMOTE_DIR="${REMOTE_DIR:-/opt/apps/thss-rag/backend/current}"

  if [[ -z "$REMOTE_SERVICE_NAME" && -f "$docs_path" ]]; then
    REMOTE_SERVICE_NAME="$(
      grep -E 'systemctl (enable|start|restart|status) ' -m1 "$docs_path" \
        | awk '{print $NF}' \
        | tr -d '\r' \
        | xargs
    )"
  fi
  if [[ -z "$REMOTE_SERVICE_NAME" && -f "$ROOT_DIR/deploy/configure_server.sh" ]]; then
    REMOTE_SERVICE_NAME="$(
      grep -E '^SERVICE_NAME=' -m1 "$ROOT_DIR/deploy/configure_server.sh" \
        | sed -E 's/.*:-([^}"]+).*/\1/' \
        | tr -d '\r' \
        | xargs
    )"
  fi
  REMOTE_SERVICE_NAME="${REMOTE_SERVICE_NAME:-thss-rag}"

  if [[ -z "$REMOTE_VENV_DIR" ]]; then
    REMOTE_VENV_DIR="$REMOTE_DIR/.venv"
  fi
}

ssh_base_args() {
  local -a args
  args=(-p "$SSH_PORT")
  args+=(-o StrictHostKeyChecking=accept-new)
  args+=(-o ServerAliveInterval=30)
  args+=(-o ServerAliveCountMax=6)
  if [[ -n "$SSH_KEY_PATH" ]]; then
    args+=(-i "$SSH_KEY_PATH")
  fi
  printf '%s\n' "${args[@]}"
}

remote_target() {
  printf '%s@%s\n' "$SSH_USER" "$SSH_HOST"
}

sync_code() {
  require_cmd rsync
  require_cmd ssh

  [[ -n "$SSH_HOST" ]] || fail "请设置 SSH_HOST，例如：SSH_HOST=example.com"

  local -a ssh_args rsync_args exclude_args
  mapfile -t ssh_args < <(ssh_base_args)

  rsync_args=(-az)
  rsync_args+=(--compress-choice=zstd)
  rsync_args+=(--mkpath)
  rsync_args+=(--timeout=60)
  rsync_args+=(--human-readable)
  rsync_args+=(--progress)
  rsync_args+=(-e "ssh ${ssh_args[*]}")

  exclude_args+=(--exclude ".git/")
  exclude_args+=(--exclude ".venv/")
  exclude_args+=(--exclude "__pycache__/")
  exclude_args+=(--exclude "*.pyc")
  exclude_args+=(--exclude ".pytest_cache/")
  exclude_args+=(--exclude ".mypy_cache/")
  exclude_args+=(--exclude ".ruff_cache/")
  exclude_args+=(--exclude ".DS_Store")
  exclude_args+=(--exclude "data/")
  exclude_args+=(--exclude "deploy/generated/")
  exclude_args+=(--exclude ".env")

  if [[ "$RSYNC_DELETE" == "1" ]]; then
    rsync_args+=(--delete)
  fi

  log "同步代码到远端: $(remote_target):$REMOTE_DIR"
  rsync "${rsync_args[@]}" "${exclude_args[@]}" ./ "$(remote_target):$REMOTE_DIR/"
}

run_remote_steps() {
  require_cmd ssh
  local -a ssh_args
  mapfile -t ssh_args < <(ssh_base_args)

  log "远端执行: venv/依赖/重启"

  local remote_cmd
  remote_cmd=$(cat <<EOF
set -Eeuo pipefail
cd "$REMOTE_DIR"

if [[ ! -f ".env" ]]; then
  echo "ERROR: .env not found at $REMOTE_DIR/.env" >&2
  exit 1
fi

python3 -m venv "$REMOTE_VENV_DIR"
"$REMOTE_VENV_DIR/bin/python" -m pip install --upgrade pip

if [[ "$REMOTE_PIP_INSTALL" == "1" ]]; then
  "$REMOTE_VENV_DIR/bin/pip" install -r requirements.txt
fi

if [[ "$REMOTE_SYSTEMD_RESTART" == "1" ]]; then
  if [[ "$(id -u)" == "0" ]]; then
    systemctl restart "$REMOTE_SERVICE_NAME"
    systemctl status "$REMOTE_SERVICE_NAME" --no-pager || true
  else
    sudo systemctl restart "$REMOTE_SERVICE_NAME"
    sudo systemctl status "$REMOTE_SERVICE_NAME" --no-pager || true
  fi
fi
EOF
)

ssh -t "${ssh_args[@]}" "$(remote_target)" "bash -lc $(printf '%q' "$remote_cmd")"
}

main() {
  infer_remote_defaults
  sync_code
  run_remote_steps
  log "完成"
}

main "$@"
