"""轻量级内存限流（单进程）；多副本部署时建议切换 Redis 实现。

注意：字典里的 key 必须能被回收。公网环境下攻击者可以用大量不同 IP 制造
无限多的 key，如果只清理 bucket 不清理 key，进程内存会单调增长。这里每
``SWEEP_EVERY`` 次调用做一次有上限的清扫，把已经过期且不再活跃的 key 删掉。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.config import settings


class SlidingWindowLimiter:
    # 每 N 次 allow 调用触发一次清扫，摊销成本可忽略。
    SWEEP_EVERY = 1000
    # 单次清扫最多处理的 key 数量，避免大字典一次性遍历造成请求抖动。
    MAX_SWEEP = 500

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._ops = 0

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        self._ops += 1
        if self._ops >= self.SWEEP_EVERY:
            self._ops = 0
            self._sweep(now)

        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window - (now - bucket[0])) + 1
            return False, max(1, retry_after)
        bucket.append(now)
        return True, 0

    def _sweep(self, now: float) -> None:
        """回收已过期的 key；单次最多处理 MAX_SWEEP 个，剩余留到下次。"""
        removed = 0
        for key in list(self._hits):
            bucket = self._hits.get(key)
            if not bucket or now - bucket[-1] > self.window:
                self._hits.pop(key, None)
                removed += 1
                if removed >= self.MAX_SWEEP:
                    break

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter(limit=10, window_seconds=300)
# api_limiter 的阈值来自 RATE_LIMIT_PER_MINUTE（此前该环境变量从未被读取，
# 配置了也不生效）。下限收紧到 60，避免误配成 0 直接锁死整个后台。
api_limiter = SlidingWindowLimiter(limit=max(60, settings.rate_limit_per_minute), window_seconds=60)
# 兼容旧版根路径回调 /webhook：该路径不在 /api 前缀下，需要独立限流。
legacy_webhook_limiter = SlidingWindowLimiter(limit=120, window_seconds=60)
