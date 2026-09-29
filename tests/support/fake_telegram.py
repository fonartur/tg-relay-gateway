"""Подставной Bot API для тестов и нагрузочного замера.

Умеет ровно то, что нужно проверкам прозрачности: ``getMe``, long poll
``getUpdates``, приём multipart с подсчётом размера, потоковую отдачу файла,
а также ``echo`` — отражает всё, что до него дошло (метод, путь, query,
заголовки, размер тела).

Отдельный запуск::

    uvicorn tests.support.fake_telegram:app --port 8081
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route


def _token(request: Request) -> str:
    return str(request.path_params["token"])


async def get_me(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "result": {
                "id": 42,
                "is_bot": True,
                "first_name": "Fake",
                "username": "fake_bot",
                "_token_seen": _token(request),  # тест сверяет токен байт в байт
            },
        }
    )


async def get_updates(request: Request) -> JSONResponse:
    """Long polling: держим соединение ``timeout`` секунд, затем пустой ответ."""
    if request.method == "POST":
        try:
            data = await request.json()
        except ValueError:
            data = {}
        timeout = float(data.get("timeout", 0))
    else:
        timeout = float(request.query_params.get("timeout", "0"))
    await asyncio.sleep(min(timeout, 60))
    return JSONResponse({"ok": True, "result": []})


async def send_document(request: Request) -> JSONResponse:
    total = 0
    async for chunk in request.stream():  # тело целиком в память не берём
        total += len(chunk)
    return JSONResponse({"ok": True, "result": {"document": {"file_id": "f", "file_size": total}}})


async def echo(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse(
        {
            "ok": True,
            "result": {
                "method": request.method,
                "raw_path": request.scope["raw_path"].decode("latin-1").split("?", 1)[0],
                "query": request.scope["query_string"].decode("latin-1"),
                "headers": [[k.decode(), v.decode()] for k, v in request.headers.raw],
                "body_size": len(body),
            },
        }
    )


async def fail(_: Request) -> JSONResponse:
    """Ошибка Bot API со своим retry_after — должна пройти насквозь без подмены."""
    return JSONResponse(
        {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after 7",
            "parameters": {"retry_after": 7},
        },
        status_code=429,
        headers={"retry-after": "7"},
    )


async def multi_header(_: Request) -> Response:
    response = JSONResponse({"ok": True, "result": True})
    response.raw_headers.append((b"x-multi", b"one"))
    response.raw_headers.append((b"x-multi", b"two"))
    return response


async def download_file(request: Request) -> StreamingResponse:
    """Потоковая отдача ``?size=`` байт (по умолчанию 1 МиБ)."""
    size = int(request.query_params.get("size", str(1024 * 1024)))
    chunk = b"x" * 65536

    async def body() -> AsyncIterator[bytes]:
        remaining = size
        while remaining > 0:
            piece = chunk[: min(len(chunk), remaining)]
            remaining -= len(piece)
            yield piece

    return StreamingResponse(
        body(),
        media_type="application/octet-stream",
        headers={"content-length": str(size)},
    )


async def catch_all(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "result": True})


app = Starlette(
    routes=[
        Route("/bot{token}/getMe", get_me, methods=["GET", "POST"]),
        Route("/bot{token}/getUpdates", get_updates, methods=["GET", "POST"]),
        Route("/bot{token}/sendDocument", send_document, methods=["POST"]),
        Route("/bot{token}/echo", echo, methods=["GET", "POST"]),
        Route("/bot{token}/echo/{rest:path}", echo, methods=["GET", "POST"]),
        Route("/bot{token}/fail", fail, methods=["GET", "POST"]),
        Route("/bot{token}/multiHeader", multi_header, methods=["GET"]),
        Route("/file/bot{token}/{file_path:path}", download_file, methods=["GET"]),
        Route("/bot{token}/{method}", catch_all, methods=["GET", "POST"]),
    ]
)
