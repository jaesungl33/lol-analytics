"""FastAPI entrypoint.

Routes:
  GET  /                       -> the stats page (static/index.html)
  POST /api/search             -> enqueue an ingest job for any player
  GET  /api/jobs/{job_id}      -> poll a job's status
  GET  /api/stats?riot_id=...  -> compute and return a player's metrics
  POST /api/ingest             -> (kept) synchronous ingest of the configured player

The frontend never talks to Riot or the database directly — it calls these
endpoints. That boundary is what lets us swap fixtures for the live API, or the
bare page for a real frontend, without touching the other side.

Milestone 2 wiring lives in `lifespan`: one shared RiotClient (so the rate
limiter actually constrains across calls), two TTL caches, and a background
ingestion worker fed by a job queue.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.cache import TTLCache
from app.coach import advice_is_grounded, make_coach
from app.config import settings
from app.db import SessionLocal, get_db, init_db
from app.ingest import ingest_player
from app.jobs import Job, JobQueue, JobStore
from app.models import Player
from app.riot_client import Account, make_riot_client
from app.schemas import SearchRequest
from app.stats.engine import compute_player_stats

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build shared singletons on startup; tear the worker down on shutdown."""
    init_db()

    # One shared client: in live mode this is what makes the rate limiter
    # effective, since every call goes through the same token buckets.
    app.state.client = make_riot_client()
    app.state.account_cache = TTLCache(settings.cache_ttl_seconds)
    app.state.stats_cache = TTLCache(settings.cache_ttl_seconds)
    app.state.coach = make_coach()
    app.state.job_store = JobStore()

    def handle_ingest(job: Job) -> str:
        # Each job gets its own DB session (the worker runs in another thread).
        with SessionLocal() as db:
            puuid = ingest_player(db, app.state.client, job.riot_id)
        # New data landed -> drop any stale cached stats for this player.
        app.state.stats_cache.delete(puuid)
        return puuid

    app.state.job_queue = JobQueue(handle_ingest, app.state.job_store)
    app.state.job_queue.start()
    try:
        yield
    finally:
        app.state.job_queue.stop()


app = FastAPI(title="LoL Analytics — Milestone 2", lifespan=lifespan)


def _resolve_account(riot_id: str) -> Account:
    """riot_id -> Account, cached. In live mode this saves a Riot call per hit."""
    cache: TTLCache = app.state.account_cache
    cached = cache.get(riot_id)
    if cached is not None:
        return cached
    account = app.state.client.get_account(riot_id)
    cache.set(riot_id, account)
    return account


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/search")
def api_search(payload: SearchRequest) -> dict:
    """Kick off ingestion for any player; returns a job id to poll."""
    job = app.state.job_queue.enqueue(payload.riot_id)
    return {"job_id": job.id, "riot_id": job.riot_id, "status": job.status}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = app.state.job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job id")
    return {
        "job_id": job.id,
        "riot_id": job.riot_id,
        "status": job.status,
        "error": job.error,
    }


def _stats_payload(db: Session, account: Account) -> dict | None:
    """Computed stats for a player (cached), or None if they're not ingested yet."""
    player = db.get(Player, account.puuid)
    if player is None:
        return None

    cache: TTLCache = app.state.stats_cache
    cached = cache.get(account.puuid)
    if cached is not None:
        return cached

    stats = compute_player_stats(db, account.puuid)
    payload = {"riot_id": player.riot_id, "ingested": True, **stats}
    cache.set(account.puuid, payload)
    return payload


@app.get("/api/stats")
def api_stats(riot_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    riot_id = riot_id or settings.hardcoded_riot_id
    account = _resolve_account(riot_id)

    payload = _stats_payload(db, account)
    if payload is None:
        return {
            "riot_id": riot_id,
            "ingested": False,
            "hint": "POST /api/search first, then poll /api/jobs/{id}",
        }
    return payload


@app.get("/api/coach")
def api_coach(riot_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Grounded coaching: compute the stats, then have the coach speak only to them."""
    riot_id = riot_id or settings.hardcoded_riot_id
    account = _resolve_account(riot_id)

    payload = _stats_payload(db, account)
    if payload is None:
        return {
            "riot_id": riot_id,
            "ingested": False,
            "hint": "POST /api/search first, then poll /api/jobs/{id}",
        }

    feedback = app.state.coach.coach(payload)
    # We verify grounding on the way out so the client can trust the advice.
    return {
        "riot_id": payload["riot_id"],
        "ingested": True,
        "feedback": feedback,
        "grounded": advice_is_grounded(feedback, payload),
    }


@app.post("/api/ingest")
def api_ingest(db: Session = Depends(get_db)) -> dict:
    """Synchronous ingest of the configured player (kept from Milestone 1)."""
    puuid = ingest_player(db, app.state.client, settings.hardcoded_riot_id)
    app.state.stats_cache.delete(puuid)
    return {"riot_id": settings.hardcoded_riot_id, "puuid": puuid, "status": "ingested"}


# Serve any other static assets (kept last so it doesn't shadow the routes above).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
