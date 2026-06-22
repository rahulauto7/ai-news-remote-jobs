"""
Data contract and utilities for the analysis step.
The actual analysis is performed by the Claude Code agent directly,
NOT via an API call. The agent reads scraped data, reasons about it, and writes
the output JSON using save_analyzed_content().

Reads:
  .tmp/jobs.json              (section 0 — remote jobs)
  .tmp/rss_articles.json      (sections 1-14, 17)
  .tmp/youtube_verified.json  (section 15 — viral verified)
  .tmp/youtube_trending.json  (section 16 — trending landscape)

Writes: .tmp/analyzed_content.json

All 18 sections get equal treatment.
Section 0 entries are remote-job listings (not stories).
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta

# News freshness: the main routing pass only surfaces articles published within
# this many hours ("last 24h news only"). The RSS scrape still collects ~7 days
# so dedupe_and_backfill can WIDEN to older items for low-volume sections
# (Quantum / RSI) that can't fill from 24h alone.
NEWS_FRESH_HOURS = 24

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "analyzed_content.json")

SECTIONS = [
    "remote_jobs",                      # 0
    "youtube_content_ideas",            # 1 - agent-generated 10M-view ideas
    "ai_search_trends",                 # 2 - what people are searching for
    "viral_video_landscape",            # 3 - merged YouTube section (verified viral, 7d)
    "instagram_viral_reels",            # 4 - viral AI reels (India + global)
    "anthropic_claude_news",            # 5
    "ai_business_automation",           # 6
    "quantum_ai_research",              # 7
    "product_showcase_opportunities",   # 8
    "ai_music_copyright_laws",          # 9
    "elon_musk_ai_vision",              # 10
    "unaddressed_ai_problems",          # 11
    "ai_business_opportunities",        # 12
    "global_ai_news",                   # 13
    "indian_ai_industry",               # 14
    "ai_self_improvement_rsi",          # 15
    "ai_model_benchmarks",              # 16
    "new_ai_tools",                     # 17
    "general_news",                     # 18
]

SECTION_LABELS = {
    "remote_jobs": "Remote AI Automation Jobs (Worldwide)",
    "youtube_content_ideas": "YouTube Content Ideas (10M-View Pitches)",
    "ai_search_trends": "What People in AI Are Searching For",
    "viral_video_landscape": "Viral AI on YouTube (Last 7 Days)",
    "instagram_viral_reels": "Viral Instagram Reels (AI)",
    "anthropic_claude_news": "Anthropic & Claude Code Updates",
    "ai_business_automation": "AI Automation & Businesses",
    "quantum_ai_research": "Quantum + AI",
    "product_showcase_opportunities": "AI Product Showcase Opportunities",
    "ai_music_copyright_laws": "Copyright & Laws in AI Music Business",
    "elon_musk_ai_vision": "Elon Musk's AI Vision",
    "unaddressed_ai_problems": "Unaddressed AI Problems",
    "ai_business_opportunities": "AI Business Opportunities",
    "global_ai_news": "Global AI News",
    "indian_ai_industry": "Indian AI Industry",
    "ai_self_improvement_rsi": "AI Self-Improvement (RSI)",
    "ai_model_benchmarks": "AI Model Benchmarks",
    "new_ai_tools": "New AI Tools",
    "general_news": "General News (non-AI)",
}


def load_scraped_data():
    """Load all scraped data files from .tmp/"""
    data = {
        "jobs": [],
        "jobs_ranked": [],
        "rss_articles": [],
        "youtube_verified": [],
        "youtube_videos": [],
        "instagram_verified": [],
        "ai_trends": [],
    }

    # Prefer the profile-ranked jobs (matched_skills + score). Fall back to
    # raw scrape if the ranker step failed (so we still ship something).
    ranked_file = os.path.join(TMP_DIR, "jobs_ranked.json")
    if os.path.exists(ranked_file):
        with open(ranked_file, "r", encoding="utf-8") as f:
            j = json.load(f)
            data["jobs_ranked"] = j.get("jobs", [])
            print(f"Loaded {len(data['jobs_ranked'])} profile-ranked jobs")

    jobs_file = os.path.join(TMP_DIR, "jobs.json")
    if os.path.exists(jobs_file):
        with open(jobs_file, "r", encoding="utf-8") as f:
            j = json.load(f)
            data["jobs"] = j.get("jobs", [])
            print(f"Loaded {len(data['jobs'])} job postings (raw)")

    ig_file = os.path.join(TMP_DIR, "instagram_verified.json")
    if os.path.exists(ig_file):
        with open(ig_file, "r", encoding="utf-8") as f:
            v = json.load(f)
            data["instagram_verified"] = v.get("reels", [])
            print(f"Loaded {len(data['instagram_verified'])} verified Instagram reels")

    trends_file = os.path.join(TMP_DIR, "ai_trends.json")
    if os.path.exists(trends_file):
        with open(trends_file, "r", encoding="utf-8") as f:
            t = json.load(f)
            data["ai_trends"] = t.get("topics", [])
            print(f"Loaded {len(data['ai_trends'])} AI search-trend topics")

    rss_file = os.path.join(TMP_DIR, "rss_articles.json")
    if os.path.exists(rss_file):
        with open(rss_file, "r", encoding="utf-8") as f:
            r = json.load(f)
            data["rss_articles"] = r.get("articles", [])
            print(f"Loaded {len(data['rss_articles'])} RSS articles")

    yt_verified_file = os.path.join(TMP_DIR, "youtube_verified.json")
    if os.path.exists(yt_verified_file):
        with open(yt_verified_file, "r", encoding="utf-8") as f:
            v = json.load(f)
            data["youtube_verified"] = v.get("videos", [])
            print(f"Loaded {len(data['youtube_verified'])} verified viral videos")

    yt_file = os.path.join(TMP_DIR, "youtube_trending.json")
    if os.path.exists(yt_file):
        with open(yt_file, "r", encoding="utf-8") as f:
            y = json.load(f)
            data["youtube_videos"] = y.get("videos", [])
            print(f"Loaded {len(data['youtube_videos'])} YouTube trending videos")

    return data


def save_analyzed_content(sections_data, total_items):
    """Save agent-produced analysis to the standard output file."""
    os.makedirs(TMP_DIR, exist_ok=True)

    output = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "total_items_analyzed": total_items,
        "sections": sections_data,
        "section_labels": SECTION_LABELS,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nAnalysis saved to {OUTPUT_FILE}")
    print("Section breakdown:")
    for i, section in enumerate(SECTIONS):
        count = len(sections_data.get(section, []))
        label = SECTION_LABELS[section]
        print(f"  [{i:>2}] [{count:>2} items] {label}")

    return output


_AI_GATE_TERMS = (
    " ai ", "artificial intelligence", "machine learning", "neural", "llm",
    "deep learning", "reinforcement learning", "transformer", "language model",
    "openai", "anthropic", "claude", "gpt", "agentic",
)


def _kw_hit(text_lower, keywords):
    """Like the keyword check in agent_analyze.kw_match: word-boundary match for
    short alpha tokens (agi/rsi) so they don't fire inside unrelated words."""
    for k in keywords:
        if len(k) <= 4 and k.isalpha():
            if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text_lower):
                return True
        elif k in text_lower:
            return True
    return False


