"""uvicorn в отдельном потоке — для проверок настоящими клиентами."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ServerThread(threading.Thread):
    def __init__(self, app: Any, port: int | None = None) -> None:
        super().__init__(daemon=True)
        self.port = port or free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def run(self) -> None:
        self.server.run()

    def __enter__(self) -> ServerThread:
        self.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline or not self.is_alive():
                raise RuntimeError("сервер не поднялся")
            time.sleep(0.02)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.join(timeout=10)
