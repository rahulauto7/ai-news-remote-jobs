"""
Generate an attractive daily AI news PDF from analyzed content.
Reads .tmp/analyzed_content.json → Outputs .tmp/ai_news_daily_YYYY-MM-DD.pdf

Features:
- Color-coded section headers with unique colors per section
- Cover page with date, table of contents, and topic distribution chart
- Relevance star ratings per story
- Source attribution and URLs
- Alternating row backgrounds
- Charts via matplotlib
"""

import html
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

from fpdf import FPDF
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(TMP_DIR, f"ai_news_remote_jobs_{TODAY}.pdf")

# ── Section Config ────────────────────────────────────────────────────────────
SECTION_CONFIG = {
    "remote_jobs": {
        "label": "Remote AI Automation Jobs (Global)",
        "icon": "✎",      # ✎
        "color": (39, 174, 96),  # Emerald green
        "desc": "Global remote roles in AI automation hiring right now — LinkedIn, Wellfound, Indeed, RemoteOK, Remotive, We Work Remotely, Himalayas, HN, X",
    },
    "global_ai_news": {
        "label": "Global AI News",
        "icon": "\u2637",      # ☷
        "color": (41, 128, 185),  # Steel blue
        "desc": "Worldwide AI: US, EU, China, Japan, Korea, Middle East & more",
    },
    "indian_ai_industry": {
        "label": "Indian AI Industry",
        "icon": "\u2605",      # ★
        "color": (255, 153, 51),  # India saffron
        "desc": "India-specific AI news, policy, startups, government initiatives",
    },
    "product_showcase_opportunities": {
        "label": "AI Product Showcase Opportunities",
        "icon": "\u2709",      # ✉
        "color": (0, 128, 128),   # Teal
        "desc": "Platforms, directories & competitions to submit your AI product — India & worldwide",
    },
    "anthropic_claude_news": {
        "label": "Claude Model Updates",
        "icon": "\u25C8",      # ◈
        "color": (204, 121, 67),  # Warm amber
        "desc": "Claude model updates, Anthropic company news, safety research & partnerships",
    },
    "elon_musk_ai_vision": {
        "label": "Elon Musk's AI Vision",
        "icon": "\u2604",      # ☄
        "color": (50, 50, 50),    # Dark gray
        "desc": "xAI & Grok news, Elon Musk's AI views, statements & predictions",
    },
    "unaddressed_ai_problems": {
        "label": "Unaddressed AI Problems",
        "icon": "\u2753",      # ❓
        "color": (180, 30, 30),   # Deep red
        "desc": "Real problems in AI that nobody is solving — gaps & unmet needs",
    },
    "ai_business_opportunities": {
        "label": "AI Business Opportunities",
        "icon": "\u2728",      # ✨
        "color": (46, 204, 113),  # Green
        "desc": "Emerging business opportunities in AI — India & world",
    },
    "quantum_ai_research": {
        "label": "Quantum + AI",
        "icon": "\u269b",      # ⚛
        "color": (26, 188, 156),  # Teal
        "desc": "Quantum computing + AI breakthroughs — only stories where AI is involved",
    },
    "ai_music_business_news": {
        "label": "AI Music Business News",
        "icon": "\u266b",      # ♫
        "color": (230, 126, 34),  # Orange
        "desc": "Suno, Udio, DistroKid — platform updates, partnerships, revenue models, market trends",
    },
    "ai_music_copyright_laws": {
        "label": "Copyright & Laws in AI Music Business",
        "icon": "\u2696",      # ⚖
        "color": (192, 57, 43),  # Dark red
        "desc": "AI music copyright lawsuits, regulations, fair use rulings, licensing — India & world",
    },
    "new_ai_tools": {
        "label": "New AI Tools",
        "icon": "\u2692",      # ⚒
        "color": (155, 89, 182),  # Purple
        "desc": "Latest AI tools with cost & feature comparisons",
    },
    "ai_model_benchmarks": {
        "label": "AI Model Benchmarks",
        "icon": "\u2261",      # ≡
        "color": (70, 130, 180),  # Steel blue
        "desc": "Model performance benchmarks — rankings, scores, and what each benchmark measures",
    },
    "ai_business_automation": {
        "label": "AI Automation & Businesses",
        "icon": "\u2699",      # ⚙
        "color": (52, 152, 219),  # Blue
        "desc": "AI automation news, tools, and market demand",
    },
    "ai_self_improvement_rsi": {
        "label": "AI Self-Improvement (RSI)",
        "icon": "\u221e",      # ∞
        "color": (142, 68, 173),  # Dark purple
        "desc": "Recursive self-improvement, AGI progress, alignment research",
    },
    "viral_video_landscape": {
        "label": "Viral Video Landscape",
        "icon": "\u25bc",      # ▼
        "color": (255, 69, 0),  # Red-orange
        "desc": "Top AI video (Global automation), top AI video (India automation), top AI Short — max views in last 24h",
    },
    "youtube_ai_landscape": {
        "label": "YouTube AI Landscape",
        "icon": "\u25b6",      # ▶
        "color": (255, 0, 0),   # YouTube Red
        "desc": "Trending AI videos, viral topics across platforms, and content gaps to cover",
    },
    "general_news": {
        "label": "General News",
        "icon": "\u2691",      # ⚑
        "color": (108, 122, 137),  # Slate gray
        "desc": "Top world & India headlines outside of AI",
    },
    "run_telemetry": {
        "label": "Run Telemetry",
        "icon": "⚙",      # gear
        "color": (90, 90, 90),
        "desc": "What this scheduler run cost: per-step timings, scrape counts, agent token usage.",
    },
}

