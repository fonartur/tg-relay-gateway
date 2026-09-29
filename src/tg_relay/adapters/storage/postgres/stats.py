"""Статистика для дашбордов в PostgreSQL. Удалённые проекты отбрасываются
так же, как в :mod:`.usage`."""

from __future__ import annotations

from collections.abc import Sequence

from ....ports.stats import ErrorRecord, HourlyStats, LastRequest
from .database import PostgresDatabase

#: Сколько последних ошибок храним на проект.
ERROR_JOURNAL_DEPTH = 500

_SAVE_HOURLY = """
    INSERT INTO request_stats (project_id, hour, requests, errors, sum_ms, p50_ms, p95_ms)
    SELECT $1::int, $2::timestamptz, $3::bigint, $4::bigint, $5::bigint, $6::int, $7::int
    WHERE EXISTS (SELECT 1 FROM projects WHERE id = $1)
    ON CONFLICT (project_id, hour) DO UPDATE SET
        requests = request_stats.requests + EXCLUDED.requests,
        errors   = request_stats.errors   + EXCLUDED.errors,
        sum_ms   = request_stats.sum_ms   + EXCLUDED.sum_ms,
        p50_ms   = EXCLUDED.p50_ms,
        p95_ms   = EXCLUDED.p95_ms
"""

_SAVE_ERROR = """
    INSERT INTO request_errors (project_id, ts, fingerprint, method, code, message)
    SELECT $1::int, $2::timestamptz, $3::text, $4::text, $5::int, $6::text
    WHERE EXISTS (SELECT 1 FROM projects WHERE id = $1)
"""

_TRIM_ERRORS = """
    DELETE FROM request_errors
    WHERE project_id = $1 AND id < (
        SELECT min(id) FROM (
            SELECT id FROM request_errors
            WHERE project_id = $1
            ORDER BY id DESC
            LIMIT $2
        ) AS newest
    )
"""

_SAVE_LAST = """
    INSERT INTO project_last_request (project_id, ts, fingerprint, method, code, duration_ms)
    SELECT $1::int, $2::timestamptz, $3::text, $4::text, $5::int, $6::int
    WHERE EXISTS (SELECT 1 FROM projects WHERE id = $1)
    ON CONFLICT (project_id) DO UPDATE SET
        ts          = EXCLUDED.ts,
        fingerprint = EXCLUDED.fingerprint,
        method      = EXCLUDED.method,
        code        = EXCLUDED.code,
        duration_ms = EXCLUDED.duration_ms
    WHERE project_last_request.ts <= EXCLUDED.ts
"""


class PostgresStatsRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._db = database

    async def save_hourly(self, rows: Sequence[HourlyStats]) -> None:
        if not rows:
            return
        async with self._db.pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                _SAVE_HOURLY,
                [
                    (r.project_id, r.hour, r.requests, r.errors, r.sum_ms, r.p50_ms, r.p95_ms)
                    for r in rows
                ],
            )

    async def save_errors(self, rows: Sequence[ErrorRecord]) -> None:
        if not rows:
            return
        async with self._db.pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                _SAVE_ERROR,
                [(r.project_id, r.at, r.fingerprint, r.method, r.status, r.message) for r in rows],
            )
            await conn.executemany(
                _TRIM_ERRORS,
                [(pid, ERROR_JOURNAL_DEPTH) for pid in sorted({r.project_id for r in rows})],
            )

    async def save_last_requests(self, rows: Sequence[LastRequest]) -> None:
        if not rows:
            return
        async with self._db.pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                _SAVE_LAST,
                [
                    (r.project_id, r.at, r.fingerprint, r.method, r.status, r.duration_ms)
                    for r in rows
                ],
            )
