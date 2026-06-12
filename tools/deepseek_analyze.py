"""DeepSeek-driven analysis for the daily 18-section PDF.

Replaces the Claude Code agent's reasoning step with a deterministic API call to
DeepSeek V4 Pro (`deepseek-v4-pro`). Categorises RSS articles into the 18 sections,
writes fresh 1-2 sentence summaries that end with an `Automation angle:` hook
(for AI sections), and assigns differentiated 1-5 relevance scores. Jobs (section 0)
and YouTube videos (sections 5, 6) are passthroughs — no LLM needed for those.

Reads:   .tmp/jobs.json, .tmp/rss_articles.json, .tmp/youtube_verified.json,
         .tmp/youtube_trending.json
Writes:  .tmp/analyzed_content.json, .tmp/agent_tokens.json (DeepSeek usage)

Env: DEEPSEEK_API_KEY (required)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
if load_dotenv:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from tools.analyze_and_categorize import (  # noqa: E402
    SECTIONS, SECTION_LABELS, load_scraped_data, save_analyzed_content,
)

TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
TOKENS_FILE = os.path.join(TMP_DIR, "agent_tokens.json")

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-pro"

# Pricing (USD per 1M tokens) — deepseek-v4-pro standard tier, cache-miss
PRICE_INPUT_PER_M = 0.28
PRICE_CACHE_HIT_PER_M = 0.07
PRICE_OUTPUT_PER_M = 1.10

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# LLM-routed sections (RSS articles only). Passthrough sections are populated
# directly from their scraper output and excluded from LLM routing + padding.
PASSTHROUGH_SECTIONS = {
    "remote_jobs", "viral_video_landscape", "youtube_content_ideas",
    "ai_search_trends", "instagram_viral_reels",
}
LLM_SECTIONS = [s for s in SECTIONS if s not in PASSTHROUGH_SECTIONS]
# Sections that should NOT receive an `Automation angle:` hook.
# `remote_jobs` (jobs use a fixed format) and `general_news` (non-AI) are exempt.
NO_ANGLE_SECTIONS = {"remote_jobs", "general_news"}
SECTION_CAP = 8           # max per LLM-routed RSS section
SECTION_MIN = 3           # min per LLM-routed RSS section (pad from rejected pool if below)
JOB_CAP = 25
YT_LANDSCAPE_CAP = 10
RSS_INPUT_CAP = 300       # max articles fed to DeepSeek per run (bumped to give the padding pass headroom)
ARTICLE_BODY_CHARS = 380  # truncate body before sending to model
CHUNK_SIZE = 25           # articles per API call
LOG_FILE = os.path.join(PROJECT_ROOT, ".tmp", "deepseek_analyze.log")


def _log(msg: str) -> None:
    """Print to stdout AND append to .tmp/deepseek_analyze.log so failures survive shell pipes like `| tail`."""
    print(msg)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg.rstrip("\n") + "\n")
    except Exception:
        pass


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = unescape(s)
    s = TAG_RE.sub("", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def parse_dt(s: str):
    if not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(s)
        except Exception:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)


SYSTEM_PROMPT = (
    "You categorise AI/tech news articles into a fixed taxonomy for a daily digest. "
    "The reader's goal is landing a remote AI-automation job globally with no prior "
    "experience, and launching a YouTube channel teaching AI automation — frame "
    "every AI-section summary through that lens. "
    "For every article you place, write a fresh 1-2 sentence plain-English summary "
    "(no HTML, no quotes from the source, no Source: prefixes) that states what "
    "happened and why it matters. "
    "MANDATORY for every section EXCEPT `remote_jobs` and `general_news`: the summary "
    "MUST end with an extra sentence that begins exactly with `Automation angle:` "
    "and states one of — what to build, what tool to try, what workflow this unlocks, "
    "what risk to watch, or why this matters for AI-automation businesses. Keep the "
    "automation angle concrete and actionable, not generic. Example: "
    "`Automation angle: build an n8n workflow that auto-summarises Anthropic release notes into a daily Slack DM.` "
    "Do NOT add `Automation angle:` to `general_news` items. "
    "Assign a 1-5 relevance score using this rubric: 5=headline-grade global impact "
    "(major model launch, Anthropic/Claude release, tier-1 funding round affecting the field), "
    "4=significant practical impact, 3=solid news for a narrower audience, "
    "2=niche/incremental, 1=filler. Differentiate scores — never give every article a 5. "
    "Aim to place at least 3 articles into every LLM-routed section; if the pool is thin "
    "for a section, lower the relevance bar there rather than under-filling. "
    "Skip articles that do not fit any section (omit them from output). Reply with strict JSON only."
)

SECTIONS_BRIEF = """Section keys and what belongs in each. Every section except `general_news` is STRICTLY AI-related — drop any article that is not about AI/ML/LLMs/AI products.

