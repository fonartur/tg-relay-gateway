"""Статистика для дашбордов: почасовые агрегаты, журнал ошибок, последний запрос.

В отличие от :mod:`.usage_ledger`, эти данные не влияют на решения шлюза —
только показываются людям. Поэтому здесь всё ограничено по памяти и
сбрасывается по принципу «лучшее, что можем».
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from ..domain.models import ProjectId, RequestOutcome, hour_bucket
from ..ports.stats import ErrorRecord, HourlyStats, LastRequest

_HourKey = tuple[ProjectId, datetime]

SAMPLE_CAPACITY = 512
"""Сколько замеров задержки держим на час и проект для перцентилей."""

ERRORS_CAPACITY = 200
"""Сколько записей журнала ошибок держим в памяти до сброса."""

MESSAGE_MAX_LENGTH = 200


@dataclass(slots=True)
class _HourTotals:
    requests: int = 0
    errors: int = 0
    sum_ms: int = 0


@dataclass(slots=True)
class _Reservoir:
    """Равномерная выборка фиксированного размера (reservoir sampling, алгоритм R).

    В отличие от «первых N замеров», не смещается к началу часа.
    """

    capacity: int
    seen: int = 0
    values: list[float] = field(default_factory=list)

    def add(self, value: float, rng: random.Random) -> None:
        self.seen += 1
        if len(self.values) < self.capacity:
            self.values.append(value)
            return
        slot = rng.randrange(self.seen)
        if slot < self.capacity:
            self.values[slot] = value

    def percentile(self, q: float) -> int:
        if not self.values:
            return 0
        ordered = sorted(self.values)
        return int(ordered[min(len(ordered) - 1, int(len(ordered) * q))])


class StatsCollector:
    """Реализует :class:`~tg_relay.ports.RequestObserver`."""

    def __init__(
        self,
        clock: Callable[[], datetime],
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._clock = clock
        self._rng = rng or random.Random()
        self._hourly: defaultdict[_HourKey, _HourTotals] = defaultdict(_HourTotals)
        self._samples: dict[_HourKey, _Reservoir] = {}
        self._errors: list[ErrorRecord] = []
        self._last: dict[ProjectId, LastRequest] = {}

    # ------------------------------------------------------ RequestObserver

    def on_request_started(self) -> None:
        pass

    def on_request_finished(self, outcome: RequestOutcome) -> None:
        project_id = outcome.project_id
        if project_id is None:
            return
        key = (project_id, hour_bucket(outcome.finished_at))

        totals = self._hourly[key]
        totals.requests += 1
        if outcome.is_error:
            totals.errors += 1
        # Long polling — ожидание апдейтов, а не задержка: в перцентили не берём.
        if not outcome.is_long_poll:
            totals.sum_ms += int(outcome.duration_ms)
            reservoir = self._samples.get(key)
            if reservoir is None:
                reservoir = self._samples[key] = _Reservoir(SAMPLE_CAPACITY)
            reservoir.add(outcome.duration_ms, self._rng)

        if outcome.is_error and len(self._errors) < ERRORS_CAPACITY:
            self._errors.append(
                ErrorRecord(
                    project_id=project_id,
                    at=outcome.finished_at,
                    fingerprint=outcome.fingerprint,
                    method=outcome.method,
                    status=outcome.status,
                    message=_describe_error(outcome),
                )
            )

        self._last[project_id] = LastRequest(
            project_id=project_id,
            at=outcome.finished_at,
            fingerprint=outcome.fingerprint,
            method=outcome.method,
            status=outcome.status,
            duration_ms=int(outcome.duration_ms),
        )

    # --------------------------------------------------------------- сброс

    def drain_hourly(self) -> list[HourlyStats]:
        """Почасовые дельты с прошлого сброса + текущие перцентили часа."""
        hourly, self._hourly = self._hourly, defaultdict(_HourTotals)
        rows = []
        for (project_id, hour), totals in hourly.items():
            reservoir = self._samples.get((project_id, hour))
            rows.append(
                HourlyStats(
                    project_id=project_id,
                    hour=hour,
                    requests=totals.requests,
                    errors=totals.errors,
                    sum_ms=totals.sum_ms,
                    p50_ms=reservoir.percentile(0.50) if reservoir else 0,
                    p95_ms=reservoir.percentile(0.95) if reservoir else 0,
                )
            )
        self._forget_past_hours()
        return rows

    def restore_hourly(self, rows: list[HourlyStats]) -> None:
        for row in rows:
            totals = self._hourly[(row.project_id, row.hour)]
            totals.requests += row.requests
            totals.errors += row.errors
            totals.sum_ms += row.sum_ms

    def drain_errors(self) -> list[ErrorRecord]:
        errors, self._errors = self._errors, []
        return errors

    def restore_errors(self, rows: list[ErrorRecord]) -> None:
        # Старые записи — вперёд, и не выходим за ёмкость журнала.
        self._errors = (rows + self._errors)[:ERRORS_CAPACITY]

    def drain_last_requests(self) -> list[LastRequest]:
        last, self._last = self._last, {}
        return list(last.values())

    def restore_last_requests(self, rows: list[LastRequest]) -> None:
        # Более свежий запрос, пришедший за время сброса, важнее.
        for row in rows:
            self._last.setdefault(row.project_id, row)

    def _forget_past_hours(self) -> None:
        current = hour_bucket(self._clock())
        for key in [k for k in self._samples if k[1] != current]:
            del self._samples[key]


def _describe_error(outcome: RequestOutcome) -> str:
    message = outcome.rejection.detail if outcome.rejection else f"upstream {outcome.status}"
    return message[:MESSAGE_MAX_LENGTH]
