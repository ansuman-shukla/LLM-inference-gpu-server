"""Model API schemas."""

from pydantic import BaseModel


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "yral"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelObject]


def model_list_response(model_ids: tuple[str, ...]) -> ModelListResponse:
    """Map configured model IDs to the OpenAI-compatible list response."""
    return ModelListResponse(data=[ModelObject(id=model_id) for model_id in model_ids])
