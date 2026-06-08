"""Tests for application import wiring."""

from backend.main import app


def test_app_imports() -> None:
    assert app.title == "GPU Inference Backend"
