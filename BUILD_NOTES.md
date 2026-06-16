# BUILD_NOTES.md

Running log of what we built, the key decisions, and the trade-offs — one
section per milestone. Read top to bottom to understand the whole system.

A note that holds across all milestones: **we added zero new runtime
dependencies.** The job queue, rate limiter, and cache are built on the Python
standard library (`queue`, `threading`, `time`); the LLM coach talks to an
OpenAI-compatible endpoint over the `httpx` we already had. Fewer moving parts
to explain and deploy.

---

## Milestone 1 — finish the thin slice

- **Implemented `vision_per_minute`** (`app/stats/vision_per_min.py`) as a pure
  function with the exact same shape as the `cs_per_minute` worked example:
  `vision_score / (duration/60)` per game, averaged, skipping `duration <= 0`
  remakes, rounded to 2dp. Keeping the shape identical means the engine treats
  every metric the same and adding one is a one-line registry change.
- **Un-skipped the vision tests** and added a `test_no_games` case to match the
  CS/min test suite, so the metric is covered for the single-game, multi-game,
  remake, and empty-input paths.
- **Added an end-to-end pipeline test** (`tests/test_pipeline.py`) that runs
  `ingest_player(FixtureRiotClient) -> compute_player_stats` against an
  **in-memory SQLite** database. This proves the full slice (fetch -> store ->
  engine -> metrics) works with no Riot key and no Docker, and it also asserts
  ingestion is idempotent (running it twice doesn't double-count games).
- **Key decision:** test against SQLite, not Postgres, so `pytest` is hermetic
  and fast. **Trade-off:** it doesn't exercise Postgres-specific behaviour — but
  we don't rely on any yet, so this is the right level of test for M1.
- **Boundaries held:** the metric stays pure (data in, number out, no I/O); the
  data source stays behind the `RiotClient` interface; nothing new reaches
  across a layer.

---

## Milestone 2 — rate-limited worker + job queue + caching (search any player)

- **Token-bucket rate limiter** (`app/ratelimit.py`). `TokenBucket` caps
  throughput at `refill_per_second` while allowing a burst up to `capacity`;
  `acquire()` blocks just long enough for the next token. `RiotRateLimiter`
  composes **two** buckets to mirror Riot's dual limits (20/s burst + 100/2min
  window) and requires a token from both. The clock and sleep are injectable so
  tests run deterministically.
- **429 back-off wired into `HttpRiotClient._get`** (the old `NOTE (Milestone
  2)` marker). Every call waits on the limiter first; on a 429 it sleeps for the
  `Retry-After` header if Riot sent one, otherwise exponential back-off
  (`base*2**attempt`, capped), retrying up to `http_max_retries`. The limiter,
  HTTP transport, and sleep fn are constructor-injected so tests use a no-op
  limiter + `httpx.MockTransport` + a fake clock — no network, no real waiting.
- **In-process job queue** (`app/jobs.py`): `queue.Queue` + one daemon worker
  thread + an in-memory `JobStore` (`queued → running → done/error`). `POST
  /api/search` enqueues and returns a job id; the worker ingests in the
  background; the client polls `GET /api/jobs/{id}`. A failing job is recorded
  as `error` and the worker keeps serving.
- **TTL cache** (`app/cache.py`): a lock-guarded dict with per-entry expiry,
  used for `riot_id → account` look-ups and computed stats. Uses a sentinel so
  falsy values still count as hits; ingest invalidates a player's cached stats.
- **Wiring** (`app/main.py`): a FastAPI `lifespan` builds one **shared**
  RiotClient (so the limiter actually constrains across calls), both caches, and
  starts/stops the worker. New/updated routes: `POST /api/search`,
  `GET /api/jobs/{id}`, `GET /api/stats?riot_id=...`. The frontend gained a
  search box that enqueues, polls, then renders — still API-only. Replaced the
  deprecated `on_event("startup")` with `lifespan` since the worker needs
  start *and* shutdown.
- **Key decisions / trade-offs:** in-process queue + cache instead of
  Redis/Celery → **zero new dependencies** and fully explainable, at the cost of
  not surviving a restart or spanning multiple processes (documented upgrade
  path: Redis/RQ). Stayed **synchronous** (a worker *thread*, sync httpx),
  consistent with CLAUDE.md; the limiter blocks the worker thread, not an event
  loop. No schema change this milestone — re-ingest is idempotent and stats are
  cached, so a persistent `last_ingested_at` was deferred.
- **Running the app** now needs Postgres (`docker compose up -d`) because
  `lifespan` calls `init_db()` against `DATABASE_URL`. Tests stay hermetic: the
  pipeline test uses SQLite, and the M2 unit tests don't touch a DB at all.

---

## Milestone 3 — more metrics + grounded LLM coaching + eval

- **Four new pure-function metrics**, each its own file and one line in the
  `METRICS` registry (engine untouched):
  * `gold_per_min` — economy, normalised by game length.
  * `kda` — `(K+A)/max(D,1)`; the headline **pools totals**
    (`(ΣK+ΣA)/max(ΣD,1)`) rather than averaging per-game ratios, so one blowout
    game doesn't dominate. Per-game ratios are still shown.
  * `win_rate` — percentage, computed as the average of per-game 100/0 scores so
    it reuses the same shape as the others.
  * `kill_participation` — `(K+A)/team_kills`.
- **`team_kills` schema extension** (the one schema touch this milestone). A
  single player's row has no team context, so kill participation was impossible
  with the old shape. We added `team_kills` to `ParticipantData`, the
  `participants` table, and `GameRow` (defaulted to 0 so existing call sites and
  tests keep working). `HttpRiotClient` sums kills for the player's `teamId`;
  fixtures gained realistic values. **Trade-off:** `create_all` won't add the
  column to an existing Postgres table — fine in dev (reset the volume); Alembic
  is the real fix, noted for later.
- **Grounded coaching** (`app/coach.py`). The `CoachLLM` interface has two
  implementations, mirroring the RiotClient pattern: `StubCoachLLM` (default,
  offline, deterministic — restates the real numbers and nothing else, so it's
  grounded by construction) and `OpenAICoachLLM` (calls an OpenAI-compatible
  `/chat/completions` over **httpx**, no new dependency; base URL/key/model from
  config). The prompt feeds the model ONLY the computed facts and forbids
  inventing numbers.
- **The grounding guard + eval.** `advice_is_grounded(feedback, stats)` extracts
  every number from the feedback and checks each against the set of numbers we
  actually computed (headline values, per-game values, game count) within a
  tolerance. `GET /api/coach` returns this `grounded` flag alongside the advice.
  `tests/test_coach_eval.py` is the eval: it proves grounded advice (including
  the stub and a hand-written example) passes, a fabricated number is caught,
  and — via a stubbed OpenAI response — that the eval catches a *hallucinated*
  number coming out of the real LLM code path, all offline.
  **Limitation (documented):** the check verifies *numeric* grounding, not
  semantic correctness.
- **Wiring + tests.** Added `GET /api/coach` and a "Coach me" button (API-only).
  Added unit tests for all four metrics and a hermetic full-app HTTP test
  (`tests/test_api.py`) that drives the real FastAPI routes against in-memory
  SQLite: search → background worker → stats → grounded coaching.
- **Final test status:** `46 passed`. Still **zero new runtime dependencies**
  across M1–M3. (README polish is intentionally left for M4.)
