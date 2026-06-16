"""Grounded LLM coaching (Milestone 3).

The feature: turn a player's computed metrics into a few sentences of feedback.
The hard requirement: the feedback must be **grounded** — it may only reference
numbers we actually computed. An LLM left to its own devices will happily invent
"your CS/min of 9.2 is great" when the real number is 6.1. That's worse than
useless for a coaching tool, so we defend against it in two ways:

  1. The prompt feeds the model ONLY the computed facts and tells it not to
     introduce any other number.
  2. A deterministic checker (`advice_is_grounded`) verifies, after the fact,
     that every number in the response matches a number we gave it. This is the
     "eval" — see tests/test_coach_eval.py.

Like the RiotClient, the LLM is behind an interface with two implementations:
  * StubCoachLLM  -- deterministic, offline, no API key. The default; it's what
                     runs in tests and in fixtures mode.
  * OpenAICoachLLM -- calls an OpenAI-compatible chat endpoint over httpx (no new
                     dependency). Used only when configured with a key.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

import httpx

from app.config import settings

# Matches integers and decimals (e.g. "6", "6.1", "66.67"). We treat every such
# token in the feedback as a factual claim that must be backed by the stats.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Metric key -> human label used in the generated text.
_LABELS = {
    "cs_per_min": "CS per minute",
    "vision_per_min": "vision score per minute",
    "gold_per_min": "gold per minute",
    "kda": "KDA",
    "kill_participation": "kill participation",
    "win_rate": "win rate",
}


def _fmt(value: float) -> str:
    """Format a metric value the way it should appear in text (7.80 -> '7.8')."""
    return f"{value:g}"


def extract_facts(stats: dict) -> list[tuple[str, float]]:
    """Pull the (name, value) pairs the coach is allowed to talk about.

    Skips metrics that didn't produce a value (e.g. unimplemented ones).
    """
    facts: list[tuple[str, float]] = []
    for name, metric in stats.get("metrics", {}).items():
        value = metric.get("value")
        if value is not None:
            facts.append((name, float(value)))
    return facts


def allowed_numbers(stats: dict) -> set[float]:
    """Every number the feedback is permitted to mention.

    That's each metric's headline value, each per-game value (still real data we
    handed over), and the game count.
    """
    allowed: set[float] = {float(stats.get("games_analysed", 0))}
    for metric in stats.get("metrics", {}).values():
        value = metric.get("value")
        if value is not None:
            allowed.add(float(value))
        for per_game in metric.get("per_game", []):
            allowed.add(float(per_game["value"]))
    return allowed


def ungrounded_numbers(feedback: str, stats: dict, tolerance: float = 0.01) -> list[float]:
    """Numbers in `feedback` that don't match any number we computed.

    An empty list means the advice is fully grounded. Comparison is by value
    with a small tolerance, so "8" and "8.0" both match a stored 8.0.
    """
    allowed = allowed_numbers(stats)
    bad: list[float] = []
    for token in _NUMBER_RE.findall(feedback):
        number = float(token)
        if not any(abs(number - a) <= tolerance for a in allowed):
            bad.append(number)
    return bad


def advice_is_grounded(feedback: str, stats: dict) -> bool:
    """True iff every number in the feedback is backed by the computed stats."""
    return not ungrounded_numbers(feedback, stats)


def build_prompt(stats: dict) -> tuple[str, str]:
    """Build (system, user) messages for an LLM, embedding only the facts."""
    facts = extract_facts(stats)
    games = stats.get("games_analysed", 0)
    fact_lines = "\n".join(f"- {_LABELS.get(n, n)}: {_fmt(v)}" for n, v in facts)
    system = (
        "You are a concise League of Legends coach. You are given a player's "
        "computed statistics. Give 2-4 sentences of specific, actionable "
        "feedback. STRICT RULES: only reference the numbers provided; never "
        "invent, estimate, or introduce any statistic or number that is not in "
        "the list. Refer to metrics by name, not by made-up benchmarks."
    )
    user = f"Player statistics, averaged over {games} games:\n{fact_lines}"
    return system, user


class CoachLLM(ABC):
    @abstractmethod
    def coach(self, stats: dict) -> str:
        """Return coaching feedback grounded in `stats`."""


class StubCoachLLM(CoachLLM):
    """Deterministic, offline coach.

    It simply restates each computed metric in plain language. Crucially it
    introduces no numbers of its own, so its output is grounded by construction
    — which is exactly what makes it a reliable default and a clean test fixture.
    """

    def coach(self, stats: dict) -> str:
        facts = extract_facts(stats)
        games = stats.get("games_analysed", 0)
        if not facts:
            return "No metrics are available yet, so there's nothing to coach on."

        lines = [f"Based on your last {games} games:"]
        for name, value in facts:
            lines.append(f"- Your {_LABELS.get(name, name)} is {_fmt(value)}.")
        lines.append(
            "Pick the one metric above you most want to improve and focus your "
            "next games on it."
        )
        return "\n".join(lines)


class OpenAICoachLLM(CoachLLM):
    """Calls an OpenAI-compatible /chat/completions endpoint via httpx.

    No new dependency: we already use httpx for Riot. The base URL, key, and
    model all come from config, so this also works against any OpenAI-compatible
    gateway. The grounding checker still runs on whatever this returns.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        # transport is injectable so tests can stub the API with MockTransport.
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
            transport=transport,
        )

    def coach(self, stats: dict) -> str:
        system, user = build_prompt(stats)
        resp = self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def make_coach() -> CoachLLM:
    """Factory: real coach when configured with a key, else the safe stub."""
    if settings.coach_provider == "openai" and settings.openai_api_key:
        return OpenAICoachLLM(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.coach_model,
        )
    return StubCoachLLM()
