"""In-memory реализации портов для тестов ядра без сети и базы."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from tg_relay.domain.credentials import hash_project_key
from tg_relay.domain.models import Limits, ProjectAccess, RequestOutcome
from tg_relay.ports.stats import ErrorRecord, HourlyStats, LastRequest
from tg_relay.ports.upstream import Header, UpstreamRequest
from tg_relay.ports.usage import MonthUsage, UsageBatch

T0 = datetime(2026, 9, 15, 12, 30, tzinfo=UTC)


class FrozenClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class ManualTimer:
    """Монотонные часы, которые двигает тест."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def access(
    project_id: int = 1, *, key: str = "k", enabled: bool = True, **limits: int
) -> ProjectAccess:
    return ProjectAccess(
        key_hash=hash_project_key(key),
        project_id=project_id,
        enabled=enabled,
        limits=Limits(**limits),
    )


_BASE_OUTCOME = RequestOutcome(
    project_id=1,
    fingerprint="fp0000000001",
    method="sendMessage",
    status=200,
    bytes_in=10,
    bytes_out=20,
    duration_ms=15.0,
    finished_at=T0,
    is_long_poll=False,
)


def outcome(project_id: int | None = 1, **overrides: Any) -> RequestOutcome:
    return replace(_BASE_OUTCOME, project_id=project_id, **overrides)


class StaticSource:
    def __init__(self, records: Mapping[str, ProjectAccess]) -> None:
        self.records = dict(records)
        self.fail = False

    async def load_all(self) -> Mapping[str, ProjectAccess]:
        if self.fail:
            raise ConnectionError("db down")
        return self.records


@dataclass
class MemoryUsageRepository:
    saved: list[UsageBatch] = field(default_factory=list)
    month_usage: MonthUsage | None = None
    fail: bool = False

    async def load_month(self, month: date) -> MonthUsage:
        if self.fail:
            raise ConnectionError("db down")
        return self.month_usage or MonthUsage(month, {}, {})

    async def save(self, batch: UsageBatch) -> None:
        if self.fail:
            raise ConnectionError("db down")
        self.saved.append(batch)


@dataclass
class MemoryStatsRepository:
    hourly: list[HourlyStats] = field(default_factory=list)
    errors: list[ErrorRecord] = field(default_factory=list)
    last: list[LastRequest] = field(default_factory=list)
    fail_hourly: bool = False
    fail_errors: bool = False
    fail_last: bool = False

    async def save_hourly(self, rows: Sequence[HourlyStats]) -> None:
        if self.fail_hourly:
            raise ConnectionError("db down")
        self.hourly.extend(rows)

    async def save_errors(self, rows: Sequence[ErrorRecord]) -> None:
        if self.fail_errors:
            raise ConnectionError("db down")
        self.errors.extend(rows)

    async def save_last_requests(self, rows: Sequence[LastRequest]) -> None:
        if self.fail_last:
            raise ConnectionError("db down")
        self.last.extend(rows)


class RecordingObserver:
    def __init__(self) -> None:
        self.started = 0
        self.outcomes: list[RequestOutcome] = []

    def on_request_started(self) -> None:
        self.started += 1

    def on_request_finished(self, outcome: RequestOutcome) -> None:
        self.outcomes.append(outcome)


@dataclass
class FakeUpstreamResponse:
    status: int = 200
    headers: Sequence[Header] = (("content-type", "application/json"),)
    chunks: Sequence[bytes] = (b'{"ok":true}',)
    closed: bool = False

    async def iter_raw(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class FakeUpstream:
    """Upstream, который читает тело запроса целиком и отдаёт заготовленный ответ."""

    def __init__(self, response: FakeUpstreamResponse | None = None) -> None:
        self.response = response or FakeUpstreamResponse()
        self.requests: list[UpstreamRequest] = []
        self.bodies: list[bytes] = []
        self.error: Exception | None = None

    async def send(self, request: UpstreamRequest) -> FakeUpstreamResponse:
        self.requests.append(request)
        self.bodies.append(b"".join([chunk async for chunk in request.body]))
        if self.error is not None:
            raise self.error
        return self.response


async def body_of(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk
