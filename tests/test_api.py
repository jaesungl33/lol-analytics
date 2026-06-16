"""End-to-end HTTP test of the real FastAPI app (Milestones 2 + 3).

We can't run Postgres in CI here, so we repoint the app's database at in-memory
SQLite, then exercise the actual routes through FastAPI's TestClient: enqueue an
ingest job, let the background worker run it, read the computed stats, and get
grounded coaching. This is the closest hermetic check to "does the whole thing
boot and work" without Docker.
"""

import time

import app.db
import app.main
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RIOT_ID = "SamplePlayer#NA1"


def _point_app_at_sqlite():
    """Rebind the app's engine/session to a shared in-memory SQLite database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    # init_db() and get_db() read these module globals; the worker uses the copy
    # imported into app.main, so patch both.
    app.db.engine = engine
    app.db.SessionLocal = SessionLocal
    app.main.SessionLocal = SessionLocal


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    status = {}
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.02)
    return status


def test_search_then_stats_then_coach():
    _point_app_at_sqlite()

    # TestClient as a context manager runs the lifespan (init_db + worker start).
    with TestClient(app.main.app) as client:
        # 1. Enqueue ingestion for the player.
        res = client.post("/api/search", json={"riot_id": RIOT_ID})
        assert res.status_code == 200
        job_id = res.json()["job_id"]

        # 2. The background worker should finish it.
        status = _wait_for_job(client, job_id)
        assert status["status"] == "done", status

        # 3. Stats are computed from the stored rows. (Pass riot_id via params so
        #    the '#' in the tag is encoded, not treated as a URL fragment.)
        stats = client.get("/api/stats", params={"riot_id": RIOT_ID}).json()
        assert stats["ingested"] is True
        assert stats["games_analysed"] == 6
        assert stats["metrics"]["cs_per_min"]["value"] > 0
        assert stats["metrics"]["kill_participation"]["value"] > 0

        # 4. Coaching is grounded in those numbers.
        coach = client.get("/api/coach", params={"riot_id": RIOT_ID}).json()
        assert coach["ingested"] is True
        assert coach["grounded"] is True
        assert coach["feedback"]


def test_search_rejects_bad_riot_id():
    _point_app_at_sqlite()
    with TestClient(app.main.app) as client:
        res = client.post("/api/search", json={"riot_id": "no-tag-here"})
        assert res.status_code == 422  # validation error from SearchRequest
