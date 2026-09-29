"""Учёт потребления в PostgreSQL.

Проект мог быть удалён между запросом и сбросом. Строки таких проектов
отбрасываются условием ``WHERE EXISTS`` — иначе одна «осиротевшая» строка
(нарушение внешнего ключа) откатывала бы всю пачку, и сброс повторялся бы
вечно, блокируя учёт всех остальных проектов.
"""

from __future__ import annotations

from datetime import date

from ....ports.usage import MonthUsage, UsageBatch
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
        pool = self._db.pool
        byte_rows = await pool.fetch(
            "SELECT project_id, bytes_in + bytes_out AS total FROM usage_counters WHERE month = $1",
            month,
        )
        bot_rows = await pool.fetch(
            "SELECT project_id, array_agg(fingerprint) AS fingerprints "
            "FROM active_bots WHERE month = $1 GROUP BY project_id",
            month,
        )
        return MonthUsage(
            month=month,
            bytes_by_project={r["project_id"]: int(r["total"]) for r in byte_rows},
            bots_by_project={r["project_id"]: frozenset(r["fingerprints"]) for r in bot_rows},
        )

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
