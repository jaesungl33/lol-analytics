"""Tests for the TTL cache: hit, miss, expiry, and invalidation."""

from app.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now


def test_hit_and_miss():
    cache = TTLCache(ttl_seconds=10)
    assert cache.get("absent") is None
    cache.set("k", 123)
    assert cache.get("k") == 123


def test_can_cache_falsy_values():
    # The sentinel design means storing 0/None/"" is still a hit, not a miss.
    cache = TTLCache(ttl_seconds=10)
    cache.set("zero", 0)
    assert cache.get("zero", default="MISS") == 0


def test_entries_expire():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=5, time_fn=clock.time)
    cache.set("k", "v")

    clock.now = 4.9
    assert cache.get("k") == "v"   # still fresh

    clock.now = 5.0
    assert cache.get("k") is None  # ttl reached -> expired


def test_delete_invalidates():
    cache = TTLCache(ttl_seconds=10)
    cache.set("k", "v")
    cache.delete("k")
    assert cache.get("k") is None
    cache.delete("k")  # deleting a missing key is a no-op, not an error
