"""Integration tests for metrics exposure."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app


def test_metrics_endpoint_exposes_expected_metric_names() -> None:
    with TestClient(create_app()) as client:
        health_response = client.get("/health")
        metrics_response = client.get("/metrics")

    assert health_response.status_code == 200
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")
    body = metrics_response.text
    assert "gpu_inference_http_requests_total" in body
    assert "gpu_inference_http_request_duration_seconds" in body
    assert "gpu_inference_stream_ttft_seconds" in body
    assert "gpu_inference_active_streams" in body
    assert "gpu_inference_analytics_queue_size" in body
    assert "gpu_inference_clickhouse_flush_failures_total" in body
    assert "gpu_inference_redis_failures_total" in body
    assert "gpu_inference_vllm_upstream_errors_total" in body
    assert 'path="/health"' in body


def test_cloudflare_config_does_not_expose_metrics_publicly() -> None:
    config = Path("infra/cloudflared/config.yml.example").read_text()

    metrics_rule = config.index("path: /metrics")
    blocked_service = config.index("service: http_status:404", metrics_rule)
    public_service = config.index("service: http://127.0.0.1:8002")

    assert metrics_rule < blocked_service < public_service