def _has_ai_signal(text_lower):
    return any(term in f" {text_lower} " for term in _AI_GATE_TERMS)


# User's automation build stack — floats portfolio-relevant tools to the top of
# the New AI Tools section. Mirrors agent_analyze.STACK_TOOLS.
_STACK_TOOLS = (
    "n8n", "voiceflow", "relevance ai", "langchain", "llamaindex", "llama index",
    "cursor", "windsurf", "claude code", "mcp server", "model context protocol",
    "ai agent builder", "agent framework", "agent sdk", "no-code agent", "copilot",
)


def _parse_dt(published_iso):
    """Best-effort parse of a published timestamp into an aware UTC datetime.
    Handles ISO8601, RFC822 (RSS/email), and a few common human formats.
    Returns None if nothing parses."""
    if not published_iso:
        return None
    s = str(published_iso).strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _within_hours(published_iso, hours, strict=False):
    """True if a `published` timestamp is within the last `hours`.

    Lenient default (strict=False): missing/unparseable dates count as fresh —
    better to over-include than drop in non-news contexts.

    strict=True (news sections — user's hard last-24h rule): an item we cannot
    PROVE is within the window is dropped. Missing or unparseable dates count as
    NOT fresh, so agent-enriched items lacking an ISO date can't leak >24h news
    into the PDF."""
    dt = _parse_dt(published_iso)
    if dt is None:
        return not strict
    return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)


