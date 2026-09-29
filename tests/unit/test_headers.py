from __future__ import annotations

from tg_relay.application.headers import end_to_end_headers


def test_hop_by_hop_headers_are_removed() -> None:
    headers = [
        ("Host", "gw"),
        ("Connection", "keep-alive"),
        ("Transfer-Encoding", "chunked"),
        ("Content-Type", "application/json"),
        ("Content-Length", "10"),
    ]
    assert end_to_end_headers(headers) == [
        ("Content-Type", "application/json"),
        ("Content-Length", "10"),
    ]


def test_headers_listed_in_connection_are_removed() -> None:
    headers = [("Connection", "close, X-Hop"), ("X-Hop", "1"), ("X-Keep", "2")]
    assert end_to_end_headers(headers) == [("X-Keep", "2")]


def test_order_and_duplicates_are_preserved() -> None:
    headers = [("X-A", "1"), ("X-B", "2"), ("X-A", "3")]
    assert end_to_end_headers(headers) == headers
