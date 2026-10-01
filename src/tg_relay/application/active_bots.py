"""Одновременно работающие боты проекта — основа лимита ботов.

Лимит считает не всех ботов, заходивших за месяц, а тех, кто работает
сейчас: бот занимает место, пока обращается к шлюзу, и освобождает его,
промолчав дольше окна активности. Выключили одного бота и включили другого —
это по-прежнему один бот.

Бот в long polling обращается к шлюзу раз в ``timeout`` секунд (обычно до 60),
поэтому окно должно быть заметно больше — по умолчанию 5 минут.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from ..domain.models import ProjectId
from ..ports.usage import BotActivity


class ActiveBots:
    def __init__(self, window: timedelta, clock: Callable[[], datetime]) -> None:
        if window <= timedelta(0):
            raise ValueError("окно активности должно быть положительным")
        self.window = window
        self._clock = clock
        self._last_seen: defaultdict[ProjectId, dict[str, datetime]] = defaultdict(dict)

    def is_active(self, project_id: ProjectId, fingerprint: str) -> bool:
        seen = self._last_seen.get(project_id, {}).get(fingerprint)
        return seen is not None and seen >= self._cutoff()

    def count(self, project_id: ProjectId) -> int:
        """Сколько ботов проекта работает сейчас. Замолчавших заодно забываем."""
        bots = self._last_seen.get(project_id)
        if not bots:
            return 0
        cutoff = self._cutoff()
        for fingerprint in [fp for fp, seen in bots.items() if seen < cutoff]:
            del bots[fingerprint]
        return len(bots)

    def touch(self, project_id: ProjectId, fingerprint: str) -> None:
        """Бот работает прямо сейчас — занимает (или продлевает) своё место."""
        self._last_seen[project_id][fingerprint] = self._clock()

    def merge(self, activity: BotActivity) -> None:
        """Учесть активность из хранилища: другие узлы или до рестарта этого.

        Момент активности только растёт — свежие локальные данные не теряются.
        """
        for project_id, bots in activity.items():
            known = self._last_seen[project_id]
            for fingerprint, seen in bots.items():
                if fingerprint not in known or known[fingerprint] < seen:
                    known[fingerprint] = seen

    def prune(self) -> None:
        """Забыть замолчавших ботов всех проектов — чтобы память не росла."""
        for project_id in list(self._last_seen):
            if not self.count(project_id):
                del self._last_seen[project_id]

    def since(self) -> datetime:
        """С какого момента активность ещё имеет значение — для запроса к хранилищу."""
        return self._cutoff()

    def _cutoff(self) -> datetime:
        return self._clock() - self.window
