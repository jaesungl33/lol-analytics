"""Tests for kill_participation."""

from app.stats import GameRow
from app.stats.kill_participation import kill_participation


def _game(
    match_id: str, k: int, a: int, team_kills: int, duration: int = 1800
) -> GameRow:
    return GameRow(
        match_id=match_id, game_duration=duration, win=True,
        kills=k, deaths=0, assists=a,
        total_minions_killed=0, neutral_minions_killed=0,
        gold_earned=0, vision_score=0, team_kills=team_kills,
    )


def test_single_game():
    # (5 + 5) / 20 = 0.5
    assert kill_participation([_game("M1", 5, 5, 20)]).value == 0.5


def test_average_across_games():
    # 0.5 and 0.8 average to 0.65.
    games = [_game("M1", 5, 5, 20), _game("M2", 4, 4, 10)]
    assert kill_participation(games).value == 0.65


def test_zero_team_kills_is_skipped():
    # No team kills -> undefined ratio; skip rather than divide by zero.
    games = [_game("M1", 5, 5, 20), _game("M2", 0, 0, 0)]
    result = kill_participation(games)
    assert len(result.per_game) == 1
    assert result.value == 0.5


def test_remake_skipped():
    games = [_game("M1", 5, 5, 20), _game("REMAKE", 1, 1, 5, duration=0)]
    assert len(kill_participation(games).per_game) == 1


def test_no_games():
    assert kill_participation([]).value == 0.0
