"""Фоновые задачи: синхронизация памяти узла с хранилищем.

Каждая задача устойчива к сбоям хранилища: при ошибке данные остаются в
памяти и уходят при следующей попытке. Разные виды данных сбрасываются
независимо, чтобы сбой одного не приводил к повторной записи другого.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from ..domain.models import billing_month
from ..ports.keys import KeySource
from ..ports.stats import StatsRepository
from ..ports.usage import UsageRepository
from .active_bots import ActiveBots
from .key_registry import KeyRegistry
from .rate_limiter import RateLimiter
from .stats_collector import StatsCollector
from .usage_ledger import UsageLedger

log = logging.getLogger("tg_relay.workers")

Action = Callable[[], Awaitable[None]]

#: Через сколько секунд простоя бакет rate limit можно забыть.
RATE_BUCKET_IDLE_SECONDS = 600.0


class KeySync:
    """Перечитывает из хранилища ключи и данные для лимитов: трафик месяца и
    активность ботов (в том числе на других узлах и до рестарта этого)."""

    def __init__(
        self,
        *,
        source: KeySource,
        registry: KeyRegistry,
        usage: UsageRepository | None = None,
        ledger: UsageLedger | None = None,
        active_bots: ActiveBots | None = None,
        limiter: RateLimiter | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._registry = registry
        self._usage = usage
        self._ledger = ledger
        self._active_bots = active_bots
        self._limiter = limiter
        self._clock = clock

    async def run(self) -> None:
        try:
            self._registry.replace(await self._source.load_all())
        except Exception:
            self._registry.mark_stale()
            log.warning("key refresh failed; serving the last known keys", exc_info=True)

        if self._usage is not None and self._ledger is not None:
            try:
                self._ledger.sync(await self._usage.load_month(billing_month(self._clock())))
            except Exception:
                log.warning("month usage refresh failed", exc_info=True)

        if self._active_bots is not None:
            if self._usage is not None:
                try:
                    since = self._active_bots.since()
                    self._active_bots.merge(await self._usage.load_bot_activity(since))
                except Exception:
                    log.warning("bot activity refresh failed", exc_info=True)
            self._active_bots.prune()

        if self._limiter is not None:
            self._limiter.prune(RATE_BUCKET_IDLE_SECONDS)


class UsageFlush:
    def __init__(self, ledger: UsageLedger, repository: UsageRepository) -> None:
        self._ledger = ledger
        self._repository = repository

    async def run(self) -> None:
        batch = self._ledger.drain()
        if not batch:
            return
        try:
            await self._repository.save(batch)
        except Exception:
            self._ledger.restore(batch)
            log.warning("usage flush failed; keeping counters in memory", exc_info=True)


class StatsFlush:
    def __init__(self, collector: StatsCollector, repository: StatsRepository) -> None:
        self._collector = collector
        self._repository = repository

    async def run(self) -> None:
        """Полный сброс: почасовые агрегаты, журнал ошибок, последний запрос."""
        hourly = self._collector.drain_hourly()
        if hourly:
            try:
                await self._repository.save_hourly(hourly)
            except Exception:
                self._collector.restore_hourly(hourly)
                log.warning("hourly stats flush failed", exc_info=True)

        errors = self._collector.drain_errors()
        if errors:
            try:
                await self._repository.save_errors(errors)
            except Exception:
                self._collector.restore_errors(errors)
                log.warning("error journal flush failed", exc_info=True)

        await self.run_last_requests()

    async def run_last_requests(self) -> None:
        """Быстрый сброс «последнего запроса» — для живого индикатора подключения."""
        last = self._collector.drain_last_requests()
        if not last:
            return
        try:
            await self._repository.save_last_requests(last)
        except Exception:
            self._collector.restore_last_requests(last)
            log.debug("last request flush failed", exc_info=True)


class PeriodicTask:
    """Запускает действие раз в ``interval`` секунд, переживая любые его сбои."""

    def __init__(self, name: str, interval: float, action: Action) -> None:
        if interval <= 0:
            raise ValueError("interval должен быть положительным")
        self.name = name
        self._interval = interval
        self._action = action
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name=self.name)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._action()
            except Exception:
                log.exception("periodic task failed", extra={"task": self.name})
