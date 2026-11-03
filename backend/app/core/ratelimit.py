"""轻量级内存限流（单进程）；多副本部署时建议切换 Redis 实现。"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window - (now - bucket[0])) + 1
            return False, max(1, retry_after)
        bucket.append(now)
        return True, 0

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter(limit=10, window_seconds=300)
api_limiter = SlidingWindowLimiter(limit=600, window_seconds=60)
