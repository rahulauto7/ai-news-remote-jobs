"""
Placeholder writer for the two agent-generated YouTube artifacts.

Run from the daily pipeline BEFORE the cloud Claude agent overwrites them with
real content. A fresh empty placeholder is (re)written whenever the file is
missing OR still an empty placeholder, so a stale placeholder from a previous run
never persists. A file that already holds real agent content is left untouched.

Writes:
  .tmp/youtube_content_ideas.json     (for PDF section: "YouTube Content Ideas")
  .tmp/youtube_section_analysis.json  (for the merged "Viral AI on YouTube" section)

Schema — youtube_content_ideas.json:
  {"generated_at": "...", "ideas": [
    {"title": "...", "hook": "...", "why_10m": ["...","...","..."],
     "thumbnail": "...", "outline": ["1...","2...","3...","4...","5..."],
     "source_sections": ["ai_search_trends","viral_video_landscape","new_ai_tools"]}
  ]}

Schema — youtube_section_analysis.json:
  {"generated_at": "...",
   "landscape": "1 short paragraph about what AI YouTubers are doing right now.",
   "content_patterns": ["...", "..."],
   "gaps":             ["...", "..."],
   "mistakes":         ["...", "..."],
   "viral_explanations": {"<video_id>": "Why it went viral: ..."}}
"""

import json
import os
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")

IDEAS_FILE = os.path.join(TMP_DIR, "youtube_content_ideas.json")
ANALYSIS_FILE = os.path.join(TMP_DIR, "youtube_section_analysis.json")
ANALYZED_FILE = os.path.join(TMP_DIR, "analyzed_content.json")

# Sections the deterministic fallback mines for the 3 pitches, in priority order.
IDEA_SOURCE_SECTIONS = [
    "new_ai_tools", "viral_video_landscape", "ai_search_trends",
    "ai_business_automation", "anthropic_claude_news", "global_ai_news",
]
# Anything except non-story passthroughs — used to top up to 3 ideas when the
# priority sections above are thin.
IDEA_FALLBACK_EXCLUDE = {"remote_jobs", "youtube_content_ideas", "general_news"}


def _has_real_content(path, keys):
    """True if `path` exists and at least one of `keys` holds non-empty content.
    Used to tell a real agent-written file apart from an empty placeholder so we
    never clobber real content — but always refresh a stale empty placeholder."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    return any(data.get(k) for k in keys)


def _write_fresh_unless_real(path, payload, real_keys):
    """Write a fresh placeholder unless the file already holds real content.

    Returns one of: 'kept real', 'refreshed placeholder', 'created placeholder'.
    The old behaviour kept ANY existing file, so a stale empty placeholder from a
    previous run (e.g. days old) silently persisted and the PDF section rendered
    blank. Now an empty/stale placeholder is always re-stamped for this run.
    """
    if _has_real_content(path, real_keys):
        return "kept real"
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return "refreshed placeholder" if existed else "created placeholder"


def _truncate(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _synth_ideas_from_analysis():
    """Build 3 template-based 10M-view pitches from the strongest stories in
    analyzed_content.json. Deterministic safety net so the PDF section is never
    empty when the cloud agent's richer Prompt-A pass doesn't run."""
    if not os.path.exists(ANALYZED_FILE):
        return []
    try:
        with open(ANALYZED_FILE, "r", encoding="utf-8") as f:
            sections = (json.load(f) or {}).get("sections", {}) or {}
    except Exception:
        return []

    # Pick the single strongest story per source section, in priority order,
    # skipping sections with no items, until we have 3 distinct seeds. If the
    # priority sections are thin, top up from any remaining story section so the
    # section always ships exactly 3 ideas.
    order = IDEA_SOURCE_SECTIONS + [
        s for s in sections if s not in IDEA_SOURCE_SECTIONS and s not in IDEA_FALLBACK_EXCLUDE
    ]
    seeds = []
    used_titles = set()
    for sec in order:
        items = sections.get(sec) or []
        if not items:
            continue
        top = max(items, key=lambda x: x.get("relevance", 0))
        title = (top.get("title") or "").strip()
        if not title or title in used_titles:
            continue
        used_titles.add(title)
        seeds.append((sec, top))
        if len(seeds) == 3:
            break

    ideas = []
    for sec, story in seeds:
        topic = _truncate(story.get("title", ""), 70).rstrip(".")
        short = _truncate(topic, 42)
        ideas.append({
            "title": _truncate(f"I Tried {short} So You Don't Have To", 60),
            "hook": _truncate(
                f"Everyone's talking about {short} — but nobody shows you what "
                f"actually happens when you use it. I did. Watch this first.", 220),
            "why_10m": [
                f"Rides a story already trending in '{sec}' — built-in search demand.",
                "First-person 'I tried X' framing is the highest-CTR AI format on YouTube.",
                "Teaches a concrete AI-automation workflow viewers can copy that day.",
            ],
            "thumbnail": _truncate(
                f"Split screen: shocked face left, '{short}' result on screen right, "
                f"bold 3-word caption.", 160),
            "outline": [
                f"0:00 Hook — the bold claim about {short}.",
                "0:30 The problem this solves for AI-automation builders.",
                "1:30 Live build/demo, step by step on screen.",
                "4:00 The surprising result + one gotcha to avoid.",
                "5:30 Payoff + how to replicate it, then subscribe CTA.",
            ],
            "source_sections": [sec],
        })
    return ideas


def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    ideas_payload = {"generated_at": now, "ideas": _synth_ideas_from_analysis()}
    analysis_payload = {
        "generated_at": now,
        "landscape": "",
        "content_patterns": [],
        "gaps": [],
        "mistakes": [],
        "viral_explanations": {},
    }

    ideas_status = _write_fresh_unless_real(IDEAS_FILE, ideas_payload, ["ideas"])
    analysis_status = _write_fresh_unless_real(
        ANALYSIS_FILE, analysis_payload,
        ["landscape", "content_patterns", "gaps", "mistakes", "viral_explanations"],
    )

    print(f"youtube_content_ideas.json: {ideas_status}")
    print(f"youtube_section_analysis.json: {analysis_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
