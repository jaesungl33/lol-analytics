"""Kill participation — share of your team's kills you were involved in.

For one game:
    kill participation = (your kills + your assists) / your team's total kills
A value of 0.65 means you got a kill or an assist on 65% of your team's kills.
It's the best single number for "how involved was this player in the action",
and it's why we added `team_kills` to the data model — a single player's row
doesn't contain team context, so we capture it at ingest time.

Design choices:
  * We skip games with team_kills <= 0 (no kills means the ratio is undefined),
    and remakes (duration <= 0).
  * The headline is the average of per-game participation, consistent with the
    other metrics. Values are ratios in roughly [0, 1], rounded to 2 decimals.
"""

from app.stats import GameRow, MetricResult, PerGameValue


def kill_participation(games: list[GameRow]) -> MetricResult:
    per_game: list[PerGameValue] = []

    for g in games:
        if g.game_duration <= 0 or g.team_kills <= 0:
            continue
        ratio = (g.kills + g.assists) / g.team_kills
        per_game.append(PerGameValue(match_id=g.match_id, value=round(ratio, 2)))

    if per_game:
        average = round(sum(p.value for p in per_game) / len(per_game), 2)
    else:
        average = 0.0

    return MetricResult(value=average, per_game=per_game)
