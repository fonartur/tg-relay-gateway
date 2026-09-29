from __future__ import annotations

from tg_relay.application.key_registry import KeyRegistry
from tg_relay.application.node import NodeState

from ..support.fakes import access


def test_lookup_by_raw_key() -> None:
    registry = KeyRegistry()
    record = access(7, key="secret")
    registry.replace({record.key_hash: record})
    assert registry.lookup("secret") == record
    assert registry.lookup("other") is None


def test_disabled_key_is_not_found() -> None:
    registry = KeyRegistry()
    record = access(key="secret", enabled=False)
    registry.replace({record.key_hash: record})
    assert registry.lookup("secret") is None


def test_stale_flag_is_cleared_by_successful_refresh() -> None:
    registry = KeyRegistry()
    registry.mark_stale()
    assert registry.is_stale
    registry.replace({})
    assert not registry.is_stale


def test_readiness() -> None:
    registry = KeyRegistry()
    node = NodeState(registry)
    assert not node.readiness().ready  # ключи ещё не загружены

    record = access()
    registry.replace({record.key_hash: record})
    assert node.readiness().ready

    node.begin_shutdown()
    readiness = node.readiness()
    assert not readiness.ready
    assert readiness.reason == "shutting down"
