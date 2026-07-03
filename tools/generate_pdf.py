"""
Generate the daily AI news PDF as a "StayingAhead"-style magazine.

Reads .tmp/analyzed_content.json (+ .tmp/youtube_content_ideas.json)
   -> Outputs .tmp/ai_news_remote_jobs_YYYY-MM-DD.pdf

Design: dark full-bleed cover + closing, oversized bold headlines with a lime
highlight behind a key word, "Quick Take" cards, lime-tick bullet lists, and
dark callout cards. Pure fpdf2 (no system deps) so the daily cloud run never
breaks on a missing renderer. Bundled fonts live in assets/fonts/; if they fail
to load the renderer degrades to Helvetica instead of crashing.

All 19 sections in SECTION_ORDER are rendered. Special renderers (jobs,
benchmarks, youtube ideas, viral video, instagram reels) keep their existing
data contracts; everything else uses the generic story card.
"""

import html
import json
import os
import re
import sys
from datetime import datetime

from fpdf import FPDF

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
TODAY = datetime.now().strftime("%Y-%m-%d")
DISPLAY_DATE = datetime.now().strftime("%a, %d %B %Y")
OUTPUT_FILE = os.path.join(TMP_DIR, f"ai_news_remote_jobs_{TODAY}.pdf")

# ── Section Config ────────────────────────────────────────────────────────────
SECTION_CONFIG = {
    "remote_jobs": {
        "label": "Remote AI Jobs",
        "desc": "Worldwide-remote AI roles ranked against workflows/user_profile.md (n8n / Voiceflow / Relevance AI / Claude Code, entry-level). Senior/lead/principal and region-locked listings dropped. Sources: Remotive, RemoteOK, WWR, Himalayas, HN, Greenhouse/Lever/Ashby boards.",
    },
    "youtube_content_ideas": {
        "label": "YouTube Content Ideas",
        "desc": "Three video ideas synthesised by the agent from the rest of this PDF, engineered to plausibly hit 10M views. Each ships with a hook, a thumbnail concept, and a 5-beat outline you can shoot the same week.",
    },
    "ai_search_trends": {
        "label": "What People Are Searching For",
        "desc": "Hottest AI topics right now: Google Trends rising queries (global + India), Hacker News top AI stories, and Reddit AI subreddits (last 24h).",
    },
    "instagram_viral_reels": {
        "label": "Viral Instagram Reels",
        "desc": "Top-engagement AI reels in the last 24h - one Global, one India. Ranked by likes + comments, AI-filtered, URL-checked. Reverse-engineer the hook for your own reels.",
    },
    "global_ai_news": {
        "label": "Global AI News",
        "desc": "Worldwide AI news only (US, EU, China, Japan, Korea, Middle East) - no general tech, no non-AI business news.",
    },
    "indian_ai_industry": {
        "label": "Indian AI Industry",
        "desc": "India-specific AI news only - Indian AI startups, AI policy, AI products.",
    },
    "product_showcase_opportunities": {
        "label": "AI Showcase Opportunities",
        "desc": "Two blocks: Hackathons & Competitions (prize + deadline) and Accelerators & Incubators (who can apply, what you get, deadline). Every item has a direct apply link. India & worldwide.",
    },
    "anthropic_claude_news": {
        "label": "Anthropic & Claude Code",
        "desc": "Anthropic company news + Claude Code feature updates (new commands, hooks, MCP, slash commands, agents, model rollouts).",
    },
    "elon_musk_ai_vision": {
        "label": "Elon Musk's AI Vision",
        "desc": "xAI & Grok news, Elon Musk's AI views, statements & predictions.",
    },
    "unaddressed_ai_problems": {
        "label": "Unaddressed AI Problems",
        "desc": "Real problems in AI that nobody is solving - gaps & unmet needs.",
    },
    "ai_business_opportunities": {
        "label": "AI Business Opportunities",
        "desc": "Emerging business opportunities in AI - India & world.",
    },
    "quantum_ai_research": {
        "label": "Quantum + AI",
        "desc": "Stories addressing both quantum (qubits, quantum hardware/algorithms) and AI/ML. Pure-quantum or pure-AI items are dropped.",
    },
    "ai_music_copyright_laws": {
        "label": "Copyright & Laws in AI Music",
        "desc": "AI music copyright lawsuits, regulations, fair-use rulings, licensing - India & world.",
    },
    "new_ai_tools": {
        "label": "New AI Tools",
        "desc": "Latest AI tools with cost & feature notes - biased to Claude Code / n8n / Voiceflow / Relevance AI / MCP / agent builders.",
    },
    "ai_model_benchmarks": {
        "label": "AI Model Benchmarks",
        "desc": "Top model per category (Text/LLM, Coding, Image, Video, Music, Audio) as a table, then benchmark news.",
    },
    "ai_business_automation": {
        "label": "AI Automation & Business",
        "desc": "How AI automation is changing work across industries: real deployments, ROI, sector updates.",
    },
    "ai_self_improvement_rsi": {
        "label": "AI Self-Improvement (RSI)",
        "desc": "Recursive self-improvement, AGI progress, alignment research.",
    },
    "viral_video_landscape": {
        "label": "Viral AI on YouTube",
        "desc": "Verified-viral picks from the last 7 days (2 long: Global + India, 1 Global Short). Floors: long >= 100K, short >= 500K. No view counts. No automation angle.",
    },
    "general_news": {
        "label": "General News",
        "desc": "Top world & India headlines outside of AI.",
    },
}

