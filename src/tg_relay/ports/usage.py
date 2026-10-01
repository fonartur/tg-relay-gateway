"""Хранилище учёта потребления (тарификация)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from ..domain.models import ProjectId

#: Когда бот последний раз работал: ``project_id -> {fingerprint: момент}``.
BotActivity = Mapping[ProjectId, Mapping[str, datetime]]


@dataclass(frozen=True, slots=True)
class UsageDelta:
    """Прирост счётчиков проекта за месяц с момента прошлого сброса."""

    project_id: ProjectId
    month: date
    requests: int
    bytes_in: int
    bytes_out: int


@dataclass(frozen=True, slots=True)
class BotSighting:
    """Бот (по отпечатку), работавший через этот узел с прошлого сброса."""

    project_id: ProjectId
    month: date
    fingerprint: str


@dataclass(frozen=True, slots=True)
class UsageBatch:
    """Пачка учёта к сбросу в хранилище."""

    counters: tuple[UsageDelta, ...] = ()
    bots: tuple[BotSighting, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.counters or self.bots)


@dataclass(frozen=True, slots=True)
class MonthUsage:
    """Трафик всех проектов за месяц — по данным всех узлов."""

    month: date
    bytes_by_project: Mapping[ProjectId, int]


class UsageRepository(Protocol):
    async def load_month(self, month: date) -> MonthUsage:
        """Кумулятивный трафик за месяц — для проверки лимита трафика."""
        ...

    async def load_bot_activity(self, since: datetime) -> BotActivity:
        """Боты, работавшие начиная с ``since`` (по данным всех узлов), —
        чтобы лимит одновременных ботов не обнулялся при рестарте узла."""
        ...

    async def save(self, batch: UsageBatch) -> None:
        """Прибавить пачку к хранилищу. Должно быть безопасно для нескольких узлов:
        значения прибавляются, а не перезаписываются. Каждый бот из пачки
        обновляет момент своей последней активности."""
        ...
