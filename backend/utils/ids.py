"""ID generation helpers."""

from uuid import uuid4


def generate_request_id() -> str:
    """Generate an opaque request identifier."""
    return f"req_{uuid4().hex}"
