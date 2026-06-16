"""Ingestion: pull a player's matches from the data source into Postgres.

For Milestone 1 this is deliberately simple and synchronous: one player, fetch,
store, done. In Milestone 2 this logic moves behind a job queue and the rate-
limited worker, but the storage shape stays the same.
"""

from sqlalchemy.orm import Session

from app.models import Match, Participant, Player
from app.riot_client import RiotClient


def ingest_player(db: Session, client: RiotClient, riot_id: str, count: int = 10) -> str:
    """Fetch and store the player's recent matches. Returns their puuid.

    Uses merge() so running it twice doesn't create duplicate rows — Riot match
    ids and the puuid are stable primary keys, so re-ingesting is idempotent
    for matches/players. (Participant rows are append-only here for simplicity;
    de-duping them is a good Milestone 2 cleanup task.)
    """
    account = client.get_account(riot_id)

    db.merge(Player(
        puuid=account.puuid,
        game_name=account.game_name,
        tag_line=account.tag_line,
    ))

    matches = client.get_recent_matches(account.puuid, count=count)

    existing_ids = {
        row.match_id
        for row in db.query(Participant.match_id).filter(
            Participant.puuid == account.puuid
        )
    }

    for m in matches:
        db.merge(Match(
            match_id=m.match_id,
            game_creation=m.game_creation,
            game_duration=m.game_duration,
            queue_id=m.queue_id,
        ))
        if m.match_id in existing_ids:
            continue  # already stored this player's row for this match
        p = m.participant
        db.add(Participant(
            match_id=m.match_id,
            puuid=p.puuid,
            champion=p.champion,
            win=p.win,
            kills=p.kills,
            deaths=p.deaths,
            assists=p.assists,
            total_minions_killed=p.total_minions_killed,
            neutral_minions_killed=p.neutral_minions_killed,
            gold_earned=p.gold_earned,
            vision_score=p.vision_score,
            team_kills=p.team_kills,
        ))

    db.commit()
    return account.puuid
