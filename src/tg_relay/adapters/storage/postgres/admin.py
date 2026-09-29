"""Управление проектами и ключами — для CLI и первого запуска."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ....domain.credentials import generate_project_key, hash_project_key
from ....domain.models import Limits, ProjectId
from .database import PostgresDatabase

log = logging.getLogger("tg_relay.postgres")


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    id: ProjectId
    name: str
    enabled: bool
    limits: Limits
    active_keys: int


class ProjectAdmin:
    def __init__(self, database: PostgresDatabase) -> None:
        self._db = database

    async def create_project(self, name: str, limits: Limits) -> tuple[ProjectId, str]:
        """Создать проект с первым ключом. Ключ возвращается один раз и нигде не хранится."""
        key = generate_project_key()
        async with self._db.pool.acquire() as conn, conn.transaction():
            project_id: ProjectId = await conn.fetchval(
                """
                INSERT INTO projects (name, rate_limit, monthly_bot_limit, monthly_byte_limit)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                name,
                limits.rate_per_second,
                limits.monthly_bots,
                limits.monthly_bytes,
            )
            await conn.execute(
                "INSERT INTO project_keys (key_hash, project_id) VALUES ($1, $2)",
                hash_project_key(key),
                project_id,
            )
        return project_id, key

    async def add_key(self, project_id: ProjectId) -> str | None:
        """Выпустить ещё один ключ проекту (ротация без простоя). ``None`` — нет проекта."""
        key = generate_project_key()
        inserted = await self._db.pool.fetchval(
            """
            INSERT INTO project_keys (key_hash, project_id)
            SELECT $1, id FROM projects WHERE id = $2
            RETURNING project_id
            """,
            hash_project_key(key),
            project_id,
        )
        return key if inserted is not None else None

    async def disable_key(self, raw_key: str) -> bool:
        status = await self._db.pool.execute(
            "UPDATE project_keys SET enabled = FALSE WHERE key_hash = $1",
            hash_project_key(raw_key),
        )
        return _affected(status) > 0

    async def disable_project(self, project_id: ProjectId) -> bool:
        status = await self._db.pool.execute(
            "UPDATE projects SET enabled = FALSE WHERE id = $1", project_id
        )
        return _affected(status) > 0

    async def list_projects(self) -> list[ProjectSummary]:
        rows = await self._db.pool.fetch(
            """
            SELECT p.id, p.name, p.enabled,
                   p.rate_limit, p.monthly_bot_limit, p.monthly_byte_limit,
                   count(k.key_hash) FILTER (WHERE k.enabled) AS active_keys
            FROM projects p
            LEFT JOIN project_keys k ON k.project_id = p.id
            GROUP BY p.id
            ORDER BY p.id
            """
        )
        return [
            ProjectSummary(
                id=r["id"],
                name=r["name"],
                enabled=r["enabled"],
                limits=Limits(r["rate_limit"], r["monthly_bot_limit"], r["monthly_byte_limit"]),
                active_keys=r["active_keys"],
            )
            for r in rows
        ]

    async def ensure_bootstrap_key(self, raw_key: str) -> bool:
        """Завести проект ``bootstrap`` с данным ключом — только на пустой базе.

        Возвращает ``True``, если проект создан. На непустой базе ключ из
        окружения игнорируется: проектами тогда управляют через CLI.
        """
        key_hash = hash_project_key(raw_key)
        async with self._db.pool.acquire() as conn, conn.transaction():
            # Блокировка таблицы исключает гонку двух узлов на первом старте.
            await conn.execute("LOCK TABLE projects IN SHARE ROW EXCLUSIVE MODE")
            if await conn.fetchval("SELECT 1 FROM projects LIMIT 1"):
                return False
            project_id = await conn.fetchval(
                "INSERT INTO projects (name) VALUES ('bootstrap') RETURNING id"
            )
            await conn.execute(
                "INSERT INTO project_keys (key_hash, project_id) VALUES ($1, $2)",
                key_hash,
                project_id,
            )
        log.info("bootstrap project created", extra={"project": project_id})
        return True


def _affected(status: str) -> int:
    """Число строк из статуса команды asyncpg (``"UPDATE 1"``)."""
    return int(status.rsplit(" ", 1)[-1])
