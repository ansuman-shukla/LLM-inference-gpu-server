"""Integration tests for model routes."""

from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app


class FakeVLLMClient:
    async def close(self) -> None:
        return None


def test_models_route_returns_expected_model_id() -> None:
    settings = Settings(model_ids_raw="model-a,model-b")

    with TestClient(create_app(settings=settings, vllm_client=FakeVLLMClient())) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {"id": "model-a", "object": "model", "owned_by": "yral"},
            {"id": "model-b", "object": "model", "owned_by": "yral"},
        ],
    }
