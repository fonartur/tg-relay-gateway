"""Кэш ключей проектов в памяти."""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.credentials import hash_project_key
from ..domain.models import ProjectAccess


class KeyRegistry:
    """Ключи проектов, загруженные из :class:`~tg_relay.ports.KeySource`.

    Обновляется целиком фоновой задачей. Если источник недоступен, реестр
    продолжает отвечать по последнему известному состоянию и поднимает
    флаг ``is_stale`` — боты не должны вставать из-за упавшей базы.
    """

    def __init__(self) -> None:
        self._by_hash: Mapping[str, ProjectAccess] = {}
        self._loaded = False
        self._stale = False

    def replace(self, records: Mapping[str, ProjectAccess]) -> None:
        # Замена ссылки атомарна для asyncio: читатель видит либо старый,
        # либо новый словарь целиком.
        self._by_hash = dict(records)
        self._loaded = True
        self._stale = False

    def mark_stale(self) -> None:
        self._stale = True

    def lookup(self, raw_key: str) -> ProjectAccess | None:
        """Найти активный ключ по его сырому значению.

        Поиск идёт по SHA-256 ключа, поэтому время ответа не зависит от того,
        насколько подобранный ключ «похож» на настоящий.
        """
        access = self._by_hash.get(hash_project_key(raw_key))
        if access is None or not access.enabled:
            return None
        return access

    @property
    def size(self) -> int:
        return len(self._by_hash)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_stale(self) -> bool:
        return self._stale
