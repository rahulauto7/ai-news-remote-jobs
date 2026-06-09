"""Post-analysis cleanup: cross-day de-duplication + min-3 backfill.

Runs AFTER the analyzer writes .tmp/analyzed_content.json and BEFORE the YouTube
ideas + PDF steps. Two jobs:

  1. Cross-day dedup (news) — drop items in RSS-routed sections whose URL was
     surfaced in the last DEDUP_DAYS days (history in data/content_seen.json via
     tools.content_history). Keeps consecutive days from repeating the same
     stories the 7-day RSS window otherwise re-serves. `ai_model_benchmarks` is
     EXEMPT — it's a standings snapshot, intentionally stable day to day.

  2. Min-3 backfill — any RSS-routed section left below SECTION_MIN is topped up
     from the unrouted RSS pool (articles not already placed and not recently
     seen), re-classified with the same gates as the main pass (so quantum/RSI
     keep their AND-AI requirement).

Finally records every surfaced RSS URL under the "news" namespace so the next
run can rotate them out.

Reads/writes: .tmp/analyzed_content.json  (in place)
Reads:        .tmp/rss_articles.json      (unrouted pool)
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tools.agent_analyze import classify, clean, is_ai, SECTION_MIN, LLM_SECTIONS
from tools.analyze_and_categorize import OUTPUT_FILE, _within_hours, NEWS_FRESH_HOURS
from tools import content_history

TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
RSS_FILE = os.path.join(TMP_DIR, "rss_articles.json")

NEWS_NS = "news"
DEDUP_DAYS = 7
# Sections that must NOT be de-duplicated across days.
#  - ai_model_benchmarks: "top model per category" standings snapshot — repetition
#    there is correct, not stale news.
#  - product_showcase_opportunities: hackathons/accelerators recur every day until
#    their deadline (weeks out). News-style dedup deletes them and records their
#    URLs as "seen", which permanently empties the user's portfolio-showcase
#    section. This is the user's most important section — it must never empty.
DEDUP_EXEMPT = {"ai_model_benchmarks", "product_showcase_opportunities"}

# ── Final deterministic guard over the categorized sections ───────────────────
# Probabilistic categorization (the Claude agent OR the keyword fallback) can
# misroute non-AI headlines into AI-only sections and leave >24h items behind.
# These two sets are scrubbed AFTER analysis so the PDF is always AI-only and
# strictly last-24h, regardless of how categorization happened.
#
# AI_ONLY_SECTIONS: drop any item whose title+summary shows no AI signal.
#   Excludes general_news (intentionally non-AI), ai_model_benchmarks (standings
#   rows carry no AI keyword), ai_search_trends (short query phrases), jobs/
#   showcase/youtube/instagram/viral (own logic, often no literal "AI" token).
AI_ONLY_SECTIONS = {
    "indian_ai_industry", "global_ai_news", "anthropic_claude_news",
    "new_ai_tools", "ai_business_automation", "ai_business_opportunities",
    "elon_musk_ai_vision", "ai_self_improvement_rsi", "quantum_ai_research",
    "unaddressed_ai_problems", "ai_music_copyright_laws",
}
# NEWS_24H_SECTIONS: drop any dated item older than NEWS_FRESH_HOURS.
#   Excludes remote_jobs (postings; freshness via job_history dedup),
#   product_showcase_opportunities (future deadlines, never-empty),
#   ai_model_benchmarks (standings snapshot), viral_video_landscape (7-day by
#   design — virality needs time), instagram_viral_reels (own 24h verify),
#   youtube_content_ideas (synthesized), ai_search_trends (no published date).
NEWS_24H_SECTIONS = AI_ONLY_SECTIONS | {"general_news"}


def _sanitize_sections(sections: dict) -> tuple[int, int]:
    """Drop non-AI items from AI-only sections and >24h items from news
    sections. Returns (non_ai_dropped, stale_dropped)."""
    non_ai = stale = 0
    for sec, items in sections.items():
        if not isinstance(items, list):
            continue
        kept = []
        for it in items:
            if not isinstance(it, dict):
                kept.append(it)
                continue
            text = f"{it.get('title', '')} {it.get('summary', '')}"
            if sec in AI_ONLY_SECTIONS and not is_ai(text):
                non_ai += 1
                continue
            if sec in NEWS_24H_SECTIONS and not _within_hours(
                    it.get("published") or it.get("posted"), NEWS_FRESH_HOURS):
                stale += 1
                continue
            kept.append(it)
        sections[sec] = kept
    return non_ai, stale

# Deterministic "Top Model Per Category" seed for ai_model_benchmarks so the
# section always leads with the standings table (like the reference PDFs), even
# on days with no fresh benchmark article. The cloud agent (enrichment step)
# refreshes the winners; this is the safety net. (category, best, runner-up, benchmark)
BENCHMARK_STANDINGS = [
    ("Text / LLM", "Claude Opus 4.x", "GPT-5.x", "LMSYS Chatbot Arena (blended Elo)"),
    ("Coding", "Claude Sonnet 4.x (via Claude Code)", "GPT-5 Codex", "SWE-bench Verified"),
    ("Image Generation", "ChatGPT Images 2.0", "Midjourney v7", "Arena + editorial eval"),
    ("Video Generation", "Sora 2", "Google Veo 3", "VBench 2.0 + human-eval"),
    ("Music / Audio", "Suno v5", "Udio v2.5", "MusicArena"),
    ("Reasoning / Math", "GPT-5.x (extended thinking)", "Claude Opus 4.x", "AIME / FrontierMath"),
]


def _seed_benchmark_standings(sections: dict) -> None:
    """Prepend the per-category 'top model' standings to ai_model_benchmarks
    unless the section already carries standings rows (agent-written or a prior
    seed). Trims trailing benchmark news so the section stays within the cap."""
    sec = sections.get("ai_model_benchmarks")
    if sec is None:
        return
    if any(isinstance(it, dict) and it.get("standings") for it in sec):
        return  # already has standings (agent refreshed them) — leave alone
    rows = []
    for category, best, runner, bench in BENCHMARK_STANDINGS:
        rows.append({
            "title": f"{category} - Best: {best} / Runner-up: {runner}",
            "url": "",
            "source": "Curated standings (refresh weekly)",
            "summary": (
                f"Current category leader: {best}; runner-up {runner}. "
                "Automation angle: switch your portfolio demos to whichever model "
                "ranks best in the category you build in this week."
            ),
            # Explicit columns for the PDF grid renderer (build_benchmark_table_section).
            "category": category,
            "best": best,
            "runner_up": runner,
            "benchmark": bench,
            "model_name": best,
            "benchmark_name": bench,
            "standings": True,
            "published": "",
            "relevance": 6,
        })
    # standings first, then keep enough news to hit the 8-item cap
    news = [it for it in sec if not (isinstance(it, dict) and it.get("standings"))]
    sections["ai_model_benchmarks"] = (rows + news)[:8]


def _item_from_article(art: dict, section: str, rel: int, summary: str) -> dict:
    return {
        "title": clean(art.get("title", "")),
        "url": art.get("url", "") or art.get("link", ""),
        "source": art.get("source", ""),
        "summary": summary,
        "published": art.get("published", "") or art.get("pubDate", ""),
        "relevance": rel,
    }


def main() -> int:
    if not os.path.exists(OUTPUT_FILE):
        print(f"[dedupe_backfill] no {OUTPUT_FILE} — nothing to do")
        return 0

    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        doc = json.load(f)
    sections = doc.get("sections", {})
    if not isinstance(sections, dict):
        print("[dedupe_backfill] malformed analyzed_content.json — skipping")
        return 0

    rss_articles = []
    if os.path.exists(RSS_FILE):
        with open(RSS_FILE, "r", encoding="utf-8") as f:
            rss_articles = (json.load(f) or {}).get("articles", []) or []

    seen = content_history.recently_seen(NEWS_NS, DEDUP_DAYS)

    # URLs already placed anywhere (used to compute the unrouted pool).
    placed_urls = {
        (it.get("url") or "")
        for sec in sections.values() if isinstance(sec, list)
        for it in sec if isinstance(it, dict)
    }

    rss_sections = [s for s in LLM_SECTIONS if s in sections]

    # --- 1. Cross-day dedup (non-exempt RSS sections) ---
    dropped = 0
    for sec in rss_sections:
        if sec in DEDUP_EXEMPT:
            continue
        kept = [it for it in sections[sec] if (it.get("url") or "") not in seen]
        dropped += len(sections[sec]) - len(kept)
        sections[sec] = kept

    # --- 2. Min-3 backfill from the unrouted pool ---
    # Classify every unrouted, not-recently-seen article once; bucket by section.
    buckets: dict[str, list] = {s: [] for s in rss_sections}
    for art in rss_articles:
        url = art.get("url", "") or art.get("link", "")
        if not url or url in placed_urls or url in seen:
            continue
        # Strict last-24h: never widen news sections with older pool items.
        # (User rule overrides the legacy "widen to <=7 days" backfill.)
        if not _within_hours(art.get("published"), NEWS_FRESH_HOURS):
            continue
        sec, rel, summary = classify(art)
        if sec in buckets:
            buckets[sec].append(_item_from_article(art, sec, rel, summary))

    added = 0
    for sec in rss_sections:
        need = SECTION_MIN - len(sections[sec])
        if need <= 0:
            continue
        # relevance desc, then most-recent first (published is an ISO string)
        pool = sorted(
            buckets.get(sec, []),
            key=lambda x: (x.get("relevance", 0), x.get("published", "")),
            reverse=True,
        )
        have = {it.get("url") for it in sections[sec]}
        for cand in pool:
            if len(sections[sec]) >= SECTION_MIN:
                break
            if cand.get("url") in have:
                continue
            sections[sec].append(cand)
            have.add(cand.get("url"))
            added += 1

    # --- 2b. Seed benchmarks standings table (exempt from dedup) ---
    _seed_benchmark_standings(sections)

    # --- 2c. Deterministic guard: AI-only + strict-24h over final sections ---
    non_ai_dropped, stale_dropped = _sanitize_sections(sections)

    # --- 3. Record surfaced RSS URLs so tomorrow rotates them out ---
    surfaced = [
        (it.get("url") or "")
        for sec in rss_sections
        for it in sections[sec]
        if (it.get("url") or "")
    ]
    content_history.record_shown(NEWS_NS, surfaced)

    doc["sections"] = sections
    doc["total_items_analyzed"] = sum(
        len(v) for v in sections.values() if isinstance(v, list)
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(
        f"[dedupe_backfill] dropped {dropped} repeat(s), backfilled {added}, "
        f"scrubbed {non_ai_dropped} non-AI + {stale_dropped} stale (>24h), "
        f"recorded {len(set(surfaced))} URL(s) in '{NEWS_NS}' history"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
