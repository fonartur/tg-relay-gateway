"""Прозрачность: всё проходит насквозь байт в байт."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import replace

from tg_relay.config import Settings

from ..conftest import TEST_TOKEN, GatewayClient, GatewayFactory
from ..support.servers import free_port


async def test_get_me_passthrough(gw: GatewayClient) -> None:
    r = await gw.http.get(gw.bot_url("getMe"))
    assert r.status_code == 200
    assert r.json()["result"]["username"] == "fake_bot"


async def test_token_reaches_upstream_intact(gw: GatewayClient) -> None:
    r = await gw.http.get(gw.bot_url("getMe"))
    assert r.json()["result"]["_token_seen"] == TEST_TOKEN


async def test_any_method_without_allow_list(gw: GatewayClient) -> None:
    r = await gw.http.post(gw.bot_url("someFutureMethod"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "result": True}


async def test_path_query_and_headers_are_forwarded_as_is(gw: GatewayClient) -> None:
    r = await gw.http.post(
        gw.bot_url("echo/a%2Fb%20c") + "?offset=5&offset=6&q=%D1%8F",
        headers={"X-Custom": "yes", "Connection": "keep-alive"},
        content=b"payload",
    )
    echo = r.json()["result"]
    assert echo["method"] == "POST"
    assert echo["raw_path"].endswith("/echo/a%2Fb%20c")  # без перекодирования
    assert echo["query"] == "offset=5&offset=6&q=%D1%8F"
    assert echo["body_size"] == len(b"payload")
    assert ["x-custom", "yes"] in echo["headers"]
    assert ["connection", "keep-alive"] not in echo["headers"]  # hop-by-hop клиента срезан


async def test_gateway_adds_no_headers_of_its_own(gw: GatewayClient) -> None:
    """До upstream доходят только заголовки клиента (+ Host и длина тела)."""
    gw.http.headers.clear()
    r = await gw.http.post(gw.bot_url("echo"), headers={"X-Only": "1"}, content=b"x")
    names = sorted(name for name, _ in r.json()["result"]["headers"])
    assert names == ["content-length", "host", "x-only"]


async def test_upstream_errors_pass_through_with_their_retry_after(gw: GatewayClient) -> None:
    r = await gw.http.get(gw.bot_url("fail"))
    assert r.status_code == 429
    assert r.json()["parameters"]["retry_after"] == 7
    assert r.headers["retry-after"] == "7"


async def test_duplicate_response_headers_are_preserved(gw: GatewayClient) -> None:
    r = await gw.http.get(gw.bot_url("multiHeader"))
    assert r.headers.get_list("x-multi") == ["one", "two"]


async def test_long_polling_is_not_cut_or_buffered(gw: GatewayClient) -> None:
    started = time.perf_counter()
    r = await gw.http.get(gw.bot_url("getUpdates") + "?timeout=2")
    elapsed = time.perf_counter() - started
    assert r.status_code == 200
    assert elapsed >= 1.8, f"соединение оборвалось через {elapsed:.2f} с"


async def test_multipart_upload_arrives_whole(gw: GatewayClient) -> None:
    payload = b"a" * (3 * 1024 * 1024)
    files = {"document": ("big.bin", payload, "application/octet-stream")}
    r = await gw.http.post(gw.bot_url("sendDocument"), files=files)
    assert r.status_code == 200
    assert r.json()["result"]["document"]["file_size"] >= len(payload)


async def test_file_download_is_streamed(gw: GatewayClient) -> None:
    size = 2 * 1024 * 1024
    received = 0
    url = f"/k/{gw.key}/file/bot{TEST_TOKEN}/documents/file_1.bin?size={size}"
    async with gw.http.stream("GET", url) as r:
        assert r.status_code == 200
        assert r.headers["content-length"] == str(size)
        async for chunk in r.aiter_raw():
            received += len(chunk)
    assert received == size


async def test_declared_body_over_limit_is_413(
    settings: Settings, make_gateway: GatewayFactory
) -> None:
    async with make_gateway(replace(settings, max_body_bytes=1024)) as gw:
        r = await gw.http.post(gw.bot_url("sendDocument"), content=b"x" * 4096)
    assert r.status_code == 413
    assert r.json()["error_code"] == 413


async def test_chunked_body_over_limit_is_413(
    settings: Settings, make_gateway: GatewayFactory
) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(8):
            yield b"x" * 512

    async with make_gateway(replace(settings, max_body_bytes=1024)) as gw:
        r = await gw.http.post(gw.bot_url("sendDocument"), content=chunks())
    assert r.status_code == 413


async def test_unreachable_upstream_is_502(
    settings: Settings, make_gateway: GatewayFactory
) -> None:
    # Порт, на котором гарантированно никто не слушает.
    unreachable = replace(settings, upstream_url=f"http://127.0.0.1:{free_port()}")
    async with make_gateway(unreachable) as gw:
        r = await gw.http.get(gw.bot_url("getMe"))
    assert r.status_code == 502
    assert r.json() == {
        "ok": False,
        "error_code": 502,
        "description": "Bad Gateway: upstream unavailable",
    }
