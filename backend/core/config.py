"""Application configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/gpu_inference",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    rate_limit_rpm: int = Field(default=1_000, alias="RATE_LIMIT_RPM")
    concurrent_request_limit: int = Field(default=10, alias="CONCURRENT_REQUEST_LIMIT")
    token_limit_tpm: int = Field(default=2_097_152, alias="TOKEN_LIMIT_TPM")
    max_input_tokens: int = Field(default=24_576, alias="MAX_INPUT_TOKENS")
    max_output_tokens: int = Field(default=8_192, alias="MAX_OUTPUT_TOKENS")
    max_total_tokens: int = Field(default=32_768, alias="MAX_TOTAL_TOKENS")
    clickhouse_url: str = Field(default="http://localhost:8123", alias="CLICKHOUSE_URL")
    clickhouse_database: str = Field(default="yral", alias="CLICKHOUSE_DATABASE")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="CLICKHOUSE_PASSWORD")
    clickhouse_secure: bool = Field(default=False, alias="CLICKHOUSE_SECURE")
    clickhouse_verify: bool = Field(default=True, alias="CLICKHOUSE_VERIFY")
    clickhouse_cluster: str = Field(default="default", alias="CLICKHOUSE_CLUSTER")
    analytics_queue_size: int = Field(default=1000, alias="ANALYTICS_QUEUE_SIZE")
    analytics_flush_batch_size: int = Field(default=500, alias="ANALYTICS_FLUSH_BATCH_SIZE")
    vllm_managed: bool = Field(default=True, alias="VLLM_MANAGED")
    vllm_base_url: str = Field(default="http://127.0.0.1:8001", alias="VLLM_BASE_URL")
    vllm_host: str = Field(default="127.0.0.1", alias="VLLM_HOST")
    vllm_port: int = Field(default=8001, alias="VLLM_PORT")
    vllm_model_path: str = Field(default="Qwen/Qwen3.6-27B-FP8", alias="VLLM_MODEL_PATH")
    vllm_served_model_name: str | None = Field(default=None, alias="VLLM_SERVED_MODEL_NAME")
    vllm_tensor_parallel_size: int = Field(default=2, alias="VLLM_TENSOR_PARALLEL_SIZE")
    vllm_max_model_len: int = Field(default=32_768, alias="VLLM_MAX_MODEL_LEN")
    vllm_gpu_memory_utilization: float = Field(default=0.95, alias="VLLM_GPU_MEMORY_UTILIZATION")
    vllm_max_num_seqs: int = Field(default=8, alias="VLLM_MAX_NUM_SEQS")
    vllm_max_num_batched_tokens: int = Field(default=16_384, alias="VLLM_MAX_NUM_BATCHED_TOKENS")
    vllm_enable_chunked_prefill: bool = Field(default=True, alias="VLLM_ENABLE_CHUNKED_PREFILL")
    vllm_kv_cache_dtype: str | None = Field(default="fp8", alias="VLLM_KV_CACHE_DTYPE")
    vllm_reasoning_parser: str | None = Field(default="qwen3", alias="VLLM_REASONING_PARSER")
    vllm_trust_remote_code: bool = Field(default=True, alias="VLLM_TRUST_REMOTE_CODE")
    vllm_startup_timeout_seconds: float = Field(default=900.0, alias="VLLM_STARTUP_TIMEOUT_SECONDS")
    vllm_connect_timeout_seconds: float = Field(default=10.0, alias="VLLM_CONNECT_TIMEOUT_SECONDS")
    vllm_read_timeout_seconds: float = Field(default=600.0, alias="VLLM_READ_TIMEOUT_SECONDS")
    model_ids_raw: str = Field(default="test-model", alias="MODEL_IDS")
    api_key_prefix: str = Field(default="an", alias="API_KEY_PREFIX")
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    sentry_send_default_pii: bool = Field(default=False, alias="SENTRY_SEND_DEFAULT_PII")
    sentry_traces_sample_rate: float = Field(default=0.05, alias="SENTRY_TRACES_SAMPLE_RATE")
    service_name: str = Field(default="gpu-inference-backend", alias="SERVICE_NAME")
    release: str | None = Field(default=None, alias="RELEASE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def model_ids(self) -> tuple[str, ...]:
        """Configured public model identifiers."""
        return tuple(
            model_id.strip() for model_id in self.model_ids_raw.split(",") if model_id.strip()
        )

    @property
    def vllm_served_model(self) -> str:
        """Model name exposed by vLLM's OpenAI-compatible API."""
        if self.vllm_served_model_name:
            return self.vllm_served_model_name
        if self.model_ids:
            return self.model_ids[0]
        return self.vllm_model_path


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application runtime."""
    return Settings()
