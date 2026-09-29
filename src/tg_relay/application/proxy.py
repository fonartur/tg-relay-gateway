"""Сервис проксирования — сердце шлюза.

Главное свойство — прозрачность: любой метод, любое тело, любой код ответа
проходят насквозь байт в байт. Шлюз не знает семантику методов Telegram.

Порядок обработки::

    фильтры (авторизация, лимиты) -> upstream (потоком) -> учёт (наблюдатели)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime
from urllib.parse import unquote

from ..domain.botapi import parse_target
from ..domain.credentials import token_fingerprint
from ..domain.errors import GatewayError
from ..domain.models import Rejection, RequestOutcome
from ..ports.observer import RequestObserver
from ..ports.upstream import Upstream, UpstreamRequest, UpstreamResponse
from .context import BufferedBody, IncomingRequest, OutgoingResponse, RequestContext
from .filters import FilterChain
from .headers import end_to_end_headers

log = logging.getLogger("tg_relay.proxy")

#: Код для запросов, которые клиент бросил, не дождавшись ответа (как в nginx).
CLIENT_CLOSED_REQUEST = 499


class ProxyService:
    def __init__(
        self,
        *,
        filters: FilterChain,
        upstream: Upstream,
        observers: Sequence[RequestObserver],
        clock: Callable[[], datetime],
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._filters = filters
        self._upstream = upstream
        self._observers = tuple(observers)
        self._clock = clock
        self._timer = timer

    async def handle(self, request: IncomingRequest) -> OutgoingResponse:
        ctx = self._begin(request)
        try:
            await self._filters.run(ctx)
            upstream_response = await self._upstream.send(self._to_upstream(ctx))
        except GatewayError as error:
            self._finish(ctx, error.status, Rejection(error.reason, error.detail))
            return error_response(error)
        except asyncio.CancelledError:
            self._finish(ctx, CLIENT_CLOSED_REQUEST, Rejection("client_closed", "client closed"))
            raise
        except Exception:
            log.exception("unexpected error while proxying", extra=_log_fields(ctx))
            internal = GatewayError()
            self._finish(ctx, internal.status, Rejection(internal.reason, "internal error"))
            return error_response(internal)

        return OutgoingResponse(
            status=upstream_response.status,
            headers=end_to_end_headers(upstream_response.headers),
            body=_RelayedBody(ctx, upstream_response, on_done=self._finish),
        )

    # ------------------------------------------------------------ helpers

    def _begin(self, request: IncomingRequest) -> RequestContext:
        target = parse_target(unquote(request.raw_path))
        ctx = RequestContext(
            request=request,
            target=target,
            fingerprint=token_fingerprint(target.token) if target.token else None,
            started_at=self._timer(),
            body=request.body,
        )
        for observer in self._observers:
            observer.on_request_started()
        return ctx

    def _to_upstream(self, ctx: RequestContext) -> UpstreamRequest:
        request = ctx.request
        return UpstreamRequest(
            method=request.method,
            raw_path=request.raw_path,
            raw_query=request.raw_query,
            headers=end_to_end_headers(request.headers),
            body=self._metered(ctx, ctx.body),
        )

    @staticmethod
    async def _metered(ctx: RequestContext, body: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        async for chunk in body:
            ctx.bytes_in += len(chunk)
            yield chunk

    def _finish(self, ctx: RequestContext, status: int, rejection: Rejection | None = None) -> None:
        outcome = RequestOutcome(
            project_id=ctx.project_id,
            fingerprint=ctx.fingerprint,
            method=ctx.target.method,
            status=status,
            bytes_in=ctx.bytes_in,
            bytes_out=ctx.bytes_out,
            duration_ms=(self._timer() - ctx.started_at) * 1000,
            finished_at=self._clock(),
            is_long_poll=ctx.target.is_long_poll,
            rejection=rejection,
        )
        for observer in self._observers:
            try:
                observer.on_request_finished(outcome)
            except Exception:
                # Сбой учёта не должен ломать ответ клиенту.
                log.exception("request observer failed", extra=_log_fields(ctx))


class _RelayedBody:
    """Тело ответа upstream, отдаваемое клиенту потоком.

    Считает байты и ровно один раз — при исчерпании, обрыве или явном
    ``aclose`` — закрывает ответ upstream и фиксирует итог запроса.
    """

    __slots__ = ("_closed", "_ctx", "_on_done", "_response")

    def __init__(
        self,
        ctx: RequestContext,
        response: UpstreamResponse,
        on_done: Callable[[RequestContext, int], None],
    ) -> None:
        self._ctx = ctx
        self._response = response
        self._on_done = on_done
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._response.iter_raw():
                self._ctx.bytes_out += len(chunk)
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._response.close()
        finally:
            self._on_done(self._ctx, self._response.status)


def error_response(error: GatewayError) -> OutgoingResponse:
    """Ответ шлюза в формате Bot API."""
    body = json.dumps(error.to_payload(), separators=(",", ":")).encode()
    headers = [
        ("content-type", "application/json"),
        ("content-length", str(len(body))),
    ]
    if error.retry_after is not None:
        headers.append(("retry-after", str(error.retry_after)))
    return OutgoingResponse(status=error.status, headers=headers, body=BufferedBody(body))


def _log_fields(ctx: RequestContext) -> dict[str, object]:
    return {"project": ctx.project_id, "token_fp": ctx.fingerprint, "method": ctx.target.method}
