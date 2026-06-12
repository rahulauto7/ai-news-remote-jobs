"""
Search YouTube for trending AI videos — no time window.
Uses YouTube Data API v3. Outputs .tmp/youtube_trending.json
"trending" = YouTube's mostPopular chart + viewCount-ordered AI searches,
no publishedAfter filter (user explicitly chose this on 2026-05-21).
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from googleapiclient.discovery import build

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "youtube_trending.json")

API_KEY = os.getenv("YOUTUBE_API_KEY")

# AI-automation-focused queries — what other creators are publishing on YouTube
# about AI automation. Feeds the user's planned AI-automation teaching channel.
SEARCH_QUERIES = [
    # Tutorials & teaching content
    "AI automation tutorial",
    "AI agent tutorial",
    "build AI agent",
    "AI workflow automation",
    "how to automate with AI",
    # Tool-specific automation
    "n8n tutorial",
    "n8n AI workflow",
    "Make.com AI tutorial",
    "Zapier AI tutorial",
    "Claude Code tutorial",
    "Cursor AI tutorial",
    "Windsurf AI tutorial",
    "Cline AI tutorial",
    # Agent platforms
    "LangGraph tutorial",
    "CrewAI tutorial",
    "AutoGen tutorial",
    # Use-case content
    "AI automation business",
    "AI agency build",
    "AI SaaS automation",
]

# Modern AI-native automation platforms — drives viral slots 1 & 2.
# See workflows/daily_ai_news.md "Modern AI-Native Automation Platforms" section.
VIRAL_AI_PLATFORMS = [
    "Claude Code", "Cursor AI", "Windsurf AI", "Cline AI", "Aider AI",
    "Devin AI", "Replit Agent", "Manus AI",
    "v0 Vercel", "Bolt.new", "Lovable AI",
    "GitHub Copilot agent", "ChatGPT agent", "Claude agents", "Jules Google", "OpenAI Codex",
    "CrewAI", "LangGraph", "AutoGen agent", "Mastra AI",
]

# Global video queries (slot 1): platform names as-is.
VIRAL_AI_QUERIES = list(VIRAL_AI_PLATFORMS)

# India video queries (slot 2): platform names + India/Hindi to surface Indian creators.
VIRAL_AI_INDIA_QUERIES = (
    [f"{p} India" for p in VIRAL_AI_PLATFORMS]
    + [f"{p} Hindi" for p in VIRAL_AI_PLATFORMS[:6]]
)

# Short queries (slot 3): broader — any viral AI product short.
VIRAL_AI_SHORT_QUERIES = [
    "Claude Code shorts", "Cursor AI shorts", "Devin AI shorts",
    "Sora 2 shorts", "Veo shorts", "ChatGPT shorts", "Gemini shorts",
    "AI agent shorts",
]

# Traditional workflow-automation tools — hard-rejected from viral slots 1 & 2.
VIRAL_EXCLUDE_TOKENS = [
    "n8n", "make.com", "integromat", "zapier", "workato",
    "pipedream", "tray.io", "activepieces",
]

# Known AI news YouTube channels to specifically check
AI_CHANNELS = [
    "UCbfYPyITQ-7l4upoX8nvctg",  # Two Minute Papers
    "UCMLkMFtICEGOV46_mLm5bTg",  # Matt Wolfe
    "UCWN3xxRkmTPphYit_FYl6Ag",   # TheAIGRID
    "UCUyeluBRhGPCW4rPe_UvBZQ",  # AI Explained
    "UCsBjURrPoezykLs9EqgamOA",  # Fireship
]


def search_youtube(youtube, query, published_after=None, max_results=10):
    """Search YouTube for trending videos matching query. No time filter."""
    try:
        params = dict(
            q=query,
            part="snippet",
            type="video",
            order="viewCount",
            maxResults=max_results,
            relevanceLanguage="en",
        )
        if published_after:
            params["publishedAfter"] = published_after
        request = youtube.search().list(**params)
        response = request.execute()

        videos = []
        video_ids = [item["id"]["videoId"] for item in response.get("items", [])]

        # Get view counts in batch
        stats = {}
        if video_ids:
            stats_request = youtube.videos().list(
                part="statistics",
                id=",".join(video_ids)
            )
            stats_response = stats_request.execute()
            for item in stats_response.get("items", []):
                stats[item["id"]] = item["statistics"]

        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]
            video_stats = stats.get(video_id, {})

            videos.append({
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "channel_id": snippet["channelId"],
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published": snippet["publishedAt"],
                "description": snippet["description"][:500],
                "thumbnail": snippet["thumbnails"].get("high", {}).get("url", ""),
                "views": int(video_stats.get("viewCount", 0)),
                "likes": int(video_stats.get("likeCount", 0)),
                "query": query,
            })

        return videos
    except Exception as e:
        print(f"  [ERROR] Query '{query}': {e}")
        return []


def get_channel_videos(youtube, channel_id, published_after=None):
    """Get recent videos from a specific channel. Time filter optional."""
    try:
        params = dict(
            channelId=channel_id,
            part="snippet",
            type="video",
            order="date",
            maxResults=5,
        )
        if published_after:
            params["publishedAfter"] = published_after
        request = youtube.search().list(**params)
        response = request.execute()

        videos = []
        for item in response.get("items", []):
            snippet = item["snippet"]
            video_id = item["id"]["videoId"]
            videos.append({
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "channel_id": snippet["channelId"],
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published": snippet["publishedAt"],
                "description": snippet["description"][:500],
                "thumbnail": snippet["thumbnails"].get("high", {}).get("url", ""),
                "views": 0,
                "likes": 0,
                "query": "channel_watch",
            })
        return videos
    except Exception as e:
        print(f"  [ERROR] Channel {channel_id}: {e}")
        return []


def parse_duration_seconds(duration_str):
    """Parse ISO 8601 duration (e.g. 'PT1M30S', 'PT58S') to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str or "")
    if not match:
        return 9999  # Unknown duration — treat as long video
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def fetch_chart_trending(youtube, region_code=None, max_results=25):
    """Fetch YouTube's trending/most-popular chart. Costs ~1 quota unit."""
    try:
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "maxResults": max_results,
        }
        if region_code:
            params["regionCode"] = region_code

        response = youtube.videos().list(**params).execute()

        region_label = region_code.lower() if region_code else "global"
        videos = []
        for item in response.get("items", []):
            duration_sec = parse_duration_seconds(item["contentDetails"]["duration"])
            vid_format = "short" if duration_sec <= 60 else "video"
            snippet = item["snippet"]
            stats = item.get("statistics", {})

            videos.append({
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "channel_id": snippet["channelId"],
                "video_id": item["id"],
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "published": snippet["publishedAt"],
                "description": snippet.get("description", "")[:500],
                "thumbnail": snippet["thumbnails"].get("high", {}).get("url", ""),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "query": "chart_trending",
                "region": region_label,
                "format": vid_format,
                "is_ai": False,
                "scrape_source": "viral_trending",
            })
        return videos
    except Exception as e:
        print(f"  [ERROR] Chart trending (region={region_code}): {e}")
        return []


