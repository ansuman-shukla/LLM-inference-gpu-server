#!/usr/bin/env bash
set -euo pipefail

DEPLOY_USER="${1:-deploy}"
AUTHORIZED_KEY_FILE="${2:-}"
APP_ROOT="${APP_ROOT:-/opt/gpu-inference-backend}"
LOG_DIR="${LOG_DIR:-/var/log/gpu-inference}"

if [ "$(id -u)" -ne 0 ]; then
  echo "bootstrap-deploy-user.sh must run as root" >&2
  exit 1
fi

if [[ ! "${DEPLOY_USER}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo "Invalid deploy user: ${DEPLOY_USER}" >&2
  exit 1
fi

if [ -z "${AUTHORIZED_KEY_FILE}" ] || [ ! -s "${AUTHORIZED_KEY_FILE}" ]; then
  echo "Usage: $0 <deploy-user> <authorized-public-key-file>" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl openssh-client sudo

if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
fi

usermod -aG sudo "${DEPLOY_USER}"

deploy_home="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${deploy_home}/.ssh"
touch "${deploy_home}/.ssh/authorized_keys"
chmod 600 "${deploy_home}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${deploy_home}/.ssh/authorized_keys"

public_key="$(tr -d '\r\n' < "${AUTHORIZED_KEY_FILE}")"
if ! grep -qxF "${public_key}" "${deploy_home}/.ssh/authorized_keys"; then
  printf '%s\n' "${public_key}" >> "${deploy_home}/.ssh/authorized_keys"
fi

cat > "/etc/sudoers.d/${DEPLOY_USER}-gpu-inference" <<EOF
${DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL
EOF
chmod 0440 "/etc/sudoers.d/${DEPLOY_USER}-gpu-inference"
visudo -cf "/etc/sudoers.d/${DEPLOY_USER}-gpu-inference" >/dev/null

install -d -m 0755 "${APP_ROOT}" "${APP_ROOT}/releases"
install -d -m 0775 "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_ROOT}" "${LOG_DIR}"

echo "Deploy user ${DEPLOY_USER} is ready for ${APP_ROOT}"
