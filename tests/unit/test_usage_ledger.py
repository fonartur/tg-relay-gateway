from __future__ import annotations

from datetime import date

from tg_relay.application.usage_ledger import UsageLedger
from tg_relay.ports.usage import MonthUsage

from ..support.fakes import outcome

SEPTEMBER = date(2026, 9, 1)


def test_records_traffic_and_new_bots() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(bytes_in=100, bytes_out=50))
    ledger.on_request_finished(outcome(bytes_in=1, bytes_out=2))

    assert ledger.bytes_used(1, SEPTEMBER) == 153
    assert ledger.bots_used(1, SEPTEMBER) == 1

    batch = ledger.drain()
    assert len(batch.counters) == 1
    delta = batch.counters[0]
    assert (delta.requests, delta.bytes_in, delta.bytes_out) == (2, 101, 52)
    assert [b.fingerprint for b in batch.bots] == ["fp0000000001"]


def test_unauthorized_requests_are_not_billed() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(project_id=None))
    assert not ledger.drain()


def test_drain_resets_pending_but_keeps_month_totals() -> None:
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


def test_sync_never_lowers_local_totals() -> None:
    ledger = UsageLedger()
    ledger.on_request_finished(outcome(bytes_in=500, bytes_out=0))
    ledger.sync(MonthUsage(SEPTEMBER, {1: 100}, {1: frozenset({"other"})}))

    assert ledger.bytes_used(1, SEPTEMBER) == 500
    assert ledger.bots_used(1, SEPTEMBER) == 2  # локальный + пришедший из базы


def test_sync_picks_up_other_nodes_usage() -> None:
    ledger = UsageLedger()
    ledger.sync(MonthUsage(SEPTEMBER, {1: 10_000}, {}))
    assert ledger.bytes_used(1, SEPTEMBER) == 10_000


def test_sync_drops_previous_months() -> None:
    ledger = UsageLedger()
    ledger.sync(MonthUsage(date(2026, 8, 1), {1: 999}, {1: frozenset({"a"})}))
    ledger.sync(MonthUsage(SEPTEMBER, {}, {}))
    assert ledger.bytes_used(1, date(2026, 8, 1)) == 0
    assert ledger.bots_used(1, date(2026, 8, 1)) == 0