- anthropic_claude_news: Anthropic company news (funding, leadership, policy, partnerships) AND Claude Code product updates (releases, MCP, hooks, slash commands, agents, model rollouts). Must mention Anthropic or Claude.
- ai_business_automation: n8n, Zapier, Make.com, RPA, agentic workflow tools, automation platforms — must be AI-related.
- quantum_ai_research: STRICTLY Quantum + AI. The article MUST address BOTH quantum computing (qubits, quantum hardware, quantum algorithms, QPUs, quantum error correction) AND AI/ML (LLMs, neural nets, ML training, RL, quantum machine learning). Pure-quantum stories (e.g., quantum hardware with no AI angle) and pure-AI stories (e.g., LLM scaling with no quantum) MUST be dropped or routed to a different section — never accept either alone here.
- product_showcase_opportunities: AI hackathons and AI competitions ONLY (worldwide) — events with a submission deadline where an AI automation product can be submitted. INCLUDE: hackathon announcements (e.g., "GitLab AI Hackathon on Devpost", "Anthropic AI Agents Hackathon", AWS/Google Cloud AI challenges), open submission windows, prize pools, and winners recaps (winners posts hint at the next iteration). Devpost / MLH / Devfolio / HackerEarth events qualify. Drop Product Hunt launches, static AI directories, ongoing platforms, and non-AI hackathons. NOTE: Native-scraped hackathons from .tmp/hackathons.json (Devpost/Kaggle/HuggingFace/MLH/lablab.ai/AIcrowd/DrivenData) are merged into this section after analysis — your output here is supplementary catch-all for off-platform sponsor hackathons.
- ai_music_copyright_laws: AI music/art copyright lawsuits, regulation, licensing battles, court rulings.
- elon_musk_ai_vision: Elon Musk, xAI, Grok, Musk's AI commentary or moves.
- unaddressed_ai_problems: AI risks, hallucinations, data leaks, scams, deepfakes, safety failures.
- ai_business_opportunities: AI funding, raises, IPOs, acquisitions, valuations.
- global_ai_news: Worldwide AI news ONLY — must be AI-related, no general tech / non-AI business news.
- indian_ai_industry: India-based AI news ONLY — Indian AI startups, India-specific AI policy, Indian-market AI products. Must be AI-related.
- ai_self_improvement_rsi: AGI, alignment, recursive self-improvement, superintelligence research.
- ai_model_benchmarks: Leaderboards and benchmark news across categories — Text/LLM, Image, Video, Music, Audio, Coding. IMPORTANT: as the FIRST item in this section, emit one synthesized leaderboard entry with title "Top Model Per Category (last 7 days)" and a summary that lists the top model per category derived from the batch you saw, formatted like "Text/LLM: <model>. Image: <model>. Video: <model>. Music: <model>. Audio: <model>. Coding: <model>." Use "n/a" for any category with no signal in the batch. Then route normal benchmark articles to this section as usual. The leaderboard entry also gets an `Automation angle:` sentence (e.g., which model to use for which portfolio demo).
- new_ai_tools: Net-new AI tool launches/releases (model APIs, dev tools, consumer apps).
- general_news: Non-AI world headlines (BBC/Hindu/NDTV-style top news). This is the ONLY non-AI section.
"""


def trim_body(s: str, n: int = ARTICLE_BODY_CHARS) -> str:
    s = clean_text(s)
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0] + "…"
    return s


def build_articles_payload(articles: list[dict]) -> list[dict]:
    out = []
    for i, a in enumerate(articles):
        out.append({
            "i": i,
            "title": clean_text(a.get("title", ""))[:240],
            "source": clean_text(a.get("source", ""))[:80],
            "body": trim_body(a.get("summary", "") or a.get("description", "")),
        })
    return out


def call_deepseek(api_key: str, articles_payload: list[dict]) -> tuple[list[dict], dict]:
    """Send one chunk to DeepSeek, return (items, usage)."""
    user_msg = (
        SECTIONS_BRIEF
        + "\nArticles to categorise (JSON list). Use the integer `i` as the article id.\n"
        + json.dumps(articles_payload, ensure_ascii=False)
        + "\n\nReturn JSON: {\"items\": [{\"i\": <int>, \"section\": \"<key>\", "
          "\"summary\": \"<1-2 sentences>\", \"relevance\": <1-5>}]}. "
          "Omit any article that does not fit a section."
    )
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 16000,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(DEEPSEEK_URL, headers=headers, json=body, timeout=180)
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            finish_reason = choice.get("finish_reason", "")
            content = (choice.get("message") or {}).get("content", "")
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # try to recover braces
                m = re.search(r"\{.*\}", content, re.S)
                parsed = json.loads(m.group(0)) if m else {"items": []}
            items = parsed.get("items", []) if isinstance(parsed, dict) else []
            usage = data.get("usage", {})
            if finish_reason == "length":
                _log(f"    [warn] finish_reason=length — output hit max_tokens; placements may be truncated")
            return items, usage
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek call failed after retries: {last_err}")


def chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ------- Job summary + score (no LLM) -------
def is_seeking_work(j: dict) -> bool:
    t = (j.get("title", "") + " " + (j.get("summary") or "")).upper()
    return "SEEKING WORK" in t or ("FREELANCER" in t and "SEEKING" in t)


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


# ------- YouTube AI landscape (no LLM) -------
AI_TERMS_QUICK = [
    "ai", "llm", "gpt", "chatgpt", "openai", "anthropic", "claude", "gemini",
    "deepmind", "mistral", "perplexity", "stable diffusion", "midjourney",
    "runway", "elevenlabs", "suno", "udio", "machine learning", "neural",
    "agentic", "agent", "rag", "transformer", "robotics", "grok", "xai",
]


def is_ai_text(text: str) -> bool:
    t = " " + text.lower() + " "
    if " ai " in t:
        return True
    return any(kw in t for kw in AI_TERMS_QUICK[1:])


def write_token_telemetry(usages: list[dict], elapsed_s: float, ok: bool, note: str = "") -> None:
    total_in = sum(u.get("prompt_tokens", 0) for u in usages)
    total_out = sum(u.get("completion_tokens", 0) for u in usages)
    cache_hit = sum(u.get("prompt_cache_hit_tokens", 0) for u in usages)
    cache_miss = total_in - cache_hit
    cost = (
        cache_miss * PRICE_INPUT_PER_M / 1_000_000
        + cache_hit * PRICE_CACHE_HIT_PER_M / 1_000_000
        + total_out * PRICE_OUTPUT_PER_M / 1_000_000
    )
    payload = {
        "available": ok,
        "provider": "deepseek",
        "model": DEEPSEEK_MODEL,
        "calls": len(usages),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cache_read_tokens": cache_hit,
        "cache_creation_tokens": 0,
        "total_tokens": total_in + total_out,
        "estimated_cost_usd": round(cost, 4),
        "elapsed_s": round(elapsed_s, 2),
        "note": note,
    }
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY not set", file=sys.stderr)
        return 2

    t0 = time.time()
    loaded = load_scraped_data()
    sections: dict[str, list] = {s: [] for s in SECTIONS}

    # ---- Section 0: Remote jobs (passthrough) ----
    # Prefer profile-ranked jobs from tools/job_match.py (carries matched_skills
    # + profile score). Fall back to raw jobs.json with the legacy keyword score
    # if the ranker step didn't run.
    ranked_jobs = loaded.get("jobs_ranked") or []
    cleaned_jobs = []
    if ranked_jobs:
        for j in ranked_jobs:
            if is_seeking_work(j):
                continue
            title = clean_text(j.get("title", ""))
            if not title:
                continue
            cleaned_jobs.append({
                "title": title,
                "company": clean_text(j.get("company", "")),
                "url": j.get("url", ""),
                "posted": j.get("posted", ""),
                "salary": j.get("salary", ""),
                "source": j.get("source", ""),
                "summary": job_summary(j),
                "matched_skills": j.get("matched_skills") or [],
                "strong_match": bool(j.get("strong_match")),
                "title_role_hit": j.get("title_role_hit"),
                "relevance": 5,
            })
        # job_match already ranked them; keep that order.
    else:
        scored = []
        for j in loaded.get("jobs", []):
            if is_seeking_work(j):
                continue
            title = clean_text(j.get("title", ""))
            if not title:
                continue
            scored.append({
                "title": title,
                "company": clean_text(j.get("company", "")),
                "url": j.get("url", ""),
                "posted": j.get("posted", ""),
                "salary": j.get("salary", ""),
                "source": j.get("source", ""),
                "summary": job_summary(j),
                "matched_skills": [],
                "strong_match": False,
                "title_role_hit": None,
                "relevance": 5,
                "_score": job_score(j),
            })
        scored.sort(key=lambda x: -x["_score"])
        for j in scored:
            j.pop("_score", None)
        cleaned_jobs = scored
    sections["remote_jobs"] = cleaned_jobs[:JOB_CAP]

    # ---- Section 1: AI search trends (passthrough) ----
    sections["ai_search_trends"] = [
        {
            "title": (t.get("topic") or "")[:140],
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
        }
        for t in loaded.get("ai_trends", []) or []
    ]

    # ---- Section 2: Viral Instagram reels (passthrough) ----
    sections["instagram_viral_reels"] = []
    for r in loaded.get("instagram_verified", []) or []:
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
                "Automation angle: study the first-2s hook and caption format - "
                "this is the structure to replicate for your AI-automation channel."
            ),
            "relevance": 5,
        })

    # ---- Merged YouTube section (passthrough; no automation angle) ----
    sections["viral_video_landscape"] = [
        {
            "title": clean_text(v.get("title", "")),
            "url": v.get("url", ""),
            "channel": clean_text(v.get("channel", "")),
            "views": v.get("views", 0),
            "format": v.get("format", "video"),
            "summary": clean_text(v.get("title", "")).rstrip(".") + ".",
            "bucket": v.get("bucket", ""),
            "video_id": v.get("video_id", ""),
            "relevance": 5,
        }
        for v in loaded.get("youtube_verified", [])
    ]

    # ---- DeepSeek-routed RSS sections ----
    rss = loaded.get("rss_articles", [])
    rss_sorted = sorted(rss, key=lambda a: parse_dt(a.get("published", "")), reverse=True)
    rss_limited = rss_sorted[:RSS_INPUT_CAP]

    payload = build_articles_payload(rss_limited)
    # Reset log per-run so it reflects only the latest invocation.
    try:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
    except Exception:
        pass
    _log(f"DeepSeek: routing {len(payload)} RSS articles in chunks of {CHUNK_SIZE}…")

    all_items: list[dict] = []
    usages: list[dict] = []
    api_ok = True
    api_note = ""
    for ci, batch in enumerate(chunk(payload, CHUNK_SIZE), start=1):
        # Renumber `i` to be local 0..len(batch)-1 for this call. The model sees
        # only batch-relative indices; we map back to absolute via `base + idx`.
        base = (ci - 1) * CHUNK_SIZE
        local_batch = [{**item, "i": j} for j, item in enumerate(batch)]
        try:
            items, usage = call_deepseek(api_key, local_batch)
            _log(f"  chunk {ci}: returned {len(items)} placements, in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}")
            for it in items:
                if not isinstance(it, dict):
                    continue
                idx = it.get("i")
                if not isinstance(idx, int):
                    continue
                if idx < 0 or idx >= len(batch):
                    continue
                it["__article_idx"] = base + idx
                all_items.append(it)
            usages.append(usage)
        except Exception as e:
            api_ok = False
            api_note = f"chunk {ci} failed: {e}"
            _log(f"  chunk {ci}: FAIL — {e}")
            break

    if not api_ok:
        write_token_telemetry(usages, time.time() - t0, ok=False, note=api_note)
        _log("DeepSeek analysis aborted; pipeline will fall back to agent_analyze.")
        return 3

    # Materialise items into sections
    seen_urls: set[str] = set()
    # Sort items by relevance desc so caps keep the best
    all_items.sort(key=lambda x: -(x.get("relevance") or 0))
    for it in all_items:
        sec = (it.get("section") or "").strip()
        if sec not in LLM_SECTIONS:
            continue
        if len(sections[sec]) >= SECTION_CAP:
            continue
        art = rss_limited[it["__article_idx"]]
        url = art.get("url", "") or art.get("link", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        rel = it.get("relevance")
        try:
            rel = max(1, min(5, int(rel)))
        except Exception:
            rel = 3
        summary = clean_text(it.get("summary", "")) or (clean_text(art.get("title", "")).rstrip(".") + ".")
        sections[sec].append({
            "title": clean_text(art.get("title", "")),
            "url": url,
            "source": art.get("source", ""),
            "summary": summary,
            "published": art.get("published", "") or art.get("pubDate", ""),
            "relevance": rel,
        })

    # ---- Padding pass: ensure every LLM-routed section has >= SECTION_MIN items ----
    under_filled = {s: (SECTION_MIN - len(sections[s])) for s in LLM_SECTIONS if len(sections[s]) < SECTION_MIN}
    if under_filled:
        unrouted = [a for a in rss_limited if (a.get("url") or a.get("link")) not in seen_urls]
        # cap the pool we send to keep the call cheap
        unrouted = unrouted[:120]
        if unrouted:
            print(f"DeepSeek: padding pass for {len(under_filled)} under-filled sections "
                  f"({sum(under_filled.values())} slots) from {len(unrouted)} unrouted articles…")
            pad_payload = build_articles_payload(unrouted)
            needs_lines = "\n".join(f"- {k}: needs {n} more" for k, n in under_filled.items())
            user_msg = (
                "PADDING PASS. The sections below are under the minimum of 3 articles. "
                "From the article pool, place additional articles into these sections only. "
                "Lower the relevance bar (1-2 is acceptable). Every summary must still end with "
                "an `Automation angle:` sentence (except for general_news). Place at most the "
                "stated number per section.\n\n"
                f"Sections to fill:\n{needs_lines}\n\n"
                "Article pool (use the integer `i` as article id):\n"
                + json.dumps(pad_payload, ensure_ascii=False)
                + "\n\nReturn JSON: {\"items\": [{\"i\": <int>, \"section\": \"<key>\", "
                  "\"summary\": \"<1-2 sentences + Automation angle hook>\", \"relevance\": <1-5>}]}. "
                  "Omit any article that does not improve a needed section."
            )
            body = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 4000,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            try:
                r = requests.post(DEEPSEEK_URL, headers=headers, json=body, timeout=180)
                r.raise_for_status()
                rdata = r.json()
                content = rdata["choices"][0]["message"]["content"]
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    m = re.search(r"\{.*\}", content, re.S)
                    parsed = json.loads(m.group(0)) if m else {"items": []}
                pad_items = parsed.get("items", []) if isinstance(parsed, dict) else []
                usages.append(rdata.get("usage", {}))
                # Sort padding items by relevance desc; respect under_filled budget per section
                pad_items.sort(key=lambda x: -(x.get("relevance") or 0))
                remaining = dict(under_filled)
                for it in pad_items:
                    sec = (it.get("section") or "").strip()
                    if sec not in remaining or remaining[sec] <= 0:
                        continue
                    if len(sections[sec]) >= SECTION_CAP:
                        continue
                    idx = it.get("i")
                    if not isinstance(idx, int) or idx < 0 or idx >= len(unrouted):
                        continue
                    art = unrouted[idx]
                    url = art.get("url", "") or art.get("link", "")
                    if url and url in seen_urls:
                        continue
                    seen_urls.add(url)
                    try:
                        rel = max(1, min(5, int(it.get("relevance") or 2)))
                    except Exception:
                        rel = 2
                    summary = clean_text(it.get("summary", "")) or (clean_text(art.get("title", "")).rstrip(".") + ".")
                    sections[sec].append({
                        "title": clean_text(art.get("title", "")),
                        "url": url,
                        "source": art.get("source", ""),
                        "summary": summary,
                        "published": art.get("published", "") or art.get("pubDate", ""),
                        "relevance": rel,
                    })
                    remaining[sec] -= 1
                still_short = {k: v for k, v in remaining.items() if v > 0}
                if still_short:
                    print(f"  padding pass: still under-filled after API call: {still_short}")
                else:
                    print("  padding pass: all sections meet minimum of 3.")
            except Exception as e:
                print(f"  padding pass FAIL (continuing): {e}", file=sys.stderr)

    total = (
        sum(len(sections[s]) for s in PASSTHROUGH_SECTIONS)
        + sum(len(sections[s]) for s in LLM_SECTIONS)
    )
    save_analyzed_content(sections, total)
    write_token_telemetry(usages, time.time() - t0, ok=True, note=f"routed {len(all_items)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
