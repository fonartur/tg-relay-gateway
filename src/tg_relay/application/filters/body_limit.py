from __future__ import annotations

from collections.abc import AsyncIterator

from ...domain.errors import PayloadTooLarge
from ..context import RequestContext


class BodyLimitFilter:
    """Ограничение размера тела запроса.

    Два рубежа: быстрый отказ по заявленному ``Content-Length`` и контроль
    фактического объёма при потоковой передаче (chunked или ложный
    ``Content-Length``). Тело при этом не буферизуется.
    """

    def __init__(self, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes должен быть положительным")
        self._max_bytes = max_bytes

    async def __call__(self, ctx: RequestContext) -> None:
        declared = ctx.request.content_length
        if declared is not None and declared > self._max_bytes:
            raise PayloadTooLarge("request body too large")
        ctx.body = self._limited(ctx.body)

    async def _limited(self, body: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        received = 0
        async for chunk in body:
            received += len(chunk)
            if received > self._max_bytes:
                raise PayloadTooLarge("request body too large")
            yield chunk
