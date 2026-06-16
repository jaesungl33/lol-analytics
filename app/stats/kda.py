"""KDA — (kills + assists) / deaths.

KDA summarises combat efficiency: how much you contribute to kills relative to
how often you die.

Two design choices worth defending in an interview:

1. Deaths of 0. A "perfect" game would divide by zero. The convention (used by
   op.gg, etc.) is to treat 0 deaths as 1 so the number stays finite. We do that
   with `max(deaths, 1)`.

2. The headline number. Averaging per-game ratios over-weights blowout games
   (a 10/0/10 game gives a ratio of 20 that swamps everything). The more honest
   aggregate pools the totals first:
        headline = (Σ kills + Σ assists) / max(Σ deaths, 1)
   We still expose each game's own ratio in `per_game` for the breakdown.

Unlike the per-minute metrics, KDA is independent of game length, so there's no
duration normalisation — but we still skip remakes (duration <= 0), which aren't
real games.
"""

from app.stats import GameRow, MetricResult, PerGameValue


def kda(games: list[GameRow]) -> MetricResult:
    per_game: list[PerGameValue] = []
    total_kills = 0
    total_deaths = 0
    total_assists = 0

    for g in games:
        if g.game_duration <= 0:
            continue
        ratio = (g.kills + g.assists) / max(g.deaths, 1)
        per_game.append(PerGameValue(match_id=g.match_id, value=round(ratio, 2)))
        total_kills += g.kills
        total_deaths += g.deaths
        total_assists += g.assists

    if per_game:
        headline = round((total_kills + total_assists) / max(total_deaths, 1), 2)
    else:
        headline = 0.0

    return MetricResult(value=headline, per_game=per_game)
