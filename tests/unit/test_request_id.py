"""Tests for request ID helpers."""

from backend.utils.ids import generate_request_id


def test_request_id_generator_returns_unique_ids() -> None:
    first = generate_request_id()
    second = generate_request_id()

    assert first.startswith("req_")
    assert second.startswith("req_")
    assert first != second
