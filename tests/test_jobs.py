"""Tests for the in-process job queue and background worker.

We start a real worker thread, enqueue work, and poll the store until the job
settles — exactly how the HTTP layer uses it.
"""

import threading
import time

from app.jobs import DONE, ERROR, JobQueue, JobStore


def _wait_for(predicate, timeout=2.0):
    """Poll until predicate() is true or we time out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_worker_runs_job_to_done():
    store = JobStore()
    handled: list[str] = []

    def handler(job):
        handled.append(job.riot_id)
        return "PUUID-FOR-" + job.riot_id

    q = JobQueue(handler, store)
    q.start()
    try:
        job = q.enqueue("Faker#KR1")
        assert _wait_for(lambda: store.get(job.id).status == DONE)
    finally:
        q.stop()

    finished = store.get(job.id)
    assert finished.status == DONE
    assert finished.result == "PUUID-FOR-Faker#KR1"
    assert handled == ["Faker#KR1"]


def test_failed_job_is_recorded_and_worker_survives():
    store = JobStore()

    def handler(job):
        if job.riot_id == "boom":
            raise RuntimeError("kaboom")
        return "ok"

    q = JobQueue(handler, store)
    q.start()
    try:
        bad = q.enqueue("boom")
        assert _wait_for(lambda: store.get(bad.id).status == ERROR)
        assert "kaboom" in store.get(bad.id).error

        # The worker must keep serving after a failure.
        good = q.enqueue("fine")
        assert _wait_for(lambda: store.get(good.id).status == DONE)
        assert store.get(good.id).result == "ok"
    finally:
        q.stop()


def test_stop_is_clean():
    q = JobQueue(lambda job: None, JobStore())
    q.start()
    q.stop()  # must not hang or raise
    # The worker thread should be gone.
    assert all(t.name != "ingest-worker" or not t.is_alive() for t in threading.enumerate())
