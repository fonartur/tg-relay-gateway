from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..context import RequestContext


class RequestFilter(Protocol):
    async def __call__(self, ctx: RequestContext) -> None:
        """Пропустить запрос (вернуть ``None``) или отклонить (``GatewayError``)."""
        ...


class FilterChain:
    def __init__(self, filters: Sequence[RequestFilter]) -> None:
        self._filters = tuple(filters)

    async def run(self, ctx: RequestContext) -> None:
        for request_filter in self._filters:
            await request_filter(ctx)

    def __len__(self) -> int:
        return len(self._filters)
