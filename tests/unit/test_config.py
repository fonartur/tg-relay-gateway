from __future__ import annotations

import pytest

from tg_relay.config import ConfigError, Settings

KEY = "rl_live_" + "a" * 32


def test_defaults_in_autonomous_mode() -> None:
    settings = Settings.from_env({"BOOTSTRAP_KEY": KEY})
    assert settings.autonomous
    assert settings.upstream_url == "https://api.telegram.org"
    assert settings.upstream_read_timeout is None
    assert settings.listen_port == 8080


def test_database_mode() -> None:
    settings = Settings.from_env({"DATABASE_URL": "postgres://x"})
    assert not settings.autonomous


def test_read_timeout_zero_means_unlimited() -> None:
    env = {"BOOTSTRAP_KEY": KEY, "UPSTREAM_READ_TIMEOUT": "0"}
    assert Settings.from_env(env).upstream_read_timeout is None


def test_read_timeout_nonzero_is_kept() -> None:
    env = {"BOOTSTRAP_KEY": KEY, "UPSTREAM_READ_TIMEOUT": "30"}
    assert Settings.from_env(env).upstream_read_timeout == 30.0


def test_trailing_slash_is_stripped_from_upstream() -> None:
    env = {"BOOTSTRAP_KEY": KEY, "UPSTREAM_URL": "https://example.com/"}
    assert Settings.from_env(env).upstream_url == "https://example.com"


def test_empty_values_fall_back_to_defaults() -> None:
    settings = Settings.from_env({"BOOTSTRAP_KEY": KEY, "LISTEN_PORT": "", "DATABASE_URL": " "})
    assert settings.listen_port == 8080
    assert settings.autonomous


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("0", False), ("OFF", False)])
def test_boolean_flags(raw: str, expected: bool) -> None:
    assert (
        Settings.from_env({"BOOTSTRAP_KEY": KEY, "ENFORCE_LIMITS": raw}).enforce_limits is expected
    )


@pytest.mark.parametrize(
    "env",
    [
        {},  # ни базы, ни ключа
        {"BOOTSTRAP_KEY": KEY, "UPSTREAM_URL": "ftp://example.com"},
        {"BOOTSTRAP_KEY": KEY, "UPSTREAM_URL": "https://example.com/?a=1"},
        {"BOOTSTRAP_KEY": KEY, "LISTEN_PORT": "not-a-number"},
        {"BOOTSTRAP_KEY": KEY, "LISTEN_PORT": "70000"},
        {"BOOTSTRAP_KEY": KEY, "LOG_FORMAT": "xml"},
        {"BOOTSTRAP_KEY": KEY, "LOG_LEVEL": "LOUD"},
        {"BOOTSTRAP_KEY": KEY, "MAX_BODY_BYTES": "0"},
        {"BOOTSTRAP_KEY": KEY, "ENFORCE_LIMITS": "maybe"},
        {"BOOTSTRAP_KEY": KEY, "UPSTREAM_READ_TIMEOUT": "-1"},
    ],
)
def test_invalid_configuration_fails_fast(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(env)
