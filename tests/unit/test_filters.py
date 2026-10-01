from __future__ import annotations

from datetime import timedelta

import pytest

from tg_relay.application.active_bots import ActiveBots
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
    @staticmethod
    def make(ledger: UsageLedger | None = None) -> tuple[QuotaFilter, ActiveBots, FrozenClock]:
        clock = FrozenClock()
        bots = ActiveBots(timedelta(minutes=5), clock)
        return QuotaFilter(ledger or UsageLedger(), bots, clock), bots, clock

    async def test_traffic_limit(self) -> None:
        ledger = UsageLedger()
        ledger.on_request_finished(outcome(bytes_in=1000, bytes_out=0))
        quota, _, _ = self.make(ledger)
        with pytest.raises(QuotaExceeded, match="traffic"):
            await quota(make_ctx(project=access(monthly_bytes=1000)))

    async def test_working_bot_keeps_its_place(self) -> None:
        quota, _, _ = self.make()
        project = access(active_bots=1)
        await quota(make_ctx(project=project, fingerprint="bot_a"))
        await quota(make_ctx(project=project, fingerprint="bot_a"))

    async def test_new_bot_over_limit_is_rejected(self) -> None:
        quota, _, _ = self.make()
        project = access(active_bots=1)
        await quota(make_ctx(project=project, fingerprint="bot_a"))
        with pytest.raises(QuotaExceeded, match="bots"):
            await quota(make_ctx(project=project, fingerprint="bot_b"))

    async def test_rejected_bot_stays_rejected(self) -> None:
        """Регрессия: второй запрос отклонённого бота не должен проходить."""
        quota, _, _ = self.make()
        project = access(active_bots=1)
        await quota(make_ctx(project=project, fingerprint="bot_a"))
        for _ in range(3):
            with pytest.raises(QuotaExceeded):
                await quota(make_ctx(project=project, fingerprint="bot_b"))

    async def test_silent_bot_frees_its_place(self) -> None:
        """Выключили одного бота, включили другого — это по-прежнему один бот."""
        quota, _, clock = self.make()
        project = access(active_bots=1)
        await quota(make_ctx(project=project, fingerprint="bot_a"))
        clock.now += timedelta(minutes=6)
        await quota(make_ctx(project=project, fingerprint="bot_b"))

    async def test_bot_is_counted_from_its_first_request(self) -> None:
        """Место занимается сразу, ещё до ответа upstream (первый запрос — long poll)."""
        quota, bots, _ = self.make()
        await quota(make_ctx(project=access(active_bots=2), fingerprint="bot_a"))
        assert bots.is_active(1, "bot_a")

    async def test_zero_means_unlimited(self) -> None:
        ledger = UsageLedger()
        ledger.on_request_finished(outcome(bytes_in=10**12))
        quota, _, _ = self.make(ledger)
        for n in range(50):
            await quota(make_ctx(project=access(), fingerprint=f"bot_{n}"))

    async def test_requests_without_token_are_not_bots(self) -> None:
        quota, bots, _ = self.make()
        await quota(make_ctx(project=access(active_bots=1), fingerprint=None))
        assert bots.count(1) == 0

    async def test_requires_auth_before_it(self) -> None:
        quota, _, _ = self.make()
        with pytest.raises(RuntimeError):
            await quota(make_ctx())


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
