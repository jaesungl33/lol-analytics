"""Tests for gold_per_minute."""

from app.stats import GameRow
from app.stats.gold_per_min import gold_per_minute


def _game(match_id: str, duration: int, gold: int) -> GameRow:
    return GameRow(
        match_id=match_id, game_duration=duration, win=True,
        kills=0, deaths=0, assists=0,
        total_minions_killed=0, neutral_minions_killed=0,
        gold_earned=gold, vision_score=0,
    )


def test_single_game():
    # 12000 gold over 30 minutes (1800s) = 400 gold/min.
    result = gold_per_minute([_game("M1", 1800, 12000)])
    assert result.value == 400.0
    assert result.per_game[0].value == 400.0


def test_average_across_games():
    # 400 and 500 average to 450.
    games = [_game("M1", 1800, 12000), _game("M2", 1800, 15000)]
    assert gold_per_minute(games).value == 450.0


def test_zero_duration_is_skipped():
    games = [_game("M1", 1800, 12000), _game("REMAKE", 0, 500)]
    result = gold_per_minute(games)
    assert len(result.per_game) == 1
    assert result.value == 400.0


def test_no_games():
    assert gold_per_minute([]).value == 0.0
