"""Project adapter over the shared rate-limit engine.

The engine (`rate_limit_engine.py`) is vendored unmodified from
`DOCS/shared/rate-limit/engine/fastapi/`. This adapter only supplies Squirrel's
slug and one bucket per AI action; the engine handles X-Forwarded-For, central
config, event mode, the kill switch (503) and fail-open.
"""

from fastapi import Request

from app.config import settings
from app.rate_limit_engine import RateLimiter

limiter = RateLimiter(
    # Slug = full project folder name (matches the central rate-limit sheet rows).
    project="ail-ay2627-s1-clayton-squirrel",
    buckets={
        "extract": settings.rate_limit_extract_max,
        "digest": settings.rate_limit_digest_max,
        "ask": settings.rate_limit_ask_max,
    },
    redis_url=settings.redis_url,
    redis_token=settings.redis_token,
    default_window=settings.rate_limit_window_seconds,
)


def check_rate_limit(request: Request, bucket: str) -> None:
    limiter.enforce(request, bucket)
