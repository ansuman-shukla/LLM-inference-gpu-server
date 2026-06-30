"""Tests for application import wiring."""

from backend.main import app
from backend.main import create_app


def test_app_imports() -> None:
    assert app.title == "GPU Inference Backend"


def test_app_factory_creates_app() -> None:
    assert create_app().title == "GPU Inference Backend"
