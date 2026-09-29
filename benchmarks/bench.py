"""Нагрузочный замер шлюза.

Показывает потолок RPS на коротких запросах, задержки p50/p95 и — главное —
сколько long-poll соединений узел держит одновременно.

Мерить надо именно соединения, а не RPS: бот в простое с ``timeout=50`` даёт
0,02 RPS, то есть 1000 ботов — это всего 20 RPS, но 1000 открытых соединений.

Запуск::

    python -m benchmarks.bench                                  # всё локально
    BENCH_URL=https://host BENCH_KEY=rl_live_... python -m benchmarks.bench

Параметры: ``BENCH_REQUESTS`` (3000), ``BENCH_CONCURRENCY`` (100),
``BENCH_LONGPOLL`` (1000), ``BENCH_LONGPOLL_TIMEOUT`` (3 с).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import statistics
import sys
import time
from collections.abc import Iterator

import httpx
from tests.support.fake_telegram import app as fake_telegram_app
from tests.support.servers import ServerThread

from tg_relay.adapters.http import create_app
from tg_relay.bootstrap import Gateway
from tg_relay.config import Settings
from tg_relay.domain.credentials import generate_project_key

TOKEN = "123456789:AA_bench_token_value_padding_000000"
REQUESTS = int(os.environ.get("BENCH_REQUESTS", "3000"))
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "100"))
LONGPOLL_CONNECTIONS = int(os.environ.get("BENCH_LONGPOLL", "1000"))
LONGPOLL_TIMEOUT = int(os.environ.get("BENCH_LONGPOLL_TIMEOUT", "3"))


@contextlib.contextmanager
def local_stack() -> Iterator[tuple[str, str]]:
    """Подставной Bot API + шлюз в автономном режиме на локальных портах."""
    key = generate_project_key()
    with ServerThread(fake_telegram_app) as upstream:
        settings = Settings(upstream_url=upstream.url, bootstrap_key=key, log_level="ERROR")
        with ServerThread(create_app(Gateway(settings))) as gateway:
            yield gateway.url, key


async def short_requests(base: str, key: str) -> None:
    url = f"{base}/k/{key}/bot{TOKEN}/getMe"
    latencies: list[float] = []
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=30) as client:

        async def one() -> int:
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(url)
                latencies.append(time.perf_counter() - started)
                return response.status_code

        started = time.perf_counter()
        statuses = await asyncio.gather(*(one() for _ in range(REQUESTS)))
        elapsed = time.perf_counter() - started

    latencies.sort()
    print(f"  короткие запросы:        {REQUESTS}, успешно {statuses.count(200)}")
    print(f"  RPS (один процесс):      {REQUESTS / elapsed:,.0f}")
    print(
        f"  задержка p50 / p95:      {statistics.median(latencies) * 1000:.1f} мс"
        f" / {latencies[int(len(latencies) * 0.95)] * 1000:.1f} мс"
    )


async def long_polls(base: str, key: str) -> None:
    url = f"{base}/k/{key}/bot{TOKEN}/getUpdates?timeout={LONGPOLL_TIMEOUT}"
    limits = httpx.Limits(
        max_connections=LONGPOLL_CONNECTIONS + 16,
        max_keepalive_connections=LONGPOLL_CONNECTIONS + 16,
    )
    timeout = httpx.Timeout(LONGPOLL_TIMEOUT + 30, connect=10)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

        async def hold() -> bool:
            try:
                started = time.perf_counter()
                response = await client.get(url)
                held = time.perf_counter() - started
            except httpx.HTTPError:
                return False
            return response.status_code == 200 and held >= LONGPOLL_TIMEOUT * 0.9

        results = await asyncio.gather(*(hold() for _ in range(LONGPOLL_CONNECTIONS)))

    print(
        f"  одновременные long poll: {sum(results)} из {LONGPOLL_CONNECTIONS} "
        f"продержались {LONGPOLL_TIMEOUT} с без обрыва"
    )


async def run(base: str, key: str) -> None:
    print(f"tg-relay bench → {base}")
    await short_requests(base, key)
    await long_polls(base, key)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # консоль Windows может быть не в UTF-8
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    base, key = os.environ.get("BENCH_URL"), os.environ.get("BENCH_KEY")
    if base and key:
        asyncio.run(run(base, key))
        return
    print("BENCH_URL/BENCH_KEY не заданы — поднимаю шлюз и подставной upstream локально")
    with local_stack() as (local_base, local_key):
        asyncio.run(run(local_base, local_key))


if __name__ == "__main__":
    main()
