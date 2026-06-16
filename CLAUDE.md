# CLAUDE.md — lol-analytics

Persistent context for Claude Code and Cursor. Read this fully before planning
or editing. Everything here is load-bearing.

## What this is

A League of Legends analytics platform built as a portfolio project. It pulls a
player's recent matches from the Riot API, stores them in Postgres, computes
performance metrics, and (later) produces grounded LLM coaching.

The point is not just "a working app." It is interview evidence of three things:
1. real system architecture,
2. coding fundamentals the author can explain line by line,
3. genuine craft.

Optimize every decision for: *could the author defend this in an interview?*
Prefer the clear, defensible choice over the clever one.

## How to work with me

- I am the engineer. You are a pair-programmer and scaffolder, not an autopilot.
- **I write the core logic myself**: the metric functions in `app/stats/` and,
  in Milestone 2, the rate limiter and queue logic. **Do not implement these for
  me** unless I explicitly say "write it." If I ask about them, explain the
  approach and the trade-offs, then let me write the code.
- You own: boilerplate, wiring, FastAPI routes, the frontend, config,
  refactors, test scaffolding, docs, deployment config.
- Hard rule I hold myself to: no code is committed until I can explain every
  line and there is a test that would catch a bug in it. When you write code,
  explain it concisely and prompt me to add or extend a test.

## Workflow — plan first, always

1. When I give a task, FIRST explore the relevant files and reply with a short
   plan: files to touch, the approach, edge cases. Then STOP and wait for my OK.
2. Do not write code before I approve the plan.
3. Keep every change scoped to the task. Never refactor unrelated code uninvited.
4. After implementing, run `pytest` and report the result.
5. Prefer the smallest change that works. Flag anything that grows scope.

## Architecture — do not violate these boundaries

```
Frontend → FastAPI → RiotClient (interface) → fixtures OR Riot API
                        │
                        ▼
                    Postgres → Stat engine → (LLM coach, M3+)
```

- The frontend talks only to the FastAPI endpoints. It never calls Riot or the
  database directly.
- Nothing downstream ever sees raw Riot JSON. `RiotClient` flattens it to the
  dataclasses in `app/riot_client.py`.
- Metrics are **pure functions**: a list of `GameRow` in, a `MetricResult` out.
  No database access, no network, no side effects inside a metric.
- The Riot client is dependency-injected and chosen by the `USE_FIXTURES` flag
  (`make_riot_client()`). Keep it swappable.

## Tech stack

Python 3.11+, FastAPI, SQLAlchemy 2.0 (ORM), Postgres (Docker locally),
Pydantic v2 + pydantic-settings, httpx, pytest. Synchronous code for now —
it reads more clearly; reconsider async in Milestone 2 if the worker needs it.

## Conventions

- Type hints on every function signature.
- Module docstrings and docstrings on non-obvious functions; explain *why*, not
  just *what*.
- snake_case, small focused functions, no premature abstraction.
- All configuration comes from env via `app/config.py`. Never hardcode API keys,
  URLs, connection strings, or player ids anywhere else.
- Keep dependencies minimal. Justify any new dependency in the plan before adding.
- Adding a metric = write the pure function + register one line in `METRICS`
  in `app/stats/engine.py`. Don't change the engine for a new metric.

## Commands

- Install: `pip install -r requirements.txt`
- Database: `docker compose up -d`
- Run: `uvicorn app.main:app --reload`  (then http://localhost:8000)
- Test: `pytest`

## Layout

```
app/
  config.py        settings from env / .env
  db.py            engine, session, table creation
  models.py        the Postgres schema (SQLAlchemy): players, matches, participants
  schemas.py       reserved for M2 typed responses
  riot_client.py   RiotClient interface + Fixture + Http implementations
  ingest.py        fetch → store
  stats/
    __init__.py    GameRow / MetricResult types
    cs_per_min.py  worked example metric (the reference for all others)
    vision_per_min.py  metric stub — I implement this
    engine.py      loads games from DB, runs the metric registry
  main.py          FastAPI routes
fixtures/          sample data so the app runs with no Riot key
static/index.html  the bare page
tests/             pytest
```

## Milestones

Current: **Milestone 1** (the scaffold exists and runs on fixtures).

- **M1 (now)**: one hardcoded player → fetch → store → one metric (CS/min) →
  bare page. Immediate task: I implement `vision_per_minute` and its tests, then
  we **deploy this thin slice publicly** (Railway / Render / Fly). Deploy before
  starting M2.
- **M2**: rate-limited ingestion worker + job queue + caching; search any
  player. The rate limiter and back-off logic are MINE to write — the most
  important part of the whole project.
- **M3**: remaining metrics + a grounded LLM coaching feature, plus an eval that
  checks the advice is actually supported by the player's numbers.
- **M4**: real frontend, README polish, a short writeup of the rate-limit design.

## Out of scope — do not propose building these yet

Auth / user accounts, multiple regions at once, live match tracking,
player-vs-player comparison, historical trend charts, a mobile app. These are
all post-M3. If one seems tempting, add it to a "later" note and move on.

## Riot API notes (for M2 live mode)

- Dev keys expire every 24h. Two rate limits run at once (a per-second burst and
  a per-2-minute window); current limits arrive in response headers, and a 429
  response includes a `Retry-After` header to honor.
- Regional routing (`americas` / `asia` / `europe`) for both account-v1 and
  match-v5.
- Call chain: Riot id → puuid (account-v1) → match ids (match-v5 by-puuid) →
  match detail (match-v5). The `HttpRiotClient` already implements this; the
  rate limiter wraps its `_get` method (see the `NOTE (Milestone 2)` marker).