# Published per-million-token rates (USD). Update when models change.
MODEL_PRICING = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_creation": 18.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_creation": 3.75},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_creation": 1.25},
}

SECTION_ORDER = [
    "remote_jobs",
    "ai_music_business_news", "ai_music_copyright_laws",
    "global_ai_news", "indian_ai_industry", "product_showcase_opportunities",
    "anthropic_claude_news", "elon_musk_ai_vision", "unaddressed_ai_problems",
    "ai_business_opportunities", "quantum_ai_research",
    "new_ai_tools", "ai_model_benchmarks",
    "ai_business_automation", "ai_self_improvement_rsi",
    "viral_video_landscape", "youtube_ai_landscape",
    "general_news",
]


class GlobalAINewsPDF(FPDF):
    """Custom PDF with headers, footers, and styling."""

    def header(self):
        if self.page_no() == 1:
            return  # Cover page has custom header
        self.set_fill_color(26, 26, 46)
        self.rect(0, 0, 210, 12, "F")
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(200, 200, 200)
        self.set_xy(5, 3)
        self.cell(100, 6, "GLOBAL AI NEWS DAILY BRIEFING", new_x="RIGHT")
        self.set_xy(150, 3)
        self.cell(55, 6, TODAY, align="R")
        self.set_text_color(0, 0, 0)
        self.ln(12)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}  |  Global AI News  |  {TODAY}", align="C")


