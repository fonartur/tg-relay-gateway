from __future__ import annotations

from collections.abc import Mapping

from ....domain.models import Limits, ProjectAccess
from .database import PostgresDatabase


class PostgresKeySource:
    def __init__(self, database: PostgresDatabase) -> None:
        self._db = database

    async def load_all(self) -> Mapping[str, ProjectAccess]:
        rows = await self._db.pool.fetch(
            """
            SELECT k.key_hash,
                   p.id AS project_id,
                   (p.enabled AND k.enabled) AS enabled,
                   p.rate_limit,
                   p.monthly_bot_limit,
                   p.monthly_byte_limit
            FROM project_keys k
            JOIN projects p ON p.id = k.project_id
            """
        )
        return {
            r["key_hash"]: ProjectAccess(
                key_hash=r["key_hash"],
                project_id=r["project_id"],
                enabled=r["enabled"],
                limits=Limits(
                    rate_per_second=r["rate_limit"],
                    active_bots=r["monthly_bot_limit"],
                    monthly_bytes=r["monthly_byte_limit"],
                ),
            )
            for r in rows
        }