def auto_categorize_fallback(loaded):
    """Deterministic keyword-based categorization fallback when no agent
    runs the analysis step (e.g. local dry-run). Less smart than the agent
    but produces a valid analyzed_content.json."""

    sections = {s: [] for s in SECTIONS}

    # Prefer profile-ranked jobs; fall back to raw if ranker didn't run.
    ranked_jobs = loaded.get("jobs_ranked") or []
    job_source = ranked_jobs if ranked_jobs else loaded.get("jobs", [])
    for job in job_source:
        matched = job.get("matched_skills") or []
        sections["remote_jobs"].append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "url": job.get("url", ""),
            "posted": job.get("posted", ""),
            "salary": job.get("salary", ""),
            "source": job.get("source", ""),
            "summary": (job.get("summary") or "")[:300],
            "matched_skills": matched,
            "strong_match": bool(job.get("strong_match")),
            "title_role_hit": job.get("title_role_hit"),
            "relevance": 5,
        })

    # AI search trends (passthrough — already aggregated/ranked by scrape_ai_trends).
    for t in loaded.get("ai_trends", []) or []:
        sections["ai_search_trends"].append({
            "title": t.get("topic", "")[:140],
            "url": (t.get("sample_urls") or [""])[0] or "",
            "sources": t.get("sources") or [],
            "geos": t.get("geos") or [],
            "score": t.get("score"),
            "sample_urls": t.get("sample_urls") or [],
            "summary": (
                f"Trending across: {', '.join(t.get('sources') or []) or 'multiple sources'}. "
                f"Geo: {', '.join(t.get('geos') or []) or 'global'}."
            ),
            "relevance": 5,
        })

    # Instagram viral reels (passthrough; bucket carries India vs Global).
    for r in loaded.get("instagram_verified", []) or []:
        if r.get("no_fresh"):
            sections["instagram_viral_reels"].append({
                "bucket": r.get("bucket", ""),
                "no_fresh": True,
                "relevance": 5,
            })
            continue
        like = int(r.get("like_count") or 0)
        comment = int(r.get("comment_count") or 0)
        sections["instagram_viral_reels"].append({
            "title": (r.get("caption") or "Untitled")[:120],
            "url": r.get("url", ""),
            "username": r.get("username", ""),
            "like_count": like,
            "comment_count": comment,
            "engagement": int(r.get("engagement") or like + comment),
            "play_count": r.get("play_count"),
            "taken_at_iso": r.get("taken_at_iso"),
            "bucket": r.get("bucket", ""),
            "hashtag": r.get("hashtag", ""),
            "summary": (
                f"@{r.get('username','')} - {like:,} likes / {comment:,} comments in 24h. "
                f"#{r.get('hashtag','')}. "
                "Automation angle: study the hook in the first 2s and the caption format - "
                "this is the structure to replicate for your AI-automation channel."
            ),
            "relevance": 5,
        })

    for vid in loaded.get("youtube_verified", []):
        # Pass through "no fresh viral this period" markers so the PDF prints a
        # per-bucket note instead of repeating a recently-shown video.
        if vid.get("no_fresh"):
            sections["viral_video_landscape"].append({
                "bucket": vid.get("bucket", ""),
                "no_fresh": True,
                "view_floor": vid.get("view_floor", 0),
                "format": vid.get("format", "video"),
                "relevance": 5,
            })
            continue
        sections["viral_video_landscape"].append({
            "title": vid.get("title", ""),
            "url": vid.get("url", ""),
            "channel": vid.get("channel", ""),
            "views": vid.get("views", 0),
            "format": vid.get("format", "video"),
            "video_id": vid.get("video_id", ""),
            "summary": (vid.get("description") or "")[:300],
            "bucket": vid.get("bucket", ""),
            "relevance": 5,
        })

    rules = [
        ("ai_music_copyright_laws", ["copyright", "lawsuit", "infringement", "licens", "regulation"]),
        ("anthropic_claude_news", ["anthropic", "claude"]),
        ("elon_musk_ai_vision", ["elon musk", "xai", "grok"]),
        ("quantum_ai_research", ["quantum"]),
        ("indian_ai_industry", ["india", "indian", "bengaluru", "mumbai", "delhi"]),
        ("ai_business_automation", ["automation", "n8n", "zapier", "workflow"]),
        ("ai_model_benchmarks", ["benchmark", "leaderboard", "mmlu", "humaneval", "gpqa"]),
        ("ai_self_improvement_rsi", ["agi", "alignment", "self-improv", "rsi", "recursive"]),
        ("new_ai_tools", ["launch", "release", "available", " api ", "introduces", "unveils",
                          "voiceflow", "relevance ai", "langchain", "llamaindex", "llama index",
                          "cursor", "windsurf", "ai agent builder", "agent framework", "agent sdk",
                          "mcp server", "no-code agent", "copilot"]),
        ("product_showcase_opportunities", ["ai hackathon", "ai agents hackathon", "ai competition", "ai challenge", "devpost", "submission deadline", "hackathon winners", "cash prize", "product hunt", "competition", "showcase", "directory", "submit"]),
        ("ai_business_opportunities", ["startup", "funding", "raised", "opportunit", "series a", "series b"]),
        ("unaddressed_ai_problems", ["problem", "challenge", "limitation", "gap"]),
    ]

    for art in loaded.get("rss_articles", []):
        # Last-24h news only on the main pass. Older items stay in the RSS pool
        # for dedupe_and_backfill to widen thin sections with.
        if not _within_hours(art.get("published"), NEWS_FRESH_HOURS):
            continue
        text = (art.get("title", "") + " " + art.get("summary", "")).lower()
        cat = art.get("category", "")
        target = None
        if cat == "general_news":
            target = "general_news"
        elif cat == "indian":
            # India section is AI-only: non-AI Indian headlines go to General News.
            target = "indian_ai_industry" if _has_ai_signal(text) else "general_news"
        else:
            for sec, keywords in rules:
                if _kw_hit(text, keywords):
                    # Quantum + AI and RSI sections are AI-gated: quantum needs
                    # both quantum AND AI; RSI needs an AI signal. Otherwise pure
                    # quantum / generic "alignment" leaks in.
                    if sec in ("quantum_ai_research", "ai_self_improvement_rsi",
                               "indian_ai_industry") and not _has_ai_signal(text):
                        continue
                    target = sec
                    break
            if not target:
                target = "global_ai_news"

        # Float the user's build-stack tools to the top of New AI Tools.
        rel = 3
        if target == "new_ai_tools" and _kw_hit(text, _STACK_TOOLS):
            rel = 5
        sections[target].append({
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source": art.get("source", ""),
            "summary": (art.get("summary") or "")[:400],
            "published": art.get("published", ""),
            "relevance": rel,
        })

    # New AI Tools sorted by relevance so stack-relevant tools lead the section.
    sections["new_ai_tools"].sort(key=lambda x: x.get("relevance", 0), reverse=True)

    for k in sections:
        cap = 25 if k == "remote_jobs" else 8
        sections[k] = sections[k][:cap]

    return sections


if __name__ == "__main__":
    print("Module: data contract + fallback categorizer for 18-section daily PDF")
    print(f"Sections ({len(SECTIONS)}):")
    for i, key in enumerate(SECTIONS):
        print(f"  [{i:>2}] {key}: {SECTION_LABELS[key]}")
