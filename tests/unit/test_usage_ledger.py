from __future__ import annotations

from datetime import date

from tg_relay.application.usage_ledger import UsageLedger
from tg_relay.domain.errors import QuotaExceeded, RateLimited
from tg_relay.domain.models import Rejection
from tg_relay.ports.usage import MonthUsage

from ..support.fakes import outcome

SEPTEMBER = date(2026, 9, 1)


def test_records_traffic_and_bots() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(bytes_in=100, bytes_out=50))
    ledger.on_request_finished(outcome(bytes_in=1, bytes_out=2))

    assert ledger.bytes_used(1, SEPTEMBER) == 153

    batch = ledger.drain()
    assert len(batch.counters) == 1
    delta = batch.counters[0]
    assert (delta.requests, delta.bytes_in, delta.bytes_out) == (2, 101, 52)
    assert [b.fingerprint for b in batch.bots] == ["fp0000000001"]


def test_bot_is_reported_in_every_batch_it_worked_in() -> None:
    """Каждая пачка обновляет в хранилище момент последней активности бота."""
    ledger = UsageLedger()
    ledger.on_request_finished(outcome())
    assert len(ledger.drain().bots) == 1
    ledger.on_request_finished(outcome())
    assert len(ledger.drain().bots) == 1


def test_bot_rejected_by_quota_is_not_a_project_bot() -> None:
    """Регрессия: отказ по лимиту не должен записывать бота в работающие."""
    ledger = UsageLedger()
    rejection = Rejection(QuotaExceeded.reason, "tariff limit exceeded (bots)")
    ledger.on_request_finished(outcome(status=402, bytes_in=0, bytes_out=0, rejection=rejection))

    batch = ledger.drain()
    assert batch.bots == ()
    assert batch.counters[0].requests == 1  # сам запрос при этом учтён


def test_other_rejections_still_count_the_bot() -> None:
    ledger = UsageLedger()
    rejection = Rejection(RateLimited.reason, "rate limited")
    ledger.on_request_finished(outcome(status=429, rejection=rejection))
    assert len(ledger.drain().bots) == 1


def test_unauthorized_requests_are_not_billed() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(project_id=None))
    assert not ledger.drain()


def test_drain_resets_pending_but_keeps_month_traffic() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(bytes_in=10, bytes_out=0))
    ledger.drain()
    assert not ledger.drain()
    assert ledger.bytes_used(1, SEPTEMBER) == 10


def test_restore_returns_batch_for_next_flush() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(bytes_in=10, bytes_out=0))
    batch = ledger.drain()
    ledger.on_request_finished(outcome(bytes_in=5, bytes_out=0))
    ledger.restore(batch)

    merged = ledger.drain()
    assert merged.counters[0].bytes_in == 15
    assert merged.counters[0].requests == 2
    assert len(merged.bots) == 1


def test_sync_never_lowers_local_traffic() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(bytes_in=500, bytes_out=0))
    ledger.sync(MonthUsage(SEPTEMBER, {1: 100}))
    assert ledger.bytes_used(1, SEPTEMBER) == 500


def test_sync_picks_up_other_nodes_traffic() -> None:
    ledger = UsageLedger()
    ledger.sync(MonthUsage(SEPTEMBER, {1: 10_000}))
    assert ledger.bytes_used(1, SEPTEMBER) == 10_000


def test_sync_drops_previous_months() -> None:
    ledger = UsageLedger()
    ledger.sync(MonthUsage(date(2026, 8, 1), {1: 999}))
    ledger.sync(MonthUsage(SEPTEMBER, {}))
    assert ledger.bytes_used(1, date(2026, 8, 1)) == 0
