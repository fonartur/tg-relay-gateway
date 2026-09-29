"""``python -m tg_relay`` — то же, что ``tg-relay``; без аргументов запускает шлюз."""

import sys

from .cli import main

raise SystemExit(main(sys.argv[1:] or ["serve"]))
