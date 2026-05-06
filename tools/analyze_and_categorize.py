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
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
OUTPUT_FILE = os.path.join(TMP_DIR, "analyzed_content.json")

SECTIONS = [
    "remote_jobs",                      # 0
    "anthropic_claude_news",            # 1
    "ai_business_automation",           # 2
    "quantum_ai_research",              # 3
    "product_showcase_opportunities",   # 4
    "viral_video_landscape",            # 5
    "youtube_ai_landscape",             # 6
    "ai_music_copyright_laws",          # 7
    "elon_musk_ai_vision",              # 8
    "unaddressed_ai_problems",          # 9
    "ai_business_opportunities",        # 10
    "ai_music_business_news",           # 11
    "global_ai_news",                   # 12
    "indian_ai_industry",               # 13
    "ai_self_improvement_rsi",          # 14
    "ai_model_benchmarks",              # 15
    "new_ai_tools",                     # 16
    "general_news",                     # 17
]

SECTION_LABELS = {
    "remote_jobs": "Remote AI Automation Jobs (USA / Global)",
    "anthropic_claude_news": "Anthropic & Claude Code Updates",
    "ai_business_automation": "AI Automation & Businesses",
    "quantum_ai_research": "Quantum + AI",
    "product_showcase_opportunities": "AI Product Showcase Opportunities",
    "viral_video_landscape": "Viral Video Landscape (verified)",
    "youtube_ai_landscape": "YouTube AI Landscape",
    "ai_music_copyright_laws": "Copyright & Laws in AI Music Business",
    "elon_musk_ai_vision": "Elon Musk's AI Vision",
    "unaddressed_ai_problems": "Unaddressed AI Problems",
    "ai_business_opportunities": "AI Business Opportunities",
    "ai_music_business_news": "AI Music Business News",
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
        "rss_articles": [],
        "youtube_verified": [],
        "youtube_videos": [],
    }

    jobs_file = os.path.join(TMP_DIR, "jobs.json")
    if os.path.exists(jobs_file):
        with open(jobs_file, "r", encoding="utf-8") as f:
            j = json.load(f)
            data["jobs"] = j.get("jobs", [])
            print(f"Loaded {len(data['jobs'])} job postings")

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


def auto_categorize_fallback(loaded):
    """Deterministic keyword-based categorization fallback when no agent
    runs the analysis step (e.g. local dry-run). Less smart than the agent
    but produces a valid analyzed_content.json."""

    sections = {s: [] for s in SECTIONS}

    for job in loaded.get("jobs", []):
        sections["remote_jobs"].append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "url": job.get("url", ""),
            "posted": job.get("posted", ""),
            "salary": job.get("salary", ""),
            "source": job.get("source", ""),
            "summary": (job.get("summary") or "")[:300],
            "relevance": 5,
        })

    for vid in loaded.get("youtube_verified", []):
        sections["viral_video_landscape"].append({
            "title": vid.get("title", ""),
            "url": vid.get("url", ""),
            "channel": vid.get("channel", ""),
            "views": vid.get("views", 0),
            "format": vid.get("format", "video"),
            "summary": (vid.get("description") or "")[:300],
            "bucket": vid.get("bucket", ""),
            "relevance": 5,
        })

    for vid in loaded.get("youtube_videos", []):
        sections["youtube_ai_landscape"].append({
            "title": vid.get("title", ""),
            "url": vid.get("url", ""),
            "channel": vid.get("channel", ""),
            "views": vid.get("views", 0),
            "summary": (vid.get("description") or "")[:300],
            "relevance": 4,
        })

    rules = [
        ("ai_music_copyright_laws", ["copyright", "lawsuit", "infringement", "licens", "regulation"]),
        ("ai_music_business_news", ["suno", "udio", "distrokid", "ai music", "music ai", "spotify ai"]),
        ("anthropic_claude_news", ["anthropic", "claude"]),
        ("elon_musk_ai_vision", ["elon musk", "xai", "grok"]),
        ("quantum_ai_research", ["quantum"]),
        ("indian_ai_industry", ["india", "indian", "bengaluru", "mumbai", "delhi"]),
        ("ai_business_automation", ["automation", "n8n", "zapier", "workflow"]),
        ("ai_model_benchmarks", ["benchmark", "leaderboard", "mmlu", "humaneval", "gpqa"]),
        ("ai_self_improvement_rsi", ["agi", "alignment", "self-improv", "rsi", "recursive"]),
        ("new_ai_tools", ["launch", "release", "available", " api ", "introduces", "unveils"]),
        ("product_showcase_opportunities", ["product hunt", "competition", "showcase", "directory", "submit"]),
        ("ai_business_opportunities", ["startup", "funding", "raised", "opportunit", "series a", "series b"]),
        ("unaddressed_ai_problems", ["problem", "challenge", "limitation", "gap"]),
    ]

    for art in loaded.get("rss_articles", []):
        text = (art.get("title", "") + " " + art.get("summary", "")).lower()
        cat = art.get("category", "")
        target = None
        if cat == "general_news":
            target = "general_news"
        elif cat == "indian":
            target = "indian_ai_industry"
        else:
            for sec, keywords in rules:
                if any(k in text for k in keywords):
                    target = sec
                    break
            if not target:
                target = "global_ai_news"

        sections[target].append({
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source": art.get("source", ""),
            "summary": (art.get("summary") or "")[:400],
            "published": art.get("published", ""),
            "relevance": 3,
        })

    for k in sections:
        cap = 25 if k == "remote_jobs" else 8
        sections[k] = sections[k][:cap]

    return sections


if __name__ == "__main__":
    print("Module: data contract + fallback categorizer for 18-section daily PDF")
    print(f"Sections ({len(SECTIONS)}):")
    for i, key in enumerate(SECTIONS):
        print(f"  [{i:>2}] {key}: {SECTION_LABELS[key]}")
