"""vLLM runtime command and readiness helpers."""

import asyncio
import shlex
import time
from collections.abc import Sequence

import httpx

from backend.core.config import Settings
from backend.core.errors import AppError


def build_vllm_serve_command(settings: Settings) -> list[str]:
    """Build the localhost-only vLLM OpenAI server command."""
    command = [
        "vllm",
        "serve",
        settings.vllm_model_path,
        "--host",
        settings.vllm_host,
        "--port",
        str(settings.vllm_port),
        "--served-model-name",
        settings.vllm_served_model,
        "--tensor-parallel-size",
        str(settings.vllm_tensor_parallel_size),
        "--max-model-len",
        str(settings.vllm_max_model_len),
        "--gpu-memory-utilization",
        str(settings.vllm_gpu_memory_utilization),
        "--max-num-seqs",
        str(settings.vllm_max_num_seqs),
        "--max-num-batched-tokens",
        str(settings.vllm_max_num_batched_tokens),
    ]
    if settings.vllm_enable_chunked_prefill:
        command.append("--enable-chunked-prefill")
    if settings.vllm_kv_cache_dtype:
        command.extend(["--kv-cache-dtype", settings.vllm_kv_cache_dtype])
    if settings.vllm_reasoning_parser:
        command.extend(["--reasoning-parser", settings.vllm_reasoning_parser])
    if settings.vllm_trust_remote_code:
        command.append("--trust-remote-code")
    return command


def command_to_shell(command: Sequence[str]) -> str:
    """Render a command for logs without changing execution semantics."""
    return " ".join(shlex.quote(part) for part in command)


async def wait_for_vllm_ready(
    base_url: str,
    *,
    timeout_seconds: float,
    interval_seconds: float = 2.0,
) -> None:
    """Wait until vLLM's OpenAI-compatible models endpoint responds."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get("/v1/models")
                if response.status_code < 500:
                    response.raise_for_status()
                    return
            except Exception as exc:  # pragma: no cover
                last_error = exc
            await asyncio.sleep(interval_seconds)
    raise AppError(
        message="vLLM did not become ready before the startup timeout",
        code="vllm_not_ready",
        status_code=503,
        type="server_error",
    ) from last_error
