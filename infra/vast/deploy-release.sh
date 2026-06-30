#!/usr/bin/env bash
set -euo pipefail

ARCHIVE_PATH="${1:-}"
ENV_FILE_PATH="${2:-}"
RELEASE_ID="${3:-}"
CLOUDFLARED_TOKEN_PATH="${4:-}"
TAILSCALE_AUTHKEY_PATH="${5:-}"

APP_ROOT="${APP_ROOT:-/opt/gpu-inference-backend}"
RELEASES_DIR="${RELEASES_DIR:-${APP_ROOT}/releases}"
CURRENT_LINK="${CURRENT_LINK:-${APP_ROOT}/current}"
APP_LINK="${APP_LINK:-/app}"
LOG_DIR="${LOG_DIR:-/var/log/gpu-inference}"
APP_HTTP_PORT="${APP_HTTP_PORT:-8002}"
VLLM_HTTP_PORT="${VLLM_HTTP_PORT:-8001}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${APP_HTTP_PORT}/health}"
DEPLOY_HEALTH_TIMEOUT_SECONDS="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-1200}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
TAILSCALE_STATE_DIR="${TAILSCALE_STATE_DIR:-/var/lib/tailscale}"
TAILSCALE_SOCKET="${TAILSCALE_SOCKET:-/run/tailscale/tailscaled.sock}"
TAILSCALE_SOCKS5_SERVER="${TAILSCALE_SOCKS5_SERVER:-127.0.0.1:1055}"
TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-vast-gpu-inference}"
POSTGRES_PRIMARY_HOST="${POSTGRES_PRIMARY_HOST:-100.78.17.101}"
POSTGRES_SECONDARY_HOST="${POSTGRES_SECONDARY_HOST:-100.79.99.107}"
POSTGRES_REMOTE_PORT="${POSTGRES_REMOTE_PORT:-15432}"
POSTGRES_PRIMARY_LOCAL_PORT="${POSTGRES_PRIMARY_LOCAL_PORT:-15432}"
POSTGRES_SECONDARY_LOCAL_PORT="${POSTGRES_SECONDARY_LOCAL_PORT:-15433}"

usage() {
  echo "Usage: $0 <release-archive.tgz> <app-env-file> <release-id> [cloudflared-token-file] [tailscale-authkey-file]" >&2
}

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

require_file() {
  local path="$1"
  if [ -z "${path}" ] || [ ! -s "${path}" ]; then
    echo "Missing required file: ${path}" >&2
    usage
    exit 1
  fi
}

link_supervisor_shims() {
  if ! command -v supervisord >/dev/null 2>&1 && [ -x /opt/sys-venv/shim/supervisord ]; then
    as_root ln -sfn /opt/sys-venv/shim/supervisord /usr/local/bin/supervisord
  fi

  if ! command -v supervisorctl >/dev/null 2>&1 && [ -x /opt/sys-venv/shim/supervisorctl ]; then
    as_root ln -sfn /opt/sys-venv/shim/supervisorctl /usr/local/bin/supervisorctl
  fi

  hash -r
}

ensure_system_packages() {
  local packages=()

  command -v curl >/dev/null 2>&1 || packages+=(curl)
  command -v git >/dev/null 2>&1 || packages+=(git)
  command -v fuser >/dev/null 2>&1 || packages+=(psmisc)
  command -v redis-server >/dev/null 2>&1 || packages+=(redis-server)
  command -v socat >/dev/null 2>&1 || packages+=(socat)
  command -v tar >/dev/null 2>&1 || packages+=(tar)

  link_supervisor_shims
  if ! command -v supervisord >/dev/null 2>&1 || ! command -v supervisorctl >/dev/null 2>&1; then
    packages+=(supervisor)
  fi

  if [ "${#packages[@]}" -gt 0 ]; then
    as_root apt-get update
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates "${packages[@]}"
  fi

  link_supervisor_shims
}

