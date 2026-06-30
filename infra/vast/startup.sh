#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"
SUPERVISOR_CONFIG="${SUPERVISOR_CONFIG:-${APP_DIR}/infra/supervisord.conf}"
LOG_DIR="${LOG_DIR:-/var/log/gpu-inference}"

mkdir -p "${LOG_DIR}"
cd "${APP_DIR}"

exec supervisord -c "${SUPERVISOR_CONFIG}"
