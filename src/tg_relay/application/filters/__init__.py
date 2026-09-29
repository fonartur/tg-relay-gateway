"""Цепочка фильтров запроса.

Каждый фильтр либо пропускает запрос дальше, либо отклоняет его доменной
ошибкой. Порядок задаётся при сборке в :mod:`tg_relay.bootstrap`::

    Auth -> Quota -> RateLimit -> BodyLimit -> (upstream)

Новая политика (белый список IP, свой лимит на метод) — это новый класс
с методом ``__call__``, без правок сервиса проксирования.
"""

from .auth import AuthFilter
from .base import FilterChain, RequestFilter
from .body_limit import BodyLimitFilter
from .quota import QuotaFilter
from .rate_limit import RateLimitFilter

__all__ = [
    "AuthFilter",
    "BodyLimitFilter",
    "FilterChain",
    "QuotaFilter",
    "RateLimitFilter",
    "RequestFilter",
]
