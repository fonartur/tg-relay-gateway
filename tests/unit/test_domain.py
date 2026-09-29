"""Доменный слой: секреты, разбор пути Bot API, ошибки."""

from __future__ import annotations

import pytest

from tg_relay.domain import errors
from tg_relay.domain.botapi import parse_target
from tg_relay.domain.credentials import (
    FINGERPRINT_LENGTH,
    generate_project_key,
    hash_project_key,
    is_well_formed_key,
    token_fingerprint,
)

TOKEN = "123456789:AA_secret"


class TestCredentials:
    def test_generated_key_is_well_formed_and_unique(self) -> None:
        key = generate_project_key()
        assert is_well_formed_key(key), key
        assert key != generate_project_key()

    def test_key_hash_is_sha256_hex(self) -> None:
        digest = hash_project_key("rl_live_x")
        assert len(digest) == 64
        assert digest == hash_project_key("rl_live_x")

    def test_fingerprint_is_short_stable_and_not_the_token(self) -> None:
        fp = token_fingerprint(TOKEN)
        assert len(fp) == FINGERPRINT_LENGTH
        assert fp == token_fingerprint(TOKEN)
        assert TOKEN not in fp


class TestParseTarget:
    def test_method_call(self) -> None:
        target = parse_target(f"bot{TOKEN}/getMe")
        assert (target.token, target.method, target.is_file) == (TOKEN, "getMe", False)

    def test_file_download(self) -> None:
        target = parse_target(f"file/bot{TOKEN}/documents/file_1.pdf")
        assert (target.token, target.method, target.is_file) == (TOKEN, "file", True)

    @pytest.mark.parametrize("path", ["", "something/else", "status"])
    def test_non_bot_api_path_is_still_parsed(self, path: str) -> None:
        target = parse_target(path)
        assert target.token is None
        assert target.method is None

    def test_token_without_method(self) -> None:
        target = parse_target(f"bot{TOKEN}")
        assert target.token == TOKEN
        assert target.method is None

    @pytest.mark.parametrize("method", ["getUpdates", "getupdates", "GETUPDATES"])
    def test_long_poll_detected_case_insensitively(self, method: str) -> None:
        assert parse_target(f"bot{TOKEN}/{method}").is_long_poll

    def test_regular_method_is_not_long_poll(self) -> None:
        assert not parse_target(f"bot{TOKEN}/sendMessage").is_long_poll


class TestErrors:
    def test_payload_is_telegram_shaped(self) -> None:
        assert errors.Unauthorized().to_payload() == {
            "ok": False,
            "error_code": 401,
            "description": "Unauthorized",
        }

    def test_rate_limited_carries_retry_after(self) -> None:
        error = errors.RateLimited(retry_after=3)
        assert error.to_payload()["parameters"] == {"retry_after": 3}

    def test_retry_after_is_at_least_one_second(self) -> None:
        assert errors.RateLimited(retry_after=0).retry_after == 1

    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (errors.Unauthorized, 401),
            (errors.QuotaExceeded, 402),
            (errors.PayloadTooLarge, 413),
            (errors.BadGateway, 502),
            (errors.GatewayTimeout, 504),
        ],
    )
    def test_status_codes(self, error: type[errors.GatewayError], status: int) -> None:
        assert error().status == status
