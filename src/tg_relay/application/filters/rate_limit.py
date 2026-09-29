from __future__ import annotations

import math

from ...domain.errors import RateLimited
from ..context import RequestContext
from ..rate_limiter import RateLimiter


class RateLimitFilter:
    """Частота запросов проекта. Отказ — 429 с ``retry_after`` в формате Telegram."""

    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def __call__(self, ctx: RequestContext) -> None:
        access = ctx.require_access()
        wait = self._limiter.acquire(access.project_id, access.limits.rate_per_second)
        if wait > 0:
            # Округляем вверх: повтор раньше срока гарантированно получит отказ.
            raise RateLimited(retry_after=math.ceil(wait))
