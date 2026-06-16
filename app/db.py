"""Database wiring.

We use SQLAlchemy's ORM. `Base` is the parent class every table model
inherits from; `engine` is the live connection to Postgres; `SessionLocal`
hands out short-lived sessions (one per request).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """All ORM models inherit from this."""


engine = create_engine(settings.database_url, echo=False, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they don't exist yet.

    For Milestone 1 this is fine. Once the schema starts changing in
    Milestone 2+, graduate to a migration tool (Alembic) instead.
    """
    # Importing models here ensures they're registered on Base before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
