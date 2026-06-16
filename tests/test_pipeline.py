"""End-to-end fixture pipeline test: ingest -> store -> engine -> metrics.

This proves the whole vertical slice works with no Riot key and no Postgres.
We point SQLAlchemy at an in-memory SQLite database instead of Postgres so the
test is hermetic (no Docker required) and fast. The ORM models are portable, so
this exercises the real ingest + engine code paths, just against a different
backend.

Trade-off: SQLite doesn't cover Postgres-specific behaviour — but we don't use
any yet, so this is the right level of test for Milestone 1.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest import ingest_player
from app.riot_client import FixtureRiotClient
from app.stats.engine import compute_player_stats

RIOT_ID = "SamplePlayer#NA1"


def _make_session():
    # StaticPool keeps a single in-memory connection alive so the schema we
    # create is visible to every session in the test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_fixture_pipeline_end_to_end():
    db = _make_session()
    client = FixtureRiotClient()

    puuid = ingest_player(db, client, RIOT_ID)
    assert puuid == "FIXTURE-PUUID-0001"

    stats = compute_player_stats(db, puuid)

    # All six fixture games were stored and analysed.
    assert stats["games_analysed"] == 6

    # Both metrics now produce real numbers (vision is no longer a TODO).
    cs = stats["metrics"]["cs_per_min"]
    vision = stats["metrics"]["vision_per_min"]
    assert cs["value"] > 0
    assert vision["value"] > 0
    assert "status" not in vision  # i.e. not "not implemented yet"
    assert len(vision["per_game"]) == 6


def test_ingest_is_idempotent():
    # Running ingest twice must not double-count the player's games.
    db = _make_session()
    client = FixtureRiotClient()

    ingest_player(db, client, RIOT_ID)
    ingest_player(db, client, RIOT_ID)

    stats = compute_player_stats(db, "FIXTURE-PUUID-0001")
    assert stats["games_analysed"] == 6
