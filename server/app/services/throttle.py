"""Two-lane rate limiting for free-tier LLM quotas (PRD section 11).

User-facing tutor turns run in the `interactive` lane; background work
(question-pool pre-generation, embeddings) runs in `background` so a burst of
batch work can never starve a live tutoring session.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict

from app.config import settings


class RateLimiter:
    """Simple async token bucket: `rpm` requests per rolling minute."""

    def __init__(self, rpm: int, name: str = "") -> None:
        self.rpm = max(1, rpm)
        self.name = name
        self._interval = 60.0 / self.rpm
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> float:
        """Block until a slot is free. Returns the seconds waited."""
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
            wait = slot - now
        if wait > 0:
            await asyncio.sleep(wait)
        return max(0.0, wait)


_lanes: Dict[str, RateLimiter] = {
    "interactive": RateLimiter(settings.llm_interactive_rpm, "interactive"),
    "background": RateLimiter(settings.llm_background_rpm, "background"),
}


def lane(name: str) -> RateLimiter:
    return _lanes.get(name, _lanes["interactive"])
