"""Strict last-24h enforcement for news sections.

User's hard rule: news is strictly last-24h only. The deterministic gate must
DROP any item in a news section that cannot be proven to be within 24h — that
includes items older than 24h AND items whose published date is missing or
unparseable. (Agent enrichment adds items that frequently lack an ISO date; the
old lenient gate waved them through, leaking 2-day-old news into the PDF.)
"""
import os
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.analyze_and_categorize import _within_hours, NEWS_FRESH_HOURS
from tools.dedupe_and_backfill import _sanitize_sections


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_within_hours_strict_drops_old():
    assert _within_hours(_iso(2), 24, strict=True) is True
    assert _within_hours(_iso(30), 24, strict=True) is False


def test_within_hours_strict_drops_unknown_dates():
    # Can't prove freshness → not fresh under strict.
    assert _within_hours(None, 24, strict=True) is False
    assert _within_hours("", 24, strict=True) is False
    assert _within_hours("not a date", 24, strict=True) is False


def test_within_hours_parses_rfc822():
    # Agent / feed items often carry an RFC822 date, not ISO.
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime(
        "%a, %d %b %Y %H:%M:%S %z")
    assert _within_hours(old, 24, strict=True) is False
    fresh = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
        "%a, %d %b %Y %H:%M:%S %z")
    assert _within_hours(fresh, 24, strict=True) is True


def test_within_hours_lenient_default_unchanged():
    # Non-news callers keep the over-include default.
    assert _within_hours(None, 24) is True
    assert _within_hours("not a date", 24) is True


def test_sanitize_drops_stale_and_undated_from_news():
    sections = {
        "global_ai_news": [
            {"title": "OpenAI ships new AI model today", "summary": "AI news.",
             "published": _iso(2)},                       # fresh → keep
            {"title": "AI startup raised funding yesterday-plus", "summary": "AI news.",
             "published": _iso(30)},                      # >24h → drop
            {"title": "Anthropic AI agent launch", "summary": "AI news.",
             "published": None},                          # undated → drop (strict)
        ],
    }
    _non_ai, stale = _sanitize_sections(sections)
    titles = [it["title"] for it in sections["global_ai_news"]]
    assert titles == ["OpenAI ships new AI model today"]
    assert stale == 2


def test_quantum_rsi_get_seven_day_window():
    # User rule 2026-07-02: niche research sections keep a 7-day window
    # (dedup prevents repeats); everything else stays strictly 24h.
    sections = {
        "quantum_ai_research": [
            {"title": "Quantum ML breakthrough in AI error correction",
             "summary": "quantum neural network research", "published": _iso(72)},
            {"title": "Old quantum AI story",
             "summary": "quantum machine learning", "published": _iso(200)},
        ],
        "ai_self_improvement_rsi": [
            {"title": "Self-improving AI agent rewrites its own model",
             "summary": "recursive self-improvement LLM research", "published": _iso(100)},
        ],
        "global_ai_news": [
            {"title": "AI model launch", "summary": "new LLM", "published": _iso(72)},
        ],
    }
    _sanitize_sections(sections)
    assert len(sections["quantum_ai_research"]) == 1      # 72h kept, 200h dropped
    assert len(sections["ai_self_improvement_rsi"]) == 1  # 100h kept (<168h)
    assert sections["global_ai_news"] == []               # 72h > 24h → dropped


def test_general_news_drops_ai_items():
    # general_news is the intentionally NON-AI section; AI stories are dupes.
    sections = {
        "general_news": [
            {"title": "Earthquake damages 58,000 buildings",
             "summary": "disaster relief underway", "published": _iso(3)},
            {"title": "OpenAI launches new AI model",
             "summary": "the LLM outperforms rivals", "published": _iso(3)},
        ],
    }
    _sanitize_sections(sections)
    titles = [it["title"] for it in sections["general_news"]]
    assert titles == ["Earthquake damages 58,000 buildings"]


def test_sanitize_only_collapses_same_story_duplicates(tmp_path, monkeypatch):
    import json
    from tools import dedupe_and_backfill as dnb
    doc = {"sections": {"global_ai_news": [
        {"title": "Anthropic releases Claude Fable 5 model today",
         "summary": "AI model launch", "published": _iso(2), "relevance": 9},
        {"title": "Anthropic releases Claude Fable 5 model",
         "summary": "AI model launch again", "published": _iso(3), "relevance": 5},
    ]}}
    f = tmp_path / "analyzed_content.json"
    f.write_text(json.dumps(doc))
    monkeypatch.setattr(dnb, "OUTPUT_FILE", str(f))
    dnb.sanitize_only()
    out = json.loads(f.read_text())
    assert len(out["sections"]["global_ai_news"]) == 1
    assert "today" in out["sections"]["global_ai_news"][0]["title"]
