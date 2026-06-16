"""Tests for the rate limiter and the 429 back-off.

Two styles:
  * a deterministic test that drives a fake clock (fast, exact), and
  * a real-time test that proves throttling actually slows wall-clock down.
Plus tests that the HttpRiotClient honours Retry-After and gives up eventually.
"""

import time

import httpx
import pytest

from app.ratelimit import RiotRateLimiter, TokenBucket, backoff_delay
from app.riot_client import HttpRiotClient


class FakeClock:
    """A controllable monotonic clock. sleep() just advances 'now'."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_token_bucket_throttles_deterministically():
    clock = FakeClock()
    # capacity 2 (burst of 2), refills 1 token/sec.
    bucket = TokenBucket(2, 1, now_fn=clock.time, sleep_fn=clock.sleep)

    # First two are free (the bucket starts full) -> no sleeping.
    bucket.acquire()
    bucket.acquire()
    assert clock.slept == []

    # Third must wait exactly 1 second for the next token to drip in.
    bucket.acquire()
    assert clock.slept == [pytest.approx(1.0)]
    assert clock.now == pytest.approx(1.0)


def test_token_bucket_throttles_in_real_time():
    # Burst of 2, then 20 tokens/sec. 10 acquires => 8 must wait ~ 8/20 = 0.4s.
    bucket = TokenBucket(2, 20)
    start = time.monotonic()
    for _ in range(10):
        bucket.acquire()
    elapsed = time.monotonic() - start
    # Comfortably above zero (proves throttling) but small enough to stay fast.
    assert elapsed >= 0.3


def test_riot_limiter_requires_all_buckets():
    clock = FakeClock()
    # A tight long window (1 token, very slow refill) gates everything.
    slow = TokenBucket(1, 0.5, now_fn=clock.time, sleep_fn=clock.sleep)
    fast = TokenBucket(100, 100, now_fn=clock.time, sleep_fn=clock.sleep)
    limiter = RiotRateLimiter([slow, fast])

    limiter.acquire()  # first call: both buckets full, no wait
    assert clock.slept == []
    limiter.acquire()  # second call: blocked by the slow bucket (1 / 0.5 = 2s)
    assert clock.slept == [pytest.approx(2.0)]


def test_backoff_delay_grows_and_caps():
    assert backoff_delay(0, base=0.5, cap=8.0) == 0.5
    assert backoff_delay(1, base=0.5, cap=8.0) == 1.0
    assert backoff_delay(2, base=0.5, cap=8.0) == 2.0
    assert backoff_delay(10, base=0.5, cap=8.0) == 8.0  # capped


# --- HttpRiotClient retry/back-off via a stubbed transport ------------------

ACCOUNT_JSON = {"puuid": "PUUID-1", "gameName": "Faker", "tagLine": "KR1"}


def _client(handler, sleep_fn, max_retries=3):
    """Build an HttpRiotClient whose HTTP is stubbed and whose limiter is a no-op."""
    return HttpRiotClient(
        api_key="test-key",
        region="americas",
        limiter=RiotRateLimiter([]),  # no real throttling in these tests
        transport=httpx.MockTransport(handler),
        sleep_fn=sleep_fn,
        max_retries=max_retries,
    )


def test_get_honors_retry_after_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # First response: throttled, with an explicit Retry-After.
            return httpx.Response(429, headers={"Retry-After": "0.5"})
        return httpx.Response(200, json=ACCOUNT_JSON)

    client = _client(handler, sleep_fn=slept.append)
    account = client.get_account("Faker#KR1")

    assert account.puuid == "PUUID-1"
    assert calls["n"] == 2          # retried exactly once
    assert slept == [0.5]           # waited the Retry-After value, not back-off


def test_get_gives_up_after_max_retries():
    slept: list[float] = []

    def always_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)  # no Retry-After -> exponential back-off

    client = _client(always_429, sleep_fn=slept.append, max_retries=2)

    with pytest.raises(httpx.HTTPStatusError):
        client.get_account("Faker#KR1")

    # 2 retries means 2 sleeps, following the back-off curve (0.5, then 1.0).
    assert slept == [0.5, 1.0]
