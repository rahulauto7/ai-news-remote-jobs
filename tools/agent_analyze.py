"""Agent-driven self-analysis: Claude Code agent reads scraped data and writes analyzed_content.json.
No external API needed — the agent reasons directly over the articles.

Reads:  .tmp/jobs.json, .tmp/rss_articles.json, .tmp/youtube_verified.json, .tmp/youtube_trending.json
Writes: .tmp/analyzed_content.json, .tmp/agent_tokens.json
"""
from __future__ import annotations
import json, os, re, sys, time
from datetime import datetime, timezone
from html import unescape

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

from tools.analyze_and_categorize import (
    SECTIONS, SECTION_LABELS, load_scraped_data, save_analyzed_content,
)

TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
TOKENS_FILE = os.path.join(TMP_DIR, "agent_tokens.json")

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

SECTION_CAP = 8
SECTION_MIN = 3
JOB_CAP = 25

PASSTHROUGH_SECTIONS = {
    "remote_jobs", "viral_video_landscape", "youtube_content_ideas",
    "ai_search_trends", "instagram_viral_reels",
}
LLM_SECTIONS = [s for s in SECTIONS if s not in PASSTHROUGH_SECTIONS]
# Sections that should NOT receive an `Automation angle:` hook.
# Merged YouTube section now carries an agent-written "why viral" line instead.
NO_ANGLE_SECTIONS = {"remote_jobs", "general_news", "viral_video_landscape", "youtube_content_ideas"}

AI_TERMS = [
    "ai", "llm", "gpt", "chatgpt", "openai", "anthropic", "claude", "gemini",
    "deepmind", "mistral", "perplexity", "stable diffusion", "midjourney",
    "runway", "elevenlabs", "suno", "udio", "machine learning", "neural",
    "agentic", "agent", "rag", "transformer", "robotics", "grok", "xai",
    "deepseek", "qwen", "alibaba ai", "copilot", "meta ai",
    # Safe multi-word ML terms — common in arXiv quantum/RSI papers that the
    # bare "neural"/"machine learning" checks would otherwise miss.
    "deep learning", "reinforcement learning", "language model",
    "diffusion model", "foundation model", "computer vision",
]

# Keyword groups for the Quantum + AI strict gate.
QUANTUM_TERMS = ["quantum", "qubit", "qpu", "quantum computing", "quantum hardware",
                 "quantum algorithm", "quantum error correction", "quantum supremacy"]
AI_ML_TERMS = [" ai ", "machine learning", "neural", "llm", "deep learning",
               "reinforcement learning", "rl ", "transformer", "language model"]

# Music-tool terms — keep AI *music* launches out of New AI Tools (the user wants
# that section to be build-stack / agent tooling, not Suno/Udio/song generators).
MUSIC_TERMS = ["suno", "udio", "ai music", "ai song", "music generat",
               "song generat", "lyrics", "text-to-music", "music model",
               "beat maker", "ai composer", "ai-generated music", "music ai",
               "songwriting ai", "ai vocal"]

# Benchmark gate — bare "benchmark" is too loose ("sets a new benchmark for…").
# Strong eval tokens pass outright; the bare word requires an AI + eval co-signal.
STRONG_BENCH_TOKENS = ["mmlu", "humaneval", "gpqa", "swe-bench", "lmsys",
                       "arena", "eval suite", "leaderboard", "model ranking",
                       "mt-bench", "livebench", "aider polyglot", "mmmu",
                       "gsm8k", "math benchmark", "benchmark score"]
BENCH_CONTEXT = ["model", "llm", "score", "outperform", "eval", "rank",
                 "accuracy", "state-of-the-art", "sota", "beats", "tokens/s",
                 "parameters", "context window", "reasoning"]

