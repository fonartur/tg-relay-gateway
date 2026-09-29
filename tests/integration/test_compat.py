"""Совместимость с настоящими клиентами: меняется только базовый URL."""

from __future__ import annotations

import pytest

from ..conftest import TEST_TOKEN


def test_requests_client(live_gateway: tuple[str, str]) -> None:
    requests = pytest.importorskip("requests")
    base, key = live_gateway
    r = requests.get(f"{base}/k/{key}/bot{TEST_TOKEN}/getMe", timeout=10)
    assert r.status_code == 200
    assert r.json()["result"]["_token_seen"] == TEST_TOKEN


async def test_aiogram3(live_gateway: tuple[str, str]) -> None:
    pytest.importorskip("aiogram")
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    base, key = live_gateway
    api = TelegramAPIServer(
        base=f"{base}/k/{key}/bot{{token}}/{{method}}",
        file=f"{base}/k/{key}/file/bot{{token}}/{{path}}",
    )
    bot = Bot(token=TEST_TOKEN, session=AiohttpSession(api=api))
    try:
        me = await bot.get_me()
        assert (me.id, me.username) == (42, "fake_bot")
    finally:
        await bot.session.close()
