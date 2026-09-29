"""Общая оснастка тестов.

Подставной Bot API поднимается на реальном порту. Шлюз — либо in-process
через ASGI-транспорт (быстро), либо на реальном порту (для настоящих
клиентов: aiogram, requests).
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager
from starlette.applications import Starlette

from tg_relay.adapters.http import create_app
from tg_relay.bootstrap import Gateway
from tg_relay.config import Settings
from tg_relay.domain.credentials import generate_project_key

from .support.fake_telegram import app as fake_telegram_app
from .support.servers import ServerThread

#: Реалистичный токен вида <число>:<строка> — проверяем, что проходит байт в байт.
TEST_TOKEN = "123456789:AA_this_is_a_fake_bot_token_value_00"


@dataclass
class GatewayClient:
    http: httpx.AsyncClient
    key: str
    app: Starlette

    @property
    def gateway(self) -> Gateway:
        gateway: Gateway = self.app.state.gateway
        return gateway

    def bot_url(self, method: str) -> str:
        return f"/k/{self.key}/bot{TEST_TOKEN}/{method}"


@pytest.fixture(scope="session")
def fake_upstream() -> Iterator[str]:
    with ServerThread(fake_telegram_app) as server:
        yield server.url


@pytest.fixture
def project_key() -> str:
    return generate_project_key()


@pytest.fixture
def settings(fake_upstream: str, project_key: str) -> Settings:
    """Автономный режим: единственный ключ, без базы."""
    return Settings(upstream_url=fake_upstream, bootstrap_key=project_key, node_name="test")


GatewayFactory = Callable[..., AbstractAsyncContextManager[GatewayClient]]


@contextlib.asynccontextmanager
async def serve_in_process(settings: Settings, key: str) -> AsyncIterator[GatewayClient]:
    """Шлюз in-process: полный жизненный цикл (start/stop) и ASGI-клиент к нему."""
    app = create_app(Gateway(settings))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw", timeout=30) as http:
            yield GatewayClient(http=http, key=key, app=app)


@pytest.fixture
async def gw(settings: Settings, project_key: str) -> AsyncIterator[GatewayClient]:
    async with serve_in_process(settings, project_key) as client:
        yield client


@pytest.fixture
def make_gateway(project_key: str) -> GatewayFactory:
    """Шлюз с изменёнными настройками: ``async with make_gateway(settings) as gw``."""

    def factory(
        custom: Settings, key: str = project_key
    ) -> AbstractAsyncContextManager[GatewayClient]:
        return serve_in_process(custom, key)

    return factory


@pytest.fixture
def live_gateway(settings: Settings, project_key: str) -> Iterator[tuple[str, str]]:
    """Шлюз на реальном порту: ``(base_url, key)``."""
    with ServerThread(create_app(Gateway(settings))) as server:
        deadline = time.monotonic() + 10
        while httpx.get(f"{server.url}/readyz").status_code != 200:
            if time.monotonic() > deadline:
                raise RuntimeError("шлюз не стал готов")
            time.sleep(0.05)
        yield server.url, project_key


# ------------------------------------------------------------- PostgreSQL ---


@pytest.fixture
def database_url() -> str:
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL не задан")
    return dsn


@pytest.fixture
async def clean_database(database_url: str) -> str:
    """Пустая схема перед тестом."""
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()
    return database_url


@pytest.fixture
def db_settings(settings: Settings, clean_database: str) -> Settings:
    return replace(settings, database_url=clean_database)