SECTION_ORDER = [
    "remote_jobs",                      # 1
    "product_showcase_opportunities",   # 2  hackathons + accelerators
    "youtube_content_ideas",            # 3
    "viral_video_landscape",            # 4  merged YouTube section
    "instagram_viral_reels",            # 5
    "quantum_ai_research",              # 6
    "ai_self_improvement_rsi",          # 7
    "elon_musk_ai_vision",              # 8
    "ai_model_benchmarks",              # 9
    "new_ai_tools",                     # 10
    "indian_ai_industry",               # 11
    "anthropic_claude_news",            # 12
    "ai_business_automation",           # 13
    "global_ai_news",                   # 14
    "ai_search_trends",                 # 15
    "unaddressed_ai_problems",          # 16
    "ai_business_opportunities",        # 17
    "ai_music_copyright_laws",          # 18
    "general_news",                     # 19
]


def _meta(section_key):
    return SECTION_CONFIG.get(section_key, {"label": section_key, "desc": ""})


# ── Magazine theme ────────────────────────────────────────────────────────────
INK = (13, 13, 13)
PAPER = (255, 255, 255)
LIME = (198, 242, 78)
MUTED = (107, 107, 107)
CARD = (240, 240, 241)
WHITE = (255, 255, 255)
LIGHT = (210, 210, 210)
LINK = (90, 120, 180)

MARGIN = 18
PAGE_W, PAGE_H = 210, 297
CONTENT_W = PAGE_W - 2 * MARGIN
BOTTOM = 280  # y past which we page-break

FONTS_DIR = os.path.join(PROJECT_ROOT, "assets", "fonts")
F_SANS, F_BLACK, F_SERIF = "Inter", "InterBlack", "Serif"
FONTS_OK = True  # flipped to False by register_fonts on load failure


def register_fonts(pdf):
    """Register bundled TTFs. On any failure, downgrade aliases to Helvetica so
    the run still produces a (plainer) PDF instead of crashing the daily job."""
    global F_SANS, F_BLACK, F_SERIF, FONTS_OK
    try:
        pdf.add_font("Inter", "", os.path.join(FONTS_DIR, "Inter-Regular.ttf"))
        pdf.add_font("Inter", "B", os.path.join(FONTS_DIR, "Inter-Bold.ttf"))
        pdf.add_font("InterBlack", "", os.path.join(FONTS_DIR, "Inter-Black.ttf"))
        pdf.add_font("Serif", "I", os.path.join(FONTS_DIR, "Newsreader-Italic.ttf"))
        F_SANS, F_BLACK, F_SERIF, FONTS_OK = "Inter", "InterBlack", "Serif", True
    except Exception as e:
        print(f"[generate_pdf] font load failed ({e}); using Helvetica fallback")
        F_SANS, F_BLACK, F_SERIF, FONTS_OK = "Helvetica", "Helvetica", "Helvetica", False


# ── Text cleaning ─────────────────────────────────────────────────────────────
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TRUNCATED_TAG_RE = re.compile(r"<[^>]*$")
_WHITESPACE_RE = re.compile(r"\s+")
_SMART = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": "-",
    " ": " ", "​": "",
}


