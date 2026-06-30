"""Token accounting helpers."""

import json
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from backend.core.errors import AppError
from backend.schemas.chat_completion import (
    ChatCompletionRequest,
    ChatMessage,
    count_message_images,
    iter_message_text_parts,
)

IMAGE_PART_TOKEN_ESTIMATE = 512


class TokenEstimator(Protocol):
    """Token estimator interface for the served model family."""

    def count_text(self, text: str) -> int: ...


class HeuristicTokenEstimator:
    """Conservative tokenizer fallback until a model tokenizer is configured."""

    def count_text(self, text: str) -> int:
        stripped = text.strip()
        if not stripped:
            return 0
        return max(1, ceil(len(stripped) / 4))


@dataclass(frozen=True)
class TokenPlan:
    prompt_tokens: int
    max_completion_tokens: int
    estimated_total_tokens: int


@dataclass(frozen=True)
class UsageRecord:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    status: str


def build_token_plan(
    request: ChatCompletionRequest,
    estimator: TokenEstimator,
    *,
    max_input_tokens: int,
    max_output_tokens: int,
    max_total_tokens: int,
) -> TokenPlan:
    """Estimate and validate tokens before request admission."""
    prompt_tokens = estimate_prompt_tokens(request.messages, estimator)
    requested_output_tokens = request.max_tokens or max_output_tokens
    if requested_output_tokens > max_output_tokens:
        raise AppError(
            message="Requested max_tokens exceeds the configured output token limit",
            code="max_output_tokens_exceeded",
            status_code=400,
            type="invalid_request_error",
            param="max_tokens",
        )
    if prompt_tokens > max_input_tokens:
        raise AppError(
            message="Prompt exceeds the configured input token limit",
            code="max_input_tokens_exceeded",
            status_code=413,
            type="invalid_request_error",
            param="messages",
        )
    estimated_total = prompt_tokens + requested_output_tokens
    if estimated_total > max_total_tokens:
        raise AppError(
            message="Request exceeds the configured total token limit",
            code="max_total_tokens_exceeded",
            status_code=413,
            type="invalid_request_error",
            param="max_tokens",
        )
    return TokenPlan(
        prompt_tokens=prompt_tokens,
        max_completion_tokens=requested_output_tokens,
        estimated_total_tokens=estimated_total,
    )


def estimate_prompt_tokens(messages: list[ChatMessage], estimator: TokenEstimator) -> int:
    """Estimate chat prompt tokens including small role/message overhead."""
    total = 0
    for message in messages:
        total += 4
        total += estimator.count_text(message.role)
        for text_part in iter_message_text_parts(message.content):
            total += estimator.count_text(text_part)
        total += count_message_images(message.content) * IMAGE_PART_TOKEN_ESTIMATE
    return total + 2


def usage_from_response(
    response: dict[str, object], token_plan: TokenPlan, estimator: TokenEstimator
) -> UsageRecord:
    """Extract usage from vLLM response, falling back to assistant text estimation."""
    usage = response.get("usage")
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens", token_plan.prompt_tokens) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", prompt + completion) or 0)
        return UsageRecord(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            status="completed",
        )

    completion_text = ""
    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        completion_text += content
    completion_tokens = estimator.count_text(completion_text)
    total = token_plan.prompt_tokens + completion_tokens
    return UsageRecord(
        prompt_tokens=token_plan.prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        status="completed",
    )


def stream_delta_text(event: str) -> str:
    """Return assistant delta text from one OpenAI-style SSE event."""
    if not event.startswith("data: "):
        return ""
    payload = event.removeprefix("data: ").strip()
    if payload == "[DONE]":
        return ""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    choices = parsed.get("choices")
    if not isinstance(choices, list):
        return ""
    chunks: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            chunks.append(delta["content"])
    return "".join(chunks)


def usage_from_stream_text(
    text: str, token_plan: TokenPlan, estimator: TokenEstimator, *, status: str
) -> UsageRecord:
    completion_tokens = estimator.count_text(text)
    total = token_plan.prompt_tokens + completion_tokens
    return UsageRecord(
        prompt_tokens=token_plan.prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        status=status,
    )
