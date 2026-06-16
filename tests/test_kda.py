"""Tests for kda."""

from app.stats import GameRow
from app.stats.kda import kda


def _game(match_id: str, k: int, d: int, a: int, duration: int = 1800) -> GameRow:
    return GameRow(
        match_id=match_id, game_duration=duration, win=True,
        kills=k, deaths=d, assists=a,
        total_minions_killed=0, neutral_minions_killed=0,
        gold_earned=0, vision_score=0,
    )


def test_single_game():
    # (5 + 5) / 2 = 5.0
    assert kda([_game("M1", 5, 2, 5)]).value == 5.0


def test_perfect_game_no_divide_by_zero():
    # 0 deaths is treated as 1: (10 + 4) / 1 = 14.0
    assert kda([_game("M1", 10, 0, 4)]).value == 14.0


def test_headline_pools_totals_not_ratio_average():
    # Game A: (10+0)/max(0,1) = 10.0 per-game.
    # Game B: (0+0)/2        = 0.0  per-game.
    # Averaging ratios would give 5.0, but pooling totals gives the honest
    # number: (10 + 0) / max(2, 1) = 5.0 ... so pick values that differ:
    #   A: 10/0/0 -> per-game ratio 10.0
    #   B: 2/4/2  -> per-game ratio (2+2)/4 = 1.0
    # ratio-average = 5.5; pooled = (12 + 2) / 4 = 3.5  <-- what we assert.
    games = [_game("A", 10, 0, 0), _game("B", 2, 4, 2)]
    result = kda(games)
    assert [pg.value for pg in result.per_game] == [10.0, 1.0]
    assert result.value == 3.5


def test_remake_skipped():
    games = [_game("M1", 5, 2, 5), _game("REMAKE", 9, 9, 9, duration=0)]
    result = kda(games)
    assert len(result.per_game) == 1
    assert result.value == 5.0


def test_no_games():
    assert kda([]).value == 0.0
