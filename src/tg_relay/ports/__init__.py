"""Порты — контракты, через которые ядро общается с внешним миром.

Ядро (``domain`` и ``application``) зависит только от этих протоколов.
Конкретные реализации лежат в ``adapters`` и выбираются в ``bootstrap``.
"""

from .keys import KeySource
from .observer import RequestObserver
from .stats import ErrorRecord, HourlyStats, LastRequest, StatsRepository
from .upstream import Upstream, UpstreamRequest, UpstreamResponse
from .usage import BotSighting, MonthUsage, UsageBatch, UsageDelta, UsageRepository

__all__ = [
    "BotSighting",
    "ErrorRecord",
    "HourlyStats",
    "KeySource",
    "LastRequest",
    "MonthUsage",
    "RequestObserver",
    "StatsRepository",
    "Upstream",
    "UpstreamRequest",
    "UpstreamResponse",
    "UsageBatch",
    "UsageDelta",
    "UsageRepository",
]
