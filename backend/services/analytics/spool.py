"""Analytics spool storage."""

import json
from dataclasses import asdict
from pathlib import Path

from backend.services.analytics.event_models import AnalyticsEvent


class LocalAnalyticsSpool:
    """Simple JSONL local spool for critical analytics events."""

    def __init__(self, path: str | Path = "/tmp/gpu-inference-analytics-spool.jsonl") -> None:
        self.path = Path(path)

    async def write(self, event: AnalyticsEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), default=str, sort_keys=True) + "\n")
