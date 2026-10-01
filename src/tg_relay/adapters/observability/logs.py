"""Логирование: JSON по строке на событие в stdout.

Обязательные поля: ``ts``, ``level``, ``logger``, ``node``, ``msg``.

Защита секретов в два эшелона:

1. Access-лог uvicorn и INFO-лог httpx отключаются: они пишут полный URL,
   а в URL лежит токен бота и ключ проекта.
2. Каждая запись лога — в любом логгере, при любой настройке логирования,
   включая текст исключений, — проходит маскировку :func:`redact`. Это
   страховка на случай, когда логирование настроено в обход
   :func:`configure_logging` (свой ``dictConfig``, отладка, встраивание шлюза
   в чужое приложение).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Literal

from ...domain.credentials import KEY_PREFIX
from ...domain.models import RequestOutcome

LogFormat = Literal["json", "text"]

_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # uvicorn дублирует сообщение с ANSI-цветами
}


_SECRET_PATTERNS = (
    # Токен бота в пути Bot API: bot123456:AA…
    (re.compile(r"bot\d+:[A-Za-z0-9_-]+"), "bot<redacted>"),
    # Ключ проекта в пути шлюза: /k/<KEY>/…
    (re.compile(r"/k/[^/\s?\"']+"), "/k/<redacted>"),
    # Ключ проекта сам по себе.
    (re.compile(re.escape(KEY_PREFIX) + r"[A-Za-z0-9_-]+"), KEY_PREFIX + "<redacted>"),
)


def redact(text: str) -> str:
    """Замаскировать токены ботов и ключи проектов в тексте."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def protect_secrets_in_logs() -> None:
    """Маскировать секреты в сообщении каждой новой записи лога.

    Ставит фабрику записей поверх текущей; повторный вызов ничего не меняет.
    """
    base = logging.getLogRecordFactory()
    if getattr(base, "_redacts_secrets", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:
            return record  # кривые аргументы — пусть ошибка всплывёт там, где её ждут
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return record

    factory._redacts_secrets = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


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
        # Traceback и extra-поля проходят мимо фабрики записей — чистим итог.
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


class TextFormatter(logging.Formatter):
    def __init__(self, node: str) -> None:
        super().__init__(f"%(asctime)s %(levelname)s [{node}] %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str, fmt: LogFormat, node: str) -> None:
    protect_secrets_in_logs()
    formatter: logging.Formatter = JsonFormatter(node) if fmt == "json" else TextFormatter(node)
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
