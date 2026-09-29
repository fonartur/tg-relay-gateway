"""Composition root: единственное место, где адаптеры связываются с ядром.

Здесь по настройкам выбирается, из чего собран узел:

* **автономный режим** (нет ``DATABASE_URL``) — ключ из окружения, без
  лимитов, учёта и статистики;
* **обычный режим** — ключи, лимиты, учёт и (опционально) статистика
  в PostgreSQL.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .adapters.observability import ErrorLogObserver, PrometheusMetrics
from .adapters.storage.postgres import (
    PostgresDatabase,
    PostgresKeySource,
    PostgresStatsRepository,
    PostgresUsageRepository,
    ProjectAdmin,
)
from .adapters.storage.static import StaticKeySource
from .adapters.upstream import HttpxUpstream, UpstreamOptions
from .application.filters import (
    AuthFilter,
    BodyLimitFilter,
    FilterChain,
    QuotaFilter,
    RateLimitFilter,
    RequestFilter,
)
from .application.key_registry import KeyRegistry
from .application.node import NodeState
from .application.proxy import ProxyService
from .application.rate_limiter import RateLimiter
from .application.stats_collector import StatsCollector
from .application.usage_ledger import UsageLedger
from .application.workers import KeySync, PeriodicTask, StatsFlush, UsageFlush
from .config import Settings
from .ports.keys import KeySource
from .ports.observer import RequestObserver

log = logging.getLogger("tg_relay")


def utc_now() -> datetime:
    return datetime.now(UTC)


class Gateway:
    """Собранный узел шлюза с жизненным циклом ``start`` / ``stop``."""

    def __init__(
        self,
        settings: Settings,
        *,
        upstream: HttpxUpstream | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings
        self.keys = KeyRegistry()
        self.node = NodeState(self.keys)
        self.metrics = PrometheusMetrics(self.keys)
        self._clock = clock
        self._upstream = upstream or HttpxUpstream(
            UpstreamOptions(
                base_url=settings.upstream_url,
                connect_timeout=settings.upstream_connect_timeout,
                read_timeout=settings.upstream_read_timeout,
                write_timeout=settings.upstream_write_timeout,
                max_connections=settings.max_connections,
                keepalive_expiry=settings.upstream_keepalive,
            )
        )

        self._database: PostgresDatabase | None = None
        self._tasks: list[PeriodicTask] = []
        self._final_flushes: list[Callable[[], Awaitable[None]]] = []

        filters: list[RequestFilter] = [AuthFilter(self.keys)]
        observers: list[RequestObserver] = [self.metrics, ErrorLogObserver()]
        key_source: KeySource

        if settings.autonomous:
            assert settings.bootstrap_key is not None  # гарантирует Settings.validate()
            key_source = StaticKeySource([settings.bootstrap_key])
            self._key_sync = KeySync(source=key_source, registry=self.keys, clock=clock)
        else:
            assert settings.database_url is not None
            self._database = PostgresDatabase(settings.database_url)
            key_source = PostgresKeySource(self._database)
            usage_repo = PostgresUsageRepository(self._database)
            ledger = UsageLedger()
            limiter = RateLimiter()
            observers.append(ledger)

            if settings.enforce_limits:
                filters += [QuotaFilter(ledger, clock), RateLimitFilter(limiter)]

            self._key_sync = KeySync(
                source=key_source,
                registry=self.keys,
                usage=usage_repo,
                ledger=ledger,
                limiter=limiter,
                clock=clock,
            )
            usage_flush = UsageFlush(ledger, usage_repo)
            self._tasks += [
                PeriodicTask("key-sync", settings.key_cache_ttl, self._key_sync.run),
                PeriodicTask("usage-flush", settings.usage_flush_interval, usage_flush.run),
            ]
            self._final_flushes.append(usage_flush.run)

            if settings.stats_enabled:
                collector = StatsCollector(clock)
                observers.append(collector)
                stats_flush = StatsFlush(collector, PostgresStatsRepository(self._database))
                self._tasks += [
                    PeriodicTask("stats-flush", settings.usage_flush_interval, stats_flush.run),
                    PeriodicTask(
                        "last-request-flush",
                        settings.last_request_flush_interval,
                        stats_flush.run_last_requests,
                    ),
                ]
                self._final_flushes.append(stats_flush.run)

        filters.append(BodyLimitFilter(settings.max_body_bytes))

        self.proxy = ProxyService(
            filters=FilterChain(filters),
            upstream=self._upstream,
            observers=observers,
            clock=clock,
        )

    async def start(self) -> None:
        if self._database is not None:
            await self._database.connect()
            applied = await self._database.migrate()
            if applied:
                log.info("migrations applied", extra={"migrations": applied})
            if self.settings.bootstrap_key:
                await ProjectAdmin(self._database).ensure_bootstrap_key(self.settings.bootstrap_key)

        await self._key_sync.run()
        for task in self._tasks:
            task.start()
        log.info(
            "gateway started",
            extra={
                "mode": "autonomous" if self.settings.autonomous else "database",
                "keys": self.keys.size,
                "limits": self.settings.enforce_limits and not self.settings.autonomous,
            },
        )

    async def stop(self) -> None:
        self.node.begin_shutdown()
        for task in self._tasks:
            await task.stop()
        for flush in self._final_flushes:
            try:
                await flush()
            except Exception:
                log.exception("final flush failed")
        if self._database is not None:
            await self._database.close()
        await self._upstream.close()
        log.info("gateway stopped")
