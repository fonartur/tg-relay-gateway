"""Логирование: JSON по строке на событие в stdout.

Обязательные поля: ``ts``, ``level``, ``logger``, ``node``, ``msg``.

Access-лог uvicorn и INFO-лог httpx отключаются намеренно: они пишут полный
URL, а в URL лежит токен бота. Включить их — значит слить чужие секреты
в журнал.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

from ...domain.models import RequestOutcome

LogFormat = Literal["json", "text"]

_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # uvicorn дублирует сообщение с ANSI-цветами
}


class JsonFormatter(logging.Formatter):
    def __init__(self, node: str) -> None:
        super().__init__()
        self._node = node

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "node": self._node,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str, fmt: LogFormat, node: str) -> None:
    formatter: logging.Formatter = (
        JsonFormatter(node)
        if fmt == "json"
        else logging.Formatter(f"%(asctime)s %(levelname)s [{node}] %(name)s: %(message)s")
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    access = logging.getLogger("uvicorn.access")
    access.handlers[:] = []
    access.propagate = False
    access.disabled = True

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers[:] = [handler]
        logger.propagate = False

    # httpx на INFO пишет URL запроса к upstream — с токеном. Глушим всегда.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class ErrorLogObserver:
    """Пишет в журнал только неуспешные запросы и только по отпечатку токена."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("tg_relay.requests")

    def on_request_started(self) -> None:
        pass

    def on_request_finished(self, outcome: RequestOutcome) -> None:
        if not outcome.is_error:
            return
        if outcome.rejection is not None and outcome.rejection.reason == "unauthorized":
            # Неизвестный ключ проекта — это перебор ключей; для него есть
            # метрика, а журнал он бы только засорял.
            return
        self._log.warning(
            outcome.rejection.detail if outcome.rejection else "upstream returned error",
            extra={
                "project": outcome.project_id,
                "token_fp": outcome.fingerprint,
                "method": outcome.method,
                "status": outcome.status,
                "duration_ms": round(outcome.duration_ms, 1),
            },
        )
