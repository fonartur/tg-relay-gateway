"""ASGI-приложение шлюза на Starlette.

Маршруты::

    GET|POST /k/{key}/{path}   прозрачное проксирование в Bot API
    GET      /healthz          процесс жив
    GET      /readyz           узел готов принимать трафик
    GET      /metrics          метрики Prometheus
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.routing import Route

from ...bootstrap import Gateway
from .probes import Probes
from .proxy_endpoint import ProxyEndpoint

PROXY_PREFIX = "/k/"


def create_app(gateway: Gateway) -> Starlette:
    probes = Probes(gateway.node, gateway.metrics)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        await gateway.start()
        try:
            yield
        finally:
            await gateway.stop()

    app = Starlette(
        routes=[
            Route("/healthz", probes.healthz, methods=["GET"]),
            Route("/readyz", probes.readyz, methods=["GET"]),
            Route("/metrics", probes.metrics, methods=["GET"]),
            Route(
                PROXY_PREFIX + "{key}/{path:path}",
                ProxyEndpoint(gateway.proxy, PROXY_PREFIX).handle,
                methods=["GET", "POST"],
            ),
        ],
        lifespan=lifespan,
    )
    app.state.gateway = gateway
    return app