ensure_tailscale() {
  echo "Ensuring Tailscale userspace networking is running on ${TAILSCALE_SOCKET}"

  if ! command -v tailscale >/dev/null 2>&1 || ! command -v tailscaled >/dev/null 2>&1; then
    local installer="/tmp/tailscale-install.sh"
    curl -fsSL https://tailscale.com/install.sh -o "${installer}"
    as_root sh "${installer}"
    hash -r
  fi

  as_root install -d -m 0755 "$(dirname "${TAILSCALE_SOCKET}")"
  as_root install -d -m 0700 "${TAILSCALE_STATE_DIR}"
  as_root install -d -m 0775 "${LOG_DIR}"

  if ! pgrep -f "tailscaled .*--socket=${TAILSCALE_SOCKET}" >/dev/null 2>&1; then
    as_root /bin/bash -lc \
      "nohup tailscaled --tun=userspace-networking --state='${TAILSCALE_STATE_DIR}/tailscaled.state' --socket='${TAILSCALE_SOCKET}' --socks5-server='${TAILSCALE_SOCKS5_SERVER}' > '${LOG_DIR}/tailscaled.log' 2>&1 &"
  fi

  for _ in $(seq 1 30); do
    if [ -S "${TAILSCALE_SOCKET}" ]; then
      break
    fi
    sleep 1
  done

  if [ ! -S "${TAILSCALE_SOCKET}" ]; then
    echo "tailscaled socket was not created at ${TAILSCALE_SOCKET}" >&2
    as_root tail -n 120 "${LOG_DIR}/tailscaled.log" 2>/dev/null || true
    exit 1
  fi

  if as_root tailscale --socket="${TAILSCALE_SOCKET}" status >/dev/null 2>&1; then
    echo "Tailscale is already logged in"
    return
  fi

  if [ -z "${TAILSCALE_AUTHKEY_PATH}" ] || [ ! -s "${TAILSCALE_AUTHKEY_PATH}" ]; then
    echo "Tailscale is not logged in. Set GitHub secret TAILSCALE_AUTH_KEY for Vast deploys." >&2
    exit 1
  fi

  local authkey
  authkey="$(tr -d '\r\n' < "${TAILSCALE_AUTHKEY_PATH}")"
  echo "Logging in to Tailscale as ${TAILSCALE_HOSTNAME}"
  as_root tailscale --socket="${TAILSCALE_SOCKET}" up \
    --auth-key "${authkey}" \
    --hostname "${TAILSCALE_HOSTNAME}" \
    --accept-routes
  rm -f "${TAILSCALE_AUTHKEY_PATH}"
  echo "Tailscale is connected"
}

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local label="$3"

  for _ in $(seq 1 30); do
    if timeout 3 bash -lc "</dev/tcp/${host}/${port}" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  echo "Timed out waiting for ${label} at ${host}:${port}" >&2
  exit 1
}

start_postgres_forward() {
  local local_port="$1"
  local remote_host="$2"
  local label="$3"

  if timeout 2 bash -lc "</dev/tcp/127.0.0.1/${local_port}" >/dev/null 2>&1; then
    return
  fi

  as_root /bin/bash -lc \
    "nohup socat TCP-LISTEN:${local_port},bind=127.0.0.1,fork,reuseaddr EXEC:'tailscale --socket=${TAILSCALE_SOCKET} nc ${remote_host} ${POSTGRES_REMOTE_PORT}' >> '${LOG_DIR}/postgres-${label}-forward.log' 2>&1 &"

  wait_for_tcp "127.0.0.1" "${local_port}" "Postgres ${label} forward"
}

ensure_postgres_forwards() {
  echo "Ensuring Postgres forwards over Tailscale"
  start_postgres_forward "${POSTGRES_PRIMARY_LOCAL_PORT}" "${POSTGRES_PRIMARY_HOST}" "primary"
  start_postgres_forward "${POSTGRES_SECONDARY_LOCAL_PORT}" "${POSTGRES_SECONDARY_HOST}" "secondary"
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi

  local installer="/tmp/uv-install.sh"
  curl -LsSf https://astral.sh/uv/install.sh -o "${installer}"
  if [ "$(id -u)" -eq 0 ]; then
    env UV_INSTALL_DIR=/usr/local/bin sh "${installer}"
  else
    sudo env UV_INSTALL_DIR=/usr/local/bin sh "${installer}"
  fi
  hash -r

  if ! command -v uv >/dev/null 2>&1; then
    echo "uv install finished but uv is still not in PATH" >&2
    exit 1
  fi
}

