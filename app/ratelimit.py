"""Client-side rate limiting for the Riot API (Milestone 2).

Why this exists
---------------
Riot enforces TWO limits at once on a dev key:
  * a short burst limit  (e.g. 20 requests / 1 second), and
  * a longer window      (e.g. 100 requests / 2 minutes).
Go over either and you get HTTP 429 with a `Retry-After` header. If we just
hammered the API we'd get throttled, rate-limited, or banned. So we throttle
*ourselves* before sending, and back off politely when we still get a 429.

The tool for "N events per unit time, with a small burst allowed" is a
**token bucket**:
  * the bucket holds up to `capacity` tokens (that's the allowed burst),
  * it refills at `refill_per_second` tokens per second,
  * every request must take one token; if the bucket is empty, the caller
    waits just long enough for the next token to drip in.
Averaged over time this caps throughput at exactly the refill rate, while still
letting a short burst through when the bucket is full.

We model Riot's two limits as two buckets and require a token from *both*
(`RiotRateLimiter`). The limiter is injected into `HttpRiotClient`, which also
adds the 429 back-off — see `riot_client.py`.

Everything here is synchronous and thread-safe (a `threading.Lock` per bucket),
because the Milestone 2 ingestion worker runs in a background thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from app.config import settings


class TokenBucket:
    """A single token bucket. Thread-safe and usable on its own.

    `now_fn` and `sleep_fn` are injectable so tests can drive the clock
    deterministically instead of sleeping in real time.
    """

    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        *,
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("capacity and refill_per_second must be positive")
        self._capacity = float(capacity)
        self._refill = float(refill_per_second)
        # Start full: a fresh process is allowed its first burst immediately.
        self._tokens = float(capacity)
        self._now = now_fn
        self._sleep = sleep_fn
        self._last = now_fn()
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        """Drip in the tokens earned since we last looked. Caller holds the lock."""
        now = self._now()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill)
            self._last = now

    def acquire(self) -> None:
        """Block until a token is available, then consume it.

        We loop rather than sleep-once because `sleep` can return slightly early
        and because another thread may take the token we were waiting for.
        """
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # Not enough yet: figure out exactly how long until one token.
                deficit = 1 - self._tokens
                wait = deficit / self._refill
            self._sleep(wait)


class RiotRateLimiter:
    """Composes several buckets; a call needs a token from every one.

    We acquire the buckets in the order given (longest window first). Acquiring
    sequentially is intentionally simple: if a later bucket makes us wait, the
    earlier buckets refill during that wait, so the effective rate is bounded by
    the tightest constraint. An empty bucket list makes `acquire()` a no-op,
    which is handy in tests that only exercise the retry/back-off path.
    """

    def __init__(self, buckets: Iterable[TokenBucket]) -> None:
        self._buckets = list(buckets)

    def acquire(self) -> None:
        for bucket in self._buckets:
            bucket.acquire()


def make_riot_rate_limiter() -> RiotRateLimiter:
    """Build the live limiter from config (Riot dev-key defaults: 20/s, 100/120s)."""
    per_second = TokenBucket(
        capacity=settings.rate_limit_per_second,
        refill_per_second=settings.rate_limit_per_second,
    )
    window = settings.rate_limit_window_seconds
    per_window = TokenBucket(
        capacity=settings.rate_limit_per_two_min,
        refill_per_second=settings.rate_limit_per_two_min / window,
    )
    # Longest window first (see RiotRateLimiter docstring).
    return RiotRateLimiter([per_window, per_second])


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential back-off: base, 2*base, 4*base, ... capped at `cap`.

    Used when a 429 has no `Retry-After` header to tell us how long to wait.
    `attempt` is 0-based, so attempt 0 waits `base` seconds.
    """
    return min(cap, base * (2 ** attempt))
