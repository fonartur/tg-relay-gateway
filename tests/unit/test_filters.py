from __future__ import annotations

import pytest

from tg_relay.application.context import IncomingRequest, RequestContext
from tg_relay.application.filters import (
    AuthFilter,
    BodyLimitFilter,
    QuotaFilter,
    RateLimitFilter,
)
from tg_relay.application.key_registry import KeyRegistry
from tg_relay.application.rate_limiter import RateLimiter
from tg_relay.application.usage_ledger import UsageLedger
from tg_relay.domain.botapi import parse_target
from tg_relay.domain.errors import PayloadTooLarge, QuotaExceeded, RateLimited, Unauthorized
from tg_relay.domain.models import ProjectAccess

from ..support.fakes import FrozenClock, ManualTimer, access, body_of, outcome


def make_ctx(
    *,
    key: str = "k",
    project: ProjectAccess | None = None,
    fingerprint: str | None = "fp0000000001",
    headers: list[tuple[str, str]] | None = None,
    body: tuple[bytes, ...] = (),
) -> RequestContext:
    stream = body_of(*body)
    return RequestContext(
        request=IncomingRequest("POST", key, "botT/sendMessage", "", headers or [], stream),
        target=parse_target("botT/sendMessage"),
        fingerprint=fingerprint,
        started_at=0.0,
        body=stream,
        access=project,
    )


class TestAuth:
    async def test_known_key_sets_access(self) -> None:
        registry = KeyRegistry()
        record = access(3, key="good")
        registry.replace({record.key_hash: record})
        ctx = make_ctx(key="good")
        await AuthFilter(registry)(ctx)
        assert ctx.project_id == 3

    async def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(Unauthorized):
            await AuthFilter(KeyRegistry())(make_ctx(key="bad"))


class TestQuota:
    async def test_traffic_limit(self) -> None:
        ledger = UsageLedger()
        ledger.on_request_finished(outcome(bytes_in=1000, bytes_out=0))
        quota = QuotaFilter(ledger, FrozenClock())
        with pytest.raises(QuotaExceeded, match="traffic"):
            await quota(make_ctx(project=access(monthly_bytes=1000)))

    async def test_known_bot_passes_even_at_bot_limit(self) -> None:
        ledger = UsageLedger()
        ledger.on_request_finished(outcome(fingerprint="fp0000000001"))
        await QuotaFilter(ledger, FrozenClock())(
            make_ctx(project=access(monthly_bots=1), fingerprint="fp0000000001")
        )

    async def test_new_bot_over_limit_is_rejected(self) -> None:
        ledger = UsageLedger()
        ledger.on_request_finished(outcome(fingerprint="fp0000000001"))
        with pytest.raises(QuotaExceeded, match="bots"):
            await QuotaFilter(ledger, FrozenClock())(
                make_ctx(project=access(monthly_bots=1), fingerprint="fp0000000002")
            )

    async def test_zero_means_unlimited(self) -> None:
        ledger = UsageLedger()
        ledger.on_request_finished(outcome(bytes_in=10**12))
        await QuotaFilter(ledger, FrozenClock())(make_ctx(project=access()))

    async def test_requires_auth_before_it(self) -> None:
        with pytest.raises(RuntimeError):
            await QuotaFilter(UsageLedger(), FrozenClock())(make_ctx())


class TestRateLimit:
    async def test_rejects_with_rounded_up_retry_after(self) -> None:
        limiter = RateLimiter(clock=ManualTimer())
        rate_limit = RateLimitFilter(limiter)
        project = access(rate_per_second=1)
        await rate_limit(make_ctx(project=project))
        with pytest.raises(RateLimited) as caught:
            await rate_limit(make_ctx(project=project))
        assert caught.value.retry_after == 1


class TestBodyLimit:
    async def test_declared_length_over_limit(self) -> None:
        with pytest.raises(PayloadTooLarge):
            await BodyLimitFilter(10)(make_ctx(headers=[("Content-Length", "11")]))

    async def test_streamed_body_over_limit(self) -> None:
        ctx = make_ctx(body=(b"x" * 6, b"x" * 6))
        await BodyLimitFilter(10)(ctx)  # заявленной длины нет — пропускаем
        with pytest.raises(PayloadTooLarge):
            async for _ in ctx.body:
                pass

    async def test_body_within_limit_passes_untouched(self) -> None:
        ctx = make_ctx(body=(b"abc", b"def"))
        await BodyLimitFilter(10)(ctx)
        assert b"".join([c async for c in ctx.body]) == b"abcdef"
