#!/usr/bin/env bash
# Switch the Vast template vLLM process (supervisor program "vllm" on port 18000).
# Run as root on the Vast instance. Does not delete model caches unless explicitly requested.
set -euo pipefail

DEFAULT_MODEL_ID="Qwen/Qwen3.6-27B-FP8"
MODEL_ID="${1:-${DEFAULT_MODEL_ID}}"
REMOVE_OLD_CACHE="${REMOVE_OLD_CACHE:-false}"
APP_ENV_FILE="${APP_ENV_FILE:-/app/.env}"
ENVIRONMENT_FILE="${ENVIRONMENT_FILE:-/etc/environment}"
VLLM_SUPERVISOR_NAME="${VLLM_SUPERVISOR_NAME:-vllm}"
VLLM_KV_CACHE_DTYPE="${VLLM_KV_CACHE_DTYPE:-fp8}"
VLLM_REASONING_PARSER="${VLLM_REASONING_PARSER:-qwen3}"
VLLM_TRUST_REMOTE_CODE="${VLLM_TRUST_REMOTE_CODE:-true}"

usage() {
  cat <<'EOF'
Usage: switch-template-vllm-model.sh [qwen-3.6-huggingface-model-id]

Example (Qwen3.6 27B FP8 on 2x L4):
  REMOVE_OLD_CACHE=true ./switch-template-vllm-model.sh Qwen/Qwen3.6-27B-FP8

Environment:
  REMOVE_OLD_CACHE=true   Remove /workspace/models/* before download
  APP_ENV_FILE            FastAPI env file (default /app/.env)
  VLLM_KV_CACHE_DTYPE     vLLM KV cache dtype (default fp8)
  VLLM_REASONING_PARSER   vLLM reasoning parser (default qwen3)
  VLLM_TRUST_REMOTE_CODE  Enable vLLM --trust-remote-code (default true)
  DRY_RUN=true            Print planned changes without applying them

After switching, supervisor restarts the template vLLM and you must restart the app API
so MODEL_IDS matches the served model id.
EOF
}

QWEN_FP8_VLLM_ARGS='--download-dir /workspace/models --host 127.0.0.1 --port 18000 --max-model-len 32768 --gpu-memory-utilization 0.95 --max-num-seqs 8 --max-num-batched-tokens 16384 --enable-chunked-prefill'

dry_run() {
  if [[ "${DRY_RUN:-false}" == "true" ]]; then
    echo "[dry-run] $*"
    return 0
  fi
  return 1
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run as root on the Vast instance." >&2
    exit 1
  fi
}

disk_check() {
  local avail_kb model_gb need_gb
  avail_kb="$(df -k /workspace | awk 'NR==2 {print $4}')"
  model_gb=27
  need_gb=$((model_gb + 2))
  if [[ "${REMOVE_OLD_CACHE}" != "true" ]]; then
    echo "Disk: $(df -h /workspace | awk 'NR==2 {print $4 " free of " $2}')"
    echo "Qwen3.6 27B FP8 needs ~${model_gb}GB download. If another model cache is present, you may need"
    echo "REMOVE_OLD_CACHE=true or a larger Vast disk before download succeeds."
  fi
  if [[ "${avail_kb}" -lt $((need_gb * 1024 * 1024)) ]] && [[ "${REMOVE_OLD_CACHE}" != "true" ]]; then
    echo "Warning: free space may be insufficient (${avail_kb} KB available)." >&2
  fi
}

with_kv_cache_dtype() {
  local args="$1"
  if [[ -z "${VLLM_KV_CACHE_DTYPE}" ]] || [[ "${args}" == *"--kv-cache-dtype "* ]]; then
    printf '%s' "${args}"
    return
  fi
  printf '%s --kv-cache-dtype %s' "${args}" "${VLLM_KV_CACHE_DTYPE}"
}

with_reasoning_parser() {
  local args="$1"
  if [[ -z "${VLLM_REASONING_PARSER}" ]] || [[ "${args}" == *"--reasoning-parser "* ]]; then
    printf '%s' "${args}"
    return
  fi
  printf '%s --reasoning-parser %s' "${args}" "${VLLM_REASONING_PARSER}"
}

with_trust_remote_code() {
  local args="$1"
  if [[ "${VLLM_TRUST_REMOTE_CODE}" != "true" ]] || [[ "${args}" == *"--trust-remote-code"* ]]; then
    printf '%s' "${args}"
    return
  fi
  printf '%s --trust-remote-code' "${args}"
}

pick_vllm_args() {
  local args
  case "${MODEL_ID}" in
    Qwen/Qwen3.6-27B-FP8)
      args="${QWEN_FP8_VLLM_ARGS}"
      ;;
    *)
      echo "Unsupported model: ${MODEL_ID}. This deployment is Qwen3.6 27B FP8 only." >&2
      exit 1
      ;;
  esac
  args="$(with_kv_cache_dtype "${args}")"
  args="$(with_reasoning_parser "${args}")"
  with_trust_remote_code "${args}"
}

update_environment_file() {
  local vllm_args
  vllm_args="$(pick_vllm_args)"
  if dry_run "update ${ENVIRONMENT_FILE}"; then
    echo "  VLLM_MODEL=${MODEL_ID}"
    echo "  MODEL_NAME=${MODEL_ID}"
    echo "  VLLM_ARGS=${vllm_args}"
    return
  fi
  cp -a "${ENVIRONMENT_FILE}" "${ENVIRONMENT_FILE}.bak.$(date +%Y%m%d%H%M%S)"
  sed -i "s|^VLLM_MODEL=.*|VLLM_MODEL=\"${MODEL_ID}\"|" "${ENVIRONMENT_FILE}"
  sed -i "s|^MODEL_NAME=.*|MODEL_NAME=\"${MODEL_ID}\"|" "${ENVIRONMENT_FILE}"
  sed -i "s|^VLLM_ARGS=.*|VLLM_ARGS=\"${vllm_args}\"|" "${ENVIRONMENT_FILE}"
}

update_app_env_file() {
  if [[ ! -f "${APP_ENV_FILE}" ]]; then
    echo "Missing ${APP_ENV_FILE}; skip app env sync." >&2
    return
  fi
  if dry_run "update ${APP_ENV_FILE}"; then
    echo "  VLLM_BASE_URL=http://127.0.0.1:18000"
    echo "  MAX_INPUT_TOKENS=24576"
    echo "  MAX_OUTPUT_TOKENS=8192"
    echo "  MAX_TOTAL_TOKENS=32768"
    echo "  VLLM_MODEL_PATH=${MODEL_ID}"
    echo "  VLLM_SERVED_MODEL_NAME=${MODEL_ID}"
    echo "  VLLM_MAX_MODEL_LEN=32768"
    echo "  VLLM_GPU_MEMORY_UTILIZATION=0.95"
    echo "  VLLM_MAX_NUM_SEQS=8"
    echo "  VLLM_MAX_NUM_BATCHED_TOKENS=16384"
    echo "  VLLM_KV_CACHE_DTYPE=${VLLM_KV_CACHE_DTYPE}"
    echo "  VLLM_REASONING_PARSER=${VLLM_REASONING_PARSER}"
    echo "  VLLM_TRUST_REMOTE_CODE=${VLLM_TRUST_REMOTE_CODE}"
    echo "  MODEL_IDS=${MODEL_ID}"
    echo "  VLLM_MANAGED=false"
    return
  fi
  cp -a "${APP_ENV_FILE}" "${APP_ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
  for key in \
    MAX_INPUT_TOKENS \
    MAX_OUTPUT_TOKENS \
    MAX_TOTAL_TOKENS \
    VLLM_BASE_URL \
    VLLM_PORT \
    VLLM_MODEL_PATH \
    VLLM_SERVED_MODEL_NAME \
    VLLM_MAX_MODEL_LEN \
    VLLM_GPU_MEMORY_UTILIZATION \
    VLLM_MAX_NUM_SEQS \
    VLLM_MAX_NUM_BATCHED_TOKENS \
    VLLM_KV_CACHE_DTYPE \
    VLLM_REASONING_PARSER \
    VLLM_TRUST_REMOTE_CODE \
    MODEL_IDS \
    VLLM_MANAGED; do
    if ! grep -q "^${key}=" "${APP_ENV_FILE}"; then
      echo "${key}=" >>"${APP_ENV_FILE}"
    fi
  done
  sed -i 's|^MAX_INPUT_TOKENS=.*|MAX_INPUT_TOKENS="24576"|' "${APP_ENV_FILE}"
  sed -i 's|^MAX_OUTPUT_TOKENS=.*|MAX_OUTPUT_TOKENS="8192"|' "${APP_ENV_FILE}"
  sed -i 's|^MAX_TOTAL_TOKENS=.*|MAX_TOTAL_TOKENS="32768"|' "${APP_ENV_FILE}"
  sed -i 's|^VLLM_BASE_URL=.*|VLLM_BASE_URL="http://127.0.0.1:18000"|' "${APP_ENV_FILE}"
  sed -i 's|^VLLM_PORT=.*|VLLM_PORT="18000"|' "${APP_ENV_FILE}"
  sed -i "s|^VLLM_MODEL_PATH=.*|VLLM_MODEL_PATH=\"${MODEL_ID}\"|" "${APP_ENV_FILE}"
  sed -i "s|^VLLM_SERVED_MODEL_NAME=.*|VLLM_SERVED_MODEL_NAME=\"${MODEL_ID}\"|" "${APP_ENV_FILE}"
  sed -i 's|^VLLM_MAX_MODEL_LEN=.*|VLLM_MAX_MODEL_LEN="32768"|' "${APP_ENV_FILE}"
  sed -i 's|^VLLM_GPU_MEMORY_UTILIZATION=.*|VLLM_GPU_MEMORY_UTILIZATION="0.95"|' "${APP_ENV_FILE}"
  sed -i 's|^VLLM_MAX_NUM_SEQS=.*|VLLM_MAX_NUM_SEQS="8"|' "${APP_ENV_FILE}"
  sed -i 's|^VLLM_MAX_NUM_BATCHED_TOKENS=.*|VLLM_MAX_NUM_BATCHED_TOKENS="16384"|' "${APP_ENV_FILE}"
  sed -i "s|^VLLM_KV_CACHE_DTYPE=.*|VLLM_KV_CACHE_DTYPE=\"${VLLM_KV_CACHE_DTYPE}\"|" "${APP_ENV_FILE}"
  sed -i "s|^VLLM_REASONING_PARSER=.*|VLLM_REASONING_PARSER=\"${VLLM_REASONING_PARSER}\"|" "${APP_ENV_FILE}"
  sed -i "s|^VLLM_TRUST_REMOTE_CODE=.*|VLLM_TRUST_REMOTE_CODE=\"${VLLM_TRUST_REMOTE_CODE}\"|" "${APP_ENV_FILE}"
  sed -i "s|^MODEL_IDS=.*|MODEL_IDS=\"${MODEL_ID}\"|" "${APP_ENV_FILE}"
  sed -i 's|^VLLM_MANAGED=.*|VLLM_MANAGED="false"|' "${APP_ENV_FILE}"
}

maybe_clear_model_cache() {
  if [[ "${REMOVE_OLD_CACHE}" != "true" ]]; then
    return
  fi
  if dry_run "rm -rf /workspace/models/*"; then
    return
  fi
  rm -rf /workspace/models/*
}

prefetch_model() {
  local downloader=""
  if command -v hf >/dev/null 2>&1; then
    downloader="hf"
  elif command -v huggingface-cli >/dev/null 2>&1; then
    downloader="huggingface-cli"
  else
    echo "hf/huggingface-cli not found; vLLM will download on first start." >&2
    return
  fi
  if dry_run "${downloader} download ${MODEL_ID}"; then
    return
  fi
  set -a
  # shellcheck disable=SC1091
  [[ -f "${APP_ENV_FILE}" ]] && . "${APP_ENV_FILE}"
  set +a
  if [[ "${downloader}" == "hf" ]]; then
    hf download "${MODEL_ID}" --cache-dir /workspace/models
  else
    huggingface-cli download "${MODEL_ID}" --cache-dir /workspace/models
  fi
}

restart_vllm() {
  if dry_run "supervisorctl restart ${VLLM_SUPERVISOR_NAME}"; then
    return
  fi
  export VLLM_MODEL="${MODEL_ID}"
  export MODEL_NAME="${MODEL_ID}"
  # shellcheck disable=SC1091
  . "${ENVIRONMENT_FILE}"
  supervisorctl restart "${VLLM_SUPERVISOR_NAME}"
}

restart_app_api() {
  if dry_run "supervisorctl restart api (gpu-inference supervisord)"; then
    return
  fi
  if supervisorctl -c /app/infra/supervisord.conf status api >/dev/null 2>&1; then
    supervisorctl -c /app/infra/supervisord.conf restart api
  elif [[ -f /tmp/gpu-inference-supervisor.sock ]]; then
    supervisorctl restart api
  else
    echo "Restart FastAPI manually (uvicorn on :8002) after vLLM is healthy." >&2
  fi
}

wait_for_vllm() {
  local i
  for i in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:18000/v1/models" | grep -q "${MODEL_ID}"; then
      echo "vLLM serves ${MODEL_ID}"
      curl -s "http://127.0.0.1:18000/v1/models"
      echo
      return 0
    fi
    sleep 10
  done
  echo "Timed out waiting for vLLM; check /var/log/portal/vllm.log" >&2
  return 1
}

main() {
  require_root
  disk_check
  update_environment_file
  update_app_env_file
  maybe_clear_model_cache
  prefetch_model
  restart_vllm
  if [[ "${DRY_RUN:-false}" == "true" ]]; then
    echo "Dry run complete. Re-run without DRY_RUN=true to apply."
    exit 0
  fi
  wait_for_vllm
  restart_app_api
  echo "Done. Verify: curl -s http://127.0.0.1:8002/v1/models -H 'Authorization: Bearer <key>'"
}

main
