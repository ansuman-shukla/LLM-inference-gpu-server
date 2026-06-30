"""Run the local Redis process used by the Vast container."""

import os


def main() -> None:
    os.execvp(
        "redis-server",
        [
            "redis-server",
            "--bind",
            "127.0.0.1",
            "--port",
            "6379",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
    )


if __name__ == "__main__":
    main()
