from __future__ import annotations

import asyncio
from datetime import date

from tg_relay.application.key_registry import KeyRegistry
from tg_relay.application.stats_collector import StatsCollector
from tg_relay.application.usage_ledger import UsageLedger
from tg_relay.application.workers import KeySync, PeriodicTask, StatsFlush, UsageFlush
from tg_relay.ports.usage import MonthUsage

from ..support.fakes import (
    FrozenClock,
    MemoryStatsRepository,
    MemoryUsageRepository,
    StaticSource,
    access,
    outcome,
)


class TestKeySync:
    async def test_loads_keys_and_month_usage(self) -> None:
        record = access()
        repo = MemoryUsageRepository(month_usage=MonthUsage(date(2026, 9, 1), {1: 42}, {}))
        registry, ledger = KeyRegistry(), UsageLedger()
        sync = KeySync(
            source=StaticSource({record.key_hash: record}),
            registry=registry,
            usage=repo,
            ledger=ledger,
            clock=FrozenClock(),
        )
        await sync.run()
        assert registry.size == 1
        assert ledger.bytes_used(1, date(2026, 9, 1)) == 42

    async def test_source_failure_keeps_last_known_keys(self) -> None:
        record = access()
        source = StaticSource({record.key_hash: record})
        registry = KeyRegistry()
        sync = KeySync(source=source, registry=registry, clock=FrozenClock())
        await sync.run()

        source.fail = True
        await sync.run()
        assert registry.size == 1
        assert registry.is_stale


class TestUsageFlush:
    async def test_saves_batch(self) -> None:
        ledger, repo = UsageLedger(), MemoryUsageRepository()
        ledger.on_request_finished(outcome())
        await UsageFlush(ledger, repo).run()
        assert len(repo.saved) == 1

    async def test_failure_keeps_counters_for_next_attempt(self) -> None:
        ledger, repo = UsageLedger(), MemoryUsageRepository(fail=True)
        ledger.on_request_finished(outcome(bytes_in=10, bytes_out=0))
        flush = UsageFlush(ledger, repo)
        await flush.run()

        repo.fail = False
        await flush.run()
        [batch] = repo.saved
        assert batch.counters[0].bytes_in == 10

    async def test_empty_ledger_does_not_touch_storage(self) -> None:
        repo = MemoryUsageRepository(fail=True)
        await UsageFlush(UsageLedger(), repo).run()  # не падает и не пишет


class TestStatsFlush:
    async def test_partial_failure_does_not_duplicate_saved_parts(self) -> None:
        """Регрессия: сбой одной части сброса не должен повторно писать остальные."""
        collector = StatsCollector(FrozenClock())
        collector.on_request_finished(outcome(status=500))
        repo = MemoryStatsRepository(fail_errors=True)
        flush = StatsFlush(collector, repo)

        await flush.run()
        assert len(repo.hourly) == 1
        assert repo.errors == []

        repo.fail_errors = False
        await flush.run()
        assert len(repo.hourly) == 1  # почасовые не записаны второй раз
        assert len(repo.errors) == 1  # а ошибки дошли со второй попытки

    async def test_last_request_is_retried(self) -> None:
        collector = StatsCollector(FrozenClock())
        collector.on_request_finished(outcome())
        repo = MemoryStatsRepository(fail_last=True)
        flush = StatsFlush(collector, repo)
        await flush.run_last_requests()
        repo.fail_last = False
        await flush.run_last_requests()
        assert len(repo.last) == 1


async def test_periodic_task_survives_failures() -> None:
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    task = PeriodicTask("flaky", 0.01, flaky)
    task.start()
    await asyncio.sleep(0.1)
    await task.stop()
    assert calls >= 2
