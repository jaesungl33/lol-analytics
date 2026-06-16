"""The coaching eval: prove the advice is supported by the data it was given.

This is the heart of the M3 LLM feature. The risk with any LLM coach is that it
fabricates statistics. `advice_is_grounded` is our guard, and these tests prove
the guard works in both directions:
  * grounded advice (including the deterministic stub) passes, and
  * advice that cites a number we never computed fails.
The last test stubs an OpenAI-style response so we can show the eval catching a
"hallucinated" number from the real LLM code path, with no network.
"""

import httpx

from app.coach import (
    OpenAICoachLLM,
    StubCoachLLM,
    advice_is_grounded,
    ungrounded_numbers,
)

# Shaped exactly like compute_player_stats() output.
STATS = {
    "games_analysed": 6,
    "metrics": {
        "cs_per_min": {"value": 7.8, "per_game": [{"match_id": "M1", "value": 7.8}]},
        "kda": {"value": 3.5, "per_game": [{"match_id": "M1", "value": 3.5}]},
        "win_rate": {"value": 66.67, "per_game": [{"match_id": "M1", "value": 100.0}]},
        "vision_per_min": {"value": None, "status": "not implemented yet"},
    },
}


def test_stub_coach_is_grounded_by_construction():
    feedback = StubCoachLLM().coach(STATS)
    # The stub mentions the real numbers...
    assert "7.8" in feedback
    assert "66.67" in feedback
    # ...and the eval agrees nothing is fabricated.
    assert advice_is_grounded(feedback, STATS)
    assert ungrounded_numbers(feedback, STATS) == []


def test_grounded_handwritten_advice_passes():
    good = "Your CS per minute is 7.8 and your win rate is 66.67 — solid."
    assert advice_is_grounded(good, STATS)


def test_fabricated_number_is_caught():
    # 9.9 is not any computed value -> must be flagged.
    bad = "Your CS per minute of 9.9 is elite; keep it up."
    assert not advice_is_grounded(bad, STATS)
    assert 9.9 in ungrounded_numbers(bad, STATS)


def test_eval_catches_hallucination_from_llm_path():
    # Stub the chat endpoint so the real OpenAICoachLLM code runs offline and
    # returns text containing a number we never computed (a hallucination).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Your KDA of 12.0 is incredible."}}
                ]
            },
        )

    coach = OpenAICoachLLM(
        api_key="test",
        base_url="https://example.test/v1",
        model="gpt-test",
        transport=httpx.MockTransport(handler),
    )
    feedback = coach.coach(STATS)

    assert "12.0" in feedback
    # The eval flags it: 12.0 isn't among the computed stats (real KDA is 3.5).
    assert not advice_is_grounded(feedback, STATS)
