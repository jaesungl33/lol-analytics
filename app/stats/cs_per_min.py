"""CS per minute -- THE WORKED EXAMPLE. Read this top to bottom.

CS ("creep score") is the number of minions and monsters a player kills.
CS/min is the classic measure of laning efficiency. We compute it per game,
then average across the player's recent games.

The math:
    cs        = total_minions_killed + neutral_minions_killed
    minutes   = game_duration_seconds / 60
    cs_per_min = cs / minutes

Notice this function:
  - takes plain data (a list of GameRow), not a database session
  - returns a plain result (MetricResult), not HTML or JSON
  - has zero side effects
That separation is what makes it easy to test and easy to explain in an
interview: "here is the formula, here is the code, they match line for line."
"""

from app.stats import GameRow, MetricResult, PerGameValue


def cs_per_minute(games: list[GameRow]) -> MetricResult:
    per_game: list[PerGameValue] = []

    for g in games:
        # Guard against a zero-length game (remakes report 0 duration).
        if g.game_duration <= 0:
            continue
        cs = g.total_minions_killed + g.neutral_minions_killed
        minutes = g.game_duration / 60
        per_game.append(PerGameValue(match_id=g.match_id, value=round(cs / minutes, 2)))

    # The headline number is the simple average of the per-game values.
    if per_game:
        average = round(sum(p.value for p in per_game) / len(per_game), 2)
    else:
        average = 0.0

    return MetricResult(value=average, per_game=per_game)
