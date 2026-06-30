"""Sentry integration."""

from collections.abc import Mapping, MutableMapping
import logging
import re
from typing import Any

from fastapi import Request

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.services.auth.api_key_service import AuthContext

_sentry_sdk: Any | None
FastApiIntegration: Any | None

try:
    import sentry_sdk as sentry_sdk_module
    from sentry_sdk.integrations.fastapi import FastApiIntegration as FastApiIntegrationClass
except ImportError:  # pragma: no cover - exercised when the optional package is absent.
    _sentry_sdk = None
    FastApiIntegration = None
else:
    _sentry_sdk = sentry_sdk_module
    FastApiIntegration = FastApiIntegrationClass

logger = logging.getLogger(__name__)
_sentry_enabled = False

REDACTED = "[Filtered]"
SECRET_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "dsn",
    "credential",
    "private_key",
    "tunnel",
)
PAYLOAD_KEY_PARTS = ("prompt", "messages", "input")
API_KEY_PATTERN = re.compile(r"\b(an_[A-Za-z0-9_\-]{12,}|sk-[A-Za-z0-9_\-]{12,})\b")
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=\-]+", re.IGNORECASE)
URL_CREDENTIAL_PATTERN = re.compile(r"://([^:/@\s]+):([^/@\s]+)@")


def initialize_sentry(settings: Settings, *, transport: Any | None = None) -> bool:
    """Initialize Sentry when a DSN is configured."""
    global _sentry_enabled
    _sentry_enabled = False
    if not settings.sentry_dsn:
        return False
    if _sentry_sdk is None:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return False

    integrations = [FastApiIntegration()] if FastApiIntegration is not None else []
    options: dict[str, Any] = {
        "dsn": settings.sentry_dsn,
        "environment": settings.app_env,
        "release": settings.release,
        "send_default_pii": settings.sentry_send_default_pii,
        "traces_sample_rate": settings.sentry_traces_sample_rate,
        "before_send": scrub_sentry_event,
        "integrations": integrations,
    }
    if transport is not None:
        options["transport"] = transport

    try:
        _sentry_sdk.init(**options)
    except Exception:
        logger.exception("sentry initialization failed")
        return False
    _sentry_enabled = True
    return True


def capture_exception(
    exc: BaseException,
    *,
    tags: Mapping[str, object | None] | None = None,
    context: Mapping[str, object | None] | None = None,
) -> str | None:
    """Capture an exception without letting Sentry affect application behavior."""
    if should_skip_exception(exc) or _sentry_sdk is None or not _sentry_enabled:
        return None

    try:
        with _sentry_sdk.push_scope() as scope:
            for key, value in (tags or {}).items():
                if value is not None:
                    scope.set_tag(key, str(value))
            if context:
                scope.set_context("app", scrub_data(dict(context)))
            return _sentry_sdk.capture_exception(exc)
    except Exception:
        logger.debug("sentry capture failed", exc_info=True)
        return None


def bind_request_context(
    request: Request, *, model: str | None = None, stream: bool | None = None
) -> None:
    """Attach safe request metadata to the current Sentry scope."""
    if _sentry_sdk is None or not _sentry_enabled:
        return

    try:
        auth_context = getattr(request.state, "auth_context", None)
        request_id = getattr(request.state, "request_id", None)
        tags: dict[str, object | None] = {
            "request_id": request_id,
            "endpoint": request.url.path,
            "method": request.method,
            "model": model,
            "stream": stream,
        }
        if isinstance(auth_context, AuthContext):
            tags.update(
                {
                    "user_id": auth_context.user_id,
                    "project_id": auth_context.project_id,
                    "api_key_id": auth_context.api_key_id,
                }
            )

        with _sentry_sdk.configure_scope() as scope:
            for key, value in tags.items():
                if value is not None:
                    scope.set_tag(key, str(value))
            if isinstance(auth_context, AuthContext):
                scope.set_user({"id": auth_context.user_id})
    except Exception:
        logger.debug("sentry request context binding failed", exc_info=True)


def capture_request_exception(
    request: Request,
    exc: BaseException,
    *,
    model: str | None = None,
    stream: bool | None = None,
) -> str | None:
    """Capture a request exception with safe request and auth metadata."""
    if getattr(request.state, "sentry_exception_captured", False):
        return None
    bind_request_context(request, model=model, stream=stream)
    auth_context = getattr(request.state, "auth_context", None)
    tags: dict[str, object | None] = {
        "request_id": getattr(request.state, "request_id", None),
        "endpoint": request.url.path,
        "method": request.method,
        "model": model,
        "stream": stream,
        "error_code": getattr(exc, "code", None),
    }
    if isinstance(auth_context, AuthContext):
        tags.update(
            {
                "user_id": auth_context.user_id,
                "project_id": auth_context.project_id,
                "api_key_id": auth_context.api_key_id,
            }
        )
    event_id = capture_exception(exc, tags=tags)
    if event_id is not None:
        request.state.sentry_exception_captured = True
    return event_id


def should_skip_exception(exc: BaseException) -> bool:
    """Return true for expected client-side API errors that should not page Sentry."""
    return isinstance(exc, AppError) and exc.status_code < 500


def scrub_sentry_event(
    event: MutableMapping[str, Any], hint: Mapping[str, Any] | None = None
) -> MutableMapping[str, Any] | None:
    """Remove sensitive payloads and credentials from a Sentry event."""
    return scrub_data(event)


def scrub_data(value: Any) -> Any:
    """Recursively redact sensitive fields and secret-looking string values."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if _is_secret_key(key_text) or _is_payload_key(key_text):
                redacted[key] = REDACTED
            else:
                redacted[key] = scrub_data(item)
        return redacted
    if isinstance(value, list):
        return [scrub_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_data(item) for item in value)
    if isinstance(value, str):
        return _scrub_string(value)
    return value


def _is_secret_key(key: str) -> bool:
    if key == "api_key_id":
        return False
    if key in {"api_key", "apikey"}:
        return True
    return any(part in key for part in SECRET_KEY_PARTS)


def _is_payload_key(key: str) -> bool:
    return any(part in key for part in PAYLOAD_KEY_PARTS)


def _scrub_string(value: str) -> str:
    scrubbed = BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    scrubbed = API_KEY_PATTERN.sub(REDACTED, scrubbed)
    scrubbed = URL_CREDENTIAL_PATTERN.sub(r"://\1:***@", scrubbed)
    return scrubbed
