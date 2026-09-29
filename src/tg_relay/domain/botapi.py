"""Разбор пути Bot API.

Шлюз не знает семантику методов Telegram и не держит белого списка: разбор
нужен только для учёта (отпечаток бота, имя метода в журнале). На само
проксирование он не влияет.

Понимает оба вида путей Bot API::

    bot<TOKEN>/<method>
    file/bot<TOKEN>/<path>
"""

from __future__ import annotations

from .models import BotApiTarget

_METHOD_PREFIX = "bot"
_FILE_PREFIX = "file/bot"


def parse_target(path: str) -> BotApiTarget:
    """Разобрать уже декодированный путь после ключа проекта."""
    if path.startswith(_FILE_PREFIX):
        token = _first_segment(path[len(_FILE_PREFIX) :])
        return BotApiTarget(token=token, method="file", is_file=True)

    if path.startswith(_METHOD_PREFIX):
        token_part, _, rest = path[len(_METHOD_PREFIX) :].partition("/")
        method = _first_segment(rest)
        return BotApiTarget(token=token_part or None, method=method, is_file=False)

    return BotApiTarget(token=None, method=None, is_file=False)


def _first_segment(path: str) -> str | None:
    segment = path.split("/", 1)[0]
    return segment or None
