"""Tests for token accounting."""

import asyncio

import pytest

from backend.core.errors import AppError
from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.inference.token_accounting import (
    IMAGE_PART_TOKEN_ESTIMATE,
    TokenEstimator,
    build_token_plan,
    usage_from_response,
)
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import tpm_key
from tests.conftest import FakeRedis


class CountingEstimator:
    def __init__(self, tokens_per_text: int = 1) -> None:
        self.calls: list[str] = []
        self.tokens_per_text = tokens_per_text

    def count_text(self, text: str) -> int:
        self.calls.append(text)
        return self.tokens_per_text if text else 0


def _request(*, max_tokens: int | None = 10, content: str = "hello") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="test-model",
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
    )


def test_prompt_token_estimator_is_called_before_admission() -> None:
    estimator = CountingEstimator(tokens_per_text=2)

    plan = build_token_plan(
        _request(max_tokens=5),
        estimator,
        max_input_tokens=100,
        max_output_tokens=10,
        max_total_tokens=110,
    )

    assert "user" in estimator.calls
    assert "hello" in estimator.calls
    assert plan.prompt_tokens > 0
    assert plan.estimated_total_tokens == plan.prompt_tokens + 5


def test_max_token_violation_returns_app_error() -> None:
    with pytest.raises(AppError) as exc_info:
        build_token_plan(
            _request(max_tokens=11),
            CountingEstimator(),
            max_input_tokens=100,
            max_output_tokens=10,
            max_total_tokens=110,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "max_output_tokens_exceeded"


def test_quota_reservation_finalizes_success() -> None:
    redis = FakeRedis()
    reserver = QuotaReserver(redis, tpm_limit=100)

    async def scenario() -> None:
        reservation = await reserver.reserve(api_key_id="key_test", estimated_tokens=20)
        assert redis.values[tpm_key("key_test")] == 20
        await reservation.finalize(actual_tokens=12)

    asyncio.run(scenario())
    assert redis.values[tpm_key("key_test")] == 12


def test_quota_reservation_finalizes_failure() -> None:
    redis = FakeRedis()
    reserver = QuotaReserver(redis, tpm_limit=100)

    async def scenario() -> None:
        reservation = await reserver.reserve(api_key_id="key_test", estimated_tokens=20)
        await reservation.finalize(actual_tokens=0, release_all=True)

    asyncio.run(scenario())
    assert tpm_key("key_test") not in redis.values


def test_usage_from_response_prefers_upstream_usage() -> None:
    estimator: TokenEstimator = CountingEstimator(tokens_per_text=1)
    plan = build_token_plan(
        _request(max_tokens=5),
        estimator,
        max_input_tokens=100,
        max_output_tokens=10,
        max_total_tokens=110,
    )

    usage = usage_from_response(
        {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}},
        plan,
        estimator,
    )

    assert usage.prompt_tokens == 3
    assert usage.completion_tokens == 4
    assert usage.total_tokens == 7


def test_multimodal_prompt_estimation_counts_text_and_image_budget() -> None:
    estimator = CountingEstimator(tokens_per_text=2)
    request = ChatCompletionRequest(
        model="test-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "classify this image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                    },
                ],
            }
        ],
        max_tokens=5,
    )

    plan = build_token_plan(
        request,
        estimator,
        max_input_tokens=IMAGE_PART_TOKEN_ESTIMATE + 100,
        max_output_tokens=10,
        max_total_tokens=IMAGE_PART_TOKEN_ESTIMATE + 200,
    )

    assert "user" in estimator.calls
    assert "classify this image" in estimator.calls
    assert plan.prompt_tokens >= IMAGE_PART_TOKEN_ESTIMATE