# Deterministic Automation angle templates per section. Used by the offline
# fallback so the PDF still ships with an actionable hook on every story.
AUTOMATION_ANGLES = {
    "anthropic_claude_news": "Build a portfolio demo on top of this Anthropic/Claude change the same week — interview proof you ride the edge of the tool.",
    "ai_business_automation": "Rebuild this workflow in n8n + Claude Code and ship the repo to your portfolio — direct evidence for AI-automation roles.",
    "quantum_ai_research": "One-line take in cover letters and tweets — signals depth beyond surface-level AI hype.",
    "product_showcase_opportunities": "Submit something to this AI hackathon/competition — every accepted entry is a public link to paste into the next job application.",
    "ai_music_copyright_laws": "Skim only; deep-read if a ruling hits a tool (Suno/Udio) you might build a workflow on.",
    "elon_musk_ai_vision": "Competitive context for interviews — name-drop xAI / Grok benchmark deltas without optimising your portfolio for them.",
    "unaddressed_ai_problems": "Pick one unsolved problem and build a 1-week Claude Code demo — post as 'I solved X with AI automation'.",
    "ai_business_opportunities": "Recently funded = hiring in 60-90 days; bookmark their careers page and apply next week.",
    "global_ai_news": "Macro signal — deep-read only if regulation affects a tool/model you use; otherwise interview small-talk fuel.",
    "indian_ai_industry": "Indian AI talent = your referral network — track exec moves at India-HQ AI startups for warm-intro paths.",
    "ai_self_improvement_rsi": "Vocabulary for senior-sounding interviews (alignment, RSI, scaling laws) even with no years on resume.",
    "ai_model_benchmarks": "Switch your portfolio demos to whichever model ranks best on coding/agent benchmarks this week.",
    "new_ai_tools": "Two uses today — integrate the best one into a portfolio demo, and shoot a 60-second 'Tool Tested' YouTube short.",
    "instagram_viral_reels": "Study the first-2s hook + caption format — replicate the structure for your AI-automation Instagram reels.",
}


def has_any(text_lower: str, terms: list[str]) -> bool:
    return any(t in text_lower for t in terms)


def kw_match(text_lower: str, keywords: list[str]) -> bool:
    """Keyword containment for classification rules.

    Short alphabetic tokens (<=4 chars, e.g. "agi", "rsi", "xai", "ipo") are
    matched on word boundaries so they don't fire inside unrelated words
    (e.g. "agi" in im-AGI-nary / m-AGI-c / man-AGI-ng, "rsi" in dive-RSI-ons /
    unive-RSI-ty / ove-RSI-ght). Longer tokens and multi-word phrases keep cheap
    substring matching.
    """
    for k in keywords:
        if len(k) <= 4 and k.isalpha():
            if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text_lower):
                return True
        elif k in text_lower:
            return True
    return False


def append_angle(section: str, summary: str) -> str:
    """Append `Automation angle: ...` to summary unless section is exempt."""
    if section in NO_ANGLE_SECTIONS:
        return summary
    angle = AUTOMATION_ANGLES.get(section)
    if not angle:
        return summary
    if "automation angle" in summary.lower():
        return summary
    sep = "" if summary.endswith(".") or summary.endswith("!") or summary.endswith("?") else "."
    return f"{summary}{sep} Automation angle: {angle}"[:600]


def clean(s: str) -> str:
    if not s:
        return ""
    s = unescape(s)
    s = TAG_RE.sub("", s)
    return WS_RE.sub(" ", s).strip()


# Aircraft / flight codes like "AI-171" (Air India) or "AI-320" read as a bare
# "ai" word token but are not the field AI — they leaked plane-crash headlines
# into the AI sections. Neutralized before the AI-signal test. Only "ai-<digit>"
# is touched: "gpt-4" is a different token, and "ai-powered"/"ai-first" keep
# matching (a letter, not a digit, follows the hyphen).
_FLIGHT_CODE_RE = re.compile(r"(?<![a-z0-9])ai-\d")


def is_ai(text: str) -> bool:
    """True if `text` carries an AI/ML signal from AI_TERMS.

    Delegates to kw_match so short alphabetic tokens (<=4 chars: ai, llm, gpt,
    rag, xai, grok, qwen, suno, udio) match on word boundaries — "rag" no longer
    fires inside "t-rag-edy"/"sto-rag-e", "ai" no longer inside "air"/"hair".
    Longer tokens and multi-word phrases keep cheap substring matching.
    """
    return kw_match(_FLIGHT_CODE_RE.sub(" flight ", text.lower()), AI_TERMS)


# ---------- Job passthrough ----------
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


def job_summary(j: dict) -> str:
    title = clean(j.get("title", ""))
    company = clean(j.get("company", ""))
    body = clean(j.get("summary", "") or j.get("description", ""))[:240]
    head = (f"{company} is hiring: {title}." if company else title.rstrip(".") + ".")
    return (head + " " + body)[:320] if body and body.lower() not in head.lower() else head[:320]


