"""Tests for request audit record building."""

from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.auth.api_key_service import AuthContext
from backend.services.inference.request_lifecycle import build_audit_start


def test_audit_record_builder_excludes_raw_prompt_and_api_key() -> None:
    request = ChatCompletionRequest(
        model="test-model",
        messages=[{"role": "user", "content": "secret prompt"}],
    )
    auth_context = AuthContext(
        api_key_id="key_test",
        user_id="user_test",
        project_id="project_test",
        allowed_models=("test-model",),
    )

    audit = build_audit_start(
        request_id="req_test",
        auth_context=auth_context,
        model=request.model,
        messages=request.messages,
    )

    serialized = repr(audit)
    assert "secret prompt" not in serialized
    assert "an_" not in serialized
    assert audit.prompt_hash is not None
    assert len(audit.prompt_hash) == 64


def test_audit_record_builder_hashes_multimodal_prompt() -> None:
    request = ChatCompletionRequest(
        model="test-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "secret prompt"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                    },
                ],
            }
        ],
    )
    auth_context = AuthContext(
        api_key_id="key_test",
        user_id="user_test",
        project_id="project_test",
        allowed_models=("test-model",),
    )

    audit = build_audit_start(
        request_id="req_test",
        auth_context=auth_context,
        model=request.model,
        messages=request.messages,
    )

    assert audit.prompt_hash is not None
    assert len(audit.prompt_hash) == 64
