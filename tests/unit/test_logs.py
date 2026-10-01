"""Маскировка секретов в логах — независимо от того, как настроено логирование."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from tg_relay.adapters.observability.logs import (
    JsonFormatter,
    TextFormatter,
    protect_secrets_in_logs,
    redact,
)

TOKEN = "123456:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
TOKEN_SECRET = TOKEN.split(":", 1)[1]
KEY = "rl_live_" + "S" * 32


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"POST https://api.telegram.org/bot{TOKEN}/getUpdates", "bot<redacted>/getUpdates"),
        (f"GET /k/{KEY}/bot{TOKEN}/getMe", "GET /k/<redacted>/bot<redacted>/getMe"),
        (f"ключ {KEY} отключён", "ключ rl_live_<redacted> отключён"),
        ("project 7, token_fp 1a2b3c4d5e6f", "project 7, token_fp 1a2b3c4d5e6f"),
    ],
)
def test_redact(raw: str, expected: str) -> None:
    assert expected in redact(raw)
    assert TOKEN_SECRET not in redact(raw)
    assert KEY not in redact(raw)


@pytest.fixture
def isolated_logger() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """Логгер со своим обработчиком — в обход configure_logging."""
    protect_secrets_in_logs()
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger = logging.getLogger("httpx.redaction-test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield logger, buffer
    finally:
        logger.removeHandler(handler)


def test_any_logger_is_redacted(isolated_logger: tuple[logging.Logger, io.StringIO]) -> None:
    """Даже httpx на INFO со своим обработчиком не выведет токен и ключ."""
    logger, buffer = isolated_logger
    logger.info("HTTP Request: %s %s", "GET", f"https://gw/k/{KEY}/bot{TOKEN}/getMe")
    out = buffer.getvalue()
    assert TOKEN_SECRET not in out
    assert KEY not in out
    assert "bot<redacted>" in out


def test_protection_is_installed_once() -> None:
    protect_secrets_in_logs()
    factory = logging.getLogRecordFactory()
    protect_secrets_in_logs()
    assert logging.getLogRecordFactory() is factory


def _record_with_exception() -> logging.LogRecord:
    try:
        raise RuntimeError(f"cannot reach https://api.telegram.org/bot{TOKEN}/getMe")
    except RuntimeError:
        import sys

        return logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())


def test_json_formatter_redacts_tracebacks() -> None:
    line = JsonFormatter("node").format(_record_with_exception())
    assert TOKEN_SECRET not in line
    assert "bot<redacted>" in json.loads(line)["exc"]


def test_text_formatter_redacts_tracebacks() -> None:
    line = TextFormatter("node").format(_record_with_exception())
    assert TOKEN_SECRET not in line