def clean(text):
    """Strip HTML, decode entities, normalise whitespace, downgrade smart
    punctuation. Preserves unicode for the bundled TTFs; only downcasts to
    latin-1 when the Helvetica fallback is active (core fonts are latin-1)."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _TRUNCATED_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    for ch, repl in _SMART.items():
        text = text.replace(ch, repl)
    if not FONTS_OK:
        text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


sanitize_text = clean  # backwards-compatible alias


_ANGLE_RE = re.compile(r"\bAutomation angle\s*:\s*", re.IGNORECASE)


def split_summary_and_angle(text):
    """Split a summary on an 'Automation angle:' marker. Returns (main, angle)."""
    if not text:
        return "", ""
    m = _ANGLE_RE.search(text)
    if not m:
        return text.strip(), ""
    main = text[:m.start()].strip().rstrip(".")
    angle = text[m.end():].strip()
    if main and not main.endswith("."):
        main += "."
    return main, angle


_STOPWORDS = {"the", "a", "an", "and", "or", "but", "just", "is", "are", "of",
              "to", "in", "on", "for", "with", "its", "it's", "this", "that",
              "you", "your", "new", "has", "have", "as", "at", "by", "from"}


def pick_highlight_word(title):
    """Longest non-stopword token in the title (deterministic), else last word."""
    if not title:
        return ""
    toks = re.findall(r"[A-Za-z0-9$%']+", title)
    if not toks:
        return ""
    pool = [t for t in toks if t.lower() not in _STOPWORDS] or toks
    return max(pool, key=len)


def stars_str(relevance):
    """Five-star relevance string. Unicode stars with TTFs, ASCII on fallback."""
    try:
        n = max(0, min(5, int(round(float(relevance)))))
    except (TypeError, ValueError):
        n = 0
    if FONTS_OK:
        return "★" * n + "☆" * (5 - n)
    return "*" * n + "." * (5 - n)


def render_stars(relevance):  # legacy helper kept for any external callers
    return stars_str(relevance)


# ── Drawing primitives ────────────────────────────────────────────────────────
def _set(pdf, family, style, size, color):
    pdf.set_font(family, style, size)
    pdf.set_text_color(*color)


def _measure_lines(pdf, w, text, family, style, size):
    """Number of wrapped lines `text` occupies in width `w` (no drawing)."""
    pdf.set_font(family, style, size)
    return pdf.multi_cell(w, 5, clean(text), dry_run=True, output="LINES")


def dark_page(pdf):
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, PAGE_W, PAGE_H, "F")


def eyebrow(pdf, x, y, text):
    """Small lime tag label, e.g. '01 . REMOTE AI JOBS'. Returns y below it."""
    _set(pdf, F_SANS, "B", 8, INK)
    label = text.upper()
    w = pdf.get_string_width(label) + 6
    pdf.set_fill_color(*LIME)
    pdf.rect(x, y, w, 6, "F")
    pdf.set_xy(x + 3, y + 0.8)
    pdf.cell(w - 6, 4.4, label)
    return y + 6


def highlight_headline(pdf, x, y, text, size=30, ink=INK):
    """Bold headline; the pick_highlight_word() token gets a lime box behind it.
    Wraps within CONTENT_W. Returns the y below the headline."""
    lead = size * 0.46
    hl = pick_highlight_word(text).lower()
    text = clean(text)
    pdf.set_font(F_BLACK, "", size)
    space = pdf.get_string_width(" ")
    cx, cy = x, y
    for word in text.split():
        ww = pdf.get_string_width(word)
        if cx + ww > x + CONTENT_W and cx > x:
            cx = x
            cy += lead
        if hl and word.strip(".,:;'\"!?").lower() == hl:
            pdf.set_fill_color(*LIME)
            pdf.rect(cx - 1, cy + lead * 0.16, ww + 2, lead * 0.84, "F")
            pdf.set_text_color(*INK)
        else:
            pdf.set_text_color(*ink)
        pdf.set_xy(cx, cy)
        pdf.cell(ww, lead, word)
        cx += ww + space
    return cy + lead


def wrapped(pdf, x, y, w, text, family, style, size, color, lh=4.6):
    _set(pdf, family, style, size, color)
    pdf.set_xy(x, y)
    pdf.multi_cell(w, lh, clean(text))
    return pdf.get_y()


def link_line(pdf, x, y, w, text, url, size=7.5, color=LINK):
    """One clickable line, truncated with a trailing ... so it fits width `w`."""
    _set(pdf, F_SANS, "", size, color)
    s = clean(text)
    while s and pdf.get_string_width(s) > w:
        s = s[:-2]
    if s != clean(text):
        s = s[:-1] + "…" if FONTS_OK else s[:-3] + "..."
    pdf.set_xy(x, y)
    pdf.cell(w, 4, s, link=url)
    return y + 5


def card_box(pdf, x, y, w, body, label=None, pad=4):
    """Grey 'Quick Take' card with a lime left bar. Returns y below the box."""
    body = clean(body)
    n = len(_measure_lines(pdf, w - 2 * pad, body, F_SANS, "", 9.5))
    body_h = n * 4.8
    label_h = 6 if label else 0
    h = pad + label_h + body_h + pad
    pdf.set_fill_color(*CARD)
    pdf.rect(x, y, w, h, "F")
    pdf.set_fill_color(*LIME)
    pdf.rect(x, y, 1.6, h, "F")
    yy = y + pad
    if label:
        _set(pdf, F_SANS, "B", 7.5, INK)
        pdf.set_xy(x + pad, yy)
        pdf.cell(60, 4, label.upper())
        yy += label_h
    _set(pdf, F_SANS, "", 9.5, INK)
    pdf.set_xy(x + pad, yy)
    pdf.multi_cell(w - 2 * pad, 4.8, body)
    return y + h


def callout(pdf, x, y, w, label, body, pad=5):
    """Dark callout card: lime label + white body."""
    body = clean(body)
    n = len(_measure_lines(pdf, w - 2 * pad, body, F_SANS, "", 9))
    h = pad + 6 + n * 4.8 + pad
    pdf.set_fill_color(*INK)
    pdf.rect(x, y, w, h, "F")
    _set(pdf, F_SANS, "B", 8, LIME)
    pdf.set_xy(x + pad, y + pad)
    pdf.cell(120, 4, label.upper())
    _set(pdf, F_SANS, "", 9, WHITE)
    pdf.set_xy(x + pad, y + pad + 6)
    pdf.multi_cell(w - 2 * pad, 4.8, body)
    return y + h


def tick_list(pdf, x, y, w, items):
    """Lime-tick bullet list. Returns y below."""
    for it in items:
        pdf.set_fill_color(*LIME)
        pdf.rect(x, y + 1.3, 2.4, 2.4, "F")
        y = wrapped(pdf, x + 5, y, w - 5, it, F_SANS, "", 9, INK, lh=4.6) + 1.5
    return y


# ── Cover / contents / closing ────────────────────────────────────────────────
COVER_PRIORITY = ["global_ai_news", "anthropic_claude_news", "new_ai_tools",
                  "indian_ai_industry", "ai_business_automation",
                  "elon_musk_ai_vision"]


def pick_cover_story(sections):
    best, best_rel = None, -1.0
    for key in COVER_PRIORITY:
        for it in sections.get(key, []) or []:
            try:
                rel = float(it.get("relevance", 0))
            except (TypeError, ValueError):
                rel = 0.0
            if rel > best_rel and it.get("title"):
                best, best_rel = it, rel
    if not best:
        return (f"Your AI briefing for {DISPLAY_DATE}",
                "The day's signal across 19 sections - jobs, tools, research, viral, and more.")
    standfirst = split_summary_and_angle(best.get("summary", ""))[0]
    return clean(best["title"]), clean(standfirst)[:280]


def _issue_number():
    epoch = datetime(2026, 4, 25)  # issue 001 anchor
    return max(1, (datetime.now() - epoch).days + 1)


def build_cover(pdf, sections, issue_no):
    pdf.add_page()
    dark_page(pdf)
    # wordmark
    pdf.set_fill_color(*LIME)
    pdf.rect(MARGIN, 16, 4.5, 4.5, "F")
    _set(pdf, F_SANS, "B", 12, WHITE)
    pdf.set_xy(MARGIN + 7, 15)
    pdf.cell(60, 5, "staying")
    _set(pdf, F_SANS, "", 12, WHITE)
    pdf.set_xy(MARGIN + 7, 20)
    pdf.cell(60, 5, "ahead")
    _set(pdf, F_SANS, "B", 9, LIME)
    pdf.set_xy(PAGE_W - MARGIN - 70, 16)
    pdf.cell(70, 5, f"ISSUE {issue_no:03d}", align="R")
    _set(pdf, F_SANS, "B", 9, MUTED)
    pdf.set_xy(PAGE_W - MARGIN - 70, 21)
    pdf.cell(70, 5, DISPLAY_DATE.upper(), align="R")
    # headline
    title, standfirst = pick_cover_story(sections)
    if len(title) > 78:
        title = title[:75].rstrip() + "..."
    eyebrow(pdf, MARGIN, 96, "TODAY'S HEADLINE")
    y = highlight_headline(pdf, MARGIN, 108, title, size=32, ink=WHITE)
    wrapped(pdf, MARGIN, y + 8, CONTENT_W, standfirst, F_SANS, "", 12, LIGHT, lh=6)
    # footer
    _set(pdf, F_SANS, "B", 11, WHITE)
    lead = "Five minutes. Then you are "
    pdf.set_xy(MARGIN, 270)
    pdf.cell(pdf.get_string_width(lead), 5, lead)
    _set(pdf, F_SANS, "B", 11, LIME)
    pdf.set_xy(MARGIN + pdf.get_string_width(lead), 270)
    pdf.cell(0, 5, "ahead.")
    _set(pdf, F_SANS, "", 8, MUTED)
    pdf.set_xy(PAGE_W - MARGIN - 70, 269)
    pdf.cell(70, 5, "SENT BY", align="R")
    _set(pdf, F_SANS, "B", 10, WHITE)
    pdf.set_xy(PAGE_W - MARGIN - 70, 274)
    pdf.cell(70, 5, "Your Daily Agent", align="R")


def build_contents(pdf, sections):
    pdf.add_page()
    eyebrow(pdf, MARGIN, 20, "MORNING DIGEST")
    highlight_headline(pdf, MARGIN, 30, "What we cover today.", size=26)
    y = 58
    for i, key in enumerate(SECTION_ORDER, 1):
        if y > 272:
            pdf.add_page()
            y = 24
        label = _meta(key)["label"]
        items = sections.get(key, []) or []
        if items and isinstance(items[0], dict) and items[0].get("title"):
            teaser = clean(items[0]["title"])[:84]
        else:
            teaser = f"{len(items)} item(s)" if items else "no new items today"
        _set(pdf, F_BLACK, "", 11, INK)
        pdf.set_xy(MARGIN, y)
        pdf.cell(11, 6, f"{i:02d}")
        _set(pdf, F_SANS, "B", 10.5, INK)
        pdf.set_xy(MARGIN + 11, y)
        pdf.cell(0, 6, label[:60])
        _set(pdf, F_SANS, "", 8.5, MUTED)
        pdf.set_xy(MARGIN + 11, y + 5.5)
        pdf.multi_cell(CONTENT_W - 11, 4, teaser)
        y = pdf.get_y() + 3.5
        pdf.set_draw_color(228, 228, 228)
        pdf.line(MARGIN, y - 1.5, PAGE_W - MARGIN, y - 1.5)


def build_closing(pdf):
    pdf.add_page()
    dark_page(pdf)
    highlight_headline(pdf, MARGIN, 86, "You are caught up. Now stay ahead.",
                       size=30, ink=WHITE)
    wrapped(pdf, MARGIN, 150, CONTENT_W,
            "Tomorrow's PDF lands at 00:00 IST - the exact stack you need to stay "
            "one day ahead of everyone else in AI.",
            F_SANS, "", 11, LIGHT, lh=6)
    _set(pdf, F_SANS, "", 9, MUTED)
    pdf.set_xy(MARGIN, 275)
    pdf.cell(0, 5, f"Issue {_issue_number():03d}  .  {DISPLAY_DATE}")


# ── Section header + generic story card ───────────────────────────────────────
def section_header(pdf, section_key, idx):
    """Magazine section opener on a fresh page. Returns starting y."""
    pdf.add_page()
    label = _meta(section_key)["label"]
    eyebrow(pdf, MARGIN, 20, f"{idx:02d} . {label}")
    y = highlight_headline(pdf, MARGIN, 32, label, size=22)
    desc = (_meta(section_key).get("desc") or "").strip()
    if desc:
        y = wrapped(pdf, MARGIN, y + 3, CONTENT_W, desc[:240],
                    F_SANS, "", 8.5, MUTED, lh=4.2)
    return y + 4


def _ensure_space(pdf, y, need, section_key, idx):
    if y + need > BOTTOM:
        pdf.add_page()
        eyebrow(pdf, MARGIN, 16, f"{idx:02d} . {_meta(section_key)['label']} (cont.)")
        return 26
    return y


def story_card(pdf, y, item, section_key, idx):
    y = _ensure_space(pdf, y, 38, section_key, idx)
    y = wrapped(pdf, MARGIN, y, CONTENT_W, item.get("title", "Untitled"),
                F_SANS, "B", 12.5, INK, lh=5.6) + 1
    summ = item.get("summary", "")
    if summ:
        y = card_box(pdf, MARGIN, y, CONTENT_W, summ, label="Quick Take") + 2
    src = item.get("source", "")
    when = str(item.get("published") or item.get("posted") or "")[:10]
    rel = item.get("relevance")
    bits = [b for b in [src, when, (stars_str(rel) if rel is not None else "")] if b]
    if bits:
        y = wrapped(pdf, MARGIN, y, CONTENT_W, "  .  ".join(bits),
                    F_SANS, "", 8, MUTED, lh=4)
    url = item.get("url")
    if url:
        y = link_line(pdf, MARGIN, y, CONTENT_W, url, url)
    pdf.set_draw_color(232, 232, 232)
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    return y + 4


def _empty_note(pdf, y, text):
    wrapped(pdf, MARGIN, y, CONTENT_W, text, F_SERIF, "I", 11, MUTED)


def build_section(pdf, section_key, stories, idx):
    y = section_header(pdf, section_key, idx)
    if not stories:
        _empty_note(pdf, y, "No new items in the last 24h.")
        return
    for it in stories:
        if not isinstance(it, dict):
            continue
        y = story_card(pdf, y, it, section_key, idx)
    takeaway = stories[0].get("section_takeaway") if isinstance(stories[0], dict) else None
    if takeaway:
        y = _ensure_space(pdf, y, 40, section_key, idx)
        callout(pdf, MARGIN, y + 2, CONTENT_W, "The Big Picture", takeaway)


# ── Special renderers ─────────────────────────────────────────────────────────
_BUCKET_LABELS = {
    "global_ai": "Global", "india_ai": "India",
    "global": "Global", "india": "India",
    "global_long": "Global - Long", "india_long": "India - Long",
    "global_short": "Global - Short",
}


def _pretty_bucket(bucket):
    if not bucket:
        return ""
    return _BUCKET_LABELS.get(str(bucket).lower(), str(bucket).replace("_", " ").title())


def _looks_dumped(text):
    """True if `text` is an HN-parsed body dump rather than a real field value."""
    t = (text or "").strip().lower()
    return bool(t) and (t.startswith("location:") or "remote:" in t
                        or "willing to relocate" in t or t.startswith("http"))


def _job_is_clean(job):
    """Both title and company must read like real values (HN posts swap a URL
    into title and a 'Location:/Remote:' dump into company)."""
    t = (job.get("title") or "").strip()
    c = (job.get("company") or "").strip()
    if not t or len(t) > 90 or _looks_dumped(t):
        return False
    if not c or len(c) > 60 or _looks_dumped(c):
        return False
    return True


def _tidy_job(job):
    """(title, company) cleaned for display: collapse URL/dump fields."""
    t = (job.get("title") or "Role").strip()
    c = (job.get("company") or "").strip()
    if _looks_dumped(t) or "github.com" in t.lower():
        t = "HN 'Who is hiring' role"
    if _looks_dumped(c) or len(c) > 50:
        c = ""
    return t[:80], c


def build_jobs(pdf, section_key, jobs, idx):
    y = section_header(pdf, section_key, idx)
    jobs = [j for j in (jobs or []) if isinstance(j, dict)]
    if not jobs:
        _empty_note(pdf, y, "No fresh remote roles surfaced today.")
        return
    # Spotlight = highest-ranked fully-clean role; fall back to jobs[0].
    spot_i = next((i for i, j in enumerate(jobs) if _job_is_clean(j)), 0)
    jobs = [jobs[spot_i]] + jobs[:spot_i] + jobs[spot_i + 1:]
    top = jobs[0]
    sx, sy = MARGIN, y
    eyebrow(pdf, sx, sy, "Today's Spotlight Role")
    t_title, t_company = _tidy_job(top)
    y = wrapped(pdf, sx, sy + 8, CONTENT_W,
                f"{t_title} - {t_company}".strip(" -"),
                F_SANS, "B", 13, INK, lh=6) + 1
    sub = [b for b in [top.get("salary", ""), top.get("source", ""),
                       stars_str(top.get("relevance"))] if b]
    if sub:
        y = wrapped(pdf, sx, y, CONTENT_W, "  .  ".join(sub), F_SANS, "", 8.5, MUTED)
    skills = [s for s in (top.get("matched_skills") or []) if s][:6]
    if skills:
        cx = sx
        y += 1
        for s in skills:
            _set(pdf, F_SANS, "B", 7.5, INK)
            w = pdf.get_string_width(str(s)) + 5
            if cx + w > sx + CONTENT_W:
                cx = sx
                y += 7
            pdf.set_fill_color(*LIME)
            pdf.rect(cx, y, w, 5, "F")
            pdf.set_xy(cx + 2.5, y + 0.5)
            pdf.cell(w - 5, 4, str(s))
            cx += w + 3
        y += 8
    if top.get("summary"):
        y = card_box(pdf, sx, y, CONTENT_W, top["summary"], label="Why it fits") + 2
    if top.get("url"):
        _set(pdf, F_SANS, "B", 8.5, LINK)
        pdf.set_xy(sx, y)
        pdf.cell(40, 5, "Apply " + ("→" if FONTS_OK else "->"), link=top["url"])
        y += 8
    pdf.set_draw_color(*LIME)
    pdf.set_line_width(0.7)
    pdf.rect(sx - 3, sy - 3, CONTENT_W + 6, (y - sy) + 3)
    pdf.set_line_width(0.2)
    y += 6
    if len(jobs) > 1:
        _set(pdf, F_SANS, "B", 9.5, INK)
        pdf.set_xy(MARGIN, y)
        pdf.cell(0, 5, "More roles today")
        y += 7
        for j in jobs[1:]:
            y = _ensure_space(pdf, y, 16, section_key, idx)
            jt, jc = _tidy_job(j)
            head = f"{jt} - {jc}".strip(" -") + f"  {stars_str(j.get('relevance'))}"
            y = wrapped(pdf, MARGIN, y, CONTENT_W, head, F_SANS, "B", 9.5, INK, lh=4.6)
            line = [b for b in [j.get("salary", ""), j.get("source", "")] if b]
            if line:
                y = wrapped(pdf, MARGIN, y, CONTENT_W, "  .  ".join(line),
                            F_SANS, "", 7.5, MUTED, lh=4)
            if j.get("url"):
                y = link_line(pdf, MARGIN, y, CONTENT_W, j["url"], j["url"], size=7)
            y += 2.5


def build_benchmark_table(pdf, section_key, stories, idx):
    y = section_header(pdf, section_key, idx)
    rows, news = [], []
    for it in (stories or []):
        if not isinstance(it, dict):
            continue
        std = it.get("standings")
        if isinstance(std, list) and std:
            for r in std:
                if isinstance(r, dict):
                    rows.append((r.get("category", ""), r.get("best", ""),
                                 r.get("runner_up", ""),
                                 r.get("benchmark", "") or r.get("benchmark_name", "")))
                elif isinstance(r, (list, tuple)) and len(r) >= 4:
                    rows.append(tuple(r[:4]))
        elif it.get("category") and it.get("best"):
            rows.append((it.get("category", ""), it.get("best", ""),
                         it.get("runner_up", ""), it.get("benchmark_name", "")))
        else:
            news.append(it)
    if rows:
        cols = [("Task", 42), ("Best", 56), ("Runner-up", 46), ("Benchmark", CONTENT_W - 144)]
        pdf.set_fill_color(*INK)
        pdf.rect(MARGIN, y, CONTENT_W, 7, "F")
        cx = MARGIN
        for name, w in cols:
            _set(pdf, F_SANS, "B", 8, LIME)
            pdf.set_xy(cx + 2, y + 1.6)
            pdf.cell(w - 2, 4, name)
            cx += w
        y += 7
        for i, row in enumerate(rows):
            heights = [len(_measure_lines(pdf, w - 3, str(v), F_SANS, "", 7.5))
                       for (n, w), v in zip(cols, row)]
            rh = max(8, max(heights) * 3.8 + 3)
            y = _ensure_space(pdf, y, rh, section_key, idx)
            if i % 2:
                pdf.set_fill_color(246, 246, 246)
                pdf.rect(MARGIN, y, CONTENT_W, rh, "F")
            cx = MARGIN
            for (name, w), val in zip(cols, row):
                _set(pdf, F_SANS, "B" if name == "Task" else "", 7.5, INK)
                pdf.set_xy(cx + 2, y + 1.6)
                pdf.multi_cell(w - 3, 3.8, clean(str(val))[:80])
                cx += w
            y += rh
        y += 4
    for it in news:
        y = story_card(pdf, y, it, section_key, idx)


def build_youtube_ideas(pdf, section_key, ideas, idx):
    y = section_header(pdf, section_key, idx)
    ideas = [i for i in (ideas or []) if isinstance(i, dict)]
    if not ideas:
        _empty_note(pdf, y, "No ideas generated this run.")
        return
    for n, idea in enumerate(ideas[:3], 1):
        y = _ensure_space(pdf, y, 56, section_key, idx)
        y = wrapped(pdf, MARGIN, y, CONTENT_W, f"{n}. {idea.get('title', 'Untitled')}",
                    F_SANS, "B", 12, INK, lh=5.6) + 1
        if idea.get("hook"):
            y = card_box(pdf, MARGIN, y, CONTENT_W, idea["hook"],
                         label="Hook (first 8s)") + 2
        why = idea.get("why_10m") or idea.get("why_it_hits") or idea.get("why")
        if why:
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "Why it hits 10M: " + str(why),
                        F_SANS, "", 9, INK) + 1
        if idea.get("thumbnail"):
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "Thumbnail: " + str(idea["thumbnail"]),
                        F_SANS, "", 9, MUTED) + 1
        outline = idea.get("outline") or idea.get("beats") or []
        if isinstance(outline, list) and outline:
            y = tick_list(pdf, MARGIN, y + 1, CONTENT_W, [str(b) for b in outline[:5]])
        y += 5


def build_viral_video(pdf, section_key, vids, idx):
    y = section_header(pdf, section_key, idx)
    vids = [v for v in (vids or []) if isinstance(v, dict)]
    if not vids:
        _empty_note(pdf, y, "No new viral video cleared the floor this period.")
        return
    for v in vids:
        y = _ensure_space(pdf, y, 34, section_key, idx)
        y = wrapped(pdf, MARGIN, y, CONTENT_W,
                    f"{v.get('title', 'Video')} - {v.get('channel', '')}".strip(" -"),
                    F_SANS, "B", 11.5, INK, lh=5.4) + 1
        tag = [b for b in [v.get("format", ""), _pretty_bucket(v.get("bucket", ""))] if b]
        if tag:
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "  .  ".join(tag),
                        F_SANS, "", 8, MUTED, lh=4)
        if v.get("summary"):
            y = card_box(pdf, MARGIN, y, CONTENT_W, v["summary"],
                         label="Why it went viral") + 1
        if v.get("url"):
            y = link_line(pdf, MARGIN, y, CONTENT_W, v["url"], v["url"])
        y += 3


def build_instagram_reels(pdf, section_key, reels, idx):
    y = section_header(pdf, section_key, idx)
    reels = [r for r in (reels or []) if isinstance(r, dict)]
    if not reels:
        _empty_note(pdf, y, "No new viral reel this period.")
        return
    for r in reels:
        y = _ensure_space(pdf, y, 30, section_key, idx)
        user = str(r.get("username", "")).strip().lstrip("@")
        parts = ([("@" + user)] if user else []) + ([_pretty_bucket(r.get("bucket"))]
                                                     if r.get("bucket") else [])
        head = "  .  ".join(parts) or clean(r.get("title", "Reel"))
        y = wrapped(pdf, MARGIN, y, CONTENT_W, head,
                    F_SANS, "B", 11, INK, lh=5.2) + 1
        if r.get("hashtag"):
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "#" + str(r["hashtag"]).lstrip("#"),
                        F_SANS, "", 8, MUTED, lh=4)
        if r.get("summary"):
            y = card_box(pdf, MARGIN, y, CONTENT_W, r["summary"], label="Why it works") + 1
        if r.get("url"):
            y = link_line(pdf, MARGIN, y, CONTENT_W, r["url"], r["url"])
        y += 3


def _fmt_deadline(iso):
    """Human-readable deadline: 'June 15, 2026' for an ISO date,
    'Rolling — apply anytime' when there's no fixed deadline."""
    if not iso:
        return "Rolling — apply anytime"
    try:
        d = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    except (ValueError, TypeError):
        return str(iso)


