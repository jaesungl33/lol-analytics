"""Tests for vision_per_minute.

Same testing style as the CS/min tests: build a few GameRow objects by hand,
call the pure function, assert the number. No database, no network.
"""

from app.stats import GameRow
from app.stats.vision_per_min import vision_per_minute


def _game(match_id: str, duration: int, vision: int) -> GameRow:
    return GameRow(
        match_id=match_id, game_duration=duration, win=True,
        kills=0, deaths=0, assists=0,
        total_minions_killed=0, neutral_minions_killed=0,
        gold_earned=0, vision_score=vision,
    )


def test_single_game():
    # vision 30 over 30 minutes (1800s) = 1.0 vision/min.
    result = vision_per_minute([_game("M1", 1800, 30)])
    assert result.value == 1.0
    assert result.per_game[0].value == 1.0


def test_average_and_zero_duration():
    # 1.0 and 2.0 average to 1.5; the remake is skipped.
    games = [_game("M1", 1800, 30), _game("M2", 1800, 60), _game("REMAKE", 0, 5)]
    result = vision_per_minute(games)
    assert result.value == 1.5
    assert len(result.per_game) == 2


def test_no_games():
    assert vision_per_minute([]).value == 0.0
