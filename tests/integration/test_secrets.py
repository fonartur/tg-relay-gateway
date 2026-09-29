"""Токен бота не утекает никуда: ни в логи, ни в метрики."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from tg_relay.adapters.observability.logs import JsonFormatter

from ..conftest import TEST_TOKEN, GatewayClient

TOKEN_SECRET_PART = TEST_TOKEN.split(":", 1)[1]


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter("test"))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield buffer
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


async def test_token_is_not_logged(gw: GatewayClient, captured_logs: io.StringIO) -> None:
    await gw.http.get(gw.bot_url("getMe"))
    await gw.http.get(gw.bot_url("fail"))  # ошибка upstream попадает в журнал
    await gw.http.get(f"/k/wrong/bot{TEST_TOKEN}/getMe")

    logged = captured_logs.getvalue()
    assert "upstream returned error" in logged  # журнал действительно писался
    assert TOKEN_SECRET_PART not in logged


async def test_token_is_not_in_metrics(gw: GatewayClient) -> None:
    await gw.http.get(gw.bot_url("getMe"))
    body = (await gw.http.get("/metrics")).text
    assert TOKEN_SECRET_PART not in body


async def test_upstream_401_is_logged_but_unknown_key_is_not(
    gw: GatewayClient, captured_logs: io.StringIO
) -> None:
    await gw.http.get(f"/k/wrong/bot{TEST_TOKEN}/getMe")
    assert "status" not in captured_logs.getvalue()

    await gw.http.get(gw.bot_url("fail"))  # ошибка самого Telegram
    assert '"status": 429' in captured_logs.getvalue()