ensure_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    return
  fi

  if [ -x /opt/instance-tools/bin/cloudflared ]; then
    as_root ln -sfn /opt/instance-tools/bin/cloudflared /usr/local/bin/cloudflared
    hash -r
    return
  fi

  if [ -x /opt/portal-aio/tunnel_manager/cloudflared ]; then
    as_root ln -sfn /opt/portal-aio/tunnel_manager/cloudflared /usr/local/bin/cloudflared
    hash -r
    return
  fi

  local arch
  case "$(uname -m)" in
    x86_64 | amd64)
      arch="amd64"
      ;;
    aarch64 | arm64)
      arch="arm64"
      ;;
    *)
      echo "Unsupported architecture for cloudflared install: $(uname -m)" >&2
      exit 1
      ;;
  esac

  local cloudflared_tmp="/tmp/cloudflared"
  curl -fsSL \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}" \
    -o "${cloudflared_tmp}"
  as_root install -m 0755 "${cloudflared_tmp}" /usr/local/bin/cloudflared
  hash -r
}

install_cloudflared_config() {
  local release_dir="$1"

  as_root install -d -m 0750 /etc/cloudflared
  as_root install -m 0644 "${release_dir}/infra/cloudflared/config.yml.example" \
    /etc/cloudflared/config.yml

  if [ -n "${CLOUDFLARED_TOKEN_PATH}" ] && [ -s "${CLOUDFLARED_TOKEN_PATH}" ]; then
    as_root install -m 0600 -o root -g root "${CLOUDFLARED_TOKEN_PATH}" /etc/cloudflared/token
    rm -f "${CLOUDFLARED_TOKEN_PATH}"
  elif [ ! -s /etc/cloudflared/token ]; then
    echo "Warning: /etc/cloudflared/token is missing; cloudflared will use named-tunnel config fallback" >&2
  fi
}

extract_release() {
  local release_dir="$1"
  local owner_id
  local group_id

  owner_id="$(id -u)"
  group_id="$(id -g)"

  as_root install -d -m 0755 "${APP_ROOT}" "${RELEASES_DIR}"
  if [ -d "${release_dir}" ]; then
    as_root rm -rf "${release_dir}"
  fi
  as_root install -d -m 0755 -o "${owner_id}" -g "${group_id}" "${release_dir}"

  tar -xzf "${ARCHIVE_PATH}" -C "${release_dir}"
  install -m 0600 "${ENV_FILE_PATH}" "${release_dir}/.env"
  chmod +x "${release_dir}"/infra/vast/*.sh
}

sync_python_environment() {
  local release_dir="$1"

  (
    cd "${release_dir}"
    uv sync --frozen --no-dev --compile-bytecode
  )
}

run_migrations() {
  local release_dir="$1"

  (
    cd "${release_dir}"
    uv run --env-file "${release_dir}/.env" alembic upgrade head
  )
}

activate_release() {
  local release_dir="$1"

  as_root ln -sfn "${release_dir}" "${CURRENT_LINK}"
  as_root ln -sfn "${release_dir}" "${APP_LINK}"
  as_root install -d -m 0775 "${LOG_DIR}"
  as_root chown "$(id -u):$(id -g)" "${LOG_DIR}" || true
}

stop_supervisor() {
  local supervisor_sock="/tmp/gpu-inference-supervisor.sock"

  if [ -S "${supervisor_sock}" ] && command -v supervisorctl >/dev/null 2>&1; then
    as_root supervisorctl -s "unix://${supervisor_sock}" shutdown || true
  fi

  for _ in $(seq 1 30); do
    if [ ! -S "${supervisor_sock}" ]; then
      return
    fi
    sleep 1
  done

  as_root pkill -TERM -f "supervisord -c .*/infra/supervisord.conf" || true
}

stop_port_listener() {
  local port="$1"
  local label="$2"

  if ! timeout 2 bash -lc "</dev/tcp/127.0.0.1/${port}" >/dev/null 2>&1; then
    return
  fi

  echo "Stopping stale ${label} listener on 127.0.0.1:${port}"
  as_root fuser -k "${port}/tcp" >/dev/null 2>&1 || true

  for _ in $(seq 1 20); do
    if ! timeout 2 bash -lc "</dev/tcp/127.0.0.1/${port}" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  echo "Warning: ${label} listener still responds on 127.0.0.1:${port}" >&2
}

