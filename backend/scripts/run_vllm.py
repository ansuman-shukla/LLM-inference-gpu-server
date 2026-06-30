"""Run the configured vLLM OpenAI-compatible server."""

import time
import os

from backend.core.config import get_settings
from backend.services.vllm.runtime import build_vllm_serve_command, command_to_shell


def main() -> None:
    settings = get_settings()
    if not settings.vllm_managed:
        print(f"Using external vLLM at {settings.vllm_base_url}; not starting vLLM.", flush=True)
        while True:
            time.sleep(3600)

    command = build_vllm_serve_command(settings)
    print(command_to_shell(command), flush=True)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