def search_viral_shorts(youtube, query, region_code=None, max_results=5, is_ai=False):
    """Search for viral Shorts (videoDuration=short). Costs 100 quota units."""
    try:
        params = {
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": "viewCount",
            "videoDuration": "short",
            "maxResults": max_results,
            "relevanceLanguage": "en",
        }
        if region_code:
            params["regionCode"] = region_code

        response = youtube.search().list(**params).execute()

        region_label = region_code.lower() if region_code else "global"
        videos = []
        video_ids = [item["id"]["videoId"] for item in response.get("items", [])]

        # Get view counts
        stats = {}
        if video_ids:
            stats_resp = youtube.videos().list(
                part="statistics", id=",".join(video_ids)
            ).execute()
            for item in stats_resp.get("items", []):
                stats[item["id"]] = item["statistics"]

        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]
            video_stats = stats.get(video_id, {})

            videos.append({
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "channel_id": snippet["channelId"],
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published": snippet["publishedAt"],
                "description": snippet.get("description", "")[:500],
                "thumbnail": snippet["thumbnails"].get("high", {}).get("url", ""),
                "views": int(video_stats.get("viewCount", 0)),
                "likes": int(video_stats.get("likeCount", 0)),
                "query": query,
                "region": region_label,
                "format": "short",
                "is_ai": is_ai,
                "scrape_source": "viral_trending",
            })
        return videos
    except Exception as e:
        print(f"  [ERROR] Shorts search '{query}' (region={region_code}): {e}")
        return []


