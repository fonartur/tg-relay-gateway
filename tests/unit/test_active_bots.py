from __future__ import annotations

from datetime import timedelta

import pytest

from tg_relay.application.active_bots import ActiveBots

from ..support.fakes import T0, FrozenClock

WINDOW = timedelta(minutes=5)


def make() -> tuple[ActiveBots, FrozenClock]:
    clock = FrozenClock()
    return ActiveBots(WINDOW, clock), clock


def test_touched_bot_is_active_within_window() -> None:
    bots, clock = make()
    bots.touch(1, "a")
    clock.now = T0 + WINDOW
    assert bots.is_active(1, "a")
    assert bots.count(1) == 1


def test_silent_bot_frees_its_place() -> None:
    bots, clock = make()
    bots.touch(1, "a")
    clock.now = T0 + timedelta(minutes=4)
    bots.touch(1, "b")
    clock.now = T0 + timedelta(minutes=6)  # «a» молчит дольше окна
    assert not bots.is_active(1, "a")
    assert bots.is_active(1, "b")
    assert bots.count(1) == 1


def test_projects_are_isolated() -> None:
    bots, _ = make()
    bots.touch(1, "a")
    assert bots.count(2) == 0
    assert not bots.is_active(2, "a")


def test_merge_keeps_the_freshest_moment() -> None:
    bots, clock = make()
    clock.now = T0 + timedelta(minutes=3)
    bots.touch(1, "a")
    bots.merge({1: {"a": T0, "b": T0 + timedelta(minutes=1)}})

    clock.now = T0 + timedelta(minutes=7)
    assert bots.is_active(1, "a")  # локальное касание свежее, чем данные из базы
    assert not bots.is_active(1, "b")


def test_merge_restores_activity_after_restart() -> None:
    bots, _ = make()
    bots.merge({1: {"a": T0 - timedelta(minutes=1), "b": T0 - timedelta(minutes=2)}})
    assert bots.count(1) == 2


def test_prune_forgets_silent_projects() -> None:
    bots, clock = make()
    bots.touch(1, "a")
    clock.now = T0 + timedelta(hours=1)
    bots.prune()
    assert dict(bots._last_seen) == {}


def test_since_is_start_of_window() -> None:
    bots, _ = make()
    assert bots.since() == T0 - WINDOW


def test_window_must_be_positive() -> None:
    with pytest.raises(ValueError, match="положительным"):
        ActiveBots(timedelta(0), FrozenClock())
