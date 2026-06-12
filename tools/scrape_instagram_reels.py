"""
Scrape candidate AI reels from Instagram via RapidAPI.

Source: a RapidAPI Instagram scraper service (host configurable via env so we
can swap providers without code edits). Default: instagram-scraper-api2.

For each hashtag in GLOBAL_HASHTAGS / INDIA_HASHTAGS, fetch recent reels,
filter for AI relevance + 24h freshness, dedupe by shortcode, and write
.tmp/instagram_reels.json with normalized fields. Verification + bucket
selection happens in tools/instagram_viral_verify.py.

Env vars:
  RAPIDAPI_KEY                 (required) - your RapidAPI bearer token
  RAPIDAPI_INSTAGRAM_HOST      (optional) - default instagram-scraper-api2.p.rapidapi.com

Output shape:
  {
    "scraped_at": "<iso>",
    "host": "<rapidapi host>",
    "reels": [
      {
        "code": "<shortcode>",
        "url": "https://www.instagram.com/reel/<code>/",
        "caption": "<first 500 chars>",
        "username": "<handle>",
        "like_count": int,
        "comment_count": int,
        "play_count": int | null,
        "taken_at_iso": "<iso>" | null,
        "hashtag": "<basket tag>",
        "bucket_hint": "global_ai" | "india_ai",
        "ai_match": bool
      }
    ]
  }
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

from tools._text_match import matches_ai

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "instagram_reels.json")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

API_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
HOST = os.environ.get("RAPIDAPI_INSTAGRAM_HOST", "instagram-scraper-api2.p.rapidapi.com").strip()

GLOBAL_HASHTAGS = [
    "aiautomation", "aiagents", "aitools", "chatgpt", "claudecode",
    "cursorai", "aitech", "aiart",
]
INDIA_HASHTAGS = [
    "aiindia", "indianai", "aistartupindia", "aitechindia", "desi_ai",
]

PER_TAG_LIMIT = 30          # how many reels we ask the API for per hashtag
HTTP_TIMEOUT = 25
INTER_TAG_DELAY = 1.5       # spacing between hashtags to stay under the rate limit


class QuotaExceeded(Exception):
    """Raised when the RapidAPI monthly request quota is exhausted — signals the
    scrape loop to stop early instead of hammering every remaining hashtag."""


def _log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def _headers():
    return {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": HOST,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; ai-news-bot/1.0)",
    }


def _normalize_taken_at(value) -> str | None:
    """Multiple providers return different shapes for the timestamp."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        s = str(value).strip()
        if not s:
            return None
        # Unix epoch as string
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc).isoformat()
        # ISO 8601 — return verbatim if parseable
        from datetime import datetime as _dt
        try:
            _dt.fromisoformat(s.replace("Z", "+00:00"))
            return s
        except Exception:
            return None
    except Exception:
        return None


def _extract_reels(payload, hashtag: str) -> list[dict]:
    """Walk the RapidAPI response shape (varies by provider) and pluck reels.

    We look for common keys (`data.items`, `items`, `data`, `medias`) and try
    to extract each as a reel record. Anything we can't parse is skipped.
    """
    items = []

    def walk(node):
        if isinstance(node, list):
            for el in node:
                walk(el)
        elif isinstance(node, dict):
            # Heuristic: a reel-ish node has a code/shortcode and engagement counts.
            code = (
                node.get("code")
                or node.get("shortcode")
                or node.get("short_code")
                or (node.get("media") or {}).get("code")
            )
            if code and isinstance(code, str) and len(code) >= 5:
                # Likely a reel record. Skip plain images surfaced in the
                # hashtag feed (reels are videos) when the flag is present.
                if node.get("is_video") is False:
                    return
                user = node.get("user") or node.get("owner") or {}
                username = (
                    user.get("username")
                    if isinstance(user, dict)
                    else node.get("username")
                ) or ""
                # Counts: flat keys (api2-style) OR GraphQL edge_* shapes
                # (instagram-scraper-stable-api).
                like_count = (
                    node.get("like_count") or node.get("likes_count") or node.get("likes")
                    or (node.get("edge_liked_by") or {}).get("count")
                    or (node.get("edge_media_preview_like") or {}).get("count")
                    or 0
                )
                comment_count = (
                    node.get("comment_count") or node.get("comments_count") or node.get("comments")
                    or (node.get("edge_media_to_comment") or {}).get("count")
                    or (node.get("edge_media_to_parent_comment") or {}).get("count")
                    or 0
                )
                play_count = (
                    node.get("play_count") or node.get("video_view_count")
                    or node.get("plays") or node.get("video_play_count") or None
                )
                caption_obj = node.get("caption")
                if isinstance(caption_obj, dict):
                    caption = caption_obj.get("text", "")
                elif caption_obj:
                    caption = caption_obj
                else:
                    cap_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
                    if cap_edges:
                        caption = (cap_edges[0].get("node") or {}).get("text", "")
                    else:
                        caption = node.get("caption_text") or node.get("text") or ""
                taken_at = (
                    node.get("taken_at")
                    or node.get("taken_at_timestamp")
                    or node.get("created_at")
                    or node.get("created_time")
                )
                items.append({
                    "code": code,
                    "url": f"https://www.instagram.com/reel/{code}/",
                    "caption": (str(caption) or "")[:500],
                    "username": (str(username) or "").lstrip("@"),
                    "like_count": int(like_count or 0),
                    "comment_count": int(comment_count or 0),
                    "play_count": int(play_count) if play_count else None,
                    "taken_at_iso": _normalize_taken_at(taken_at),
                    "hashtag": hashtag,
                })
            else:
                for v in node.values():
                    walk(v)

    try:
        walk(payload)
    except Exception as e:
        _log(f"  [extract:{hashtag}] walk error: {e}")
    return items


