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


def test_is_ai_video_rejects_generic_description_boilerplate():
    """2026-08-21: 'Ai Tìm Được MECCHA CHAMELEON…' (Vietnamese for 'whoever
    finds…') shipped as the Global viral AI pick. The bare 'Ai' matched and the
    old gate accepted ANY occurrence of a generic cue ('video', 'app', 'code')
    anywhere in the description — words present in every YouTube description.
    The cue must now sit within 40 chars of the bare token, and generic words
    are no longer cues at all."""
    desc = ("Nếu các bạn xem video thấy hay thì đừng quên ấn Thích và Chia sẻ. "
            "Facebook: ... TikTok: ... Email: ...")
    assert not yv.is_ai_video(
        "Ai Tìm Được MECCHA CHAMELEON Trong Siêu Thị Sẽ Được Mua Đồ Miễn Phí!", desc)
    assert not yv.is_ai_video("Bikin Kasur Ulang Tahun Ai", "subscribe untuk video lainnya")


def test_is_ai_video_no_phantom_phrase_across_title_description_boundary():
    """A title ending in 'Ai' glued to a description starting with 'video'
    used to synthesise the phrase 'ai video'. Title and description are now
    joined with a separator."""
    assert not yv.is_ai_video("Thùng Hộp bí ẩn của Ai", "video moi nhat, dang ky kenh")


def test_is_ai_video_still_accepts_genuine_ai_content():
    assert yv.is_ai_video("Mom VS AI #shorts", "#shorts #funny #ai #chatgpt #comedy")
    assert yv.is_ai_video("I built an AI agent with n8n", "full tutorial")
    assert yv.is_ai_video("Best AI video generator 2026")
    assert yv.is_ai_video("ML pipeline tutorial", "python walkthrough")
