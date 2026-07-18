#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

load_env() {
  local env_path
  env_path="${ENV_FILE:-$ROOT_DIR/.env}"
  if [[ -f "$env_path" ]]; then
    local old_SSH_HOST="" old_SSH_HOST_set=0
    local old_SSH_USER="" old_SSH_USER_set=0
    local old_SSH_PORT="" old_SSH_PORT_set=0
    local old_SSH_KEY_PATH="" old_SSH_KEY_PATH_set=0
    local old_SSH_PASS="" old_SSH_PASS_set=0
    local old_SSH_PASSWORD="" old_SSH_PASSWORD_set=0
    local old_SSHPASS="" old_SSHPASS_set=0
    local old_REMOTE_DIR="" old_REMOTE_DIR_set=0
    local old_REMOTE_VENV_DIR="" old_REMOTE_VENV_DIR_set=0
    local old_REMOTE_SERVICE_NAME="" old_REMOTE_SERVICE_NAME_set=0
    local old_RSYNC_DELETE="" old_RSYNC_DELETE_set=0
    local old_REMOTE_PIP_INSTALL="" old_REMOTE_PIP_INSTALL_set=0
    local old_REMOTE_SYSTEMD_RESTART="" old_REMOTE_SYSTEMD_RESTART_set=0

    if [[ -n "${SSH_HOST:-}" ]]; then old_SSH_HOST="$SSH_HOST"; old_SSH_HOST_set=1; fi
    if [[ -n "${SSH_USER:-}" ]]; then old_SSH_USER="$SSH_USER"; old_SSH_USER_set=1; fi
    if [[ -n "${SSH_PORT:-}" ]]; then old_SSH_PORT="$SSH_PORT"; old_SSH_PORT_set=1; fi
    if [[ -n "${SSH_KEY_PATH:-}" ]]; then old_SSH_KEY_PATH="$SSH_KEY_PATH"; old_SSH_KEY_PATH_set=1; fi
    if [[ -n "${SSH_PASS:-}" ]]; then old_SSH_PASS="$SSH_PASS"; old_SSH_PASS_set=1; fi
    if [[ -n "${SSH_PASSWORD:-}" ]]; then old_SSH_PASSWORD="$SSH_PASSWORD"; old_SSH_PASSWORD_set=1; fi
    if [[ -n "${SSHPASS:-}" ]]; then old_SSHPASS="$SSHPASS"; old_SSHPASS_set=1; fi
    if [[ -n "${REMOTE_DIR:-}" ]]; then old_REMOTE_DIR="$REMOTE_DIR"; old_REMOTE_DIR_set=1; fi
    if [[ -n "${REMOTE_VENV_DIR:-}" ]]; then old_REMOTE_VENV_DIR="$REMOTE_VENV_DIR"; old_REMOTE_VENV_DIR_set=1; fi
    if [[ -n "${REMOTE_SERVICE_NAME:-}" ]]; then old_REMOTE_SERVICE_NAME="$REMOTE_SERVICE_NAME"; old_REMOTE_SERVICE_NAME_set=1; fi
    if [[ -n "${RSYNC_DELETE:-}" ]]; then old_RSYNC_DELETE="$RSYNC_DELETE"; old_RSYNC_DELETE_set=1; fi
    if [[ -n "${REMOTE_PIP_INSTALL:-}" ]]; then old_REMOTE_PIP_INSTALL="$REMOTE_PIP_INSTALL"; old_REMOTE_PIP_INSTALL_set=1; fi
    if [[ -n "${REMOTE_SYSTEMD_RESTART:-}" ]]; then old_REMOTE_SYSTEMD_RESTART="$REMOTE_SYSTEMD_RESTART"; old_REMOTE_SYSTEMD_RESTART_set=1; fi

    set -a
    source "$env_path"
    set +a

    if [[ "$old_SSH_HOST_set" == "1" ]]; then SSH_HOST="$old_SSH_HOST"; export SSH_HOST; fi
    if [[ "$old_SSH_USER_set" == "1" ]]; then SSH_USER="$old_SSH_USER"; export SSH_USER; fi
    if [[ "$old_SSH_PORT_set" == "1" ]]; then SSH_PORT="$old_SSH_PORT"; export SSH_PORT; fi
    if [[ "$old_SSH_KEY_PATH_set" == "1" ]]; then SSH_KEY_PATH="$old_SSH_KEY_PATH"; export SSH_KEY_PATH; fi
    if [[ "$old_SSH_PASS_set" == "1" ]]; then SSH_PASS="$old_SSH_PASS"; export SSH_PASS; fi
    if [[ "$old_SSH_PASSWORD_set" == "1" ]]; then SSH_PASSWORD="$old_SSH_PASSWORD"; export SSH_PASSWORD; fi
    if [[ "$old_SSHPASS_set" == "1" ]]; then SSHPASS="$old_SSHPASS"; export SSHPASS; fi
    if [[ "$old_REMOTE_DIR_set" == "1" ]]; then REMOTE_DIR="$old_REMOTE_DIR"; export REMOTE_DIR; fi
    if [[ "$old_REMOTE_VENV_DIR_set" == "1" ]]; then REMOTE_VENV_DIR="$old_REMOTE_VENV_DIR"; export REMOTE_VENV_DIR; fi
    if [[ "$old_REMOTE_SERVICE_NAME_set" == "1" ]]; then REMOTE_SERVICE_NAME="$old_REMOTE_SERVICE_NAME"; export REMOTE_SERVICE_NAME; fi
    if [[ "$old_RSYNC_DELETE_set" == "1" ]]; then RSYNC_DELETE="$old_RSYNC_DELETE"; export RSYNC_DELETE; fi
    if [[ "$old_REMOTE_PIP_INSTALL_set" == "1" ]]; then REMOTE_PIP_INSTALL="$old_REMOTE_PIP_INSTALL"; export REMOTE_PIP_INSTALL; fi
    if [[ "$old_REMOTE_SYSTEMD_RESTART_set" == "1" ]]; then REMOTE_SYSTEMD_RESTART="$old_REMOTE_SYSTEMD_RESTART"; export REMOTE_SYSTEMD_RESTART; fi
  fi
}

