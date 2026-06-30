"""API key hashing helpers."""

from hashlib import sha256

KEY_DEBUG_PREFIX_LENGTH = 16


def hash_api_key(raw_key: str) -> str:
    """Hash a raw API key for durable storage."""
    return sha256(raw_key.encode("utf-8")).hexdigest()


def key_debug_prefix(raw_key: str) -> str:
    """Return the non-secret prefix stored for lookup/debugging."""
    return raw_key[:KEY_DEBUG_PREFIX_LENGTH]
