"""Per-customer sliding-window rate limit for the WhatsApp webhook (CLAUDE.md §69).

Every inbound message costs an LLM call and the number is public, so one sender must not be able to burn the
Groq quota. In-memory and per-process: right-sized for v0.1 (single uvicorn worker, CLAUDE.md §49 says no Redis
until needed). With several workers each one enforces its own window; move to a shared store then.

Decision per message:
    ALLOW   process normally
    NOTIFY  first message over the limit in this window: send ONE short "slow down" reply, no LLM call
    DROP    further messages over the limit: ignore silently (never reply-loop)
"""
import time
from collections import deque
from collections.abc import Callable
from enum import Enum
from functools import lru_cache


class Decision(Enum):
    ALLOW = "allow"
    NOTIFY = "notify"
    DROP = "drop"


RATE_LIMIT_REPLY = "You're sending messages very quickly. Please wait a minute and try again."


class RateLimiter:
    def __init__(
        self,
        max_messages: int = 10,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_keys: int = 10_000,
    ) -> None:
        self._max = max_messages
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_tracked_keys
        self._hits: dict[str, deque[float]] = {}
        self._notified: dict[str, float] = {}  # key -> time of last "slow down" reply

    def check(self, key: str) -> Decision:
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()

        if len(hits) < self._max:
            hits.append(now)
            self._notified.pop(key, None)
            self._evict_if_needed(now)
            return Decision.ALLOW

        # Over the limit: rejected messages are not counted, so the window frees up on schedule.
        last = self._notified.get(key)
        if last is None or now - last >= self._window:
            self._notified[key] = now
            return Decision.NOTIFY
        return Decision.DROP

    def _evict_if_needed(self, now: float) -> None:
        """Bound memory: drop idle keys once too many are tracked."""
        if len(self._hits) <= self._max_keys:
            return
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self._window]:
            del self._hits[key]
            self._notified.pop(key, None)


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter()
