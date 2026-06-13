"""YouTube viral gate: strong AI-video detection + verified-URL drop.

Substring/bare-word matching shipped non-AI foreign-language clips that merely
spelled "Ai" ("Bikin Kasur Ulang Tahun Ai", "Thùng Hộp ... của Ai") and kept
picks whose watch URL never verified (url_verified:false). is_ai_video() now
needs a real AI signal, and pick_top() drops any candidate that fails HEAD.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import youtube_viral_verify as yv


def test_is_ai_video_rejects_foreign_ai_word_false_positives():
    assert not yv.is_ai_video("Bikin Kasur Ulang Tahun Ai")
    assert not yv.is_ai_video("Thùng Hộp Đồ Chơi của Ai")
    # bare "ai" with no English AI cue is not enough
    assert not yv.is_ai_video("Lagu Ai yang sedih banget")


def test_is_ai_video_accepts_real_ai():
    assert yv.is_ai_video("ChatGPT just changed everything")
    assert yv.is_ai_video("I built an AI agent in 10 minutes")
    assert yv.is_ai_video("New AI tools you need to try")
    assert yv.is_ai_video("Claude Code is insane", "anthropic agentic coding")
    # bare "ai" rescued by an English AI cue ("video generator")
    assert yv.is_ai_video("This AI video generator is wild")


def _item(vid, title, views, duration_iso="PT5M", desc=""):
    return {
        "id": vid,
        "snippet": {"title": title, "description": desc, "channelTitle": "c",
                    "publishedAt": "2026-06-13T00:00:00Z"},
        "statistics": {"viewCount": str(views)},
        "contentDetails": {"duration": duration_iso},
    }


def test_pick_top_drops_non_ai_and_unverified(monkeypatch):
    # Every candidate clears the view floor + long-form duration.
    items = [
        _item("foreign1", "Tahun Ai paling viral", 5_000_000),  # not AI → drop
        _item("deadlink", "ChatGPT breaks the internet", 4_000_000),  # AI but URL fails
        _item("good1", "Claude AI agent demo", 1_000_000),  # AI + verifies → pick
    ]
    monkeypatch.setattr(yv, "is_short_video", lambda *a, **k: False)
    monkeypatch.setattr(yv, "verify_url", lambda url: "deadlink" not in url)

    it, views, duration, status = yv.pick_top(items, must_be_short=False,
                                              view_floor=yv.LONG_VIEW_FLOOR, seen=set())
    assert status == "fresh"
    assert it["id"] == "good1"


def test_pick_top_returns_none_when_all_unverified(monkeypatch):
    items = [_item("a", "ChatGPT news today", 9_000_000)]
    monkeypatch.setattr(yv, "is_short_video", lambda *a, **k: False)
    monkeypatch.setattr(yv, "verify_url", lambda url: False)  # proxy-blocked
    it, _v, _d, status = yv.pick_top(items, must_be_short=False,
                                     view_floor=yv.LONG_VIEW_FLOOR, seen=set())
    assert status == "none"
    assert it is None