def process_jobs(jobs: list, ranked: list | None = None) -> list:
    """Build the remote_jobs section. If `ranked` (from tools/job_match.py) is
    given, use that order + matched_skills; otherwise score with the legacy
    keyword heuristic."""
    use_ranked = bool(ranked)
    source = ranked if use_ranked else jobs
    out = []
    for j in source:
        t = clean(j.get("title", ""))
        if not t:
            continue
        text = (t + " " + (j.get("summary") or "")).upper()
        if "SEEKING WORK" in text or ("FREELANCER" in text and "SEEKING" in text):
            continue
        rec = {
            "title": t,
            "company": clean(j.get("company", "")),
            "url": j.get("url", ""),
            "posted": j.get("posted", ""),
            "salary": j.get("salary", ""),
            "source": j.get("source", ""),
            "summary": job_summary(j),
            "matched_skills": j.get("matched_skills") or [],
            "strong_match": bool(j.get("strong_match")),
            "title_role_hit": j.get("title_role_hit"),
            "relevance": 5,
        }
        if not use_ranked:
            rec["_score"] = job_score(j)
        out.append(rec)
    if not use_ranked:
        out.sort(key=lambda x: -x["_score"])
        for j in out:
            j.pop("_score", None)
    return out[:JOB_CAP]


def process_ai_trends(topics: list) -> list:
    """Passthrough for the AI search-trends section."""
    out = []
    for t in topics or []:
        out.append({
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
        })
    return out


def process_instagram_reels(reels: list) -> list:
    """Passthrough for the viral Instagram reels section."""
    out = []
    for r in reels or []:
        like = int(r.get("like_count") or 0)
        comment = int(r.get("comment_count") or 0)
        out.append({
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
            "summary": append_angle(
                "instagram_viral_reels",
                f"@{r.get('username','')} - {like:,} likes / {comment:,} comments in 24h. #{r.get('hashtag','')}.",
            ),
            "relevance": 5,
        })
    return out


# ---------- Agent classification rules (ordered by specificity) ----------
# Returns (section_key, relevance, summary_override_or_None)
RULES: list[tuple[list[str], str, int]] = [
    # Anthropic / Claude
    (["anthropic", "claude code", "claude 3", "claude 4", "claude opus", "claude sonnet",
      "claude haiku", "mcp server", "model context protocol"], "anthropic_claude_news", 5),
    # xAI / Elon
    (["elon musk", "xai", "grok", "tesla ai", "spacex ai", "neuralink"], "elon_musk_ai_vision", 4),
    # AI music / art copyright (rulings, licensing)
    (["copyright lawsuit", "ai infringement", "music licens", "art licens",
      "deepfake law", "personality rights", "ai regulation bill", "ai copyright law",
      "ai music copyright", "ai art copyright"], "ai_music_copyright_laws", 4),
    # Deepfakes / unaddressed problems
    (["deepfake", "ai fake", "fake ai", "ai scam", "ai hallucin", "ai bias",
      "ai risk", "ai safety failure", "ai misuse", "synthetic media",
      "ai avatar boost", "fake avatar"], "unaddressed_ai_problems", 4),
    # quantum_ai_research is omitted from RULES — Stage 2 cloud agent owns it via
    # semantic evaluation (no keyword matching). See workflows/daily_ai_news_remote.md
    # step 6.7 for the per-article reading + judgment procedure.
    # Product showcase / hackathons & competitions
    # NOTE: Native-scraped hackathons (.tmp/hackathons.json) are merged into
    # product_showcase_opportunities after this stage. These keyword matches
    # are supplementary catch-all for off-platform sponsor hackathons that the
    # native scrapers (Devpost/Kaggle/HF/MLH/lablab.ai/AIcrowd/DrivenData) miss.
    (["ai hackathon", "ai agents hackathon", "ai agent hackathon",
      "agent platform hackathon", "ai competition", "ai challenge",
      "devpost", "submission deadline", "hackathon winners",
      "hackathon launches", "cash prize", "prize pool",
      "product hunt", "ai directory", "ai showcase", "hackathon", "competition launch",
      "agentpeek", "mac notch", "codex mac"], "product_showcase_opportunities", 3),
    # AI benchmarks
    (["benchmark", "leaderboard", "mmlu", "humaneval", "gpqa", "swe-bench",
      "arena ranking", "eval suite", "model ranking"], "ai_model_benchmarks", 4),
    # ai_self_improvement_rsi is omitted from RULES — Stage 2 cloud agent owns it
    # via semantic evaluation (no keyword matching). See workflows/daily_ai_news_remote.md
    # step 6.7 for the per-article reading + judgment procedure.
    # AI automation & businesses (tools / workflows)
    (["n8n", "zapier", "make.com", "rpa", "workflow automation", "agentic workflow",
      "automation platform", "no-code ai", "low-code ai"], "ai_business_automation", 4),
    # India-specific AI. Gated by is_ai() in classify() so non-AI Indian business
    # news (Swiggy/Infosys/VC-inflow headlines) no longer leaks into this section.
    (["india ai", "indian ai", "indiaai", "iit ai", "bengaluru ai", "mumbai ai",
      "ai mission india", "paperwork ai", "ip concern india",
      "tharoor deepfake", "india startup ai", "india funding ai",
      "ltts ai", "swiggy ai", "magicpin ai", "yourstory ai"], "indian_ai_industry", 3),
    # AI business opportunities / funding
    (["series a", "series b", "funding round", "ipo", "raised $", "raised million",
      "raised billion", "acquisition", "valuation", "startup funding",
      "sk hynix", "chip supply deal", "cloud deal", "akamai deal",
      "colossus compute", "data center deal"], "ai_business_opportunities", 4),
    # New AI tools — incl. the user's build stack (Claude Code / agent tooling)
    # so portfolio-relevant tools surface here, not just generic launches.
    (["launches", "releases", "new model", "api available", "introduces", "unveils",
      "qwen ai", "agentic shopping", "alibaba ai", "logitech ai",
      "agentpeek", "grok imagine",
      "voiceflow", "relevance ai", "langchain", "llamaindex", "llama index",
      "cursor", "windsurf", "ai agent builder", "agent framework", "agent sdk",
      "mcp server", "no-code agent", "copilot"], "new_ai_tools", 3),
    # General global AI (catch-all for AI news)
    (["artificial intelligence", " ai ", "machine learning", "large language model",
      "llm", "generative ai", "neural network", "openai", "google ai",
      "microsoft ai", "amazon ai", "meta ai", "intel ai"], "global_ai_news", 3),
]

