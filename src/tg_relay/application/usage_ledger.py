"""Учёт потребления для тарификации: трафик и работавшие боты.

Счётчики копятся в памяти и сбрасываются пачками. Потеря части учёта при
аварии узла допустима — простой ботов недопустим.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from ..domain.errors import QuotaExceeded
from ..domain.models import ProjectId, RequestOutcome
from ..ports.usage import BotSighting, MonthUsage, UsageBatch, UsageDelta

_Key = tuple[ProjectId, date]


@dataclass(slots=True)
class _Counter:
    requests: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


class UsageLedger:
    """Реализует :class:`~tg_relay.ports.RequestObserver`.

    Держит два вида данных:

    * **дельты к сбросу** — запросы, трафик и боты, которых этот узел
      насчитал с прошлого сброса;
    * **трафик месяца** — сколько проект уже потратил (по данным всех узлов
      плюс локальный прирост); по нему проверяется лимит трафика.
    """

    def __init__(self) -> None:
        self._pending: defaultdict[_Key, _Counter] = defaultdict(_Counter)
        self._pending_bots: defaultdict[_Key, set[str]] = defaultdict(set)
        self._month_bytes: defaultdict[_Key, int] = defaultdict(int)

    # ------------------------------------------------------ RequestObserver

    def on_request_started(self) -> None:
        pass

    def on_request_finished(self, outcome: RequestOutcome) -> None:
        if outcome.project_id is None:
            return  # запрос без проекта (401) не тарифицируется
        key = (outcome.project_id, outcome.month)

        counter = self._pending[key]
        counter.requests += 1
        counter.bytes_in += outcome.bytes_in
        counter.bytes_out += outcome.bytes_out
        self._month_bytes[key] += outcome.bytes_in + outcome.bytes_out

        # Бот, которому отказали по лимиту тарифа, ботом проекта не становится:
        # иначе отказ записал бы его в работающие, и следующий запрос прошёл бы.
        rejected_by_quota = (
            outcome.rejection is not None and outcome.rejection.reason == QuotaExceeded.reason
        )
        if outcome.fingerprint and not rejected_by_quota:
            # Бот попадает в каждую пачку, где он работал: так хранилище знает
            # момент его последней активности.
            self._pending_bots[key].add(outcome.fingerprint)

    # -------------------------------------------------------- лимит трафика

    def bytes_used(self, project_id: ProjectId, month: date) -> int:
        return self._month_bytes.get((project_id, month), 0)

    def sync(self, snapshot: MonthUsage) -> None:
        """Подтянуть трафик месяца из хранилища (там учтены все узлы).

        Итоги только растут: локальный прирост, ещё не сброшенный в хранилище,
        не теряется. Итоги прошлых месяцев выбрасываются.
        """
        month = snapshot.month
        for key in [k for k in self._month_bytes if k[1] != month]:
            del self._month_bytes[key]
        for project_id, total in snapshot.bytes_by_project.items():
            key = (project_id, month)
            self._month_bytes[key] = max(self._month_bytes.get(key, 0), total)

    # --------------------------------------------------------------- сброс

    def drain(self) -> UsageBatch:
        """Забрать накопленные дельты. Счётчики к сбросу обнуляются."""
        pending, self._pending = self._pending, defaultdict(_Counter)
        pending_bots, self._pending_bots = self._pending_bots, defaultdict(set)
        return UsageBatch(
            counters=tuple(
                UsageDelta(pid, month, c.requests, c.bytes_in, c.bytes_out)
                for (pid, month), c in pending.items()
                if c.requests or c.bytes_in or c.bytes_out
            ),
            bots=tuple(
                BotSighting(pid, month, fp)
                for (pid, month), fingerprints in pending_bots.items()
                for fp in fingerprints
            ),
        )

    def restore(self, batch: UsageBatch) -> None:
        """Вернуть несохранённую пачку — она уйдёт при следующем сбросе."""
        for delta in batch.counters:
            counter = self._pending[(delta.project_id, delta.month)]
            counter.requests += delta.requests
            counter.bytes_in += delta.bytes_in
            counter.bytes_out += delta.bytes_out
        for bot in batch.bots:
            self._pending_bots[(bot.project_id, bot.month)].add(bot.fingerprint)
