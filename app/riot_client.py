"""Talking to the data source.

Key design idea: the rest of the app never calls Riot directly. It depends on
the `RiotClient` *interface*. We provide two implementations:

  FixtureRiotClient -- reads sample_matches.json. No network, no API key.
  HttpRiotClient    -- the real thing, talks to Riot's servers.

This is dependency injection. Because everything downstream only knows about
the interface, you can develop and test against fixtures and flip to live data
by changing one config flag. In Milestone 2 the HttpRiotClient is exactly where
the rate limiter and retry/back-off logic will live (see the TODO markers).
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings
from app.ratelimit import RiotRateLimiter, backoff_delay, make_riot_rate_limiter

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "sample_matches.json"


# --- Normalised shapes ------------------------------------------------------
# Both clients return these. Riot's real JSON is deeply nested and noisy; we
# flatten it to exactly the fields we store. Downstream code never sees raw
# Riot JSON, only these clean dataclasses.

@dataclass
class ParticipantData:
    puuid: str
    champion: str
    win: bool
    kills: int
    deaths: int
    assists: int
    total_minions_killed: int
    neutral_minions_killed: int
    gold_earned: int
    vision_score: int
    # Total kills by OUR player's team in this game. Needed for kill
    # participation = (our kills + assists) / team kills. We capture team
    # context here so downstream code never has to re-derive it from raw JSON.
    team_kills: int


@dataclass
class MatchData:
    match_id: str
    game_creation: int  # epoch ms
    game_duration: int  # seconds
    queue_id: int
    participant: ParticipantData  # just OUR player's row in this match


@dataclass
class Account:
    puuid: str
    game_name: str
    tag_line: str


# --- Interface --------------------------------------------------------------

class RiotClient(ABC):
    @abstractmethod
    def get_account(self, riot_id: str) -> Account:
        """Resolve 'GameName#TAG' to an account (puuid + name parts)."""

    @abstractmethod
    def get_recent_matches(self, puuid: str, count: int = 10) -> list[MatchData]:
        """Return the player's most recent `count` matches, newest first."""


# --- Fixture implementation -------------------------------------------------

class FixtureRiotClient(RiotClient):
    def __init__(self, fixture_path: Path = FIXTURE_PATH) -> None:
        self._data = json.loads(fixture_path.read_text())

    def get_account(self, riot_id: str) -> Account:
        acct = self._data["accounts"].get(riot_id)
        if acct is None:
            raise ValueError(f"No fixture account for {riot_id!r}")
        return Account(**acct)

    def get_recent_matches(self, puuid: str, count: int = 10) -> list[MatchData]:
        raw_matches = self._data["matches_by_puuid"].get(puuid, [])
        matches = [self._to_match_data(m) for m in raw_matches]
        return matches[:count]

    @staticmethod
    def _to_match_data(raw: dict) -> MatchData:
        return MatchData(
            match_id=raw["match_id"],
            game_creation=raw["game_creation"],
            game_duration=raw["game_duration"],
            queue_id=raw["queue_id"],
            participant=ParticipantData(**raw["participant"]),
        )


# --- Real HTTP implementation ----------------------------------------------

class HttpRiotClient(RiotClient):
    """Live Riot API client. Only used when USE_FIXTURES=false.

    Endpoints (region = americas | asia | europe):
      account: GET https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}
      ids:     GET https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?count={n}
      match:   GET https://{region}.api.riotgames.com/lol/match/v5/matches/{matchId}
    Auth header on every call: X-Riot-Token: {api_key}
    """

    def __init__(
        self,
        api_key: str,
        region: str,
        *,
        limiter: RiotRateLimiter | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        max_retries: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("RIOT_API_KEY is empty. Set it or use USE_FIXTURES=true.")
        self._region = region
        # The rate limiter and sleep function are injected so tests can supply a
        # no-op limiter and a fake clock. `transport` lets tests stub HTTP with
        # httpx.MockTransport instead of hitting the network.
        self._limiter = limiter if limiter is not None else make_riot_rate_limiter()
        self._sleep = sleep_fn
        self._max_retries = (
            max_retries if max_retries is not None else settings.http_max_retries
        )
        self._client = httpx.Client(
            base_url=f"https://{region}.api.riotgames.com",
            headers={"X-Riot-Token": api_key},
            timeout=10.0,
            transport=transport,
        )

    # Milestone 2: every call first waits for the rate limiter, then honours a
    # 429 by sleeping (Retry-After if present, else exponential back-off) and
    # retrying up to `max_retries` times. This is the single most important
    # upgrade over the naive "fire and raise" client.
    def _get(self, path: str, **params) -> dict:
        last_resp: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()  # block until both rate-limit buckets allow it
            resp = self._client.get(path, params=params)
            last_resp = resp

            if resp.status_code == 429 and attempt < self._max_retries:
                self._sleep(self._retry_delay(resp, attempt))
                continue

            resp.raise_for_status()
            return resp.json()

        # Retries exhausted while still seeing 429: surface the error.
        assert last_resp is not None
        last_resp.raise_for_status()
        return last_resp.json()  # unreachable, but keeps the type checker happy

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        """How long to wait before retrying a 429.

        Riot tells us exactly how long via `Retry-After` (in seconds); honour it
        when present. Otherwise fall back to exponential back-off.
        """
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass  # malformed header -> fall through to back-off
        return backoff_delay(
            attempt, settings.backoff_base_seconds, settings.backoff_cap_seconds
        )

    def get_account(self, riot_id: str) -> Account:
        name, tag = riot_id.split("#", 1)
        data = self._get(f"/riot/account/v1/accounts/by-riot-id/{name}/{tag}")
        return Account(
            puuid=data["puuid"],
            game_name=data["gameName"],
            tag_line=data["tagLine"],
        )

    def get_recent_matches(self, puuid: str, count: int = 10) -> list[MatchData]:
        ids = self._get(f"/lol/match/v5/matches/by-puuid/{puuid}/ids", count=count)
        return [self._fetch_match(mid, puuid) for mid in ids]

    def _fetch_match(self, match_id: str, puuid: str) -> MatchData:
        raw = self._get(f"/lol/match/v5/matches/{match_id}")
        info = raw["info"]
        # Find OUR player among the 10 participants.
        p = next(x for x in info["participants"] if x["puuid"] == puuid)
        # Sum kills for everyone on our player's team (teamId is 100 or 200).
        team_kills = sum(
            x["kills"] for x in info["participants"] if x["teamId"] == p["teamId"]
        )
        return MatchData(
            match_id=match_id,
            game_creation=info["gameCreation"],
            game_duration=info["gameDuration"],
            queue_id=info["queueId"],
            participant=ParticipantData(
                puuid=puuid,
                champion=p["championName"],
                win=p["win"],
                kills=p["kills"],
                deaths=p["deaths"],
                assists=p["assists"],
                total_minions_killed=p["totalMinionsKilled"],
                neutral_minions_killed=p["neutralMinionsKilled"],
                gold_earned=p["goldEarned"],
                vision_score=p["visionScore"],
                team_kills=team_kills,
            ),
        )


def make_riot_client() -> RiotClient:
    """Factory: returns the right client based on config."""
    if settings.use_fixtures:
        return FixtureRiotClient()
    return HttpRiotClient(api_key=settings.riot_api_key, region=settings.riot_region)
