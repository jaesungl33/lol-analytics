"""An in-process job queue with a background worker (Milestone 2).

Why this exists
---------------
Ingesting a player can be slow: under live mode each match is a separate Riot
call, and the rate limiter may deliberately make us wait. We don't want the HTTP
request that triggered the search to block for all of that. So `POST /api/search`
just *enqueues* an ingest job and returns a job id immediately; a background
worker thread does the slow work; the client polls `GET /api/jobs/{id}` for
progress.

Design choice: this is the standard-library `queue.Queue` plus one worker
thread, not Celery/RQ + Redis. Pros: zero new dependencies, and you can read the
whole thing top to bottom. Cons (documented in BUILD_NOTES): jobs live in memory
in a single process, so they don't survive a restart and don't fan out across
multiple processes. The clean upgrade is to back this with Redis/RQ.

The queue is deliberately ignorant of *what* a job does — it's handed a
`handler` callable. The wiring in `main.py` supplies a handler that opens a DB
session and runs ingestion, which keeps this module free of DB/Riot details.
"""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

# Job lifecycle states.
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
ERROR = "error"


@dataclass
class Job:
    id: str
    riot_id: str
    status: str = QUEUED
    error: str | None = None
    result: str | None = None  # the player's puuid once ingestion succeeds


class JobStore:
    """Thread-safe registry of jobs by id.

    Reads return the live `Job` object; attribute reads are cheap and the worker
    only mutates jobs through `update()` under the lock, so a poller seeing a
    half-updated job isn't a concern in practice.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, riot_id: str) -> Job:
        job = Job(id=uuid.uuid4().hex, riot_id=riot_id)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: object) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            return job


class JobQueue:
    """A single-worker background queue.

    `handler(job) -> result` runs the actual work; whatever it returns is stored
    on the job as `result`, and any exception is captured as `error` instead of
    crashing the worker thread.
    """

    # Unique sentinel pushed onto the queue to tell the worker to stop.
    _STOP = object()

    def __init__(self, handler: Callable[[Job], object], store: JobStore) -> None:
        self._handler = handler
        self._store = store
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="ingest-worker", daemon=True
        )
        self._thread.start()

    def enqueue(self, riot_id: str) -> Job:
        job = self._store.create(riot_id)
        self._queue.put(job.id)
        return job

    def stop(self) -> None:
        """Ask the worker to finish the current job and exit (used on shutdown)."""
        if self._thread is None:
            return
        self._queue.put(self._STOP)
        self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return
                self._process(item)
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        self._store.update(job_id, status=RUNNING)
        job = self._store.get(job_id)
        assert job is not None  # we just created it; it can't be gone
        try:
            result = self._handler(job)
            self._store.update(job_id, status=DONE, result=result)
        except Exception as exc:  # noqa: BLE001 - we want to record ANY failure
            # A failed job must not kill the worker; record it and keep serving.
            self._store.update(job_id, status=ERROR, error=str(exc))
