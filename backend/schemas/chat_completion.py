"""Chat completion schemas."""

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TextContentPart(BaseModel):
    type: Literal["text"]
    text: str

    model_config = ConfigDict(extra="allow")


class ImageUrlContent(BaseModel):
    url: str
    detail: str | None = None

    model_config = ConfigDict(extra="allow")


class ImageContentPart(BaseModel):
    type: Literal["image_url"]
    image_url: ImageUrlContent | str

    model_config = ConfigDict(extra="allow")


MessageContentPart: TypeAlias = Annotated[
    TextContentPart | ImageContentPart,
    Field(discriminator="type"),
]
ChatMessageContent: TypeAlias = str | list[MessageContentPart]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: ChatMessageContent

    model_config = ConfigDict(extra="allow")

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: ChatMessageContent) -> ChatMessageContent:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("content is required")
            return value
        if not value:
            raise ValueError("content is required")
        return value


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stop: str | list[str] | None = None
    user: str | None = None
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("model")
    @classmethod
    def model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model is required")
        return value


def iter_message_text_parts(content: ChatMessageContent) -> tuple[str, ...]:
    """Return text segments that should count toward prompt tokens."""
    if isinstance(content, str):
        return (content,)
    return tuple(part.text for part in content if isinstance(part, TextContentPart))


def count_message_images(content: ChatMessageContent) -> int:
    """Return the number of image parts in one chat message."""
    if isinstance(content, str):
        return 0
    return sum(1 for part in content if isinstance(part, ImageContentPart))
