"""
Viral AI on YouTube — verified (last 7 days).
Picks up to 3 videos using YouTube Data API v3, ordered by viewCount,
restricted to videos published in the last 7 days, AND filtered by a
virality floor so only genuinely viral picks survive:
  bucket A: global AI long video        — >= LONG_VIEW_FLOOR views
  bucket B: global AI Short (<= 60s)    — >= SHORT_VIEW_FLOOR views
  bucket C: India  AI long video        — >= LONG_VIEW_FLOOR views

For each pick, verifies the watch URL is reachable.
Writes .tmp/youtube_verified.json
Requires: YOUTUBE_API_KEY env var.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
import isodate

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT = os.path.join(TMP_DIR, "youtube_verified.json")

from tools import content_history

YT_NS = "youtube"
DEDUP_DAYS = 7

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

WINDOW_DAYS = 7
LONG_VIEW_FLOOR = 100_000      # long-form virality threshold (per bucket)
SHORT_VIEW_FLOOR = 500_000     # Shorts virality threshold


def _published_after_iso(days_back=WINDOW_DAYS):
    return (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")


def search_candidates(query, region_code=None, max_results=25, published_after=None):
    """Search videos ordered by viewCount, restricted to the last 7 days by default."""
    if not API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY missing")
    params = {
        "key": API_KEY,
        "part": "snippet",
        "type": "video",
        "q": query,
        "order": "viewCount",
        "maxResults": max_results,
        "publishedAfter": published_after or _published_after_iso(),
    }
    if region_code:
        params["regionCode"] = region_code
    r = requests.get(SEARCH_URL, params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("items", [])
    return [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]


def fetch_video_details(video_ids):
    if not video_ids:
        return []
    r = requests.get(VIDEOS_URL, params={
        "key": API_KEY,
        "part": "snippet,contentDetails,statistics",
        "id": ",".join(video_ids),
    }, timeout=20)
    r.raise_for_status()
    return r.json().get("items", [])


def verify_url(url):
    try:
        r = requests.head(url, timeout=10, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code == 200
    except Exception:
        return False


def is_short_video(video_id, title="", description=""):
    """True if the video is a YouTube Short.

    Duration alone lies — Shorts now run up to 180s, so a 90s Short would pass a
    naive `duration > 60` long-form filter and land in the long-video slot.
    Authoritative signal: GET youtube.com/shorts/<id> with redirects OFF — a real
    Short returns 200, a regular video 30x-redirects to /watch. Secondary signal:
    an explicit #shorts tag in the title/description.
    """
    blob = f"{title} {description}".lower()
    if "#short" in blob:
        return True
    if not video_id:
        return False
    try:
        r = requests.get(
            f"https://www.youtube.com/shorts/{video_id}",
            timeout=10, allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return r.status_code == 200
    except Exception:
        return False


def pick_top(items, must_be_short=False, view_floor=0, seen=None):
    """Pick the max-views item in the bucket that clears the virality floor AND
    was not shown in the last 7 days. Returns (it, views, duration, status):
      status "fresh"     — an unseen qualifying pick (use it)
      status "seen_only" — qualifying items exist but all were shown recently
                           (caller should WIDEN the search before settling)
      status "none"      — nothing cleared the floor at all
    Never fabricates: the floor must always be cleared."""
    seen = seen or set()
    qualified = []  # (views, it, duration)
    for it in items:
        try:
            views = int(it.get("statistics", {}).get("viewCount", "0"))
            duration = isodate.parse_duration(it.get("contentDetails", {}).get("duration", "PT0S")).total_seconds()
        except Exception:
            continue
        if views < view_floor:
            continue
        # Cheap duration pre-filter only (Shorts run up to 180s). The authoritative
        # short/long decision is is_short_video() on the candidate we actually pick,
        # so we don't pay an HTTP call for every item — just the ones we'd surface.
        if must_be_short and duration > 180:
            continue
        if not must_be_short and duration <= 30:
            continue
        qualified.append((views, it, duration))
    if not qualified:
        return (None, 0, 0, "none")
    qualified.sort(key=lambda x: x[0], reverse=True)

    seen_fallback = None
    for views, it, duration in qualified:
        sn = it.get("snippet", {})
        actually_short = is_short_video(it.get("id"), sn.get("title", ""), sn.get("description", ""))
        if actually_short != must_be_short:
            continue  # wrong format for this bucket (e.g. a Short in the long slot)
        if it.get("id") not in seen:
            return (it, views, duration, "fresh")
        if seen_fallback is None:
            seen_fallback = (it, views, duration)
    if seen_fallback is not None:
        it, views, duration = seen_fallback
        return (it, views, duration, "seen_only")
    return (None, 0, 0, "none")


def fill_bucket(bucket, query, widen_query, region_code, must_be_short, view_floor, seen):
    """Return a verified-video record for one bucket, preferring a FRESH (unseen)
    pick. If the primary query only yields recently-shown videos, widen the search
    (broader query + more results) once before giving up. If still nothing fresh
    clears the floor, return a `no_fresh` marker so the PDF prints a note instead
    of repeating yesterday's pick."""
    items = fetch_video_details(search_candidates(query, region_code=region_code))
    it, views, duration, status = pick_top(items, must_be_short, view_floor, seen)
    if status != "fresh":
        # Widen: broader phrasing + a bigger candidate pool, then re-pick on the
        # combined set so a fresh viral video gets a real chance to surface.
        more = fetch_video_details(search_candidates(widen_query, region_code=region_code, max_results=50))
        merged = {i.get("id"): i for i in items + more if i.get("id")}.values()
        it, views, duration, status = pick_top(list(merged), must_be_short, view_floor, seen)
    if status == "fresh":
        rec = to_record(it, views, duration, bucket=bucket, is_short=must_be_short)
        print(f"  [{bucket}] {views:,} views — {it['snippet']['title'][:60]}")
        return rec
    why = "no candidate cleared the floor" if status == "none" else "only already-shown videos qualified"
    print(f"  [{bucket}] no fresh pick ({why})")
    return {"bucket": bucket, "no_fresh": True, "reason": why,
            "format": "short" if must_be_short else "video",
            "view_floor": view_floor}


