"""Фильтрация заголовков при проксировании (RFC 9110, §7.6.1).

Hop-by-hop заголовки описывают конкретное соединение, а не сообщение, поэтому
срезаются в обе стороны. Всё остальное проходит как есть, включая
``Content-Length`` и ``Content-Encoding`` — тело тоже идёт без изменений.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..ports.upstream import Header

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        # Host выставит HTTP-клиент под адрес upstream.
        "host",
    }
)


def end_to_end_headers(headers: Iterable[Header]) -> list[Header]:
    """Оставить только end-to-end заголовки, сохранив порядок и дубликаты.

    Кроме фиксированного списка срезаются заголовки, перечисленные в
    ``Connection`` — так отправитель помечает свои hop-by-hop заголовки.
    """
    materialized = list(headers)
    listed_in_connection = {
        token.strip().lower()
        for name, value in materialized
        if name.lower() == "connection"
        for token in value.split(",")
    }
    return [
        (name, value)
        for name, value in materialized
        if (lname := name.lower()) not in HOP_BY_HOP and lname not in listed_in_connection
    ]
