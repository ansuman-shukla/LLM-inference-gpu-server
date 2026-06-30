"""Tests for model response mapping."""

from backend.schemas.model import model_list_response


def test_model_config_maps_to_response_shape() -> None:
    response = model_list_response(("model-a", "model-b"))

    assert response.model_dump() == {
        "object": "list",
        "data": [
            {"id": "model-a", "object": "model", "owned_by": "yral"},
            {"id": "model-b", "object": "model", "owned_by": "yral"},
        ],
    }
