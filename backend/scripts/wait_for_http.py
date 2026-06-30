"""Wait for an HTTP endpoint to return a successful response."""

import argparse
import asyncio
import time

import httpx


async def wait_for_http(url: str, *, timeout_seconds: float, interval_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url)
                if 200 <= response.status_code < 500:
                    return
            except Exception as exc:  # pragma: no cover - timeout path depends on wall clock
                last_error = exc
            await asyncio.sleep(interval_seconds)
    raise TimeoutError(f"{url} did not become ready within {timeout_seconds:g}s") from last_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--interval", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        wait_for_http(
            args.url,
            timeout_seconds=args.timeout,
            interval_seconds=args.interval,
        )
    )


if __name__ == "__main__":
    main()
