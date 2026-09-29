from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ...domain.errors import QuotaExceeded
from ...domain.models import billing_month
from ..context import RequestContext
from ..usage_ledger import UsageLedger


class QuotaFilter:
    """Месячные лимиты тарифа: трафик и число активных ботов.

    Лимит мягкий: итоги месяца узел знает с точностью до интервала
    синхронизации, поэтому возможен небольшой перерасход — но никогда
    не ложный отказ из-за недоступной базы.
    """

    def __init__(self, ledger: UsageLedger, clock: Callable[[], datetime]) -> None:
        self._ledger = ledger
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
        if (
            limits.monthly_bots
            and fingerprint is not None
            and not self._ledger.knows_bot(project_id, month, fingerprint)
            and self._ledger.bots_used(project_id, month) >= limits.monthly_bots
        ):
            raise QuotaExceeded("tariff limit exceeded (bots)")
