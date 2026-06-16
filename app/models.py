"""The Postgres schema, expressed as SQLAlchemy models.

Three tables, normalised so each fact lives in exactly one place:

  players       -- one row per summoner we've looked up
  matches       -- one row per game (the parts shared by all 10 players)
  participants  -- one row per (player, match): how THIS player did in THAT game

CS/min for a player is computed by joining participants -> matches and
averaging over their recent games. Keeping match-level facts (duration) out
of the participant row avoids storing the same duration ten times.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Player(Base):
    __tablename__ = "players"

    puuid: Mapped[str] = mapped_column(String(78), primary_key=True)
    game_name: Mapped[str] = mapped_column(String(64))
    tag_line: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    participants: Mapped[list["Participant"]] = relationship(back_populates="player")

    @property
    def riot_id(self) -> str:
        return f"{self.game_name}#{self.tag_line}"


class Match(Base):
    __tablename__ = "matches"

    # Riot's match id, e.g. "NA1_1234567890"
    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    game_creation: Mapped[int] = mapped_column(BigInteger)  # epoch ms
    game_duration: Mapped[int] = mapped_column(Integer)     # seconds
    queue_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    participants: Mapped[list["Participant"]] = relationship(back_populates="match")


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"))
    puuid: Mapped[str] = mapped_column(ForeignKey("players.puuid"))

    champion: Mapped[str] = mapped_column(String(32))
    win: Mapped[bool] = mapped_column(Boolean)
    kills: Mapped[int] = mapped_column(Integer)
    deaths: Mapped[int] = mapped_column(Integer)
    assists: Mapped[int] = mapped_column(Integer)
    total_minions_killed: Mapped[int] = mapped_column(Integer)
    neutral_minions_killed: Mapped[int] = mapped_column(Integer)
    gold_earned: Mapped[int] = mapped_column(Integer)
    vision_score: Mapped[int] = mapped_column(Integer)
    # Total kills by this player's team in the game (for kill participation).
    team_kills: Mapped[int] = mapped_column(Integer, default=0)

    match: Mapped["Match"] = relationship(back_populates="participants")
    player: Mapped["Player"] = relationship(back_populates="participants")
