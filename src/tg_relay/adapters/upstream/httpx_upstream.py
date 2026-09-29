"""Upstream поверх httpx: потоковая передача в обе стороны."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx

from ...domain.errors import BadGateway, GatewayTimeout
from ...ports.upstream import Header, UpstreamRequest


@dataclass(frozen=True, slots=True)
class UpstreamOptions:
    base_url: str
    connect_timeout: float = 10.0
    #: ``None`` — без ограничения. Любое конечное значение ломает long polling.
    read_timeout: float | None = None
    write_timeout: float = 120.0
    max_connections: int = 2000
    #: Дефолт httpx — 5 с: при редких запросах бота соединение успевает закрыться,
    #: и каждый запрос платит TCP+TLS рукопожатие (~100+ мс).
    keepalive_expiry: float = 90.0


class HttpxUpstream:
    def __init__(
        self, options: UpstreamOptions, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        _silence_url_logging()
        self._base_url = options.base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=options.connect_timeout,
            read=options.read_timeout,
            write=options.write_timeout,
            pool=options.connect_timeout,
        )
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=options.max_connections,
                max_keepalive_connections=options.max_connections,
                keepalive_expiry=options.keepalive_expiry,
            ),
            # Безопасность: upstream не должен увести запрос с токеном на чужой хост.
            follow_redirects=False,
            transport=transport,
        )

    async def send(self, request: UpstreamRequest) -> _HttpxResponse:
        url = f"{self._base_url}/{request.raw_path}"
        if request.raw_query:
            url = f"{url}?{request.raw_query}"
        # Запрос собирается напрямую, а не через client.build_request: тот
        # подмешивает заголовки клиента по умолчанию (User-Agent: python-httpx,
        # Accept, Accept-Encoding) — а прозрачный шлюз шлёт только то, что
        # прислал клиент. Путь уже percent-encoded: httpx сохраняет %XX как есть.
        outgoing = httpx.Request(
            request.method,
            url,
            headers=list(request.headers),
            content=request.body,
            extensions={"timeout": self._timeout.as_dict()},
        )
        try:
            response = await self._client.send(outgoing, stream=True)
        except httpx.TimeoutException as exc:
            raise GatewayTimeout("upstream did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise BadGateway("upstream unreachable") from exc
        return _HttpxResponse(response)

    async def close(self) -> None:
        await self._client.aclose()


class _HttpxResponse:
    __slots__ = ("_response",)

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def status(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> Sequence[Header]:
        return [
            (name.decode("latin-1"), value.decode("latin-1"))
            for name, value in self._response.headers.raw
        ]

    async def iter_raw(self) -> AsyncIterator[bytes]:
        # aiter_raw: байты как есть — gzip не распаковывается.
        async for chunk in self._response.aiter_raw():
            yield chunk

    async def close(self) -> None:
        await self._response.aclose()


def _silence_url_logging() -> None:
    """httpx на INFO и httpcore на DEBUG пишут URL запроса, а в URL лежит токен
    бота. Поднимаем их порог до WARNING, даже если приложение встроено в чужую
    конфигурацию логирования."""
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        # Явный уровень, а не эффективный: иначе поздняя настройка корневого
        # логгера на DEBUG снова открыла бы утечку.
        if logger.level < logging.WARNING:  # включая NOTSET
            logger.setLevel(logging.WARNING)