def platform_for_query(query):
    """Map a VIRAL_AI_QUERIES / VIRAL_AI_INDIA_QUERIES string back to its platform name."""
    q_lower = query.lower()
    for platform in VIRAL_AI_PLATFORMS:
        if platform.lower() in q_lower:
            return platform
    return None


def search_platform_video(youtube, query, region_code, platform_name):
    """Search YouTube for long-form AI-automation platform videos, ordered by viewCount."""
    try:
        params = {
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": "viewCount",
            "maxResults": 5,
            "relevanceLanguage": "en",
        }
        if region_code:
            params["regionCode"] = region_code
        response = youtube.search().list(**params).execute()

        region_label = region_code.lower() if region_code else "global"
        video_ids = [item["id"]["videoId"] for item in response.get("items", [])]

        stats = {}
        if video_ids:
            stats_resp = youtube.videos().list(
                part="statistics,contentDetails", id=",".join(video_ids)
            ).execute()
            for item in stats_resp.get("items", []):
                stats[item["id"]] = {
                    "statistics": item["statistics"],
                    "duration": item["contentDetails"]["duration"],
                }

        results = []
        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]
            video_stats = stats.get(video_id, {})
            stat_data = video_stats.get("statistics", {})
            duration_sec = parse_duration_seconds(video_stats.get("duration"))
            vid_format = "short" if duration_sec <= 60 else "video"

            results.append({
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "channel_id": snippet["channelId"],
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published": snippet["publishedAt"],
                "description": snippet.get("description", "")[:500],
                "thumbnail": snippet["thumbnails"].get("high", {}).get("url", ""),
                "views": int(stat_data.get("viewCount", 0)),
                "likes": int(stat_data.get("likeCount", 0)),
                "query": query,
                "region": region_label,
                "format": vid_format,
                "is_ai": True,
                "platform": platform_name,
                "scrape_source": "viral_trending",
            })
        return results
    except Exception as e:
        print(f"  [ERROR] Platform search '{query}' (region={region_code}): {e}")
        return []


def filter_viral_exclude(videos):
    """Drop slot-1/2 candidates whose title/description mentions traditional workflow tools."""
    kept = []
    dropped = 0
    for v in videos:
        # Only apply exclude to video-format viral results tagged with a platform.
        if v.get("format") == "video" and v.get("platform"):
            haystack = f"{v.get('title', '')} {v.get('description', '')}".lower()
            if any(tok in haystack for tok in VIRAL_EXCLUDE_TOKENS):
                dropped += 1
                continue
        kept.append(v)
    if dropped:
        print(f"  [filter] Dropped {dropped} viral video(s) matching excluded workflow tools")
    return kept


