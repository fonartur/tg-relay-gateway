"""Upstream — сервер Bot API, куда шлюз проксирует запросы."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

Header = tuple[str, str]


@dataclass(frozen=True, slots=True)
class UpstreamRequest:
    method: str
    #: Путь в исходном (percent-encoded) виде — без перекодирования.
    raw_path: str
    #: Query-строка в исходном виде, без ``?``.
    raw_query: str
    headers: Sequence[Header]
    body: AsyncIterator[bytes]


class UpstreamResponse(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Sequence[Header]: ...

    def iter_raw(self) -> AsyncIterator[bytes]:
        """Тело ответа сырыми байтами: без распаковки gzip и перекодирования."""
        ...

    async def close(self) -> None: ...


class Upstream(Protocol):
    async def send(self, request: UpstreamRequest) -> UpstreamResponse:
        """Отправить запрос и вернуть ответ, не читая тело.

        Сетевые сбои адаптер обязан переводить в доменные ошибки
        :class:`~tg_relay.domain.errors.BadGateway` и
        :class:`~tg_relay.domain.errors.GatewayTimeout`.
        """
        ...
