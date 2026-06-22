"""Post-analysis cleanup: cross-day de-duplication (no min-floor backfill).

Runs AFTER the analyzer writes .tmp/analyzed_content.json and BEFORE the YouTube
ideas + PDF steps. Jobs:

  1. Cross-day dedup (news) — drop items in RSS-routed sections whose URL was
     surfaced in the last DEDUP_DAYS days (history in data/content_seen.json via
     tools.content_history). Keeps consecutive days from repeating the same
     stories the 7-day RSS window otherwise re-serves. `ai_model_benchmarks` is
     EXEMPT — it's a standings snapshot, intentionally stable day to day.

  2. Min-3 backfill — DISABLED (user rule 2026-06-13: "just the 24-hour rule, no
     minimum floor"). Sections show ONLY what the strict last-24h classifier
     routed; a thin/empty section is left honest rather than padded from the
     older pool. The fix for genuinely empty sections is healthy feeds, not
     backfill.

Finally records every surfaced RSS URL under the "news" namespace so the next
run can rotate them out.

Reads/writes: .tmp/analyzed_content.json  (in place)
Reads:        .tmp/rss_articles.json      (unrouted pool)
"""

from __future__ import annotations

import json
import os
import re
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

# Sections whose dedup is DEFERRED to tools/finalize_qrsi_dedup.py, run after
# AGENT ENRICHMENT. Enrichment is the step that "confirms/repopulates" these two
# sections by reasoning over the unrouted pool — if we dedup+record them here
# (before enrichment runs), any item the agent adds afterward skips the
# seen-history check entirely and never gets recorded either, so it can repeat
# indefinitely. Deferring means they're checked exactly once, against the final
# post-enrichment contents. finalize_qrsi_dedup.py uses its own "qrsi" namespace
# (not "news"), so articles that appeared in other sections on previous days are
# still eligible to receive dedicated quantum/RSI treatment.
DEFERRED_DEDUP_SECTIONS = {"quantum_ai_research", "ai_self_improvement_rsi"}

# ── Title-similarity dedup within a section ───────────────────────────────────
_STOP = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at",
         "with", "is", "are", "was", "were", "by", "its", "this", "that", "new"}

def _title_key(title: str) -> frozenset:
    words = re.findall(r"[a-z]+", title.lower())
    return frozenset(w for w in words if w not in _STOP and len(w) > 2)


def _dedup_section_by_title(items: list) -> list:
    """Drop articles whose title shares >55% Jaccard overlap with a prior item.

    Collapses multi-source same-story coverage (e.g. TechCrunch + Verge + VentureBeat
    all covering the same release). Keeps the highest-relevance item per story.
    """
    sorted_items = sorted(
        items,
        key=lambda x: x.get("relevance_score", x.get("relevance", 0)),
        reverse=True,
    )
    kept: list = []
    seen_keys: list[frozenset] = []
    for item in sorted_items:
        key = _title_key(item.get("title", ""))
        if not key:
            kept.append(item)
            continue
        if any(
            len(key & sk) / max(len(key | sk), 1) > 0.55
            for sk in seen_keys
        ):
            continue
        seen_keys.append(key)
        kept.append(item)
    return kept

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
            # The appended "Automation angle: …" hook is always AI-flavored, so
            # testing the full summary would mask a misrouted non-AI headline.
            # Check the head (title + real summary) only, before that hook.
            head = text.lower().split("automation angle:", 1)[0]
            if sec in AI_ONLY_SECTIONS and not is_ai(head):
                non_ai += 1
                continue
            if sec in NEWS_24H_SECTIONS and not _within_hours(
                    it.get("published") or it.get("posted"), NEWS_FRESH_HOURS,
                    strict=True):
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


