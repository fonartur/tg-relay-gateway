"""Настройки шлюза из переменных окружения.

Шлюз падает на старте, если настройка задана неверно: лучше не запуститься,
чем молча работать с неожиданным значением.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar, cast
from urllib.parse import urlsplit

from .adapters.observability.logs import LogFormat

T = TypeVar("T")

MIB = 1024 * 1024


class ConfigError(ValueError):
    """Настройка не задана или задана неверно."""


# Без slots: значения по умолчанию должны оставаться доступны как атрибуты класса.
@dataclass(frozen=True)
class Settings:
    upstream_url: str = "https://api.telegram.org"
    #: Нет базы — автономный режим: единственный ключ из ``bootstrap_key``, без лимитов.
    database_url: str | None = None
    bootstrap_key: str | None = None

    listen_host: str = "0.0.0.0"
    listen_port: int = 8080

    upstream_connect_timeout: float = 10.0
    #: ``None`` — без ограничения. Любое конечное значение ломает long polling.
    upstream_read_timeout: float | None = None
    upstream_write_timeout: float = 120.0
    upstream_keepalive: float = 90.0
    max_connections: int = 2000
    max_body_bytes: int = 60 * MIB

    enforce_limits: bool = True
    stats_enabled: bool = True
    key_cache_ttl: float = 30.0
    usage_flush_interval: float = 10.0
    last_request_flush_interval: float = 2.0
    shutdown_grace: float = 90.0

    log_level: str = "INFO"
    log_format: LogFormat = "json"
    node_name: str = "edge-1"

    @property
    def autonomous(self) -> bool:
        return self.database_url is None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        reader = _EnvReader(os.environ if env is None else env)
        read_timeout = reader.get("UPSTREAM_READ_TIMEOUT", float, 0.0)
        settings = cls(
            upstream_url=reader.get("UPSTREAM_URL", str, cls.upstream_url).rstrip("/"),
            database_url=reader.optional("DATABASE_URL"),
            bootstrap_key=reader.optional("BOOTSTRAP_KEY"),
            listen_host=reader.get("LISTEN_HOST", str, cls.listen_host),
            listen_port=reader.get("LISTEN_PORT", int, cls.listen_port),
            upstream_connect_timeout=reader.get(
                "UPSTREAM_CONNECT_TIMEOUT", float, cls.upstream_connect_timeout
            ),
            upstream_read_timeout=None if read_timeout == 0 else read_timeout,
            upstream_write_timeout=reader.get(
                "UPSTREAM_WRITE_TIMEOUT", float, cls.upstream_write_timeout
            ),
            upstream_keepalive=reader.get("UPSTREAM_KEEPALIVE", float, cls.upstream_keepalive),
            max_connections=reader.get("MAX_CONNECTIONS", int, cls.max_connections),
            max_body_bytes=reader.get("MAX_BODY_BYTES", int, cls.max_body_bytes),
            enforce_limits=reader.get("ENFORCE_LIMITS", _parse_bool, cls.enforce_limits),
            stats_enabled=reader.get("STATS_ENABLED", _parse_bool, cls.stats_enabled),
            key_cache_ttl=reader.get("KEY_CACHE_TTL", float, cls.key_cache_ttl),
            usage_flush_interval=reader.get(
                "USAGE_FLUSH_INTERVAL", float, cls.usage_flush_interval
            ),
            last_request_flush_interval=reader.get(
                "LAST_REQUEST_FLUSH_INTERVAL", float, cls.last_request_flush_interval
            ),
            shutdown_grace=reader.get("SHUTDOWN_GRACE", float, cls.shutdown_grace),
            log_level=reader.get("LOG_LEVEL", str, cls.log_level).upper(),
            log_format=cast(LogFormat, reader.get("LOG_FORMAT", str, str(cls.log_format)).lower()),
            node_name=reader.get("NODE_NAME", str, cls.node_name),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        url = urlsplit(self.upstream_url)
        if url.scheme not in ("http", "https") or not url.netloc:
            raise ConfigError("UPSTREAM_URL должен быть абсолютным http(s)-адресом")
        if url.query or url.fragment:
            raise ConfigError("UPSTREAM_URL не должен содержать query или fragment")
        if self.autonomous and not self.bootstrap_key:
            raise ConfigError(
                "Задайте DATABASE_URL (обычный режим) или BOOTSTRAP_KEY (автономный режим без БД)"
            )
        if self.log_format not in ("json", "text"):
            raise ConfigError("LOG_FORMAT должен быть json или text")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ConfigError("LOG_LEVEL должен быть DEBUG, INFO, WARNING, ERROR или CRITICAL")
        if not 0 < self.listen_port < 65536:
            raise ConfigError("LISTEN_PORT вне диапазона 1..65535")
        positive = {
            "MAX_BODY_BYTES": self.max_body_bytes,
            "MAX_CONNECTIONS": self.max_connections,
            "UPSTREAM_CONNECT_TIMEOUT": self.upstream_connect_timeout,
            "UPSTREAM_WRITE_TIMEOUT": self.upstream_write_timeout,
            "KEY_CACHE_TTL": self.key_cache_ttl,
            "USAGE_FLUSH_INTERVAL": self.usage_flush_interval,
            "LAST_REQUEST_FLUSH_INTERVAL": self.last_request_flush_interval,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ConfigError(f"{name} должен быть положительным")
        if self.upstream_read_timeout is not None and self.upstream_read_timeout < 0:
            raise ConfigError("UPSTREAM_READ_TIMEOUT не может быть отрицательным")
        if self.shutdown_grace < 0:
            raise ConfigError("SHUTDOWN_GRACE не может быть отрицательным")


class _EnvReader:
    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env

    def optional(self, name: str) -> str | None:
        value = self._env.get(name, "").strip()
        return value or None

    def get(self, name: str, parse: Callable[[str], T], default: T) -> T:
        raw = self.optional(name)
        if raw is None:
            return default
        try:
            return parse(raw)
        except ValueError as exc:
            raise ConfigError(f"{name}: не удалось разобрать значение {raw!r}") from exc


def _parse_bool(raw: str) -> bool:
    value = raw.lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(raw)
