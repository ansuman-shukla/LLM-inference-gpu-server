"""Tests for error mapping."""

from backend.core.errors import openai_error_object


def test_error_formatter_returns_openai_style_error() -> None:
    error = openai_error_object(
        message="No API key provided",
        code="missing_api_key",
        error_type="invalid_request_error",
        request_id="req_test",
    )

    assert error == {
        "error": {
            "message": "No API key provided",
            "type": "invalid_request_error",
            "param": None,
            "code": "missing_api_key",
            "request_id": "req_test",
        }
    }
