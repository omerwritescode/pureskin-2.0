"""The chat's limits (7d, Unit 3), held in this process's memory (they reset on restart; the
API runs as one process).

- Per user: rolling windows from chat_config.RATE_LIMITS (10 a minute, 100 a day). A request
  over a limit is refused (429) with the seconds until one would be allowed; a refused
  request isn't counted. Keyed by user id, which is never logged.
- One generation at a time (one GPU): a slot taken just before the model is called and
  given back when its stream ends, however it ends.
"""

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from . import chat_config as cfg


class RateLimiter:
    def __init__(self, limits: tuple[tuple[int, int], ...] = cfg.RATE_LIMITS,
                 clock: Callable[[], float] = time.monotonic):
        self.limits = limits
        self.clock = clock
        self.longest = max(window for window, _ in limits)
        self._hits: dict[object, deque[float]] = {}

    def hit(self, key) -> int | None:
        """Count a request: None if it is allowed, else the whole seconds to wait (and it is
        not counted)."""
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.longest:
            hits.popleft()
        waits = []
        for window, limit in self.limits:
            recent = [t for t in hits if t > now - window]
            if len(recent) >= limit:
                waits.append(recent[-limit] + window - now)  # when the oldest of them leaves the window
        if waits:
            return max(1, math.ceil(max(waits)))
        hits.append(now)
        return None


class GenerationSlot:
    """Non-blocking: a request that finds every slot taken gets a 503, never a queue. Used from
    the event loop only (no await between the check and the take)."""

    def __init__(self, size: int = cfg.MAX_CONCURRENT_GENERATIONS):
        self.size = size
        self.in_use = 0

    def try_acquire(self) -> bool:
        if self.in_use >= self.size:
            return False
        self.in_use += 1
        return True

    def release(self) -> None:
        self.in_use = max(0, self.in_use - 1)


@dataclass
class ChatLimits:
    rate: RateLimiter = field(default_factory=RateLimiter)
    slot: GenerationSlot = field(default_factory=GenerationSlot)
