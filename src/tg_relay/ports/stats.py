"""Хранилище статистики для дашбордов: почасовые агрегаты, журнал ошибок,
последний запрос проекта. Всё — без токенов, только по отпечаткам."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain.models import ProjectId


@dataclass(frozen=True, slots=True)
class HourlyStats:
    project_id: ProjectId
    hour: datetime
    requests: int
    errors: int
    sum_ms: int
    p50_ms: int
    p95_ms: int


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    project_id: ProjectId
    at: datetime
    fingerprint: str | None
    method: str | None
    status: int
    message: str


@dataclass(frozen=True, slots=True)
class LastRequest:
    project_id: ProjectId
    at: datetime
    fingerprint: str | None
    method: str | None
    status: int
    duration_ms: int


class StatsRepository(Protocol):
    async def save_hourly(self, rows: Sequence[HourlyStats]) -> None:
        """Прибавить почасовые дельты (перцентили — перезаписать)."""
        ...

    async def save_errors(self, rows: Sequence[ErrorRecord]) -> None:
        """Дописать записи в журнал ошибок."""
        ...

    async def save_last_requests(self, rows: Sequence[LastRequest]) -> None:
        """Перезаписать «последний запрос» проектов."""
        ...
