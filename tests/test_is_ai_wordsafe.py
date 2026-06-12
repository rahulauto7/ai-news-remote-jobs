"""Part 2: word-safe is_ai() + un-poisoned _sanitize_sections backstop.

Substring matching let "rag" fire inside "tragedy" and "ai" inside "air", so
non-AI Hindu headlines (Air India crash, Kerala forests) leaked into the
indian_ai_industry section. The backstop also re-checked is_ai() on a summary
that already carried the always-AI "Automation angle: …" hook, so it never
caught the misroute.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.agent_analyze import is_ai
from tools.dedupe_and_backfill import _sanitize_sections


def test_is_ai_rejects_non_ai_india_headlines():
    assert not is_ai("Air India crash: families mourn the tragedy in Ahmedabad")
    assert not is_ai("Kerala forests face encroachment, wildlife at risk says report")


def test_is_ai_accepts_real_ai():
    assert is_ai("Anthropic India hires new enterprise sales lead")
    assert is_ai("a new rag pipeline for llms")


def test_is_ai_rejects_airline_flight_code_but_keeps_real_tokens():
    # "AI-171" is Air India's flight code, not the field AI.
    assert not is_ai("Air India flight AI-171 crashed near Ahmedabad airport")
    # Real AI tokens around a hyphen/digit are unaffected:
    assert is_ai("the gpt-4 rollout continues")      # different token (gpt)
    assert is_ai("an ai-powered coding assistant")   # letter after hyphen


def test_sanitize_drops_non_ai_india_item_despite_automation_angle():
    angle = (" Automation angle: Indian AI talent = your referral network — track "
             "exec moves at India-HQ AI startups for warm-intro paths.")
    sections = {
        "indian_ai_industry": [
            {  # non-AI headline; only the appended hook mentions AI
                "title": "Air India crash probe begins in Ahmedabad",
                "summary": "Investigators start probing the tragedy." + angle,
            },
            {  # genuinely AI
                "title": "Anthropic opens an India engineering office",
                "summary": "Anthropic expands its Claude team to Bengaluru." + angle,
            },
        ]
    }
    non_ai, _stale = _sanitize_sections(sections)

    kept = [it["title"] for it in sections["indian_ai_industry"]]
    assert kept == ["Anthropic opens an India engineering office"]
    assert non_ai == 1
