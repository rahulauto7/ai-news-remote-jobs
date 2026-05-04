"""
Section 15: Viral Video Landscape — verified.
Picks exactly 3 videos using YouTube Data API v3:
  bucket A: global AI Automation video (>= VIRAL_GLOBAL_VIEWS in last 24h)
  bucket B: India AI Automation video (>= VIRAL_INDIA_VIEWS in last 24h)
  bucket C: global AI Short (<= 60s, >= VIRAL_SHORT_VIEWS in last 24h)

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
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT = os.path.join(TMP_DIR, "youtube_verified.json")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

THRESH_GLOBAL = int(os.environ.get("VIRAL_GLOBAL_VIEWS", "100000"))
THRESH_INDIA = int(os.environ.get("VIRAL_INDIA_VIEWS", "25000"))
THRESH_SHORT = int(os.environ.get("VIRAL_SHORT_VIEWS", "250000"))


def search_candidates(query, region_code=None, max_results=25):
    """Search videos published in last 24h, ordered by viewCount."""
    if not API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY missing")
    published_after = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "key": API_KEY,
        "part": "snippet",
        "type": "video",
        "q": query,
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": max_results,
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


def pick_top(items, min_views, must_be_short=False):
    """Pick top item passing thresholds."""
    best = None
    best_views = -1
    for it in items:
        try:
            views = int(it.get("statistics", {}).get("viewCount", "0"))
            duration = isodate.parse_duration(it.get("contentDetails", {}).get("duration", "PT0S")).total_seconds()
        except Exception:
            continue
        if views < min_views:
            continue
        if must_be_short and duration > 60:
            continue
        if not must_be_short and duration <= 60:
            continue  # exclude shorts from non-short bucket
        if views > best_views:
            best_views = views
            best = (it, views, duration)
    return best


def to_record(item, views, duration, bucket):
    vid = item.get("id")
    sn = item.get("snippet", {})
    url = f"https://www.youtube.com/watch?v={vid}"
    return {
        "video_id": vid,
        "url": url,
        "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""),
        "description": (sn.get("description") or "")[:500],
        "published": sn.get("publishedAt", ""),
        "views": views,
        "duration_sec": int(duration),
        "format": "short" if duration <= 60 else "video",
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

    # Bucket A: global automation
    try:
        ids = search_candidates("AI automation tutorial OR n8n OR Make.com OR Zapier", region_code=None)
        items = fetch_video_details(ids)
        pick = pick_top(items, THRESH_GLOBAL, must_be_short=False)
        if pick:
            out.append(to_record(*pick, bucket="global_automation"))
            print(f"  [global_automation] {pick[1]:,} views — {pick[0]['snippet']['title'][:60]}")
        else:
            print("  [global_automation] none qualified")
    except Exception as e:
        print(f"  [global_automation ERROR] {e}")

    # Bucket B: India automation
    try:
        ids = search_candidates("AI automation India OR \"n8n India\" OR \"AI agent India\"", region_code="IN")
        items = fetch_video_details(ids)
        pick = pick_top(items, THRESH_INDIA, must_be_short=False)
        if pick:
            out.append(to_record(*pick, bucket="india_automation"))
            print(f"  [india_automation] {pick[1]:,} views — {pick[0]['snippet']['title'][:60]}")
        else:
            print("  [india_automation] none qualified")
    except Exception as e:
        print(f"  [india_automation ERROR] {e}")

    # Bucket C: global AI Short
    try:
        ids = search_candidates("AI #shorts OR ChatGPT #shorts OR Claude #shorts", region_code=None)
        items = fetch_video_details(ids)
        pick = pick_top(items, THRESH_SHORT, must_be_short=True)
        if pick:
            out.append(to_record(*pick, bucket="global_short"))
            print(f"  [global_short] {pick[1]:,} views — {pick[0]['snippet']['title'][:60]}")
        else:
            print("  [global_short] none qualified")
    except Exception as e:
        print(f"  [global_short ERROR] {e}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "thresholds": {
                "global_views": THRESH_GLOBAL,
                "india_views": THRESH_INDIA,
                "short_views": THRESH_SHORT,
            },
            "videos": out,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nVerified videos saved → {OUTPUT} ({len(out)}/3 buckets filled)")
    return out


if __name__ == "__main__":
    run()
