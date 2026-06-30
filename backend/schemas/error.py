"""Error response schemas."""

from pydantic import BaseModel


class ErrorBody(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
