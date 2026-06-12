"""
Viral Instagram Reels — verified.

Filters .tmp/instagram_reels.json down to two buckets:
  - global_ai: max-engagement AI reel from the Global hashtag basket
  - india_ai:  max-engagement AI reel from the India hashtag basket

"Engagement" = like_count + comment_count. Reels older than 24h, non-AI reels,
or reels whose URL returns non-200 are dropped. Bucket empty -> placeholder
record so the PDF can render "no AI reels in last 24h" without breaking.

Output: .tmp/instagram_verified.json (max 2 reels).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from tools._text_match import matches_ai
from tools import content_history

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
INPUT_FILE = os.path.join(TMP_DIR, "instagram_reels.json")
OUTPUT_FILE = os.path.join(TMP_DIR, "instagram_verified.json")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

WINDOW_HOURS = 24
IG_NS = "instagram"
DEDUP_DAYS = 7


def _within_hours(taken_iso: str | None, hours: int) -> bool:
    if not taken_iso:
        return False
    try:
        dt = datetime.fromisoformat(taken_iso.replace("Z", "+00:00"))
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)


# How far back to WIDEN the search when every in-window reel was already shown,
# before giving up and printing a "no new reel" note (instead of repeating).
WIDEN_HOURS = 24 * 7


def verify_url(url: str) -> bool:
    """HEAD against Instagram; treat 200 + 301/302 redirects as OK.

    Instagram often returns 302 to a login wall for HEAD requests; we treat
    any sub-400 status as "the reel exists" (the URL is shareable and the user
    can open it in browser). Same posture as YouTube viral verify.
    """
    try:
        r = requests.head(
            url, timeout=10, allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)"},
        )
        return r.status_code < 400
    except Exception:
        return False


def pick_bucket(reels: list[dict], bucket_key: str, seen: set | None = None) -> dict | None:
    """Pick the max-engagement FRESH (unseen) AI reel for the given bucket.
    Prefers an unseen reel from the last 24h; if every 24h reel was already shown,
    WIDENS to the last 7 days for an unseen one. If nothing unseen qualifies it
    returns a `no_fresh` marker rather than repeating a recently-shown reel —
    callers/PDF render a 'no new reel' note. Returns None only when the bucket has
    no qualifying AI reels at all."""
    seen = seen or set()
    within24, widened = [], []  # (engagement, reel)
    for r in reels:
        if r.get("bucket_hint") != bucket_key:
            continue
        # AI gate: matches_ai over caption + username + hashtag.
        haystack = f"{r.get('caption','')} {r.get('username','')} {r.get('hashtag','')}"
        if not (r.get("ai_match") or matches_ai(haystack)):
            continue
        engagement = int(r.get("like_count") or 0) + int(r.get("comment_count") or 0)
        if _within_hours(r.get("taken_at_iso"), WINDOW_HOURS):
            within24.append((engagement, r))
        elif _within_hours(r.get("taken_at_iso"), WIDEN_HOURS):
            widened.append((engagement, r))

    if not within24 and not widened:
        return None

    # Prefer a fresh unseen reel: 24h pool first, then the widened pool.
    for pool in (within24, widened):
        pool.sort(key=lambda x: x[0], reverse=True)
        for score, r in pool:
            if r.get("url") not in seen:
                record = dict(r)
                record["engagement"] = score
                record["bucket"] = bucket_key
                record["url_verified"] = verify_url(record.get("url", ""))
                return record

    # Everything that qualifies was already shown recently — note it, don't repeat.
    return {"bucket": bucket_key, "no_fresh": True}


def run() -> bool:
    os.makedirs(TMP_DIR, exist_ok=True)
    if not os.path.exists(INPUT_FILE):
        payload = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "reels": [],
            "note": "instagram_reels.json missing - run scrape_instagram_reels first",
        }
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"[ig_verify] no input - wrote empty {OUTPUT_FILE}")
        return True

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    reels = data.get("reels", []) or []

    seen = content_history.recently_seen(IG_NS, DEDUP_DAYS)
    out = []
    for bucket in ("global_ai", "india_ai"):
        pick = pick_bucket(reels, bucket, seen=seen)
        if pick and not pick.get("no_fresh"):
            out.append(pick)
            print(
                f"  [{bucket}] {pick.get('engagement', 0):,} engagement "
                f"@{pick.get('username','?')} - {pick.get('caption','')[:60]}"
            )
        elif pick and pick.get("no_fresh"):
            out.append(pick)
            print(f"  [{bucket}] only already-shown reels qualified - no new reel this period")
        else:
            out.append({"bucket": bucket, "no_fresh": True})
            print(f"  [{bucket}] no AI reels in last 24h")

    # Record only the REAL reels so tomorrow rotates them out.
    content_history.record_shown(
        IG_NS, [r.get("url") for r in out if r.get("url") and not r.get("no_fresh")]
    )

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": WINDOW_HOURS,
        "reels": out,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    filled = sum(1 for r in out if not r.get("no_fresh"))
    print(f"[ig_verify] {filled}/2 buckets filled -> {OUTPUT_FILE}")
    return True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
