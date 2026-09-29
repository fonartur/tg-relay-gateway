"""Наблюдатель за запросами: метрики, учёт, статистика подписываются одинаково."""

from __future__ import annotations

from typing import Protocol

from ..domain.models import RequestOutcome


class RequestObserver(Protocol):
    def on_request_started(self) -> None:
        """Запрос принят в обработку."""
        ...

    def on_request_finished(self, outcome: RequestOutcome) -> None:
        """Запрос завершён: ответ отдан целиком, оборван или отклонён шлюзом.

        Вызывается на пути запроса — реализация обязана быть быстрой и
        не делать ввода-вывода.
        """
        ...
