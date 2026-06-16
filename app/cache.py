"""A tiny in-process TTL cache (Milestone 2).

Why this exists
---------------
Two kinds of work are wasteful to repeat:
  * resolving the same `riot_id -> puuid` (a Riot account call), and
  * recomputing a player's metrics from rows that haven't changed.
A short-lived cache makes a second look-up of the same player cheap and keeps us
from spending rate-limit budget on data we already have.

Design choice: this is a plain in-process dict guarded by a lock, not Redis.
That keeps the dependency count at zero and is trivial to explain. The
trade-off: the cache lives in one process and is lost on restart, and it is not
shared across multiple workers. Swapping in Redis later is the upgrade path if
we ever run more than one process. (See BUILD_NOTES.)
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Sentinel so we can distinguish "missing" from a stored value of None.
_MISS = object()


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    """Key -> value with a per-cache time-to-live, in seconds.

    `time_fn` is injectable so tests can expire entries without sleeping.
    """

    def __init__(
        self,
        ttl_seconds: float,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._now = time_fn
        self._entries: dict[Any, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the cached value, or `default` if missing or expired."""
        with self._lock:
            entry = self._entries.get(key, _MISS)
            if entry is _MISS:
                return default
            if self._now() >= entry.expires_at:
                # Lazy eviction: drop it the first time we notice it's stale.
                del self._entries[key]
                return default
            return entry.value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._entries[key] = _Entry(value=value, expires_at=self._now() + self._ttl)

    def delete(self, key: Any) -> None:
        """Remove a key if present (used to invalidate stale stats after ingest)."""
        with self._lock:
            self._entries.pop(key, None)
