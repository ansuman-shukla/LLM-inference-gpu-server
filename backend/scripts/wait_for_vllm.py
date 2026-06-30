"""Wait for the configured vLLM server to become ready."""

import asyncio

from backend.core.config import get_settings
from backend.services.vllm.runtime import wait_for_vllm_ready


async def main() -> None:
    settings = get_settings()
    await wait_for_vllm_ready(
        settings.vllm_base_url,
        timeout_seconds=settings.vllm_startup_timeout_seconds,
    )


if __name__ == "__main__":
    asyncio.run(main())
