"""Модели запроса и ответа на границе прикладного слоя.

Они не зависят от HTTP-фреймворка: HTTP-адаптер переводит в них ASGI-запрос
и обратно, а сервис проксирования работает только с ними.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..domain.models import BotApiTarget, ProjectAccess, ProjectId
from ..ports.upstream import Header


@dataclass(frozen=True, slots=True)
class IncomingRequest:
    """Запрос клиента к шлюзу: ``/k/<key>/<raw_path>?<raw_query>``."""

    method: str
    key: str
    #: Путь после ключа проекта в исходном (percent-encoded) виде.
    raw_path: str
    raw_query: str
    headers: Sequence[Header]
    body: AsyncIterator[bytes]

    @property
    def content_length(self) -> int | None:
        for name, value in self.headers:
            if name.lower() == "content-length":
                return int(value) if value.isdigit() else None
        return None


@dataclass(slots=True)
class RequestContext:
    """Изменяемое состояние запроса по ходу обработки."""

    request: IncomingRequest
    target: BotApiTarget
    fingerprint: str | None
    started_at: float
    #: Тело запроса. Фильтры могут обернуть его (например, ограничить размер).
    body: AsyncIterator[bytes]
    #: Заполняется фильтром авторизации.
    access: ProjectAccess | None = None
    bytes_in: int = 0
    bytes_out: int = 0

    @property
    def project_id(self) -> ProjectId | None:
        return self.access.project_id if self.access else None

    def require_access(self) -> ProjectAccess:
        if self.access is None:
            raise RuntimeError("фильтр требует авторизованный запрос — поставьте его после auth")
        return self.access


class ResponseBody(Protocol):
    """Тело ответа: итерируется один раз; ``aclose`` идемпотентен и безопасен
    даже если итерация не начиналась."""

    def __aiter__(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


class BufferedBody:
    """Тело, целиком лежащее в памяти (ответы самого шлюза)."""

    __slots__ = ("_content",)

    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._content

    async def aclose(self) -> None:
        pass


@dataclass(frozen=True, slots=True)
class OutgoingResponse:
    status: int
    headers: Sequence[Header]
    body: ResponseBody
