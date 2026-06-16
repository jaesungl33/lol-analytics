"""Gold per minute.

Gold earned measures overall economic output: last-hits, kills, assists,
objectives, and passive income all roll into it. Like CS, it only compares
fairly once normalised by game length, so we divide by minutes and average.

Same pure-function shape as cs_per_min.py.

Spec:
    gold/min for one game = gold_earned / (game_duration / 60)
    headline value        = average of the per-game gold/min values
    skip any game where game_duration <= 0
    round per-game values and the average to 2 decimals
"""

from app.stats import GameRow, MetricResult, PerGameValue


def gold_per_minute(games: list[GameRow]) -> MetricResult:
    per_game: list[PerGameValue] = []

    for g in games:
        if g.game_duration <= 0:
            continue
        minutes = g.game_duration / 60
        per_game.append(
            PerGameValue(match_id=g.match_id, value=round(g.gold_earned / minutes, 2))
        )

    if per_game:
        average = round(sum(p.value for p in per_game) / len(per_game), 2)
    else:
        average = 0.0

    return MetricResult(value=average, per_game=per_game)
