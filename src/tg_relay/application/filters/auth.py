from __future__ import annotations

from ...domain.errors import Unauthorized
from ..context import RequestContext
from ..key_registry import KeyRegistry


class AuthFilter:
    """Ключ проекта из пути ``/k/<key>/...`` должен существовать и быть включён."""

    def __init__(self, registry: KeyRegistry) -> None:
        self._registry = registry

    async def __call__(self, ctx: RequestContext) -> None:
        access = self._registry.lookup(ctx.request.key)
        if access is None:
            raise Unauthorized("unknown or disabled project key")
        ctx.access = access
