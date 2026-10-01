"""Командная строка шлюза.

    tg-relay serve                                   запустить шлюз
    tg-relay migrate                                 накатить миграции
    tg-relay create-project --name acme --rate 30    проект + первый ключ
    tg-relay add-key --project 1                     ещё один ключ (ротация)
    tg-relay list-projects
    tg-relay disable-key --key rl_live_...
    tg-relay disable-project --project 1

Ключ печатается ОДИН раз при создании — в базе хранится только его SHA-256.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable, Sequence

from . import __version__
from .adapters.storage.postgres import PostgresDatabase, ProjectAdmin
from .domain.models import Limits

GIB = 1024**3

Command = Callable[[argparse.Namespace, ProjectAdmin], Awaitable[int]]


async def _create_project(args: argparse.Namespace, admin: ProjectAdmin) -> int:
    limits = Limits(
        rate_per_second=args.rate,
        active_bots=args.bots,
        monthly_bytes=int(args.gb * GIB),
    )
    project_id, key = await admin.create_project(args.name, limits)
    print(f"project id: {project_id}")
    print(f"key (сохраните — больше не покажем): {key}")
    return 0


async def _add_key(args: argparse.Namespace, admin: ProjectAdmin) -> int:
    key = await admin.add_key(args.project)
    if key is None:
        print(f"проект {args.project} не найден", file=sys.stderr)
        return 1
    print(f"key (сохраните — больше не покажем): {key}")
    return 0


async def _list_projects(_: argparse.Namespace, admin: ProjectAdmin) -> int:
    print(f"{'id':>4}  {'name':<20} {'on':<3} {'rate':>5} {'bots':>6} {'GiB':>6} {'keys':>4}")
    for p in await admin.list_projects():
        print(
            f"{p.id:>4}  {p.name:<20.20} {'y' if p.enabled else 'n':<3} "
            f"{p.limits.rate_per_second:>5} {p.limits.active_bots:>6} "
            f"{p.limits.monthly_bytes / GIB:>6.0f} {p.active_keys:>4}"
        )
    return 0


async def _disable_key(args: argparse.Namespace, admin: ProjectAdmin) -> int:
    done = await admin.disable_key(args.key)
    print("ключ отключён" if done else "ключ не найден")
    return 0 if done else 1


async def _disable_project(args: argparse.Namespace, admin: ProjectAdmin) -> int:
    done = await admin.disable_project(args.project)
    print("проект отключён" if done else "проект не найден")
    return 0 if done else 1


async def _migrate(_: argparse.Namespace, admin: ProjectAdmin) -> int:
    # Миграции накатываются в _run_admin до вызова команды.
    print("схема актуальна")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-relay", description="Прозрачный шлюз к Telegram Bot API"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="запустить шлюз (настройки — из окружения)")

    p = sub.add_parser("migrate", help="накатить миграции базы")
    p.set_defaults(handler=_migrate)

    p = sub.add_parser("create-project", help="создать проект и первый ключ")
    p.add_argument("--name", required=True)
    p.add_argument("--rate", type=_non_negative_int, default=30, help="запросов/с, 0 — без лимита")
    p.add_argument(
        "--bots",
        type=_non_negative_int,
        default=0,
        help="ботов, работающих одновременно; 0 — без лимита",
    )
    p.add_argument(
        "--gb", type=_non_negative_float, default=0, help="ГиБ трафика в месяц, 0 — без лимита"
    )
    p.set_defaults(handler=_create_project)

    p = sub.add_parser("add-key", help="выпустить ещё один ключ проекту")
    p.add_argument("--project", type=int, required=True)
    p.set_defaults(handler=_add_key)

    p = sub.add_parser("list-projects", help="список проектов")
    p.set_defaults(handler=_list_projects)

    p = sub.add_parser("disable-key", help="отключить ключ")
    p.add_argument("--key", required=True)
    p.set_defaults(handler=_disable_key)

    p = sub.add_parser("disable-project", help="отключить проект целиком")
    p.add_argument("--project", type=int, required=True)
    p.set_defaults(handler=_disable_project)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_console()
    args = build_parser().parse_args(argv)

    if args.command == "serve":
        from .server import serve

        serve()
        return 0

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL не задан", file=sys.stderr)
        return 2
    return asyncio.run(_run_admin(dsn, args.handler, args))


async def _run_admin(dsn: str, handler: Command, args: argparse.Namespace) -> int:
    database = PostgresDatabase(dsn, max_size=1)
    await database.connect()
    try:
        await database.migrate()
        return await handler(args, ProjectAdmin(database))
    finally:
        await database.close()


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("значение не может быть отрицательным")
    return value


def _non_negative_float(raw: str) -> float:
    value = float(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("значение не может быть отрицательным")
    return value


def _force_utf8_console() -> None:
    # Консоль Windows по умолчанию может быть не в UTF-8 — кириллица упадёт.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
