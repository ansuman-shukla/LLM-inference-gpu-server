"""Tests for application configuration."""

from backend.core.config import Settings


def test_settings_load_from_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("APP_PORT", "8002")
    monkeypatch.setenv("VLLM_MANAGED", "false")
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8001")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.app_port == 8002
    assert settings.vllm_managed is False
    assert settings.vllm_base_url == "http://127.0.0.1:8001"


def test_settings_parses_model_ids() -> None:
    settings = Settings(model_ids_raw="model-a, model-b,,")

    assert settings.model_ids == ("model-a", "model-b")


def test_settings_parse_vllm_runtime_knobs(monkeypatch) -> None:
    monkeypatch.setenv("VLLM_MODEL_PATH", "/models/qwen")
    monkeypatch.setenv("VLLM_SERVED_MODEL_NAME", "")
    monkeypatch.setenv("MODEL_IDS", "served-model")
    monkeypatch.setenv("VLLM_TENSOR_PARALLEL_SIZE", "4")
    monkeypatch.setenv("VLLM_MAX_MODEL_LEN", "4096")
    monkeypatch.setenv("VLLM_GPU_MEMORY_UTILIZATION", "0.85")
    monkeypatch.setenv("VLLM_MAX_NUM_SEQS", "32")
    monkeypatch.setenv("VLLM_MAX_NUM_BATCHED_TOKENS", "8192")
    monkeypatch.setenv("VLLM_KV_CACHE_DTYPE", "fp8")
    monkeypatch.setenv("VLLM_REASONING_PARSER", "qwen3")
    monkeypatch.setenv("VLLM_TRUST_REMOTE_CODE", "true")

    settings = Settings()

    assert settings.vllm_model_path == "/models/qwen"
    assert settings.vllm_served_model == "served-model"
    assert settings.vllm_tensor_parallel_size == 4
    assert settings.vllm_max_model_len == 4096
    assert settings.vllm_gpu_memory_utilization == 0.85
    assert settings.vllm_max_num_seqs == 32
    assert settings.vllm_max_num_batched_tokens == 8192
    assert settings.vllm_kv_cache_dtype == "fp8"
    assert settings.vllm_reasoning_parser == "qwen3"
    assert settings.vllm_trust_remote_code is True