def _showcase_group(it):
    """'hackathon' or 'accelerator'; default missing/unknown -> 'hackathon'."""
    g = (it.get("group") or "").strip().lower()
    return g if g in ("hackathon", "accelerator") else "hackathon"


def _kv(pdf, x, y, w, label, value):
    """Bold 'Label:' + regular value. One line when it fits, else the label then
    the wrapped value beneath it. Missing/empty value -> nothing drawn (so a
    null prize shows no 'Prize:' line rather than 'Prize: None'). Returns y."""
    if value is None:
        return y
    value = clean(str(value))
    if not value:
        return y
    lab = label + ": "
    _set(pdf, F_SANS, "B", 9.5, INK)
    lw = pdf.get_string_width(lab)
    _set(pdf, F_SANS, "", 9.5, INK)
    if lw + pdf.get_string_width(value) <= w:
        _set(pdf, F_SANS, "B", 9.5, INK)
        pdf.set_xy(x, y)
        pdf.cell(lw, 5, lab)
        _set(pdf, F_SANS, "", 9.5, INK)
        pdf.cell(0, 5, value)
        return y + 5.4
    _set(pdf, F_SANS, "B", 9.5, INK)
    pdf.set_xy(x, y)
    pdf.cell(lw, 5, lab)
    return wrapped(pdf, x, y + 5, w, value, F_SANS, "", 9.5, INK, lh=4.8) + 1