stop_stale_runtime_processes() {
  stop_port_listener "${APP_HTTP_PORT}" "FastAPI"
  stop_port_listener "${VLLM_HTTP_PORT}" "vLLM"
}

start_supervisor() {
  as_root /bin/bash -lc \
    "cd '${APP_LINK}' && nohup env APP_DIR='${APP_LINK}' '${APP_LINK}/infra/vast/startup.sh' >> '${LOG_DIR}/startup.log' 2>&1 &"

  for _ in $(seq 1 30); do
    if [ -S /tmp/gpu-inference-supervisor.sock ]; then
      return
    fi
    sleep 1
  done

  echo "Warning: supervisor socket was not created within 30 seconds" >&2
}

dump_runtime_diagnostics() {
  local response_file="${1:-}"

  if [ -n "${response_file}" ] && [ -s "${response_file}" ]; then
    echo "Health response:" >&2
    sed -n '1,80p' "${response_file}" >&2 || true
  fi

  echo "Listening sockets:" >&2
  as_root ss -ltnp 2>/dev/null | sed -n '1,80p' >&2 || true

  echo "Supervisor status:" >&2
  as_root supervisorctl -s "unix:///tmp/gpu-inference-supervisor.sock" status 2>/dev/null >&2 || true

  as_root tail -n 120 "${LOG_DIR}/supervisord.log" 2>/dev/null || true
  as_root tail -n 120 "${LOG_DIR}/startup.log" 2>/dev/null || true
  as_root tail -n 120 "${LOG_DIR}/api.log" 2>/dev/null || true
  as_root tail -n 120 "${LOG_DIR}/api.err.log" 2>/dev/null || true
}

wait_for_health() {
  local deadline
  local response_file
  local status_code
  deadline=$((SECONDS + DEPLOY_HEALTH_TIMEOUT_SECONDS))
  response_file="$(mktemp)"

  while [ "${SECONDS}" -lt "${deadline}" ]; do
    status_code="$(curl -sS --max-time 10 -o "${response_file}" -w "%{http_code}" "${HEALTH_URL}" || true)"
    if [[ "${status_code}" =~ ^2[0-9][0-9]$ ]]; then
      echo "Health check passed: ${HEALTH_URL}"
      rm -f "${response_file}"
      return
    fi
    if [ "${status_code}" != "000" ]; then
      echo "Health check returned HTTP ${status_code}: ${HEALTH_URL}" >&2
      dump_runtime_diagnostics "${response_file}"
      rm -f "${response_file}"
      exit 1
    fi
    sleep 5
  done

  echo "Health check failed after ${DEPLOY_HEALTH_TIMEOUT_SECONDS}s: ${HEALTH_URL}" >&2
  dump_runtime_diagnostics "${response_file}"
  rm -f "${response_file}"
  exit 1
}

cleanup_old_releases() {
  local active_release

  if [ "${KEEP_RELEASES}" -le 0 ]; then
    return
  fi

  active_release="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"

  find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' |
    sort -rn |
    awk -v keep="${KEEP_RELEASES}" 'NR > keep {print $2}' |
    while read -r old_release; do
      if [ -n "${old_release}" ] && [ "${old_release}" != "${active_release}" ]; then
        as_root rm -rf "${old_release}"
      fi
    done
}

if [ -z "${RELEASE_ID}" ]; then
  RELEASE_ID="$(date -u +%Y%m%d%H%M%S)"
fi

if [[ ! "${RELEASE_ID}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid release id: ${RELEASE_ID}" >&2
  exit 1
fi

require_file "${ARCHIVE_PATH}"
require_file "${ENV_FILE_PATH}"

release_dir="${RELEASES_DIR}/${RELEASE_ID}"

ensure_system_packages
ensure_uv
ensure_cloudflared
ensure_tailscale
ensure_postgres_forwards
extract_release "${release_dir}"
install_cloudflared_config "${release_dir}"
sync_python_environment "${release_dir}"
run_migrations "${release_dir}"
activate_release "${release_dir}"
stop_supervisor
stop_stale_runtime_processes
start_supervisor
wait_for_health
cleanup_old_releases

echo "Deployed ${RELEASE_ID} to ${APP_LINK}"
