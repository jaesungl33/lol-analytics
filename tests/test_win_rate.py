"""Tests for win_rate."""

from app.stats import GameRow
from app.stats.win_rate import win_rate


def _game(match_id: str, win: bool, duration: int = 1800) -> GameRow:
    return GameRow(
        match_id=match_id, game_duration=duration, win=win,
        kills=0, deaths=0, assists=0,
        total_minions_killed=0, neutral_minions_killed=0,
        gold_earned=0, vision_score=0,
    )


def test_all_wins():
    assert win_rate([_game("M1", True), _game("M2", True)]).value == 100.0


def test_mixed():
    # 2 wins out of 3 = 66.67%.
    games = [_game("M1", True), _game("M2", False), _game("M3", True)]
    assert win_rate(games).value == 66.67


def test_remake_skipped():
    # The remake shouldn't count toward the denominator.
    games = [_game("M1", True), _game("M2", False), _game("REMAKE", False, duration=0)]
    assert win_rate(games).value == 50.0
    assert len(win_rate(games).per_game) == 2


def test_no_games():
    assert win_rate([]).value == 0.0
