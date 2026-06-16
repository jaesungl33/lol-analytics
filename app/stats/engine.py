"""The stat engine: turn stored rows into a dict of metric results.

It does two jobs:
  1. Load the player's games out of Postgres and convert them to GameRow.
  2. Run every registered metric and collect the results.

Adding a metric later = write the function + add one line to METRICS. The
engine never changes. If a metric isn't implemented yet (raises
NotImplementedError), we record that instead of crashing the whole request.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import Match, Participant
from app.stats import GameRow, MetricResult
from app.stats.cs_per_min import cs_per_minute
from app.stats.gold_per_min import gold_per_minute
from app.stats.kda import kda
from app.stats.kill_participation import kill_participation
from app.stats.vision_per_min import vision_per_minute
from app.stats.win_rate import win_rate

# name shown in the API -> the function that computes it.
# Adding a metric is exactly this: write the pure function, add one line here.
METRICS: dict[str, Callable[[list[GameRow]], MetricResult]] = {
    "cs_per_min": cs_per_minute,
    "vision_per_min": vision_per_minute,
    "gold_per_min": gold_per_minute,
    "kda": kda,
    "kill_participation": kill_participation,
    "win_rate": win_rate,
}


def load_games(db: Session, puuid: str) -> list[GameRow]:
    rows = (
        db.query(Participant, Match)
        .join(Match, Participant.match_id == Match.match_id)
        .filter(Participant.puuid == puuid)
        .order_by(Match.game_creation.desc())
        .all()
    )
    return [
        GameRow(
            match_id=p.match_id,
            game_duration=m.game_duration,
            win=p.win,
            kills=p.kills,
            deaths=p.deaths,
            assists=p.assists,
            total_minions_killed=p.total_minions_killed,
            neutral_minions_killed=p.neutral_minions_killed,
            gold_earned=p.gold_earned,
            vision_score=p.vision_score,
            team_kills=p.team_kills,
        )
        for p, m in rows
    ]


def compute_player_stats(db: Session, puuid: str) -> dict:
    games = load_games(db, puuid)
    results: dict = {"games_analysed": len(games), "metrics": {}}

    for name, fn in METRICS.items():
        try:
            r = fn(games)
            results["metrics"][name] = {
                "value": r.value,
                "per_game": [{"match_id": pg.match_id, "value": pg.value} for pg in r.per_game],
            }
        except NotImplementedError:
            results["metrics"][name] = {"value": None, "status": "not implemented yet"}

    return results
