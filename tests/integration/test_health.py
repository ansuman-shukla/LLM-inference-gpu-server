"""Integration tests for health routes."""

from fastapi.testclient import TestClient

from backend.core.constants import REQUEST_ID_HEADER
from backend.main import create_app


def test_health_and_ready_work() -> None:
    with TestClient(create_app()) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert health_response.headers[REQUEST_ID_HEADER].startswith("req_")

    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}
    assert ready_response.headers[REQUEST_ID_HEADER].startswith("req_")


def test_request_id_header_is_preserved() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "req_external"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req_external"
