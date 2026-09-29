"""Режим с PostgreSQL. Нужен TEST_DATABASE_URL (база будет очищена!)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime

import asyncpg
import pytest

from tg_relay.adapters.storage.postgres import (
    PostgresDatabase,
    PostgresKeySource,
    PostgresStatsRepository,
    PostgresUsageRepository,
    ProjectAdmin,
)
from tg_relay.config import Settings
from tg_relay.domain.models import Limits
from tg_relay.ports.stats import ErrorRecord, HourlyStats, LastRequest
from tg_relay.ports.usage import BotSighting, UsageBatch, UsageDelta

from ..conftest import TEST_TOKEN, GatewayFactory

pytestmark = pytest.mark.postgres

SEPTEMBER = date(2026, 9, 1)
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture
async def db(clean_database: str) -> AsyncIterator[PostgresDatabase]:
    database = PostgresDatabase(clean_database)
    await database.connect()
    await database.migrate()
    try:
        yield database
    finally:
        await database.close()


async def test_migrations_are_idempotent(db: PostgresDatabase) -> None:
    assert await db.migrate() == []


async def test_admin_and_key_source(db: PostgresDatabase) -> None:
    admin = ProjectAdmin(db)
    project_id, key = await admin.create_project("acme", Limits(10, 5, 1024))
    second = await admin.add_key(project_id)
    assert second is not None
    assert await admin.add_key(9999) is None

    keys = await PostgresKeySource(db).load_all()
    assert len(keys) == 2
    record = next(iter(keys.values()))
    assert record.limits == Limits(10, 5, 1024)
    assert record.enabled

    assert await admin.disable_key(key)
    assert not await admin.disable_key("rl_live_unknown")
    [summary] = await admin.list_projects()
    assert summary.active_keys == 1

    assert await admin.disable_project(project_id)
    assert not any(r.enabled for r in (await PostgresKeySource(db).load_all()).values())


async def test_bootstrap_key_only_on_empty_database(db: PostgresDatabase) -> None:
    admin = ProjectAdmin(db)
    assert await admin.ensure_bootstrap_key("rl_live_first")
    assert not await admin.ensure_bootstrap_key("rl_live_second")
    assert len(await PostgresKeySource(db).load_all()) == 1


async def test_usage_is_added_not_overwritten(db: PostgresDatabase) -> None:
    project_id, _ = await ProjectAdmin(db).create_project("p", Limits())
    repo = PostgresUsageRepository(db)
    batch = UsageBatch(
        counters=(UsageDelta(project_id, SEPTEMBER, 1, 10, 20),),
        bots=(BotSighting(project_id, SEPTEMBER, "fp1"),),
    )
    await repo.save(batch)
    await repo.save(batch)  # второй узел прислал то же самое

    usage = await repo.load_month(SEPTEMBER)
    assert usage.bytes_by_project[project_id] == 60
    assert usage.bots_by_project[project_id] == frozenset({"fp1"})


async def test_rows_of_deleted_projects_are_skipped(db: PostgresDatabase) -> None:
    """Регрессия: строка удалённого проекта не должна блокировать сброс остальных."""
    alive, _ = await ProjectAdmin(db).create_project("alive", Limits())
    deleted = 424242
    repo = PostgresUsageRepository(db)
    await repo.save(
        UsageBatch(
            counters=(
                UsageDelta(deleted, SEPTEMBER, 1, 1, 1),
                UsageDelta(alive, SEPTEMBER, 1, 5, 5),
            ),
            bots=(BotSighting(deleted, SEPTEMBER, "x"),),
        )
    )
    stats = PostgresStatsRepository(db)
    await stats.save_hourly([HourlyStats(deleted, NOW, 1, 0, 1, 1, 1)])
    await stats.save_errors([ErrorRecord(deleted, NOW, None, None, 500, "x")])
    await stats.save_last_requests([LastRequest(deleted, NOW, None, None, 200, 1)])

    assert (await repo.load_month(SEPTEMBER)).bytes_by_project == {alive: 10}


async def test_stats_are_accumulated(db: PostgresDatabase) -> None:
    project_id, _ = await ProjectAdmin(db).create_project("p", Limits())
    stats = PostgresStatsRepository(db)
    await stats.save_hourly([HourlyStats(project_id, NOW, 3, 1, 30, 10, 20)])
    await stats.save_hourly([HourlyStats(project_id, NOW, 2, 0, 20, 12, 25)])
    await stats.save_last_requests([LastRequest(project_id, NOW, "fp", "getMe", 200, 5)])

    row = await db.pool.fetchrow("SELECT * FROM request_stats WHERE project_id = $1", project_id)
    assert row is not None
    assert (row["requests"], row["errors"], row["sum_ms"], row["p95_ms"]) == (5, 1, 50, 25)
    last = await db.pool.fetchrow("SELECT * FROM project_last_request")
    assert last is not None
    assert last["method"] == "getMe"


async def test_error_journal_is_trimmed(db: PostgresDatabase) -> None:
    from tg_relay.adapters.storage.postgres.stats import ERROR_JOURNAL_DEPTH

    project_id, _ = await ProjectAdmin(db).create_project("p", Limits())
    rows = [
        ErrorRecord(project_id, NOW, None, "m", 500, str(i))
        for i in range(ERROR_JOURNAL_DEPTH + 20)
    ]
    await PostgresStatsRepository(db).save_errors(rows)
    count = await db.pool.fetchval("SELECT count(*) FROM request_errors")
    assert count == ERROR_JOURNAL_DEPTH


async def test_gateway_end_to_end_with_database(
    db_settings: Settings, make_gateway: GatewayFactory
) -> None:
    """Полный путь: bootstrap-ключ из окружения, запрос, сброс учёта в базу."""
    async with make_gateway(replace(db_settings, stats_enabled=True)) as gw:
        r = await gw.http.get(gw.bot_url("getMe"))
        assert r.status_code == 200
        r = await gw.http.get(f"/k/{gw.key}/bot{TEST_TOKEN}/fail")
        assert r.status_code == 429
    # Выход из контекста = остановка шлюза = финальный сброс.

    conn = await asyncpg.connect(db_settings.database_url)
    try:
        usage = await conn.fetchrow("SELECT requests FROM usage_counters")
        bots = await conn.fetchval("SELECT count(*) FROM active_bots")
        errors = await conn.fetchval("SELECT count(*) FROM request_errors")
        last = await conn.fetchrow("SELECT code FROM project_last_request")
    finally:
        await conn.close()
    assert usage is not None
    assert usage["requests"] == 2
    assert bots == 1
    assert errors == 1
    assert last is not None
    assert last["code"] == 429


async def test_limits_are_enforced(db_settings: Settings, make_gateway: GatewayFactory) -> None:
    database = PostgresDatabase(db_settings.database_url or "")
    await database.connect()
    await database.migrate()
    _, key = await ProjectAdmin(database).create_project("tight", Limits(rate_per_second=1))
    await database.close()

    settings = replace(db_settings, bootstrap_key=None, enforce_limits=True)
    async with make_gateway(settings, key) as gw:
        first = await gw.http.get(gw.bot_url("getMe"))
        second = await gw.http.get(gw.bot_url("getMe"))
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["description"] == "Too Many Requests: gateway rate limit"
    assert int(second.headers["retry-after"]) >= 1
