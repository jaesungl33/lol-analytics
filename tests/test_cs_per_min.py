"""Tests for the worked example. Run with: pytest

These show the testing style you'll reuse for your own metric: build a couple
of GameRow objects by hand, call the function, assert the number. No database,
no network — because the metric is a pure function.
"""

from app.stats import GameRow
from app.stats.cs_per_min import cs_per_minute


def _game(match_id: str, duration: int, minions: int, monsters: int) -> GameRow:
    return GameRow(
        match_id=match_id, game_duration=duration, win=True,
        kills=0, deaths=0, assists=0,
        total_minions_killed=minions, neutral_minions_killed=monsters,
        gold_earned=0, vision_score=0,
    )


def test_single_game():
    # 240 CS over a 30-minute (1800s) game = exactly 8.0 CS/min.
    games = [_game("M1", 1800, 230, 10)]
    result = cs_per_minute(games)
    assert result.value == 8.0
    assert result.per_game[0].value == 8.0


def test_average_across_games():
    # 8.0 and 6.0 average to 7.0.
    games = [_game("M1", 1800, 230, 10), _game("M2", 1800, 170, 10)]
    result = cs_per_minute(games)
    assert result.value == 7.0


def test_zero_duration_is_skipped():
    # A remake (0 duration) must not divide-by-zero or pollute the average.
    games = [_game("M1", 1800, 230, 10), _game("REMAKE", 0, 5, 0)]
    result = cs_per_minute(games)
    assert len(result.per_game) == 1
    assert result.value == 8.0


def test_no_games():
    assert cs_per_minute([]).value == 0.0
