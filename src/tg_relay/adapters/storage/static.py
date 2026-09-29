"""Хранилище без базы — для автономного режима (один ключ из окружения)."""

from __future__ import annotations

from collections.abc import Mapping

from ...domain.credentials import hash_project_key
from ...domain.models import Limits, ProjectAccess

AUTONOMOUS_PROJECT_ID = 0


class StaticKeySource:
    """Фиксированный набор ключей без лимитов."""

    def __init__(self, raw_keys: list[str]) -> None:
        self._records = {
            key_hash: ProjectAccess(
                key_hash=key_hash,
                project_id=AUTONOMOUS_PROJECT_ID,
                enabled=True,
                limits=Limits.unlimited(),
            )
            for key_hash in map(hash_project_key, raw_keys)
        }

    async def load_all(self) -> Mapping[str, ProjectAccess]:
        return self._records
