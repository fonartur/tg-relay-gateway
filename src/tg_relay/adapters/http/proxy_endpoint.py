"""Перевод HTTP-запроса в :class:`IncomingRequest` и ответа сервиса — обратно."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from ...application.context import IncomingRequest, OutgoingResponse
from ...application.proxy import ProxyService


class ProxyEndpoint:
    """Эндпоинт ``/k/{key}/{path}``.

    Работает с ``raw_path`` из ASGI-scope, а не с декодированным путём
    Starlette, чтобы не перекодировать путь и не нарушить прозрачность.
    """

    def __init__(self, service: ProxyService, prefix: str) -> None:
        self._service = service
        self._prefix = prefix

    async def handle(self, request: Request) -> StreamingResponse:
        key, raw_path = split_proxy_path(_raw_path(request.scope), self._prefix)
        outgoing = await self._service.handle(
            IncomingRequest(
                method=request.method,
                key=key,
                raw_path=raw_path,
                raw_query=request.scope.get("query_string", b"").decode("latin-1"),
                headers=[
                    (name.decode("latin-1"), value.decode("latin-1"))
                    for name, value in request.headers.raw
                ],
                body=request.stream(),
            )
        )
        return RelayResponse(outgoing)


class RelayResponse(StreamingResponse):
    """Потоковый ответ, сохраняющий порядок и дубликаты заголовков upstream.

    ``aclose`` тела вызывается в любом случае — даже если клиент отключился
    до начала передачи, — чтобы соединение с upstream вернулось в пул,
    а запрос был учтён.
    """

    def __init__(self, outgoing: OutgoingResponse) -> None:
        super().__init__(outgoing.body, status_code=outgoing.status)
        self.raw_headers = [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in outgoing.headers
        ]
        self._outgoing = outgoing

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._outgoing.body.aclose()


def split_proxy_path(path: str, prefix: str) -> tuple[str, str]:
    """``/k/<key>/<rest>`` -> ``(key, rest)``, ``rest`` в исходном кодировании."""
    after_prefix = path[len(prefix) :] if path.startswith(prefix) else path.lstrip("/")
    key, _, rest = after_prefix.partition("/")
    return key, rest


def _raw_path(scope: Scope) -> str:
    raw: bytes | None = scope.get("raw_path")
    if not raw:
        return str(scope["path"])  # сервер не передал raw_path — берём декодированный
    # Некоторые ASGI-серверы кладут в raw_path и query-строку.
    return raw.decode("latin-1").split("?", 1)[0]
