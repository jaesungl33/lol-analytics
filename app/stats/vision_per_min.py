"""Vision per minute.

Vision score measures map awareness: wards placed, wards cleared, and time the
enemy spent revealed by your wards. Like CS/min, it only means something per
minute, because a 40-minute game has more time to accumulate vision than a
20-minute one. So we normalise by game length, then average across games.

Deliberately the same shape as cs_per_min.py — pure function, GameRow in,
MetricResult out — so it slots into the engine the same way.

Spec:
    vision/min for one game = vision_score / (game_duration / 60)
    headline value          = average of the per-game vision/min values
    skip any game where game_duration <= 0  (remakes report 0 duration)
    round per-game values and the average to 2 decimals
"""

from app.stats import GameRow, MetricResult, PerGameValue


def vision_per_minute(games: list[GameRow]) -> MetricResult:
    per_game: list[PerGameValue] = []

    for g in games:
        # Same guard as cs_per_minute: a remake reports 0 duration, and we must
        # never divide by zero or let a non-game pollute the average.
        if g.game_duration <= 0:
            continue
        minutes = g.game_duration / 60
        per_game.append(
            PerGameValue(match_id=g.match_id, value=round(g.vision_score / minutes, 2))
        )

    # Headline number is the simple average of the per-game values.
    if per_game:
        average = round(sum(p.value for p in per_game) / len(per_game), 2)
    else:
        average = 0.0

    return MetricResult(value=average, per_game=per_game)