load_env

SSH_HOST="${SSH_HOST:-}"
SSH_USER="${SSH_USER:-root}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
SSH_PASS="${SSH_PASS:-}"
SSH_PASSWORD="${SSH_PASSWORD:-}"
SSHPASS="${SSHPASS:-}"

REMOTE_DIR="${REMOTE_DIR:-}"
REMOTE_VENV_DIR="${REMOTE_VENV_DIR:-}"
REMOTE_SERVICE_NAME="${REMOTE_SERVICE_NAME:-}"

RSYNC_DELETE="${RSYNC_DELETE:-1}"
REMOTE_PIP_INSTALL="${REMOTE_PIP_INSTALL:-0}"
REMOTE_SYSTEMD_RESTART="${REMOTE_SYSTEMD_RESTART:-0}"

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

has_ssh_password() {
  [[ -n "$SSH_PASS" || -n "$SSH_PASSWORD" || -n "$SSHPASS" ]]
}

ensure_sshpass_env() {
  if [[ -n "$SSHPASS" ]]; then
    export SSHPASS
    return 0
  fi
  if [[ -n "$SSH_PASSWORD" ]]; then
    export SSHPASS="$SSH_PASSWORD"
    return 0
  fi
  if [[ -n "$SSH_PASS" ]]; then
    export SSHPASS="$SSH_PASS"
    return 0
  fi
  return 1
}

use_sshpass() {
  [[ -z "$SSH_KEY_PATH" ]] && has_ssh_password
}