def build_showcase(pdf, section_key, items, idx):
    """Two labeled sub-blocks so the user clearly sees BOTH kinds of opportunity:
      Hackathons & Competitions  -> Title / Prize / Deadline / apply link
      Accelerators & Incubators  -> Title / Who can apply / What you get /
                                    Deadline / apply link
    Each list is sorted by deadline ascending (rolling/undated last)."""
    y = section_header(pdf, section_key, idx)
    items = [it for it in (items or []) if isinstance(it, dict)]
    if not items:
        _empty_note(pdf, y, "No open hackathons or accelerator programs right now.")
        return

    def _dl_key(it):
        # First-time entries lead the block; within each tier, soonest deadline first.
        d = it.get("deadline_iso")
        return (0 if it.get("is_new") else 1, 1 if not d else 0, str(d or "")[:10])

    hackathons = sorted([it for it in items if _showcase_group(it) == "hackathon"], key=_dl_key)
    accelerators = sorted([it for it in items if _showcase_group(it) == "accelerator"], key=_dl_key)

    def _title(it):
        t = clean(it.get("title") or "Untitled")
        return f"NEW · {t}" if it.get("is_new") else t

    def _apply_url(it):
        return (it.get("url") or it.get("submission_url") or it.get("apply_url") or "").strip()

    if hackathons:
        y = _ensure_space(pdf, y, 18, section_key, idx)
        y = eyebrow(pdf, MARGIN, y, "Hackathons & Competitions") + 3
        for it in hackathons:
            y = _ensure_space(pdf, y, 30, section_key, idx)
            y = wrapped(pdf, MARGIN, y, CONTENT_W, _title(it), F_SANS, "B", 11.5, INK, lh=5.2) + 1
            y = _kv(pdf, MARGIN, y, CONTENT_W, "Prize", it.get("prize_summary"))
            y = _kv(pdf, MARGIN, y, CONTENT_W, "Deadline", _fmt_deadline(it.get("deadline_iso")))
            url = _apply_url(it)
            if url:
                y = link_line(pdf, MARGIN, y, CONTENT_W, url, url)
            y += 4

    if accelerators:
        y = _ensure_space(pdf, y, 22, section_key, idx)
        y = eyebrow(pdf, MARGIN, y + 2, "Accelerators & Incubators") + 3
        for it in accelerators:
            y = _ensure_space(pdf, y, 36, section_key, idx)
            y = wrapped(pdf, MARGIN, y, CONTENT_W, _title(it), F_SANS, "B", 11.5, INK, lh=5.2) + 1
            y = _kv(pdf, MARGIN, y, CONTENT_W, "Who can apply", it.get("eligibility"))
            y = _kv(pdf, MARGIN, y, CONTENT_W, "What you get",
                    it.get("benefits") or it.get("summary"))
            y = _kv(pdf, MARGIN, y, CONTENT_W, "Deadline", _fmt_deadline(it.get("deadline_iso")))
            url = _apply_url(it)
            if url:
                y = link_line(pdf, MARGIN, y, CONTENT_W, url, url)
            y += 4


