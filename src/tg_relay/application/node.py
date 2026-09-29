"""Состояние узла для проверок живости и готовности."""

from __future__ import annotations

from dataclasses import dataclass

from .key_registry import KeyRegistry


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    reason: str


class NodeState:
    """Узел готов принимать трафик, пока не идёт остановка и ключи загружены.

    При остановке узел сразу становится неготовым, чтобы балансировщик увёл
    новый трафик, пока висящие long poll доживают свой таймаут.
    """

    def __init__(self, registry: KeyRegistry) -> None:
        self._registry = registry
        self._shutting_down = False

    def begin_shutdown(self) -> None:
        self._shutting_down = True

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    def readiness(self) -> Readiness:
        if self._shutting_down:
            return Readiness(False, "shutting down")
        if not self._registry.is_loaded or self._registry.size == 0:
            return Readiness(False, "key cache empty")
        return Readiness(True, "ready")
