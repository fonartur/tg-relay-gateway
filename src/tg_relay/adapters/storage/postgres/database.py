"""Пул соединений и миграции."""

from __future__ import annotations

import logging
from importlib import resources

import asyncpg

log = logging.getLogger("tg_relay.postgres")

_MIGRATIONS_PACKAGE = "tg_relay.adapters.storage.postgres.migrations"

# Произвольная константа: под этим advisory-lock миграции накатывает только
# один узел, даже если несколько стартуют одновременно.
_MIGRATION_LOCK_ID = 0x7467_7265_6C61  # "tgrela"


class PostgresDatabase:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 4) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                command_timeout=10,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresDatabase.connect() не вызван")
        return self._pool

    async def migrate(self) -> list[str]:
        """Накатить недостающие миграции. Возвращает имена применённых."""
        applied_now: list[str] = []
        async with self.pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_ID)
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version    TEXT        PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                applied = {
                    r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")
                }
                for version, sql in _migrations():
                    if version in applied:
                        continue
                    log.info("applying migration", extra={"migration": version})
                    async with conn.transaction():
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO schema_migrations(version) VALUES ($1)", version
                        )
                    applied_now.append(version)
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_ID)
        return applied_now


def _migrations() -> list[tuple[str, str]]:
    files = resources.files(_MIGRATIONS_PACKAGE)
    return sorted(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in files.iterdir()
        if entry.name.endswith(".sql")
    )