def generate_topic_chart(sections_data):
    """Generate a bar chart of stories per section. Returns PNG bytes."""
    labels = []
    counts = []
    colors = []

    for section_key in SECTION_ORDER:
        config = SECTION_CONFIG[section_key]
        stories = sections_data.get(section_key, [])
        if stories:
            labels.append(config["label"])
            counts.append(len(stories))
            r, g, b = config["color"]
            colors.append((r / 255, g / 255, b / 255))

    if not labels:
        return None

    fig, ax = plt.subplots(figsize=(7, 3.5))
    bars = ax.barh(range(len(labels)), counts, color=colors, height=0.6)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("Number of Stories", fontsize=8)
    ax.set_title("Today's Coverage Distribution", fontsize=10, fontweight="bold")
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for bar, count in zip(bars, counts):
        ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                str(count), va="center", fontsize=7, fontweight="bold")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TRUNCATED_TAG_RE = re.compile(r"<[^>]*$")  # opens but never closes (e.g. truncated RSS)
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(text):
    """Strip HTML, decode entities, normalise whitespace, and downcast to latin-1."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # Strip HTML tags and decode entities (raw RSS often leaks <p>, <a>, &amp;, etc.)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _TRUNCATED_TAG_RE.sub("", text)  # cut dangling unclosed tags
    text = html.unescape(text)
    # Collapse whitespace
    text = _WHITESPACE_RE.sub(" ", text).strip()
    replacements = {
        "\u2014": "-",   # em-dash
        "\u2013": "-",   # en-dash
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2026": "...", # ellipsis
        "\u2022": "-",   # bullet
        "\u00a0": " ",   # non-breaking space
        "\u200b": "",    # zero-width space
    }
    for char, repl in replacements.items():
        text = text.replace(char, repl)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def render_stars(relevance):
    """Return star string for relevance score."""
    filled = min(max(int(relevance), 0), 5)
    return "*" * filled + "." * (5 - filled)  # star rating


def build_cover_page(pdf, sections_data):
    """Build the cover page with title, date, chart, and table of contents."""
    # Dark header bar
    pdf.set_fill_color(26, 26, 46)
    pdf.rect(0, 0, 210, 70, "F")

    # Title
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, 15)
    pdf.cell(180, 15, "AI NEWS + REMOTE JOBS", align="C")

    # Subtitle
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(180, 200, 255)
    pdf.set_xy(15, 32)
    pdf.cell(180, 10, "Daily Briefing for Remote AI Automators", align="C")

    # Date
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(255, 215, 0)
    pdf.set_xy(15, 48)
    nice_date = datetime.now().strftime("%A, %B %d, %Y")
    pdf.cell(180, 10, nice_date, align="C")

    pdf.set_text_color(0, 0, 0)

    # Topic distribution chart
    chart_buf = generate_topic_chart(sections_data)
    if chart_buf:
        chart_path = os.path.join(TMP_DIR, "topic_chart.png")
        with open(chart_path, "wb") as f:
            f.write(chart_buf.read())
        pdf.image(chart_path, x=15, y=75, w=180)

    # Table of contents
    toc_y = 165
    pdf.set_xy(15, toc_y)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(180, 8, "TABLE OF CONTENTS", align="C")
    toc_y += 12

    pdf.set_font("Helvetica", "", 9)
    for i, section_key in enumerate(SECTION_ORDER, 1):
        config = SECTION_CONFIG[section_key]
        stories = sections_data.get(section_key, [])
        count = len(stories)

        r, g, b = config["color"]
        pdf.set_fill_color(r, g, b)
        pdf.rect(20, toc_y, 3, 5, "F")

        pdf.set_text_color(50, 50, 50)
        pdf.set_xy(26, toc_y)
        label_text = f"{i}. {config['label']}"
        if count > 0:
            label_text += f"  ({count} stories)"
        pdf.cell(160, 5, label_text)
        toc_y += 6

        if toc_y > 280:
            break


def build_section(pdf, section_key, stories):
    """Build a full section with header, description, and stories."""
    config = SECTION_CONFIG[section_key]
    r, g, b = config["color"]

    # Check if we need a new page (at least 60mm space needed for header + one story)
    if pdf.get_y() > 220:
        pdf.add_page()

    y = pdf.get_y() + 5

    # Section header bar
    pdf.set_fill_color(r, g, b)
    pdf.rect(10, y, 190, 12, "F")

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, y + 1)
    icon = config.get("icon", "")
    pdf.cell(180, 10, f"  {config['label'].upper()}")

    y += 14

    # Section description
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(12, y)
    pdf.cell(186, 5, sanitize_text(config["desc"]))
    y += 7

    # Thin accent line
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.5)
    pdf.line(12, y, 198, y)
    y += 3

    if not stories:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(150, 150, 150)
        pdf.set_xy(15, y)
        pdf.cell(180, 8, "No stories in this section today.")
        pdf.set_y(y + 12)
        return

    # Stories
    for idx, story in enumerate(stories):
        # Check page break
        if y > 255:
            pdf.add_page()
            y = pdf.get_y() + 2

        # Alternating background
        if idx % 2 == 0:
            pdf.set_fill_color(245, 247, 250)
            pdf.rect(10, y, 190, 24, "F")

        # Title + relevance stars (title is a clickable hyperlink to story URL)
        story_url = story.get("url", "")
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(25, 75, 200)  # link blue
        pdf.set_xy(14, y + 1)

        title = sanitize_text(story.get("title", "Untitled")[:90])
        relevance = story.get("relevance", 3)
        stars = render_stars(relevance)

        pdf.cell(155, 5, title, link=story_url)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(r, g, b)
        pdf.cell(25, 5, stars, align="R")

        # Source and metadata line
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(120, 120, 120)
        pdf.set_xy(14, y + 6)

        source = story.get("source") or story.get("channel") or "Unknown"
        source = sanitize_text(source)
        meta_parts = [f"Source: {source}"]

        # Section-specific metadata
        if section_key == "new_ai_tools":
            pricing = story.get("pricing", "")
            category = story.get("category", "")
            if pricing:
                meta_parts.append(f"Price: {pricing}")
            if category:
                meta_parts.append(f"Type: {category}")
        elif section_key == "unaddressed_ai_problems":
            who = story.get("who_affected", "")
            severity = story.get("severity", "")
            if who:
                meta_parts.append(f"Affects: {who}")
            if severity:
                meta_parts.append(f"[{severity.upper()}]")
        elif section_key == "product_showcase_opportunities":
            platform = story.get("platform_type", "")
            region = story.get("region", "")
            sub_url = story.get("submission_url", "")
            if platform:
                meta_parts.append(f"Type: {platform}")
            if region:
                meta_parts.append(f"Region: {region}")
            if sub_url:
                meta_parts.append(f"Submit: {sub_url}")
        elif section_key == "ai_music_business_news":
            platform = story.get("platform", "")
            deal_value = story.get("deal_value", "")
            if platform:
                meta_parts.append(f"Platform: {platform}")
            if deal_value:
                meta_parts.append(f"Deal: {deal_value}")
        elif section_key == "ai_music_copyright_laws":
            case_name = story.get("case_name", "")
            jurisdiction = story.get("jurisdiction", "")
            status = story.get("status", "")
            if case_name:
                meta_parts.append(f"Case: {case_name}")
            if jurisdiction:
                meta_parts.append(f"Jurisdiction: {jurisdiction}")
            if status:
                meta_parts.append(f"[{status.upper()}]")
        elif section_key == "ai_model_benchmarks":
            model_name = story.get("model_name", "")
            benchmark_name = story.get("benchmark_name", "")
            score = story.get("score", "")
            rank = story.get("rank", "")
            if model_name:
                meta_parts.append(f"Model: {model_name}")
            if benchmark_name:
                meta_parts.append(f"Benchmark: {benchmark_name}")
            if score:
                meta_parts.append(f"Score: {score}")
            if rank:
                meta_parts.append(f"Rank: {rank}")

        elif section_key == "youtube_ai_landscape":
            views = story.get("views", 0)
            channel = story.get("channel", "")
            platform = story.get("platform", "")
            content_gap = story.get("content_gap", "")
            if channel:
                meta_parts.append(f"Channel: {channel}")
            if views:
                meta_parts.append(f"Views: {views:,}")
            if platform:
                meta_parts.append(f"Platform: {platform}")
            if content_gap:
                meta_parts.append(f"Gap: {content_gap}")

        pdf.cell(180, 4, sanitize_text("  |  ".join(meta_parts)))

        # Summary
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.set_xy(14, y + 11)
        summary = sanitize_text(story.get("summary", "")[:250])
        pdf.multi_cell(178, 3.5, summary)

        y = pdf.get_y() + 1
        if story.get("url"):
            pdf.set_font("Helvetica", "U", 7)
            pdf.set_text_color(25, 75, 200)
            pdf.set_xy(14, y)
            url_txt = sanitize_text(story["url"][:140])
            pdf.cell(180, 4, url_txt, link=story["url"])
            y += 5
        y += 3


def build_viral_video_section(pdf, section_key, stories):
    """Build the Viral Video Landscape section with Global/India subsection headers."""
    config = SECTION_CONFIG[section_key]
    r, g, b = config["color"]

    if pdf.get_y() > 220:
        pdf.add_page()

    y = pdf.get_y() + 5

    # Section header bar (same as build_section)
    pdf.set_fill_color(r, g, b)
    pdf.rect(10, y, 190, 12, "F")
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, y + 1)
    pdf.cell(180, 10, f"  {config['label'].upper()}")
    y += 14

    # Section description
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(12, y)
    pdf.cell(186, 5, sanitize_text(config["desc"]))
    y += 7

    # Accent line
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.5)
    pdf.line(12, y, 198, y)
    y += 3

    if not stories:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(150, 150, 150)
        pdf.set_xy(15, y)
        pdf.cell(180, 8, "No stories in this section today.")
        pdf.set_y(y + 12)
        return

    # Define subsection rendering order — 3 AI categories, max-views per category, last 24h
    subsection_order = [
        ("global", True, "video", "AI Automation - Global (max views, 24h)"),
        ("india", True, "video", "AI Automation - India (max views, 24h)"),
        ("global", True, "short", "General AI Short - Global (max views, 24h)"),
    ]

    # Group stories by (region, is_ai, format)
    grouped = {}
    for story in stories:
        key = (
            story.get("region", "global").lower(),
            story.get("is_ai", False),
            story.get("format", "video").lower(),
        )
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(story)

    current_region = None
    story_idx = 0

    for region, is_ai, fmt, subsection_label in subsection_order:
        group_stories = grouped.get((region, is_ai, fmt), [])
        if not group_stories:
            continue

        # Region header (only when region changes)
        if region != current_region:
            current_region = region
            if y > 250:
                pdf.add_page()
                y = pdf.get_y() + 2

            # Light background bar for region
            pdf.set_fill_color(
                min(r + 80, 255), min(g + 80, 255), min(b + 80, 255)
            )
            pdf.rect(10, y, 190, 8, "F")
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(40, 40, 40)
            pdf.set_xy(14, y + 1)
            pdf.cell(180, 6, region.upper())
            y += 10

        # Subsection label
        if y > 255:
            pdf.add_page()
            y = pdf.get_y() + 2

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(r, g, b)
        pdf.set_xy(16, y)
        pdf.cell(180, 5, subsection_label)
        y += 6

        # Render story (just the top 1)
        story = group_stories[0]

        if y > 255:
            pdf.add_page()
            y = pdf.get_y() + 2

        # Alternating background
        if story_idx % 2 == 0:
            pdf.set_fill_color(245, 247, 250)
            pdf.rect(10, y, 190, 24, "F")

        # Title + stars (clickable)
        story_url = story.get("url", "")
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(25, 75, 200)
        pdf.set_xy(14, y + 1)
        title = sanitize_text(story.get("title", "Untitled")[:90])
        relevance = story.get("relevance", 3)
        stars = render_stars(relevance)
        pdf.cell(155, 5, title, link=story_url)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(r, g, b)
        pdf.cell(25, 5, stars, align="R")

        # Metadata line
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(120, 120, 120)
        pdf.set_xy(14, y + 6)
        meta_parts = []
        channel = story.get("channel", "")
        views = story.get("views", 0)
        vid_format = story.get("format", "video").upper()
        if channel:
            meta_parts.append(f"Channel: {channel}")
        if views:
            meta_parts.append(f"Views: {views:,}")
        meta_parts.append(f"[{vid_format}]")
        pdf.cell(180, 4, sanitize_text("  |  ".join(meta_parts)))

        # Summary
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.set_xy(14, y + 11)
        summary = sanitize_text(story.get("summary", "")[:250])
        pdf.multi_cell(178, 3.5, summary)

        y = pdf.get_y() + 1
        if story.get("url"):
            pdf.set_font("Helvetica", "U", 7)
            pdf.set_text_color(25, 75, 200)
            pdf.set_xy(14, y)
            url_txt = sanitize_text(story["url"][:140])
            pdf.cell(180, 4, url_txt, link=story["url"])
            y += 5
        y += 3
        story_idx += 1

    pdf.set_y(y)


def build_telemetry_section(pdf, telemetry):
    """Render the run_telemetry section: per-step timings + agent token usage."""
    config = SECTION_CONFIG["run_telemetry"]
    r, g, b = config["color"]

    if pdf.get_y() > 220:
        pdf.add_page()
    y = pdf.get_y() + 5

    pdf.set_fill_color(r, g, b)
    pdf.rect(10, y, 190, 12, "F")
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, y + 1)
    pdf.cell(180, 10, f"  {config['label'].upper()}")
    y += 14

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(12, y)
    pdf.cell(186, 5, sanitize_text(config["desc"]))
    y += 7

    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.5)
    pdf.line(12, y, 198, y)
    y += 4

    # Run summary
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(14, y)
    pdf.cell(180, 5, "Pipeline Run")
    y += 6

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    started = telemetry.get("started_at", "?")
    finished = telemetry.get("finished_at", "?")
    total = telemetry.get("total_elapsed_s", 0)
    pdf.set_xy(14, y); pdf.cell(180, 5, sanitize_text(f"Started:  {started}")); y += 5
    pdf.set_xy(14, y); pdf.cell(180, 5, sanitize_text(f"Finished: {finished}")); y += 5
    pdf.set_xy(14, y); pdf.cell(180, 5, sanitize_text(f"Total:    {total:.1f}s")); y += 8

    # Per-step timings table
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(14, y); pdf.cell(180, 5, "Per-Step Timings"); y += 6

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(14, y)
    pdf.cell(90, 6, "  Step", border=0, fill=True)
    pdf.cell(30, 6, "Status", border=0, fill=True, align="C")
    pdf.cell(30, 6, "Elapsed (s)", border=0, fill=True, align="R")
    pdf.cell(30, 6, "Items", border=0, fill=True, align="R")
    y += 7

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(60, 60, 60)
    for step_name, info in (telemetry.get("steps") or {}).items():
        if y > 270:
            pdf.add_page(); y = pdf.get_y() + 2
        ok = info.get("ok")
        status = "OK" if ok else ("SKIP" if ok is None else "FAIL")
        elapsed_s = info.get("elapsed_s", 0) or 0
        items = info.get("items")
        items_s = str(items) if items is not None else "-"
        pdf.set_xy(14, y)
        pdf.cell(90, 5, sanitize_text(f"  {step_name}"))
        pdf.cell(30, 5, status, align="C")
        pdf.cell(30, 5, f"{elapsed_s:.1f}", align="R")
        pdf.cell(30, 5, items_s, align="R")
        y += 5
    y += 3

    # Agent token usage
    if y > 250:
        pdf.add_page(); y = pdf.get_y() + 2

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(14, y); pdf.cell(180, 5, "Agent Token Usage"); y += 6

    tok = telemetry.get("agent_tokens") or {}
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)

    if not tok or tok.get("available") is False:
        reason = tok.get("reason", "agent did not write .tmp/agent_tokens.json")
        pdf.set_xy(14, y)
        pdf.multi_cell(180, 5, sanitize_text(f"Token usage unavailable. Reason: {reason}"))
        y = pdf.get_y() + 2
    else:
        model = tok.get("model", "unknown")
        in_tok = int(tok.get("input_tokens", 0) or 0)
        out_tok = int(tok.get("output_tokens", 0) or 0)
        cr_tok = int(tok.get("cache_read_tokens", 0) or 0)
        cc_tok = int(tok.get("cache_creation_tokens", 0) or 0)
        total_tok = in_tok + out_tok + cr_tok + cc_tok

        rates = MODEL_PRICING.get(model)
        cost = None
        if rates:
            cost = (
                in_tok / 1e6 * rates["input"]
                + out_tok / 1e6 * rates["output"]
                + cr_tok / 1e6 * rates["cache_read"]
                + cc_tok / 1e6 * rates["cache_creation"]
            )

        rows = [
            ("Model", model),
            ("Input tokens", f"{in_tok:,}"),
            ("Output tokens", f"{out_tok:,}"),
            ("Cache read", f"{cr_tok:,}"),
            ("Cache creation", f"{cc_tok:,}"),
            ("Total tokens", f"{total_tok:,}"),
            ("Estimated cost (USD)", f"${cost:.4f}" if cost is not None else "n/a (unknown model rates)"),
        ]
        for label, val in rows:
            pdf.set_xy(14, y)
            pdf.cell(60, 5, sanitize_text(label))
            pdf.cell(120, 5, sanitize_text(val))
            y += 5

        notes = tok.get("notes")
        if notes:
            y += 2
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(100, 100, 100)
            pdf.set_xy(14, y)
            pdf.multi_cell(180, 4, sanitize_text(f"Notes: {notes}"))
            y = pdf.get_y() + 2

    pdf.set_y(y + 3)


def generate_pdf():
    """Main function: load analyzed content and generate PDF."""
    input_file = os.path.join(TMP_DIR, "analyzed_content.json")

    if not os.path.exists(input_file):
        print("ERROR: analyzed_content.json not found. Run analyze_and_categorize.py first.")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    sections_data = data.get("sections", {})

    print("Generating PDF...")

    # Create PDF
    pdf = GlobalAINewsPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Cover page
    pdf.add_page()
    build_cover_page(pdf, sections_data)

    # Section pages
    for section_key in SECTION_ORDER:
        stories = sections_data.get(section_key, [])
        pdf.add_page()
        if section_key == "viral_video_landscape":
            build_viral_video_section(pdf, section_key, stories)
        else:
            build_section(pdf, section_key, stories)

    # Run telemetry section (appended; not part of canonical 18)
    telemetry_file = os.path.join(TMP_DIR, "run_telemetry.json")
    telemetry = {}
    if os.path.exists(telemetry_file):
        try:
            with open(telemetry_file, "r", encoding="utf-8") as f:
                telemetry = json.load(f)
        except Exception as e:
            print(f"  [telemetry] failed to load: {e}")
    pdf.add_page()
    build_telemetry_section(pdf, telemetry)

    # Save
    os.makedirs(TMP_DIR, exist_ok=True)
    pdf.output(OUTPUT_FILE)

    file_size = os.path.getsize(OUTPUT_FILE) / 1024
    total_stories = sum(len(sections_data.get(s, [])) for s in SECTION_ORDER)

    print(f"\nPDF generated: {OUTPUT_FILE}")
    print(f"  Size: {file_size:.0f} KB")
    print(f"  Pages: {pdf.page_no()}")
    print(f"  Stories: {total_stories}")

    return OUTPUT_FILE


if __name__ == "__main__":
    generate_pdf()