ssh_prefix() {
  if use_sshpass; then
    require_cmd sshpass
    ensure_sshpass_env || fail "未设置 SSH 密码（SSH_PASS / SSH_PASSWORD / SSHPASS）"
    printf '%s\n' "sshpass -e"
    return 0
  fi
  printf '%s\n' ""
}

ssh_base_args() {
  local -a args
  args=(-p "$SSH_PORT")
  args+=(-o StrictHostKeyChecking=accept-new)
  args+=(-o ConnectTimeout=15)
  args+=(-o ServerAliveInterval=30)
  args+=(-o ServerAliveCountMax=6)
  if [[ -n "$SSH_KEY_PATH" ]]; then
    args+=(-i "$SSH_KEY_PATH")
    args+=(-o IdentitiesOnly=yes)
    args+=(-o BatchMode=yes)
  else
    if has_ssh_password; then
      args+=(-o PreferredAuthentications=password)
      args+=(-o PubkeyAuthentication=no)
    fi
  fi
  printf '%s\n' "${args[@]}"
}

remote_target() {
  printf '%s@%s\n' "$SSH_USER" "$SSH_HOST"
}

run_ssh() {
  local -a ssh_args
  mapfile -t ssh_args < <(ssh_base_args)
  local prefix
  prefix="$(ssh_prefix)"
  if [[ -n "$prefix" ]]; then
    $prefix ssh "${ssh_args[@]}" "$(remote_target)" "$@"
  else
    ssh "${ssh_args[@]}" "$(remote_target)" "$@"
  fi
}

run_ssh_tty() {
  local -a ssh_args
  mapfile -t ssh_args < <(ssh_base_args)
  local prefix
  prefix="$(ssh_prefix)"
  if [[ -n "$prefix" ]]; then
    $prefix ssh -t "${ssh_args[@]}" "$(remote_target)" "$@"
  else
    ssh -t "${ssh_args[@]}" "$(remote_target)" "$@"
  fi
}

rsync_supports() {
  rsync --help 2>&1 | grep -qF -- "$1"
}

sync_code() {
  require_cmd rsync
  require_cmd ssh

  [[ -n "$SSH_HOST" ]] || fail "请设置 SSH_HOST（可在 .env 中配置），例如：SSH_HOST=example.com"
  if [[ -z "$SSH_KEY_PATH" && ! has_ssh_password ]]; then
    fail "请设置 SSH 密钥 SSH_KEY_PATH，或提供 SSH_PASS / SSH_PASSWORD（或 SSHPASS）用于 sshpass 密码登录"
  fi

  local -a ssh_args rsync_args exclude_args
  mapfile -t ssh_args < <(ssh_base_args)

  rsync_args=(-az)
  if rsync_supports "--compress-choice"; then rsync_args+=(--compress-choice=zstd); fi
  if rsync_supports "--mkpath"; then rsync_args+=(--mkpath); fi
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
  if use_sshpass; then
    require_cmd sshpass
    ensure_sshpass_env || fail "未设置 SSH 密码（SSH_PASS / SSH_PASSWORD / SSHPASS）"
    sshpass -e rsync "${rsync_args[@]}" "${exclude_args[@]}" ./ "$(remote_target):$REMOTE_DIR/"
  else
    rsync "${rsync_args[@]}" "${exclude_args[@]}" ./ "$(remote_target):$REMOTE_DIR/"
  fi
}

run_remote_steps() {
  if [[ "$REMOTE_PIP_INSTALL" != "1" && "$REMOTE_SYSTEMD_RESTART" != "1" ]]; then
    log "跳过远端步骤: REMOTE_PIP_INSTALL=$REMOTE_PIP_INSTALL REMOTE_SYSTEMD_RESTART=$REMOTE_SYSTEMD_RESTART"
    return 0
  fi

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

  run_ssh_tty "bash -lc $(printf '%q' "$remote_cmd")"
}

main() {
  infer_remote_defaults
  sync_code
  run_remote_steps
  log "完成"
}

main "$@"
