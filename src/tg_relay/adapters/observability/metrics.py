"""Метрики Prometheus.

Метка ``project`` — числовой id проекта. Никаких имён, ключей и токенов в метках.
Каждый экземпляр держит свой реестр: несколько приложений в одном процессе
(например, в тестах) не конфликтуют.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from ...application.key_registry import KeyRegistry
from ...domain.models import RequestOutcome

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)


class PrometheusMetrics:
    """Реализует :class:`~tg_relay.ports.RequestObserver`."""

    content_type = CONTENT_TYPE_LATEST

    def __init__(self, keys: KeyRegistry, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.requests = Counter(
            "relay_requests_total",
            "Запросы по проектам и кодам ответа",
            ["project", "code"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "relay_request_seconds",
            "Длительность проксирования без long polling, секунды",
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.inflight = Gauge(
            "relay_inflight_requests",
            "Запросы в обработке прямо сейчас",
            registry=self.registry,
        )
        self.rejections = Counter(
            "relay_rejections_total",
            "Ответы, сформированные самим шлюзом, по причинам",
            ["reason"],
            registry=self.registry,
        )
        Gauge("relay_key_cache_size", "Ключей в кэше", registry=self.registry).set_function(
            lambda: keys.size
        )
        Gauge(
            "relay_key_cache_stale",
            "1 — хранилище недоступно, узел работает на последнем известном кэше",
            registry=self.registry,
        ).set_function(lambda: int(keys.is_stale))

    # ------------------------------------------------------ RequestObserver

    def on_request_started(self) -> None:
        self.inflight.inc()

    def on_request_finished(self, outcome: RequestOutcome) -> None:
        self.inflight.dec()
        project = "-" if outcome.project_id is None else str(outcome.project_id)
        self.requests.labels(project, str(outcome.status)).inc()
        if outcome.rejection is not None:
            self.rejections.labels(outcome.rejection.reason).inc()
        if not outcome.is_long_poll:
            self.latency.observe(outcome.duration_ms / 1000)

    def render(self) -> bytes:
        body: bytes = generate_latest(self.registry)
        return body
