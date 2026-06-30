"""Integration tests for API documentation metadata."""

from fastapi.testclient import TestClient

from backend.main import create_app


class FakeVLLMClient:
    async def close(self) -> None:
        return None


def test_swagger_ui_is_available() -> None:
    with TestClient(create_app(vllm_client=FakeVLLMClient())) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_openapi_marks_protected_routes_with_bearer_auth() -> None:
    with TestClient(create_app(vllm_client=FakeVLLMClient())) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API key",
        "description": "Use `Authorization: Bearer an_...`.",
    }
    assert schema["paths"]["/v1/chat/completions"]["post"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/v1/batch/jobs"]["post"]["security"] == [{"BearerAuth": []}]
    assert "security" not in schema["paths"]["/health"]["get"]
    assert "security" not in schema["paths"]["/v1/models"]["get"]
