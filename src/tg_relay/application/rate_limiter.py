"""Ограничение частоты запросов на проект: token bucket в памяти узла.

Ёмкость бакета равна лимиту (запросов в секунду), пополняется непрерывно.
Лимит действует в пределах одного узла; общий лимит на несколько узлов
потребует разделяемого хранилища (например, Redis) — это отдельный адаптер.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..domain.models import ProjectId

Clock = Callable[[], float]


class TokenBucket:
    __slots__ = ("_clock", "capacity", "rate", "tokens", "updated")

    def __init__(self, rate: float, clock: Clock = time.monotonic) -> None:
        if rate <= 0:
            raise ValueError("rate должен быть положительным")
        self._clock = clock
        self.rate = rate
        self.capacity = float(rate)
        self.tokens = float(rate)
        self.updated = clock()

    def take(self) -> float:
        """Взять один токен.

        Возвращает ``0.0``, если запрос можно пропустить, иначе — сколько
        секунд подождать до появления следующего токена.
        """
        now = self._clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        return (1.0 - self.tokens) / self.rate


class RateLimiter:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[ProjectId, TokenBucket] = {}

    def acquire(self, project_id: ProjectId, rate: int) -> float:
        """``rate <= 0`` — без ограничения. Иначе секунды ожидания (0 — пропустить)."""
        if rate <= 0:
            return 0.0
        bucket = self._buckets.get(project_id)
        if bucket is None or bucket.rate != rate:
            # Новый проект или сменился тариф — начинаем с полного бакета.
            bucket = TokenBucket(rate, self._clock)
            self._buckets[project_id] = bucket
        return bucket.take()

    def prune(self, idle_seconds: float) -> int:
        """Удалить бакеты, к которым не обращались дольше ``idle_seconds``.

        Бакет, простоявший дольше секунды, всё равно полон, поэтому удаление
        не меняет поведения — только освобождает память.
        """
        threshold = self._clock() - idle_seconds
        idle = [pid for pid, bucket in self._buckets.items() if bucket.updated < threshold]
        for pid in idle:
            del self._buckets[pid]
        return len(idle)

    def __len__(self) -> int:
        return len(self._buckets)
