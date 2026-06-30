"""Optional real-vLLM integration tests for Vast/runtime smoke checks."""

import asyncio
import os

import pytest

from backend.services.vllm.client import VLLMClient


@pytest.mark.skipif(
    not os.getenv("REAL_VLLM_BASE_URL"),
    reason="set REAL_VLLM_BASE_URL to run against a real local vLLM server",
)
def test_real_vllm_models_endpoint_responds() -> None:
    async def scenario() -> dict[str, object]:
        client = VLLMClient(os.environ["REAL_VLLM_BASE_URL"])
        try:
            return await client.list_models()
        finally:
            await client.close()

    response = asyncio.run(scenario())

    assert response.get("object") == "list"
    assert isinstance(response.get("data"), list)
