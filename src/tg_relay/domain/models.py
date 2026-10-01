"""Доменные модели шлюза."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

ProjectId = int

#: Методы Bot API, которые держат соединение открытым в ожидании событий.
#: Их длительность — это ожидание апдейтов, а не задержка шлюза.
LONG_POLL_METHODS = frozenset({"getupdates"})


@dataclass(frozen=True, slots=True)
class Limits:
    """Лимиты тарифа проекта. Ноль в любом поле означает «без ограничения»."""

    rate_per_second: int = 0
    #: Сколько ботов проекта может работать одновременно. Бот занимает место,
    #: пока обращается к шлюзу; замолчавший бот место освобождает.
    active_bots: int = 0
    monthly_bytes: int = 0

    @classmethod
    def unlimited(cls) -> Limits:
        return cls()


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """То, что шлюз знает о ключе проекта: чей он, включён ли и какие лимиты."""

    key_hash: str
    project_id: ProjectId
    enabled: bool
    limits: Limits


@dataclass(frozen=True, slots=True)
class BotApiTarget:
    """Разбор пути Bot API после ключа проекта.

    Шлюз проксирует любой путь, даже если он не похож на Bot API, —
    тогда ``token`` и ``method`` просто равны ``None``.
    """

    token: str | None
    method: str | None
    is_file: bool

    @property
    def is_long_poll(self) -> bool:
        return self.method is not None and self.method.lower() in LONG_POLL_METHODS


@dataclass(frozen=True, slots=True)
class Rejection:
    """Почему шлюз ответил сам, не дойдя до upstream (или не дождавшись его)."""

    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class RequestOutcome:
    """Итог одного запроса через шлюз — единица учёта и наблюдения.

    Токен бота сюда не попадает никогда: только отпечаток.
    """

    project_id: ProjectId | None
    fingerprint: str | None
    method: str | None
    status: int
    bytes_in: int
    bytes_out: int
    duration_ms: float
    finished_at: datetime
    is_long_poll: bool
    #: Заполнено, если ответ сформировал сам шлюз (401, 402, 413, 429, 502, 504).
    rejection: Rejection | None = None

    @property
    def is_error(self) -> bool:
        return self.status >= 400

    @property
    def month(self) -> date:
        return billing_month(self.finished_at)


def billing_month(moment: datetime) -> date:
    """Расчётный месяц — первое число месяца."""
    return date(moment.year, moment.month, 1)


def hour_bucket(moment: datetime) -> datetime:
    """Начало часа — ключ почасовой статистики."""
    return moment.replace(minute=0, second=0, microsecond=0)
