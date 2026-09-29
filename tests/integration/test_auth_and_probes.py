"""Авторизация по ключу проекта, health-пробы и метрики."""

from __future__ import annotations

from ..conftest import TEST_TOKEN, GatewayClient


async def test_unknown_key_is_401_in_telegram_format(gw: GatewayClient) -> None:
    r = await gw.http.get(f"/k/rl_live_wrong_key_000000000000000000000/bot{TEST_TOKEN}/getMe")
    assert r.status_code == 401
    assert r.json() == {"ok": False, "error_code": 401, "description": "Unauthorized"}


async def test_valid_key_passes(gw: GatewayClient) -> None:
    assert (await gw.http.get(gw.bot_url("getMe"))).status_code == 200


async def test_only_get_and_post_are_proxied(gw: GatewayClient) -> None:
    assert (await gw.http.delete(gw.bot_url("getMe"))).status_code == 405


async def test_healthz(gw: GatewayClient) -> None:
    r = await gw.http.get("/healthz")
    assert (r.status_code, r.text) == (200, "ok")


async def test_readyz(gw: GatewayClient) -> None:
    assert (await gw.http.get("/readyz")).status_code == 200


async def test_readyz_is_503_while_shutting_down(gw: GatewayClient) -> None:
    gw.gateway.node.begin_shutdown()
    r = await gw.http.get("/readyz")
    assert (r.status_code, r.text) == (503, "shutting down")


async def test_metrics_in_prometheus_format(gw: GatewayClient) -> None:
    await gw.http.get(gw.bot_url("getMe"))
    await gw.http.get(f"/k/wrong/bot{TEST_TOKEN}/getMe")
    r = await gw.http.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    for name in (
        "relay_requests_total",
        "relay_request_seconds",
        "relay_inflight_requests",
        "relay_key_cache_size 1.0",
        "relay_key_cache_stale 0.0",
        'relay_rejections_total{reason="unauthorized"} 1.0',
    ):
        assert name in body, name
    assert "relay_inflight_requests 0.0" in body  # всё, что начато, завершено