def to_record(item, views, duration, bucket, is_short=None):
    vid = item.get("id")
    sn = item.get("snippet", {})
    url = f"https://www.youtube.com/watch?v={vid}"
    # Format reflects the bucket's verified short/long decision (pick_top enforced
    # is_short == must_be_short), not the unreliable duration<=60 heuristic.
    fmt = "short" if (is_short if is_short is not None else duration <= 60) else "video"
    return {
        "video_id": vid,
        "url": url,
        "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""),
        "description": (sn.get("description") or "")[:500],
        "published": sn.get("publishedAt", ""),
        "views": views,
        "duration_sec": int(duration),
        "format": fmt,
        "bucket": bucket,
        "url_verified": verify_url(url),
    }


def run():
    os.makedirs(TMP_DIR, exist_ok=True)
    if not API_KEY:
        print("WARNING: YOUTUBE_API_KEY not set — skipping section 15 verification")
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump({"checked_at": datetime.now(timezone.utc).isoformat(), "videos": [], "note": "no API key"}, f, indent=2)
        return []

    out = []
    seen = content_history.recently_seen(YT_NS, DEDUP_DAYS)

    buckets = [
        # (bucket, query, widen_query, region, must_be_short, floor)
        ("global_automation",
         '"AI" OR "ChatGPT" OR "Claude" OR "Gemini" OR "AI agent"',
         '"AI news" OR "artificial intelligence" OR "OpenAI" OR "Gemini" OR "AI tools" OR "AI breakthrough"',
         None, False, LONG_VIEW_FLOOR),
        ("global_short",
         '"AI #shorts" OR "ChatGPT #shorts" OR "AI tools #shorts"',
         '"AI #shorts" OR "ChatGPT #shorts" OR "Gemini #shorts" OR "AI hack #shorts" OR "AI prompt #shorts"',
         None, True, SHORT_VIEW_FLOOR),
        ("india_automation",
         '"AI India" OR "ChatGPT Hindi" OR "AI tools India"',
         '"AI India" OR "ChatGPT India" OR "Gemini India" OR "AI Hindi" OR "AI news India"',
         "IN", False, LONG_VIEW_FLOOR),
    ]
    for bucket, query, widen_query, region, is_short, floor in buckets:
        try:
            out.append(fill_bucket(bucket, query, widen_query, region, is_short, floor, seen))
        except Exception as e:
            print(f"  [{bucket} ERROR] {e}")

    # Record only the REAL picks so tomorrow prefers fresh videos over these.
    content_history.record_shown(
        YT_NS, [v.get("video_id") for v in out if v.get("video_id") and not v.get("no_fresh")]
    )

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "window_days": WINDOW_DAYS,
            "thresholds": {"long_views": LONG_VIEW_FLOOR, "short_views": SHORT_VIEW_FLOOR},
            "videos": out,
        }, f, indent=2, ensure_ascii=False)

    filled = sum(1 for v in out if not v.get("no_fresh"))
    print(f"\nVerified videos saved → {OUTPUT} ({filled}/3 buckets filled)")
    return out


if __name__ == "__main__":
    run()
