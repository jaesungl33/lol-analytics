"""Win rate — percentage of games won.

The simplest metric, and a useful sanity check on everything else. We express it
as a percentage (0–100) so the page reads naturally ("60.0").

Implementation note: we reuse the same "average of per-game values" shape as the
other metrics by scoring each game 100.0 for a win and 0.0 for a loss — the
average of those is exactly the win percentage. Remakes (duration <= 0) are
skipped because they aren't real wins or losses.
"""

from app.stats import GameRow, MetricResult, PerGameValue


def win_rate(games: list[GameRow]) -> MetricResult:
    per_game: list[PerGameValue] = []

    for g in games:
        if g.game_duration <= 0:
            continue
        per_game.append(
            PerGameValue(match_id=g.match_id, value=100.0 if g.win else 0.0)
        )

    if per_game:
        average = round(sum(p.value for p in per_game) / len(per_game), 2)
    else:
        average = 0.0

    return MetricResult(value=average, per_game=per_game)
