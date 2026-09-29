"""Запуск шлюза под uvicorn с корректной остановкой.

По сигналу остановки узел сразу помечается неготовым (``/readyz`` -> 503),
а висящие long poll получают ``SHUTDOWN_GRACE`` секунд, чтобы завершиться.
"""

from __future__ import annotations

from types import FrameType

import uvicorn

from .adapters.http import create_app
from .adapters.observability import configure_logging
from .application.node import NodeState
from .bootstrap import Gateway
from .config import Settings


class _GracefulServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, node: NodeState) -> None:
        super().__init__(config)
        self._node = node

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        self._node.begin_shutdown()
        super().handle_exit(sig, frame)


def serve(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level, settings.log_format, settings.node_name)
    gateway = Gateway(settings)
    config = uvicorn.Config(
        create_app(gateway),
        host=settings.listen_host,
        port=settings.listen_port,
        # Свой логгер вместо дефолтного и никакого access-лога: в URL лежит токен.
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=int(settings.shutdown_grace),
        # uvloop и httptools, если установлены (uvicorn[standard]).
        loop="auto",
        http="auto",
        server_header=False,
        date_header=False,
    )
    _GracefulServer(config, gateway.node).run()