GENERAL_NEWS_SOURCES = {"BBC World", "NDTV Top Stories", "The Hindu - National"}

# The user's automation build stack — tools whose news is most portfolio-relevant.
# Used to boost relevance within the New AI Tools section. (Claude Code itself
# routes to the Anthropic section, which is intended.)
STACK_TOOLS = (
    "n8n", "voiceflow", "relevance ai", "langchain", "llamaindex", "llama index",
    "cursor", "windsurf", "claude code", "mcp server", "model context protocol",
    "ai agent builder", "agent framework", "agent sdk", "no-code agent", "copilot",
)


def classify(article: dict) -> tuple[str, int, str]:
    """Returns (section, relevance, summary). Summary already includes the
    Automation angle hook for non-exempt sections."""
    title = clean(article.get("title", ""))
    source = article.get("source", "")
    raw_summary = clean(article.get("summary", "") or article.get("description", ""))
    text = (title + " " + raw_summary).lower()

    def _finalise(section: str, rel: int, summary: str) -> tuple[str, int, str]:
        s = summary[:300]
        s = append_angle(section, s)
        return section, rel, s

    # Source-based shortcuts
    if source == "Elon Musk on X (via Google News)":
        summary = title.rstrip(".") + ". " + raw_summary[:200] if raw_summary else title.rstrip(".") + "."
        return _finalise("elon_musk_ai_vision", 3, summary)
    if source == "Product Hunt AI":
        summary = clean(title).rstrip(".") + ". New AI tool launched on Product Hunt."
        return _finalise("product_showcase_opportunities", 4, summary)
    if source in GENERAL_NEWS_SOURCES:
        # Route to indian_ai_industry ONLY if India-specific AND genuinely AI.
        # (A bare tech/startup/digital signal isn't enough — that's what leaked
        # non-AI India headlines into the AI section.)
        if ("india" in text or "indian" in text or "bengaluru" in text or
                "hyderabad" in text or "chennai" in text or "mumbai" in text or
                "telangana" in text or "kerala" in text or "karnataka" in text):
            if is_ai(text):
                summary = title.rstrip(".") + ". " + raw_summary[:200] if raw_summary else title.rstrip(".") + "."
                return _finalise("indian_ai_industry", 2, summary)
        summary = title.rstrip(".") + ". " + raw_summary[:200] if raw_summary else title.rstrip(".") + "."
        return _finalise("general_news", 2, summary)

    # Rule-based classification
    for keywords, section, base_rel in RULES:
        if kw_match(text, keywords):
            # India section is AI-ONLY: drop non-AI Indian business/tech headlines.
            if section == "indian_ai_industry":
                if not is_ai(text):
                    continue
            # New AI Tools excludes AI *music* tools (Suno/Udio/song generators) —
            # those fall through to global_ai_news instead of polluting Tools.
            if section == "new_ai_tools":
                if has_any(text, MUSIC_TERMS):
                    continue
            # Benchmarks: a strong eval token passes; a bare "benchmark" needs an
            # AI + eval co-signal so casual "new benchmark for X" headlines drop out.
            if section == "ai_model_benchmarks":
                if not (has_any(text, STRONG_BENCH_TOKENS)
                        or (is_ai(text) and has_any(text, BENCH_CONTEXT))):
                    continue
            summary = title.rstrip(".") + ". " + raw_summary[:200] if raw_summary else title.rstrip(".") + "."
            # Boost relevance for tier-1 news
            rel = base_rel
            if any(k in text for k in ["$1.8 billion", "1.8b", "billion deal", "colossus",
                                         "akamai", "major launch", "headline"]):
                rel = 5
            # New AI Tools: float the user's build-stack tools to the top so the
            # section answers "which tools relate to my Claude Code work".
            if section == "new_ai_tools" and any(k in text for k in STACK_TOOLS):
                rel = 5
            return _finalise(section, rel, summary)

    # Final fallback
    summary = title.rstrip(".") + ". " + raw_summary[:200] if raw_summary else title.rstrip(".") + "."
    return _finalise("global_ai_news", 2, summary)


