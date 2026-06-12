"""Agent-driven RSS categorization for the daily 18-section PDF.

This is the analysis step. It loads scraped data from .tmp/, routes articles
into the 18 sections defined in tools.analyze_and_categorize, writes plain-
English 1-2 sentence summaries from titles (because most RSS bodies are
paywalled or empty), and saves the result via save_analyzed_content().
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from html import unescape

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tools.analyze_and_categorize import (  # noqa: E402
    SECTIONS, load_scraped_data, save_analyzed_content,
)

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = unescape(s)
    s = TAG_RE.sub("", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def summary_from(title: str, body: str, max_len: int = 320) -> str:
    """Build a plain-English 1-2 sentence summary. Prefer a clean RSS body
    if available, else echo the title. Strip HTML and truncate cleanly."""
    title = clean_text(title)
    body = clean_text(body)
    if body and len(body) > 30 and body.lower() != title.lower():
        # Prefer first 1-2 sentences of the body if useful
        m = re.match(r"(.{40,400}?[.!?])(\s|$)", body)
        text = m.group(1) if m else body[:max_len]
        if len(text) > max_len:
            text = text[: max_len - 1].rsplit(" ", 1)[0] + "…"
        return text
    # Fall back to the title alone — phrased as a sentence.
    if not title:
        return ""
    if title.endswith((".", "!", "?")):
        return title
    return title + "."


def has_any(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def has_all_groups(text: str, groups: list[list[str]]) -> bool:
    return all(has_any(text, g) for g in groups)


def parse_dt(s: str):
    if not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        # Accept ISO and a few RSS variants
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2)
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(s)
        except Exception:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)


def article_entry(art: dict, relevance: int) -> dict:
    title = clean_text(art.get("title", ""))
    return {
        "title": title,
        "url": art.get("url", "") or art.get("link", ""),
        "source": art.get("source", ""),
        "summary": summary_from(title, art.get("summary", "") or art.get("description", "")),
        "published": art.get("published", "") or art.get("pubDate", ""),
        "relevance": relevance,
    }


# ------- AI relevance helpers -------
AI_TERMS = [
    "ai", "a.i", "artificial intelligence", "llm", "large language",
    "gpt", "chatgpt", "openai", "anthropic", "claude", "gemini", "google ai",
    "deepmind", "meta ai", "mistral", "perplexity", "huggingface", "hugging face",
    "stable diffusion", "midjourney", "runway", "elevenlabs", "suno", "udio",
    "machine learning", "neural", "agentic", "agents", "agent", "rag",
    "transformer", "model", "robotics", "autonomous", "copilot", "grok", "xai",
]


def is_ai_related(text: str) -> bool:
    t = " " + text.lower() + " "
    # require an AI-ish term — but exclude tangential matches like "Mumbai" containing "ai"
    # so we check whole-word for short tokens
    if " ai " in t or " a.i. " in t:
        return True
    for kw in AI_TERMS[2:]:
        if kw in t:
            return True
    return False


# Mirrors tools/agent_analyze.py — keep these in sync.
# AI music tools stay OUT of New AI Tools; bare "benchmark" needs an eval co-signal.
MUSIC_TERMS = ["suno", "udio", "ai music", "ai song", "music generat",
               "song generat", "lyrics", "text-to-music", "music model",
               "beat maker", "ai composer", "ai-generated music", "music ai",
               "songwriting ai", "ai vocal"]
STRONG_BENCH_TOKENS = ["mmlu", "humaneval", "gpqa", "swe-bench", "lmsys", "arena",
                       "eval suite", "leaderboard", "model ranking", "mt-bench",
                       "livebench", "aider polyglot", "mmmu", "gsm8k",
                       "math benchmark", "benchmark score", "evals"]
BENCH_CONTEXT = ["model", "llm", "score", "outperform", "eval", "rank", "accuracy",
                 "state-of-the-art", "sota", "beats", "tokens/s", "parameters",
                 "context window", "reasoning"]


# ------- Job filtering -------
def is_seeking_work(j: dict) -> bool:
    t = (j.get("title", "") + " " + (j.get("summary") or "")).upper()
    return "SEEKING WORK" in t or "FREELANCER" in t and "SEEKING" in t


def job_summary(j: dict) -> str:
    title = clean_text(j.get("title", ""))
    company = clean_text(j.get("company", ""))
    body = clean_text(j.get("summary", "") or j.get("description", ""))[:240]
    if company and title:
        head = f"{company} is hiring: {title}."
    elif title:
        head = title.rstrip(".") + "."
    else:
        head = "Remote AI role."
    if body and body.lower() not in head.lower():
        return (head + " " + body)[:320]
    return head[:320]


def job_score(j: dict) -> int:
    """Higher = more relevant for remote AI automation seekers."""
    text = (j.get("title", "") + " " + (j.get("summary") or "")).lower()
    score = 0
    for kw, pts in [
        ("ai automation", 6), ("automation engineer", 5), ("ml engineer", 4),
        ("ai engineer", 5), ("llm", 4), ("agent", 3), ("claude", 4),
        ("python", 2), ("remote", 2), ("n8n", 4), ("zapier", 4), ("workflow", 2),
        ("prompt", 3), ("anthropic", 5), ("openai", 3),
    ]:
        if kw in text:
            score += pts
    return score


# ------- Section routing -------
def route_article(art: dict) -> str | None:
    title = (art.get("title", "") or "")
    body = (art.get("summary", "") or "")
    text = (title + " " + body).lower()
    src = (art.get("source", "") or "").lower()
    cat = (art.get("category", "") or "").lower()

    # Section 17 — General News (BBC/Hindu/NDTV) unless clearly AI
    if cat == "general_news" or src in {"bbc world", "the hindu - national", "ndtv top stories"}:
        if not is_ai_related(text):
            return "general_news"
        # else AI-touching world story → fall through to AI routing

    # Section 1 — Anthropic / Claude
    if has_any(text, ["anthropic", "claude code", "claude "]) or "anthropic" in src or "claude code" in src:
        return "anthropic_claude_news"

    # Section 8 — Elon Musk / xAI / Grok
    if has_any(text, ["elon musk", "elon's", " xai", "x.ai", "grok"]) or "elon musk" in src or "xai news" in src:
        return "elon_musk_ai_vision"

    # Section 7 — AI music copyright
    if has_any(text, ["copyright", "lawsuit", "sued", "infringement", "license", "regulation", "court"]) \
            and has_any(text, ["ai", "music", "song", "deepfake", "voice", "image generator"]):
        return "ai_music_copyright_laws"

    # Section 3 — Quantum + AI
    if "quantum" in src or "quantum" in text:
        return "quantum_ai_research"

    # Section 14 — RSI / AGI / alignment
    if has_any(text, ["agi", "superintelligence", "alignment", "self-improv", "recursive self", "rsi"]):
        return "ai_self_improvement_rsi"

    # Section 15 — Benchmarks. Strong eval tokens pass; a bare "benchmark" needs an
    # AI + eval co-signal so casual "new benchmark for X" headlines drop out.
    if has_any(text, STRONG_BENCH_TOKENS) or (
        "benchmark" in text and is_ai_related(text) and has_any(text, BENCH_CONTEXT)
    ):
        return "ai_model_benchmarks"

    # Section 4 — Product showcase / Hackathons & competitions
    # Source-based routing: dedicated hackathon feeds always land here.
    if "hackathon" in src or "competition" in src or "devpost" in src:
        return "product_showcase_opportunities"
    if has_any(text, [
        "ai hackathon", "ai agents hackathon", "ai agent hackathon",
        "agent platform hackathon", "ai competition", "ai challenge",
        "devpost", "submission deadline", "hackathon winners",
        "hackathon launches", "cash prize", "prize pool",
        "product hunt", "showcase", "directory", "submit your",
    ]):
        return "product_showcase_opportunities"

    # Section 16 — New AI tools (launch / release / introduces). Excludes AI music
    # tools (Suno/Udio/song generators) — those fall through to global_ai_news.
    if has_any(text, ["launches", "launched", "launch ", "releases", "released", "introduces", "unveils", "rolls out", " new ai ", "open-sources", "open sources"]) \
            and is_ai_related(text) and not has_any(text, MUSIC_TERMS):
        return "new_ai_tools"

    # Section 2 — AI business automation tooling
    if has_any(text, ["n8n", "zapier", "make.com", "make ", "workflow automation", "automation", "ai agent", "agentic", "rpa"]) and is_ai_related(text):
        return "ai_business_automation"

    # Section 10 — AI business opportunities
    if has_any(text, ["raised $", "raises $", "raises ", "funding", "series a", "series b", "series c", "valuation", "ipo", "acquires", "acquisition"]) and is_ai_related(text):
        return "ai_business_opportunities"

    # Section 9 — Unaddressed AI problems
    if has_any(text, ["risk", "concern", "fail", "limitation", "problem", "hallucinat", "exposed", "leak", "vulnerab", "scam", "deepfake"]) and is_ai_related(text):
        return "unaddressed_ai_problems"

    # Section 13 — Indian AI industry
    indian_src = src in {"yourstory", "economic times tech", "inc42"}
    if indian_src and is_ai_related(text):
        return "indian_ai_industry"
    if has_any(text, ["india", "indian", "bengaluru", "mumbai", "delhi", "hyderabad", "chennai", "noida"]) and is_ai_related(text):
        return "indian_ai_industry"

    # Default — Global AI news (only if AI-related)
    if is_ai_related(text):
        return "global_ai_news"

    # Non-AI but from a non-general source — drop into general news only if from a news outlet
    if src in {"bbc world", "the hindu - national", "ndtv top stories", "economic times tech"}:
        return "general_news"

    return None


def relevance_for(section: str, art: dict, idx: int) -> int:
    """Differentiated 1–5 score per the workflow rubric."""
    text = ((art.get("title", "") or "") + " " + (art.get("summary", "") or "")).lower()
    src = (art.get("source", "") or "").lower()

    # Anthropic + Claude: 5 if direct, 4 otherwise
    if section == "anthropic_claude_news":
        return 5 if "anthropic" in text or "claude " in text else 4

    # Elon vision: top item 5, rest 4
    if section == "elon_musk_ai_vision":
        return 5 if idx == 0 else 4

    # Major model launches / OpenAI / Google: 5
    if section in {"global_ai_news", "new_ai_tools"}:
        if has_any(text, ["openai launches", "openai releases", "google releases", "deepmind", "gpt-5", "gpt-4o", "gemini 3", "frontier model"]):
            return 5
        return 4 if is_ai_related(text) else 3

    # Quantum / RSI / Benchmarks: arXiv = 3 (research), industry pieces 4
    if section in {"quantum_ai_research", "ai_self_improvement_rsi"}:
        return 3 if "arxiv" in src else 4
    if section == "ai_model_benchmarks":
        return 4

    # Indian AI: top-3 are 4, then 3
    if section == "indian_ai_industry":
        return 4 if idx < 3 else 3

    # Music copyright: 3 by default, 4 if a major label / regulator
    if section == "ai_music_copyright_laws":
        if has_any(text, ["warner", "sony", "universal", "spotify", "supreme court", "eu ai act"]):
            return 4
        return 3

    # Showcase / new tools: 3
    if section in {"product_showcase_opportunities", "new_ai_tools"}:
        return 3

    # Business automation: 3 default, 4 if Anthropic/major SaaS
    if section == "ai_business_automation":
        return 4 if has_any(text, ["anthropic", "openai", "zapier", "n8n"]) else 3

    # Business opportunities: top 2 are 4, rest 3
    if section == "ai_business_opportunities":
        return 4 if idx < 2 else 3

    # Unaddressed problems: 3
    if section == "unaddressed_ai_problems":
        return 3

    # General news: top-3 are 4 (world headlines), rest 3
    if section == "general_news":
        return 4 if idx < 3 else 3

    return 3


def main() -> None:
    loaded = load_scraped_data()
    sections: dict[str, list] = {s: [] for s in SECTIONS}

    # ---- Section 0: Remote jobs (US/global remote AI automation) ----
    raw_jobs = loaded.get("jobs", [])
    cleaned = []
    for j in raw_jobs:
        if is_seeking_work(j):
            continue
        title = clean_text(j.get("title", ""))
        if not title:
            continue
        cleaned.append({
            "title": title,
            "company": clean_text(j.get("company", "")),
            "url": j.get("url", ""),
            "posted": j.get("posted", ""),
            "salary": j.get("salary", ""),
            "source": j.get("source", ""),
            "summary": job_summary(j),
            "relevance": 5,
            "_score": job_score(j),
        })
    cleaned.sort(key=lambda x: (-x["_score"], x.get("posted", "")), reverse=False)
    cleaned.sort(key=lambda x: -x["_score"])
    for j in cleaned:
        j.pop("_score", None)
    sections["remote_jobs"] = cleaned[:25]

    # ---- Merged YouTube section (passthrough; 2 long + 1 short, 7d verified) ----
    sections["viral_video_landscape"] = [
        {
            "title": clean_text(v.get("title", "")),
            "url": v.get("url", ""),
            "channel": clean_text(v.get("channel", "")),
            "views": v.get("views", 0),
            "format": v.get("format", "video"),
            "summary": summary_from(v.get("title", ""), v.get("description", "")),
            "bucket": v.get("bucket", ""),
            "video_id": v.get("video_id", ""),
            "relevance": 5,
        }
        for v in loaded.get("youtube_verified", [])
    ]

    # ---- RSS-routed sections ----
    rss = loaded.get("rss_articles", [])
    rss_sorted = sorted(rss, key=lambda a: parse_dt(a.get("published", "")), reverse=True)
    seen_urls = set()
    routed_count = 0
    for art in rss_sorted[:300]:
        url = art.get("url", "") or art.get("link", "")
        if url and url in seen_urls:
            continue
        sec = route_article(art)
        if not sec:
            continue
        if len(sections[sec]) >= (8 if sec != "general_news" else 8):
            continue
        seen_urls.add(url)
        idx = len(sections[sec])
        entry = article_entry(art, relevance_for(sec, art, idx))
        sections[sec].append(entry)
        routed_count += 1

    # Ensure each section has at least a placeholder count printout
    total = (
        len(sections["remote_jobs"])
        + len(sections["viral_video_landscape"])
        + routed_count
    )
    save_analyzed_content(sections, total)


if __name__ == "__main__":
    main()