def sanitize_only() -> int:
    """Re-run ONLY the deterministic AI-only + strict-24h guard over the final
    analyzed_content.json — no dedup, no history recording, no backfill.

    The normal main() sanitize (step 6.6) runs BEFORE Stage 2 AGENT ENRICHMENT
    (step 6.7), which rewrites/adds news items the early gate never sees. Without
    a re-run, agent-enriched items older than 24h (or carrying a non-ISO date)
    leak into the PDF — the "news from the last two days" bug. Call this AFTER
    enrichment (step 6.7c) so the hard last-24h rule is enforced on the items the
    PDF actually renders. Idempotent and side-effect-free; safe to call twice."""
    if not os.path.exists(OUTPUT_FILE):
        print(f"[sanitize] no {OUTPUT_FILE} — nothing to do")
        return 0
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        doc = json.load(f)
    sections = doc.get("sections", {})
    if not isinstance(sections, dict):
        print("[sanitize] malformed analyzed_content.json — skipping")
        return 0
    non_ai_dropped, stale_dropped = _sanitize_sections(sections)
    doc["sections"] = sections
    doc["total_items_analyzed"] = sum(
        len(v) for v in sections.values() if isinstance(v, list)
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"[sanitize] scrubbed {non_ai_dropped} non-AI + {stale_dropped} "
          f"stale (>24h) item(s) post-enrichment")
    return 0


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
        if sec in DEDUP_EXEMPT or sec in DEFERRED_DEDUP_SECTIONS:
            continue
        kept = [it for it in sections[sec] if (it.get("url") or "") not in seen]
        dropped += len(sections[sec]) - len(kept)
        sections[sec] = kept

    # --- 1b. Title-similarity dedup within each section ---
    # Multiple RSS sources often cover the same story with different URLs.
    # Collapse same-story duplicates, keeping the highest-relevance item.
    title_dropped = 0
    _title_exempt = DEDUP_EXEMPT | DEFERRED_DEDUP_SECTIONS | {
        "remote_jobs", "ai_search_trends", "viral_video_landscape",
        "instagram_viral_reels", "youtube_content_ideas", "ai_model_benchmarks",
        "product_showcase_opportunities",
    }
    for sec in rss_sections:
        if sec in _title_exempt:
            continue
        before = len(sections[sec])
        sections[sec] = _dedup_section_by_title(sections[sec])
        title_dropped += before - len(sections[sec])

    # --- 2. Min-3 backfill: DISABLED (user rule 2026-06-13) ---
    # The user's standing rule is "just the 24-hour rule, no minimum floor":
    # every section shows ONLY what the strict last-24h classifier routed, even if
    # that leaves a section below 3 items or empty. We no longer top sections up to
    # SECTION_MIN from the unrouted pool — an honest thin/empty section beats padding
    # with marginal items pulled in just to hit a floor. (The fix for genuinely empty
    # sections is healthy feeds, not backfill — see the brotli/arXiv feed fixes.)
    added = 0

    # --- 2b. Seed benchmarks standings table (exempt from dedup) ---
    _seed_benchmark_standings(sections)

    # --- 2c. Deterministic guard: AI-only + strict-24h over final sections ---
    non_ai_dropped, stale_dropped = _sanitize_sections(sections)

    # --- 3. Record surfaced RSS URLs so tomorrow rotates them out ---
    # DEFERRED_DEDUP_SECTIONS are recorded later by finalize_qrsi_dedup.py, once
    # their post-enrichment contents are final.
    surfaced = [
        (it.get("url") or "")
        for sec in rss_sections
        if sec not in DEFERRED_DEDUP_SECTIONS
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
        f"[dedupe_backfill] dropped {dropped} URL-repeat(s) + {title_dropped} same-story "
        f"duplicate(s), backfilled {added}, scrubbed {non_ai_dropped} non-AI + "
        f"{stale_dropped} stale (>24h), recorded {len(set(surfaced))} URL(s) in '{NEWS_NS}' history"
    )
    return 0


if __name__ == "__main__":
    if "--sanitize-only" in sys.argv:
        raise SystemExit(sanitize_only())
    raise SystemExit(main())
