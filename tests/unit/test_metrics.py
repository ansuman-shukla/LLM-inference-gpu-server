"""Tests for Prometheus metrics instrumentation."""

from backend.services.observability.metrics import (
    generate_metrics,
    record_clickhouse_flush_failure,
    record_http_request,
    record_redis_failure,
    record_stream_finished,
    record_stream_started,
    record_stream_ttft,
    record_vllm_upstream_error,
)


def test_metrics_counters_increment() -> None:
    record_http_request(
        method="POST",
        path="/unit/metrics",
        status_code=429,
        elapsed_seconds=0.01,
        error_code="rate_limit_exceeded",
    )
    record_http_request(
        method="POST",
        path="/unit/metrics",
        status_code=503,
        elapsed_seconds=0.02,
        error_code="dependency_unavailable",
    )
    record_stream_started()
    record_stream_ttft(model="test-model", ttft_seconds=0.03)
    record_stream_finished()
    record_clickhouse_flush_failure()
    record_redis_failure()
    record_vllm_upstream_error("upstream_timeout")

    output = generate_metrics().decode("utf-8")

    assert (
        'gpu_inference_http_requests_total{method="POST",path="/unit/metrics",status_code="429"}'
        in output
    )
    assert 'gpu_inference_http_429_total{error_code="rate_limit_exceeded"}' in output
    assert 'gpu_inference_http_503_total{error_code="dependency_unavailable"}' in output
    assert "gpu_inference_stream_ttft_seconds_bucket" in output
    assert "gpu_inference_active_streams" in output
    assert "gpu_inference_clickhouse_flush_failures_total" in output
    assert "gpu_inference_redis_failures_total" in output
    assert 'gpu_inference_vllm_upstream_errors_total{error_code="upstream_timeout"}' in output
