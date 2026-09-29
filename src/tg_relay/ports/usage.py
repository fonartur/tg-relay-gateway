"""Хранилище учёта потребления (тарификация)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ..domain.models import ProjectId


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
    """Бот (по отпечатку), впервые замеченный этим узлом в расчётном месяце."""

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
    """Потребление всех проектов за месяц — по данным всех узлов."""

    month: date
    bytes_by_project: Mapping[ProjectId, int]
    bots_by_project: Mapping[ProjectId, frozenset[str]]


class UsageRepository(Protocol):
    async def load_month(self, month: date) -> MonthUsage:
        """Кумулятивное потребление за месяц — для проверки лимитов."""
        ...

    async def save(self, batch: UsageBatch) -> None:
        """Прибавить пачку к хранилищу. Должно быть безопасно для нескольких узлов:
        значения прибавляются, а не перезаписываются."""
        ...
