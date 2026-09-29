"""Работа с секретами: ключи проектов и отпечатки токенов ботов.

Токен бота проходит транзитом и НИКОГДА не сохраняется. В логи, БД и метрики
попадает только отпечаток — первые 12 hex-символов SHA-256 от токена.

Ключ проекта хранится только хешем: в БД лежит SHA-256, а не сам ключ.
Сам ключ показывается один раз — в момент создания.
"""

from __future__ import annotations

import hashlib
import re
import secrets

KEY_PREFIX = "rl_live_"
FINGERPRINT_LENGTH = 12

# 24 случайных байта в base64url дают ровно 32 символа.
_KEY_ENTROPY_BYTES = 24
_KEY_PATTERN = re.compile(rf"^{KEY_PREFIX}[A-Za-z0-9_-]{{32}}$")


def generate_project_key() -> str:
    """Новый ключ проекта вида ``rl_live_<32 символа>``."""
    return KEY_PREFIX + secrets.token_urlsafe(_KEY_ENTROPY_BYTES)


def is_well_formed_key(key: str) -> bool:
    return bool(_KEY_PATTERN.match(key))


def hash_project_key(key: str) -> str:
    """SHA-256 (hex) ключа проекта — то, что лежит в БД и в кэше."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def token_fingerprint(token: str) -> str:
    """Отпечаток токена бота — единственное, что о токене попадает наружу."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]