def _candidate_endpoints(hashtag: str) -> list[str]:
    """Try a handful of common RapidAPI Instagram endpoint shapes.

    Different providers under the RapidAPI marketplace expose the same
    hashtag-feed under different paths. We try a few and keep the first
    one that returns reel-ish JSON. Caller short-circuits on first match.
    """
    tag = hashtag.lstrip("#")
    base = f"https://{HOST}"
    return [
        f"{base}/search_hashtag.php?hashtag={tag}",   # instagram-scraper-stable-api
        f"{base}/v1/hashtag/{tag}/recent?count={PER_TAG_LIMIT}",
        f"{base}/v1/tag/{tag}/recent?count={PER_TAG_LIMIT}",
        f"{base}/hashtag/{tag}?type=recent&count={PER_TAG_LIMIT}",
        f"{base}/hashtag?tag={tag}&type=recent&count={PER_TAG_LIMIT}",
        f"{base}/tag/{tag}",
    ]


def _get_with_retry(url: str, max_retries: int = 4):
    """GET with exponential backoff on HTTP 429. The RapidAPI plan rate-limits
    bursts; without backoff the whole run gets 429'd after the first call.
    Returns the final Response (which may still be 429) or None on network error."""
    delay = 2.0
    r = None
    for _ in range(max_retries):
        try:
            r = requests.get(url, headers=_headers(), timeout=HTTP_TIMEOUT)
        except Exception as e:
            _log(f"  [get] {url[len('https://'+HOST):][:50]}: {e}")
            return None
        if r.status_code != 429:
            return r
        # Monthly-quota exhaustion is not transient — retrying wastes 30s/tag.
        if "monthly quota" in (r.text or "").lower():
            return r
        retry_after = r.headers.get("Retry-After", "")
        wait = float(retry_after) if retry_after.isdigit() else delay
        time.sleep(min(wait, 30.0))
        delay *= 2
    return r  # still 429 after retries


def fetch_hashtag(hashtag: str, bucket_hint: str) -> list[dict]:
    if not API_KEY:
        return []
    reels: list[dict] = []
    for endpoint in _candidate_endpoints(hashtag):
        r = _get_with_retry(endpoint)
        if r is None:
            continue
        if r.status_code in (401, 403):
            _log(f"  [#{hashtag}] HTTP {r.status_code} - check RAPIDAPI_KEY / RAPIDAPI_INSTAGRAM_HOST")
            return []
        if r.status_code == 429:
            if "monthly quota" in (r.text or "").lower():
                _log(
                    "  [instagram] RapidAPI MONTHLY quota exhausted "
                    f"(plan limit {r.headers.get('X-RateLimit-Requests-Limit','?')}/mo). "
                    "Instagram section will show 'no candidates' until the quota resets "
                    "or the plan is upgraded. Aborting remaining hashtags."
                )
                raise QuotaExceeded()
            _log(f"  [#{hashtag}] HTTP 429 - rate limited after retries; skipping tag")
            return []
        if r.status_code == 404:
            continue  # endpoint shape mismatch - try next
        if r.status_code != 200:
            _log(f"  [#{hashtag}] HTTP {r.status_code} on {endpoint[len('https://'+HOST):]}")
            continue
        try:
            payload = r.json()
        except Exception:
            continue
        # A 200 + parseable JSON means this is the right endpoint for the host.
        # Stop here (even on 0 reels — the grid may just be photos) instead of
        # thrashing the other candidate paths and burning the rate limit.
        extracted = _extract_reels(payload, hashtag)
        for it in extracted:
            it["bucket_hint"] = bucket_hint
            it["ai_match"] = matches_ai(f"{it.get('caption','')} {it.get('username','')} {hashtag}")
        reels.extend(extracted)
        break
    return reels


def dedupe(reels: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in reels:
        code = r.get("code")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(r)
    return out


def scrape_instagram() -> bool:
    """Entry point used by run_daily_pipeline.py."""
    os.makedirs(TMP_DIR, exist_ok=True)

    if not API_KEY:
        _log("[instagram] RAPIDAPI_KEY not set - skipping. Section will show 'no candidates'.")
        payload = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "host": HOST,
            "skipped_reason": "RAPIDAPI_KEY not set",
            "reels": [],
        }
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True

    all_reels: list[dict] = []
    quota_exhausted = False
    try:
        for tag in GLOBAL_HASHTAGS:
            items = fetch_hashtag(tag, "global_ai")
            _log(f"  [#{tag}] {len(items)} reels")
            all_reels.extend(items)
            time.sleep(INTER_TAG_DELAY)
        for tag in INDIA_HASHTAGS:
            items = fetch_hashtag(tag, "india_ai")
            _log(f"  [#{tag}] {len(items)} reels")
            all_reels.extend(items)
            time.sleep(INTER_TAG_DELAY)
    except QuotaExceeded:
        quota_exhausted = True

    deduped = dedupe(all_reels)
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "host": HOST,
        "input_count": len(all_reels),
        "deduped_count": len(deduped),
        "reels": deduped,
    }
    if quota_exhausted:
        payload["skipped_reason"] = "RapidAPI monthly quota exhausted"
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    _log(f"[instagram] {len(all_reels)} raw -> {len(deduped)} unique -> {OUTPUT_FILE}")
    return True


if __name__ == "__main__":
    ok = scrape_instagram()
    sys.exit(0 if ok else 1)