SPECIAL = {
    "remote_jobs": build_jobs,
    "product_showcase_opportunities": build_showcase,
    "ai_model_benchmarks": build_benchmark_table,
    "youtube_content_ideas": build_youtube_ideas,
    "viral_video_landscape": build_viral_video,
    "instagram_viral_reels": build_instagram_reels,
}


# ── Orchestration ─────────────────────────────────────────────────────────────
def generate_pdf():
    """Load analyzed content and render the magazine PDF."""
    input_file = os.path.join(TMP_DIR, "analyzed_content.json")
    if not os.path.exists(input_file):
        print("ERROR: analyzed_content.json not found. Run analyze_and_categorize.py first.")
        sys.exit(1)
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    sections = data.get("sections", {}) or {}

    # Merge agent-written YouTube ideas (separate file) into the section payload.
    ideas_path = os.path.join(TMP_DIR, "youtube_content_ideas.json")
    if os.path.exists(ideas_path):
        try:
            with open(ideas_path, "r", encoding="utf-8") as f:
                ideas = (json.load(f) or {}).get("ideas", []) or []
            if ideas:
                sections["youtube_content_ideas"] = ideas
        except Exception:
            pass

    print("Generating magazine PDF...")
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_title("Daily AI News & Remote Jobs")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    register_fonts(pdf)

    issue_no = _issue_number()
    build_cover(pdf, sections, issue_no)
    build_contents(pdf, sections)
    for idx, key in enumerate(SECTION_ORDER, 1):
        stories = sections.get(key, []) or []
        builder = SPECIAL.get(key)
        if builder:
            builder(pdf, key, stories, idx)
        else:
            build_section(pdf, key, stories, idx)
    build_closing(pdf)

    os.makedirs(TMP_DIR, exist_ok=True)
    pdf.output(OUTPUT_FILE)
    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    total = sum(len(sections.get(s, [])) for s in SECTION_ORDER
                if isinstance(sections.get(s), list))
    print(f"[generate_pdf] wrote {OUTPUT_FILE} ({pdf.page_no()} pages, "
          f"{size_kb:.0f} KB, {total} items)")
    return True, OUTPUT_FILE


if __name__ == "__main__":
    generate_pdf()
