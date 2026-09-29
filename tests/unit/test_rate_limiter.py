from __future__ import annotations

import pytest

from tg_relay.application.rate_limiter import RateLimiter, TokenBucket

from ..support.fakes import ManualTimer


def test_bucket_allows_burst_up_to_capacity() -> None:
    timer = ManualTimer()
    bucket = TokenBucket(rate=2, clock=timer)
    assert bucket.take() == 0.0
    assert bucket.take() == 0.0
    assert bucket.take() == pytest.approx(0.5)


def test_bucket_refills_over_time() -> None:
    timer = ManualTimer()
    bucket = TokenBucket(rate=2, clock=timer)
    bucket.take()
    bucket.take()
    timer.advance(0.5)
    assert bucket.take() == 0.0


def test_zero_rate_means_unlimited() -> None:
    limiter = RateLimiter()
    assert all(limiter.acquire(1, rate=0) == 0.0 for _ in range(1000))
    assert len(limiter) == 0


def test_projects_are_isolated() -> None:
    limiter = RateLimiter(clock=ManualTimer())
    assert limiter.acquire(1, rate=1) == 0.0
    assert limiter.acquire(1, rate=1) > 0
    assert limiter.acquire(2, rate=1) == 0.0


def test_changed_rate_starts_a_fresh_bucket() -> None:
    limiter = RateLimiter(clock=ManualTimer())
    limiter.acquire(1, rate=1)
    assert limiter.acquire(1, rate=1) > 0
    assert limiter.acquire(1, rate=5) == 0.0


def test_prune_forgets_idle_buckets_only() -> None:
    timer = ManualTimer()
    limiter = RateLimiter(clock=timer)
    limiter.acquire(1, rate=1)
    timer.advance(100)
    limiter.acquire(2, rate=1)
    assert limiter.prune(idle_seconds=50) == 1
    assert len(limiter) == 1
