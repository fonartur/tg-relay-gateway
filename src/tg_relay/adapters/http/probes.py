from __future__ import annotations

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from ...application.node import NodeState
from ..observability.metrics import PrometheusMetrics


class Probes:
    def __init__(self, node: NodeState, metrics: PrometheusMetrics) -> None:
        self._node = node
        self._metrics = metrics

    async def healthz(self, _: Request) -> Response:
        # Процесс жив и обслуживает event loop. Пока отвечает — никогда не 503.
        return PlainTextResponse("ok")

    async def readyz(self, _: Request) -> Response:
        readiness = self._node.readiness()
        return PlainTextResponse(readiness.reason, status_code=200 if readiness.ready else 503)

    async def metrics(self, _: Request) -> Response:
        return Response(self._metrics.render(), media_type=self._metrics.content_type)
