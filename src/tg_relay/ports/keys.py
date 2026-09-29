"""Источник ключей проектов."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ..domain.models import ProjectAccess


class KeySource(Protocol):
    """Откуда шлюз берёт ключи. Читается целиком и кэшируется в памяти."""

    async def load_all(self) -> Mapping[str, ProjectAccess]:
        """Все ключи: ``key_hash -> ProjectAccess``."""
        ...
