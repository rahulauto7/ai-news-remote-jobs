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