def main() -> int:
    t0 = time.time()
    loaded = load_scraped_data()
    sections: dict[str, list] = {s: [] for s in SECTIONS}

    # Section 0: Jobs (prefer profile-ranked output from tools/job_match.py)
    sections["remote_jobs"] = process_jobs(
        loaded.get("jobs", []), ranked=loaded.get("jobs_ranked") or None
    )

    # Section 1: AI search trends (passthrough)
    sections["ai_search_trends"] = process_ai_trends(loaded.get("ai_trends", []))

    # Section 2: Viral Instagram reels (passthrough)
    sections["instagram_viral_reels"] = process_instagram_reels(loaded.get("instagram_verified", []))

    # Merged YouTube section: verified viral (2 long + 1 short, last 7d, no angle)
    sections["viral_video_landscape"] = [
        {
            "title": clean(v.get("title", "")),
            "url": v.get("url", ""),
            "channel": clean(v.get("channel", "")),
            "views": v.get("views", 0),
            "format": v.get("format", "video"),
            "summary": clean(v.get("title", "")).rstrip(".") + ".",
            "bucket": v.get("bucket", ""),
            "video_id": v.get("video_id", ""),
            "relevance": 5,
        }
        for v in loaded.get("youtube_verified", [])
    ]

    # RSS articles → classify
    seen_urls: set[str] = set()
    rss = sorted(
        loaded.get("rss_articles", []),
        key=lambda a: a.get("published", "") or "",
        reverse=True,
    )

    staged: dict[str, list] = {s: [] for s in LLM_SECTIONS}
    for art in rss:
        url = art.get("url", "") or art.get("link", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        sec, rel, summary = classify(art)
        if sec not in LLM_SECTIONS:
            continue
        staged[sec].append({
            "title": clean(art.get("title", "")),
            "url": url,
            "source": art.get("source", ""),
            "summary": summary,
            "published": art.get("published", "") or art.get("pubDate", ""),
            "relevance": rel,
        })

    # Sort each section by relevance desc, cap at SECTION_CAP
    for sec in LLM_SECTIONS:
        staged[sec].sort(key=lambda x: -x.get("relevance", 0))
        sections[sec] = staged[sec][:SECTION_CAP]

    total = sum(len(sections[s]) for s in SECTIONS)
    save_analyzed_content(sections, total)

    elapsed = time.time() - t0
    payload = {
        "available": True,
        "provider": "agent_self",
        "model": "claude-agent-direct",
        "calls": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "elapsed_s": round(elapsed, 2),
        "note": f"Agent self-analysis: {total} items classified in {elapsed:.1f}s",
    }
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\nAgent self-analysis complete in {elapsed:.1f}s — {total} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
