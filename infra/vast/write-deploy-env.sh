#!/usr/bin/env bash
set -euo pipefail

OUTPUT_FILE="${1:-.env.deploy}"

required_keys=(
  DATABASE_URL
  CLICKHOUSE_URL
  CLICKHOUSE_DATABASE
  CLICKHOUSE_USER
  CLICKHOUSE_PASSWORD
)

quote_env_value() {
  local value="$1"

  if [[ "${value}" == *$'\n'* ]]; then
    echo "Environment values with newlines are not supported in ${OUTPUT_FILE}" >&2
    exit 1
  fi

  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\$/\\\$}"
  value="${value//\`/\\\`}"
  printf '"%s"' "${value}"
}

require_key() {
  local key="$1"
  if [ -z "${!key:-}" ]; then
    echo "Missing required deployment environment variable: ${key}" >&2
    exit 1
  fi
}

write_key() {
  local key="$1"
  local default="${2:-}"
  local value="${!key:-}"

  if [ -z "${value}" ]; then
    value="${default}"
  fi

  printf '%s=%s\n' "${key}" "$(quote_env_value "${value}")"
}

for key in "${required_keys[@]}"; do
  require_key "${key}"
done

tmp_file="${OUTPUT_FILE}.tmp"
umask 077
{
  write_key APP_ENV production
  write_key LOG_LEVEL INFO
  write_key APP_HOST 127.0.0.1
  write_key APP_PORT 8002
  write_key DATABASE_URL
  write_key REDIS_PORT 6380
  write_key REDIS_URL redis://127.0.0.1:6380/0
  write_key RATE_LIMIT_RPM 1000
  write_key CONCURRENT_REQUEST_LIMIT 10
  write_key TOKEN_LIMIT_TPM 2097152
  write_key MAX_INPUT_TOKENS 24576
  write_key MAX_OUTPUT_TOKENS 8192
  write_key MAX_TOTAL_TOKENS 32768
  write_key CLICKHOUSE_URL
  write_key CLICKHOUSE_DATABASE
  write_key CLICKHOUSE_USER
  write_key CLICKHOUSE_PASSWORD
  write_key CLICKHOUSE_SECURE true
  write_key CLICKHOUSE_VERIFY false
  write_key CLICKHOUSE_CLUSTER default
  write_key ANALYTICS_QUEUE_SIZE 1000
  write_key ANALYTICS_FLUSH_BATCH_SIZE 500
  write_key VLLM_MANAGED false
  write_key VLLM_BASE_URL http://127.0.0.1:18000
  write_key VLLM_HOST 127.0.0.1
  write_key VLLM_PORT 18000
  write_key VLLM_MODEL_PATH Qwen/Qwen3.6-27B-FP8
  write_key VLLM_SERVED_MODEL_NAME Qwen/Qwen3.6-27B-FP8
  write_key VLLM_TENSOR_PARALLEL_SIZE 2
  write_key VLLM_MAX_MODEL_LEN 32768
  write_key VLLM_GPU_MEMORY_UTILIZATION 0.95
  write_key VLLM_MAX_NUM_SEQS 8
  write_key VLLM_MAX_NUM_BATCHED_TOKENS 16384
  write_key VLLM_ENABLE_CHUNKED_PREFILL true
  write_key VLLM_KV_CACHE_DTYPE fp8
  write_key VLLM_REASONING_PARSER qwen3
  write_key VLLM_TRUST_REMOTE_CODE true
  write_key VLLM_STARTUP_TIMEOUT_SECONDS 900
  write_key VLLM_CONNECT_TIMEOUT_SECONDS 10
  write_key VLLM_READ_TIMEOUT_SECONDS 600
  write_key MODEL_IDS Qwen/Qwen3.6-27B-FP8
  write_key HF_TOKEN
  write_key API_KEY_PREFIX an
  write_key SENTRY_DSN
  write_key SENTRY_SEND_DEFAULT_PII false
  write_key SENTRY_TRACES_SAMPLE_RATE 0.05
  write_key SERVICE_NAME gpu-inference-backend
  write_key RELEASE
} > "${tmp_file}"

mv "${tmp_file}" "${OUTPUT_FILE}"
chmod 0600 "${OUTPUT_FILE}"
