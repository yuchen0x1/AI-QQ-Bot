"""Generous public callback limits and bounded, aggregated signature-error samples.

These are process-local safeguards. A reverse proxy/shared limiter is still
required for a deployment-wide budget with multiple backend replicas.
"""

import time
from collections import OrderedDict

from app.core.ratelimit import SlidingWindowLimiter

webhook_limiter = SlidingWindowLimiter(limit=1200, window_seconds=60)
_signature_samples: OrderedDict[str, tuple[float, int]] = OrderedDict()
SAMPLE_SECONDS = 60.0
MAX_SAMPLE_KEYS = 2048


def allow_webhook(source: str, kind: str) -> tuple[bool, int]:
    return webhook_limiter.allow(f"{kind}:{source}")


def signature_failure_sample(target: str) -> int | None:
    """Return aggregated failure count once per target/minute, not per forged IP."""
    now = time.monotonic()
    last, count = _signature_samples.pop(target, (-SAMPLE_SECONDS, 0))
    count += 1
    if now - last >= SAMPLE_SECONDS:
        _signature_samples[target] = (now, 0)
        report = count
    else:
        _signature_samples[target] = (last, count)
        report = None
    while len(_signature_samples) > MAX_SAMPLE_KEYS:
        _signature_samples.popitem(last=False)
    return report
