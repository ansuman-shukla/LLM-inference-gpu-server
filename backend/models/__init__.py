"""Database model registration helpers."""

from importlib import import_module

MODEL_MODULES = (
    "api_key",
    "batch_job",
    "project",
    "quota_policy",
    "request_audit",
    "user",
    "webhook_config",
)


def load_models() -> None:
    """Import all SQLAlchemy model modules so foreign keys can resolve."""
    for module_name in MODEL_MODULES:
        import_module(f"{__name__}.{module_name}")
