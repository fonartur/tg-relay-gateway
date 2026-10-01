from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ...domain.errors import QuotaExceeded
from ...domain.models import billing_month
from ..active_bots import ActiveBots
from ..context import RequestContext
from ..usage_ledger import UsageLedger


class QuotaFilter:
    """Лимиты тарифа: трафик за месяц и число одновременно работающих ботов.

    Лимиты мягкие: узел знает итоги с точностью до интервала синхронизации,
    поэтому возможен небольшой перерасход — но никогда не ложный отказ из-за
    недоступной базы.
    """

    def __init__(
        self,
        ledger: UsageLedger,
        active_bots: ActiveBots,
        clock: Callable[[], datetime],
    ) -> None:
        self._ledger = ledger
        self._active_bots = active_bots
        self._clock = clock

    async def __call__(self, ctx: RequestContext) -> None:
        access = ctx.require_access()
        limits = access.limits
        project_id = access.project_id
        month = billing_month(self._clock())

        if (
            limits.monthly_bytes
            and self._ledger.bytes_used(project_id, month) >= limits.monthly_bytes
        ):
            raise QuotaExceeded("tariff limit exceeded (traffic)")

        fingerprint = ctx.fingerprint
        if fingerprint is None:
            return
        if (
            limits.active_bots
            and not self._active_bots.is_active(project_id, fingerprint)
            and self._active_bots.count(project_id) >= limits.active_bots
        ):
            raise QuotaExceeded("tariff limit exceeded (bots)")
        # Место занимается сразу, а не по завершении запроса: первый запрос бота —
        # обычно long poll, и до его ответа место успел бы занять другой бот.
        self._active_bots.touch(project_id, fingerprint)
