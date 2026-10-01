"""Учёт потребления в PostgreSQL.

Проект мог быть удалён между запросом и сбросом. Строки таких проектов
отбрасываются условием ``WHERE EXISTS`` — иначе одна «осиротевшая» строка
(нарушение внешнего ключа) откатывала бы всю пачку, и сброс повторялся бы
вечно, блокируя учёт всех остальных проектов.
"""

from __future__ import annotations

from datetime import date, datetime

from ....domain.models import ProjectId
from ....ports.usage import BotActivity, MonthUsage, UsageBatch
from .database import PostgresDatabase

_SAVE_COUNTERS = """
    INSERT INTO usage_counters (project_id, month, requests, bytes_in, bytes_out)
    SELECT $1::int, $2::date, $3::bigint, $4::bigint, $5::bigint
    WHERE EXISTS (SELECT 1 FROM projects WHERE id = $1)
    ON CONFLICT (project_id, month) DO UPDATE SET
        requests  = usage_counters.requests  + EXCLUDED.requests,
        bytes_in  = usage_counters.bytes_in  + EXCLUDED.bytes_in,
        bytes_out = usage_counters.bytes_out + EXCLUDED.bytes_out
"""

_SAVE_BOTS = """
    INSERT INTO active_bots (project_id, month, fingerprint)
    SELECT $1::int, $2::date, $3::text
    WHERE EXISTS (SELECT 1 FROM projects WHERE id = $1)
    ON CONFLICT (project_id, month, fingerprint) DO UPDATE SET last_seen = now()
"""


class PostgresUsageRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._db = database

    async def load_month(self, month: date) -> MonthUsage:
        rows = await self._db.pool.fetch(
            "SELECT project_id, bytes_in + bytes_out AS total FROM usage_counters WHERE month = $1",
            month,
        )
        return MonthUsage(
            month=month,
            bytes_by_project={r["project_id"]: int(r["total"]) for r in rows},
        )

    async def load_bot_activity(self, since: datetime) -> BotActivity:
        # На стыке месяцев у бота две строки — берём самую свежую.
        rows = await self._db.pool.fetch(
            """
            SELECT project_id, fingerprint, max(last_seen) AS last_seen
            FROM active_bots
            WHERE last_seen >= $1
            GROUP BY project_id, fingerprint
            """,
            since,
        )
        activity: dict[ProjectId, dict[str, datetime]] = {}
        for r in rows:
            activity.setdefault(r["project_id"], {})[r["fingerprint"]] = r["last_seen"]
        return activity

    async def save(self, batch: UsageBatch) -> None:
        if not batch:
            return
        async with self._db.pool.acquire() as conn, conn.transaction():
            if batch.counters:
                await conn.executemany(
                    _SAVE_COUNTERS,
                    [
                        (d.project_id, d.month, d.requests, d.bytes_in, d.bytes_out)
                        for d in batch.counters
                    ],
                )
            if batch.bots:
                await conn.executemany(
                    _SAVE_BOTS,
                    [(b.project_id, b.month, b.fingerprint) for b in batch.bots],
                )
