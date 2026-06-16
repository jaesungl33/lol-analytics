"""Shared types every metric uses.

A metric is just a function: given a list of the player's games, return a
MetricResult. Keeping a consistent signature means the engine can call them all
the same way, and adding a new metric is a one-line registration.
"""

from dataclasses import dataclass


@dataclass
class GameRow:
    """One game from the player's point of view: the fields metrics need.

    The engine builds these by joining participants -> matches, so a metric
    never has to touch the database or the ORM directly. Pure data in,
    number out — which makes metrics trivial to unit-test.
    """
    match_id: str
    game_duration: int  # seconds
    win: bool
    kills: int
    deaths: int
    assists: int
    total_minions_killed: int
    neutral_minions_killed: int
    gold_earned: int
    vision_score: int
    # Defaulted so older call sites / tests that don't care about team context
    # still construct a GameRow; metrics that need it (kill participation) read
    # it explicitly.
    team_kills: int = 0


@dataclass
class PerGameValue:
    match_id: str
    value: float


@dataclass
class MetricResult:
    """An aggregate value plus the per-game breakdown that produced it."""
    value: float
    per_game: list[PerGameValue]
