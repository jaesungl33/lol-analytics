# LoL Analytics

A League of Legends analytics platform built as a portfolio project. It pulls a player's recent matches from the Riot API, stores them in Postgres, computes performance metrics, and produces grounded LLM coaching feedback.

**Live demo:** *(link once deployed)*

---

## What it demonstrates

- **Layered architecture** — frontend → FastAPI → `RiotClient` interface → fixtures or Riot API → Postgres → stat engine. Nothing reaches across a layer boundary.
- **Dependency injection** — `RiotClient`, `CoachLLM`, and the rate limiter are all behind interfaces with swappable implementations. You change one config flag to go from sample data to the live API, or from a stub coach to GPT-4o-mini.
- **Rate limiting from scratch** — a dual token-bucket limiter (`app/ratelimit.py`) mirrors Riot's two concurrent limits (burst/s + window/2min). Clock and sleep are injectable so tests run without sleeping.
- **Async-style UX with sync code** — `POST /api/search` enqueues and returns immediately; a background worker thread ingests; the client polls `GET /api/jobs/{id}`. Built on `queue.Queue` + `threading` — zero new dependencies.
- **Pure-function metric layer** — every metric is `list[GameRow] → MetricResult`, no I/O, trivially unit-testable. Adding a metric is one file + one line in the registry.
- **Grounded LLM coaching** — the prompt feeds the model only the computed facts. A deterministic checker verifies every number in the output is backed by the stats we gave it.
- **Zero new runtime dependencies across all three milestones.** The job queue, rate limiter, cache, and LLM client are all built on the standard library + what was already installed.

---

## Architecture

```
Browser  ──POST /api/search──▶  FastAPI  ──enqueue──▶  JobQueue (worker thread)
                                                              │
Browser  ──GET /api/jobs/{id}▶  FastAPI  (poll)              │  ingest_player()
                                                              │       │
Browser  ──GET /api/stats  ──▶  FastAPI  ──▶  Stat engine    ▼       ▼
Browser  ──GET /api/coach  ──▶  FastAPI  ──▶  CoachLLM    RiotClient → Postgres
```

### Key files

```
app/
  config.py          all settings from env / .env (pydantic-settings)
  db.py              SQLAlchemy engine, session factory, init_db
  models.py          Postgres schema: players, matches, participants
  schemas.py         Pydantic request models (SearchRequest)
  riot_client.py     RiotClient ABC + FixtureRiotClient + HttpRiotClient
  ratelimit.py       TokenBucket, RiotRateLimiter, backoff_delay
  ingest.py          fetch → normalise → upsert (idempotent)
  jobs.py            Job, JobStore, JobQueue (in-process worker)
  cache.py           TTLCache (in-process, lock-guarded)
  coach.py           CoachLLM ABC + StubCoachLLM + OpenAICoachLLM + grounding eval
  stats/
    __init__.py      GameRow, MetricResult, PerGameValue types
    engine.py        load_games + compute_player_stats (METRICS registry)
    cs_per_min.py    CS per minute
    vision_per_min.py vision score per minute
    gold_per_min.py  gold per minute
    kda.py           (K+A)/max(D,1), pools totals for the headline
    win_rate.py      win percentage
    kill_participation.py  (K+A) / team kills
  main.py            FastAPI routes + lifespan wiring
fixtures/            sample_matches.json — runs the app with no Riot key
static/index.html    single-page UI
tests/               46 passing pytest tests (hermetic — SQLite, no network)
```

---

## Metrics

| Metric | Formula | Notes |
|---|---|---|
| CS/min | `(minions + monsters) / minutes` | per game, then averaged |
| Vision/min | `vision_score / minutes` | per game, then averaged |
| Gold/min | `gold_earned / minutes` | per game, then averaged |
| KDA | `(K+A) / max(D,1)` | headline pools totals to avoid blowout bias |
| Win rate | `wins / games × 100` | expressed as a percentage |
| Kill participation | `(K+A) / team_kills` | requires `team_kills` captured at ingest |

Remakes (`game_duration ≤ 0`) are skipped by every metric.

---

## Grounded coaching

`GET /api/coach` calls a `CoachLLM`:

- **Stub (default)** — deterministic, offline, no API key. Restates the computed numbers in plain language. Grounded by construction.
- **OpenAI** — calls any OpenAI-compatible `/chat/completions` endpoint via httpx. The prompt feeds the model *only* the computed facts and forbids inventing numbers.

Either way, `advice_is_grounded(feedback, stats)` checks that every number in the output matches a number from the stats payload. The `grounded` flag is returned alongside the advice. See `tests/test_coach_eval.py` for the eval suite.

---

## Run it locally

Prerequisites: Python 3.11+, Docker.

```bash
# 1. Start Postgres
docker compose up -d

# 2. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env        # defaults work as-is (fixtures + stub coach)

# 4. Run
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000). Type `SamplePlayer#NA1` and click **Search** — the app ingests the fixture data, computes all six metrics, and shows them. Click **Coach me** for feedback grounded in those numbers.

### Switch to live Riot data

1. Get a dev key at [developer.riotgames.com](https://developer.riotgames.com/) (expires every 24h; apply for a production key for a permanent deployment).
2. In `.env`:
   ```
   USE_FIXTURES=false
   RIOT_API_KEY=RGAPI-your-key-here
   RIOT_REGION=americas          # or asia / europe
   ```
3. Restart. Same endpoints, same page — only the data source changes.

### Enable real LLM coaching

```
COACH_PROVIDER=openai
OPENAI_API_KEY=sk-...
COACH_MODEL=gpt-4o-mini         # or any OpenAI-compatible model
```

The grounding check still runs on every response.

---

## Tests

```bash
pytest
```

46 tests, all passing. The suite is hermetic: metric tests build `GameRow` objects by hand; the pipeline and API tests use in-memory SQLite. No Riot key, no network, no Docker required.

---

## Deploy (Railway)

Railway is the fastest path: it auto-provisions Postgres and injects `DATABASE_URL`.

1. Push this repo to GitHub.
2. Create a new Railway project → **Deploy from GitHub repo**.
3. Add a **Postgres** plugin — Railway sets `DATABASE_URL` automatically.
4. Add environment variables in the Railway dashboard:
   ```
   USE_FIXTURES=true             # or false if you have a Riot key
   HARDCODED_RIOT_ID=SamplePlayer#NA1
   ```
5. Deploy. Railway reads the `Procfile` and runs:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

The app creates its tables on startup (`init_db`). No migration step needed for a fresh database.

> **Schema note:** Milestone 3 added a `team_kills` column to `participants`. If you're upgrading an existing Postgres database (rather than starting fresh), you need to add it manually or drop and recreate the volume: `docker compose down -v && docker compose up -d`.

---

## Known limitations / upgrade path

| Current | Upgrade |
|---|---|
| In-process job queue (lost on restart) | Redis + RQ |
| In-process TTL cache (not shared across workers) | Redis |
| `create_all` schema management | Alembic migrations |
| Dev Riot key (expires 24h) | Riot Production Application key |
| Single region (`americas`) | Per-request region routing |

These are documented trade-offs, not oversights — the current choices keep the dependency count at zero and every component explainable line by line.

---

## Milestones

- **M1** ✅ — fixtures → ingest → CS/min + vision/min → bare page
- **M2** ✅ — rate limiter, job queue, caching, search any player
- **M3** ✅ — 6 metrics, grounded LLM coaching + eval
- **M4** — frontend polish, rate-limit design writeup
