"""Model listing routes."""

from fastapi import APIRouter, Request

from backend.core.config import Settings
from backend.schemas.model import ModelListResponse, model_list_response

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def list_models(request: Request) -> ModelListResponse:
    """Return configured public model IDs."""
    settings: Settings = request.app.state.settings
    return model_list_response(settings.model_ids)
