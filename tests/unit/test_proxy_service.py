"""Сервис проксирования без сети: fake upstream + in-memory наблюдатель."""

from __future__ import annotations

import json

import pytest

from tg_relay.application.context import IncomingRequest, OutgoingResponse
from tg_relay.application.filters import AuthFilter, BodyLimitFilter, FilterChain
from tg_relay.application.key_registry import KeyRegistry
from tg_relay.application.proxy import ProxyService
from tg_relay.domain.credentials import token_fingerprint
from tg_relay.domain.errors import BadGateway
from tg_relay.domain.models import RequestOutcome

from ..support.fakes import (
    FakeUpstream,
    FakeUpstreamResponse,
    FrozenClock,
    ManualTimer,
    RecordingObserver,
    access,
    body_of,
)

TOKEN = "123:secret"


def make_service(
    upstream: FakeUpstream, observer: RecordingObserver, *, max_body: int = 1024
) -> ProxyService:
    registry = KeyRegistry()
    record = access(5, key="good")
    registry.replace({record.key_hash: record})
    return ProxyService(
        filters=FilterChain([AuthFilter(registry), BodyLimitFilter(max_body)]),
        upstream=upstream,
        observers=[observer],
        clock=FrozenClock(),
        timer=ManualTimer(),
    )


def request(
    key: str = "good", path: str = f"bot{TOKEN}/sendMessage", *chunks: bytes
) -> IncomingRequest:
    return IncomingRequest(
        method="POST",
        key=key,
        raw_path=path,
        raw_query="a=1&a=2",
        headers=[("Connection", "keep-alive"), ("X-Custom", "v")],
        body=body_of(*chunks),
    )


async def read(response: OutgoingResponse) -> bytes:
    return b"".join([chunk async for chunk in response.body])


async def test_request_is_forwarded_verbatim() -> None:
    upstream, observer = FakeUpstream(), RecordingObserver()
    response = await make_service(upstream, observer).handle(
        request("good", f"bot{TOKEN}/send%20It", b"hi")
    )
    await read(response)

    [sent] = upstream.requests
    assert sent.raw_path == f"bot{TOKEN}/send%20It"  # без перекодирования
    assert sent.raw_query == "a=1&a=2"
    assert list(sent.headers) == [("X-Custom", "v")]  # hop-by-hop срезан
    assert upstream.bodies == [b"hi"]


async def test_outcome_is_recorded_once_after_body_is_sent() -> None:
    upstream = FakeUpstream(FakeUpstreamResponse(chunks=(b"ab", b"cde")))
    observer = RecordingObserver()
    response = await make_service(upstream, observer).handle(
        request("good", f"bot{TOKEN}/getMe", b"xyz")
    )
    assert observer.outcomes == []  # тело ещё не отдано

    assert await read(response) == b"abcde"
    await response.body.aclose()  # повторное закрытие безопасно

    [outcome] = observer.outcomes
    assert (outcome.project_id, outcome.status) == (5, 200)
    assert (outcome.bytes_in, outcome.bytes_out) == (3, 5)
    assert outcome.fingerprint == token_fingerprint(TOKEN)
    assert outcome.method == "getMe"
    assert upstream.response.closed


async def test_body_closed_without_iteration_is_still_accounted() -> None:
    """Клиент отключился до начала тела: upstream закрыт, запрос учтён."""
    upstream, observer = FakeUpstream(), RecordingObserver()
    response = await make_service(upstream, observer).handle(request())
    await response.body.aclose()
    assert upstream.response.closed
    assert len(observer.outcomes) == 1


async def test_unknown_key_gets_telegram_error_and_skips_upstream() -> None:
    upstream, observer = FakeUpstream(), RecordingObserver()
    response = await make_service(upstream, observer).handle(request(key="bad"))

    assert response.status == 401
    assert json.loads(await read(response)) == {
        "ok": False,
        "error_code": 401,
        "description": "Unauthorized",
    }
    assert upstream.requests == []
    [outcome] = observer.outcomes
    assert outcome.project_id is None
    assert outcome.rejection is not None
    assert outcome.rejection.reason == "unauthorized"


async def test_upstream_failure_becomes_502() -> None:
    upstream, observer = FakeUpstream(), RecordingObserver()
    upstream.error = BadGateway("upstream unreachable")
    response = await make_service(upstream, observer).handle(request())
    assert response.status == 502
    assert observer.outcomes[0].rejection is not None


async def test_streamed_body_over_limit_becomes_413() -> None:
    upstream, observer = FakeUpstream(), RecordingObserver()
    service = make_service(upstream, observer, max_body=4)
    response = await service.handle(request("good", f"bot{TOKEN}/sendDocument", b"abc", b"def"))
    assert response.status == 413
    assert observer.outcomes[0].status == 413


async def test_unexpected_error_is_contained() -> None:
    upstream, observer = FakeUpstream(), RecordingObserver()
    upstream.error = ZeroDivisionError()
    response = await make_service(upstream, observer).handle(request())
    assert response.status == 500
    assert json.loads(await read(response))["ok"] is False
    assert observer.started == len(observer.outcomes) == 1


async def test_failing_observer_does_not_break_the_response() -> None:
    class Broken(RecordingObserver):
        def on_request_finished(self, outcome: RequestOutcome) -> None:
            raise RuntimeError("boom")

    upstream = FakeUpstream()
    response = await make_service(upstream, Broken()).handle(request())
    assert await read(response) == b'{"ok":true}'


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_upstream_errors_pass_through_unchanged(status: int) -> None:
    body = b'{"ok":false,"error_code":%d}' % status
    upstream = FakeUpstream(FakeUpstreamResponse(status=status, chunks=(body,)))
    observer = RecordingObserver()
    response = await make_service(upstream, observer).handle(request())
    assert response.status == status
    assert await read(response) == body
    assert observer.outcomes[0].rejection is None  # это ответ Telegram, не шлюза