def scrape_viral_trending(youtube):
    """Fetch viral/trending videos and Shorts for Global and India."""
    all_viral = []

    # Chart trending — Global and India (1 quota unit each)
    print("\nFetching viral trending charts...")
    for region, label in [(None, "Global"), ("IN", "India")]:
        videos = fetch_chart_trending(youtube, region_code=region, max_results=25)
        print(f"  [{len(videos):>2} videos] Chart trending — {label}")
        all_viral.extend(videos)

    # Slot 1 — Global AI-automation platform videos (100 units per query)
    print("\nSearching viral AI-platform videos (Global)...")
    for query in VIRAL_AI_QUERIES:
        platform = platform_for_query(query)
        hits = search_platform_video(youtube, query, region_code=None, platform_name=platform)
        print(f"  [{len(hits):>2} videos] '{query}' — Global [platform={platform}]")
        all_viral.extend(hits)

    # Slot 2 — India AI-automation platform videos
    print("\nSearching viral AI-platform videos (India)...")
    for query in VIRAL_AI_INDIA_QUERIES:
        platform = platform_for_query(query)
        hits = search_platform_video(youtube, query, region_code="IN", platform_name=platform)
        print(f"  [{len(hits):>2} videos] '{query}' — India [platform={platform}]")
        all_viral.extend(hits)

    # Slot 3 — AI-product Shorts (100 units each)
    print("\nSearching viral AI Shorts...")
    for query in VIRAL_AI_SHORT_QUERIES:
        for region, label in [(None, "Global"), ("IN", "India")]:
            shorts = search_viral_shorts(youtube, query, region_code=region, max_results=5, is_ai=True)
            print(f"  [{len(shorts):>2} shorts] '{query}' — {label}")
            all_viral.extend(shorts)

    # General viral Shorts (non-AI) for Global and India
    print("\nSearching general viral Shorts...")
    for region, label in [(None, "Global"), ("IN", "India")]:
        shorts = search_viral_shorts(youtube, "viral shorts today", region_code=region, max_results=5, is_ai=False)
        print(f"  [{len(shorts):>2} shorts] General viral — {label}")
        all_viral.extend(shorts)

    # Reject traditional-automation tools from slot 1/2 candidates
    all_viral = filter_viral_exclude(all_viral)

    print(f"\nTotal viral videos fetched: {len(all_viral)}")
    return all_viral


def scrape_youtube():
    """Run all YouTube searches and save results."""
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set in .env")
        sys.exit(1)

    os.makedirs(TMP_DIR, exist_ok=True)
    youtube = build("youtube", "v3", developerKey=API_KEY)

    all_videos = []

    # Search queries (each costs 100 quota units) - no time filter, trending now
    print(f"Searching {len(SEARCH_QUERIES)} queries...")
    for query in SEARCH_QUERIES:
        videos = search_youtube(youtube, query, max_results=5)
        print(f"  [{len(videos):>2} videos] '{query}'")
        all_videos.extend(videos)

    # Check known channels - latest 5 per channel
    print(f"\nChecking {len(AI_CHANNELS)} AI channels...")
    for channel_id in AI_CHANNELS:
        videos = get_channel_videos(youtube, channel_id)
        if videos:
            print(f"  [{len(videos):>2} videos] {videos[0]['channel']}")
        all_videos.extend(videos)

    # Viral trending (Global + India charts, AI searches, Shorts)
    viral_videos = scrape_viral_trending(youtube)
    all_videos.extend(viral_videos)

    # Deduplicate by video_id
    seen_ids = set()
    unique_videos = []
    for video in all_videos:
        if video["video_id"] not in seen_ids:
            seen_ids.add(video["video_id"])
            unique_videos.append(video)

    # Sort by views (most popular first)
    unique_videos.sort(key=lambda v: v["views"], reverse=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "cutoff": None,  # no time window - trending now
            "total_videos": len(unique_videos),
            "queries_searched": len(SEARCH_QUERIES),
            "channels_checked": len(AI_CHANNELS),
            "videos": unique_videos,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nDone! {len(unique_videos)} unique videos saved to {OUTPUT_FILE}")
    return unique_videos


if __name__ == "__main__":
    scrape_youtube()
