from __future__ import annotations

import random
from datetime import timedelta

from tg_relay.application.stats_collector import ERRORS_CAPACITY, StatsCollector
from tg_relay.domain.models import Rejection

from ..support.fakes import T0, FrozenClock, outcome


def make() -> StatsCollector:
    return StatsCollector(FrozenClock(), rng=random.Random(0))


def test_hourly_totals_and_percentiles() -> None:
    stats = make()
    for ms in range(1, 101):
        stats.on_request_finished(outcome(duration_ms=float(ms)))
    stats.on_request_finished(outcome(status=500, duration_ms=1.0))

    [row] = stats.drain_hourly()
    assert row.requests == 101
    assert row.errors == 1
    assert row.hour == T0.replace(minute=0)
    assert 45 <= row.p50_ms <= 55
    assert 90 <= row.p95_ms <= 100


def test_long_poll_is_excluded_from_latency() -> None:
    stats = make()
    stats.on_request_finished(outcome(method="getUpdates", is_long_poll=True, duration_ms=50_000))
    [row] = stats.drain_hourly()
    assert row.requests == 1
    assert row.sum_ms == 0
    assert row.p95_ms == 0


def test_error_journal_uses_rejection_detail() -> None:
    stats = make()
    stats.on_request_finished(
        outcome(status=402, rejection=Rejection("quota", "tariff limit exceeded (bots)"))
    )
    stats.on_request_finished(outcome(status=400))
    messages = [e.message for e in stats.drain_errors()]
    assert messages == ["tariff limit exceeded (bots)", "upstream 400"]


def test_error_journal_is_bounded() -> None:
    stats = make()
    for _ in range(ERRORS_CAPACITY + 50):
        stats.on_request_finished(outcome(status=500))
    assert len(stats.drain_errors()) == ERRORS_CAPACITY


def test_restore_errors_respects_capacity_and_order() -> None:
    stats = make()
    stats.on_request_finished(outcome(status=500, method="old"))
    failed = stats.drain_errors()
    stats.on_request_finished(outcome(status=500, method="new"))
    stats.restore_errors(failed)
    assert [e.method for e in stats.drain_errors()] == ["old", "new"]


def test_last_request_keeps_newest_on_restore() -> None:
    stats = make()
    stats.on_request_finished(outcome(method="first"))
    failed = stats.drain_last_requests()
    stats.on_request_finished(outcome(method="second", finished_at=T0 + timedelta(seconds=1)))
    stats.restore_last_requests(failed)
    [last] = stats.drain_last_requests()
    assert last.method == "second"


def test_unauthorized_requests_are_ignored() -> None:
    stats = make()
    stats.on_request_finished(outcome(project_id=None, status=401))
    assert stats.drain_hourly() == []
    assert stats.drain_errors() == []


def test_samples_of_past_hours_are_forgotten() -> None:
    clock = FrozenClock()
    stats = StatsCollector(clock)
    stats.on_request_finished(outcome(duration_ms=10.0))
    clock.now = T0 + timedelta(hours=1)
    stats.drain_hourly()
    stats.on_request_finished(outcome(duration_ms=10.0))
    # Выборка прошлого часа выброшена: у нового часа своя.
    assert len(stats._samples) == 1
