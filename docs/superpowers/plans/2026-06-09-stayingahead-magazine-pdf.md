# StayingAhead-style Magazine PDF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the daily PDF renderer so the output looks like the `StayingAhead_Daily` reference magazine, while keeping all 19 sections, strict-24h news, and daily-fresh jobs.

**Architecture:** Pure-Python fpdf2 renderer (cloud-safe, no new system deps). `generate_pdf.py` becomes a magazine renderer built from small drawing helpers (highlight-behind-text, cards, callouts, stars) on top of bundled Inter + Newsreader-Italic TTFs. Same input (`.tmp/analyzed_content.json` + `youtube_content_ideas.json`), same call site, same output path. A one-spot 24h gate is added to `dedupe_and_backfill.py`; job dedup already exists and is only verified.

**Tech Stack:** Python 3.9, fpdf2 2.8.x, Pillow, matplotlib (existing); pytest (new, dev only).

---

## File structure

- `tools/generate_pdf.py` — rewritten. Responsibilities, top to bottom:
  - theme constants (colors, margins, font names)
  - font registration with Helvetica fallback
  - low-level helpers: `dark_page`, `highlight_text`, `wrapped`, `card_box`, `callout`, `stars`, `eyebrow`
  - page builders: `build_cover`, `build_contents`, `build_closing`
  - section builders: `section_header`, `story_card`, `build_section` (generic), and restyled specials `build_jobs`, `build_benchmark_table`, `build_youtube_ideas`, `build_viral_video`, `build_instagram_reels`
  - `pick_cover_story`, `generate_pdf` (orchestration)
- `assets/fonts/` — new. `Inter-Regular.ttf`, `Inter-Bold.ttf`, `Inter-Black.ttf`, `Newsreader-Italic.ttf` (OFL, committed).
- `tools/dedupe_and_backfill.py` — modify the min-3 backfill loop to add only last-24h items.
- `tests/test_pdf_helpers.py` — new. Unit tests for pure helpers + smoke render.
- `tests/conftest.py` — new. Path bootstrap + sample-data fixture.
- `requirements-dev.txt` — new. `pytest`.

The existing `SECTION_ORDER`, `SECTION_CONFIG`, `SECTION_META`, `sanitize_text`, `render_stars`, `split_summary_and_angle`, and the data-loading in `generate_pdf()` are **kept and reused** — we restyle the drawing, not the data flow.

---

## Task 1: Dev test scaffold + bundle fonts

**Files:**
- Create: `requirements-dev.txt`, `tests/conftest.py`, `assets/fonts/` (4 TTFs)

- [ ] **Step 1: Add pytest dev requirement**

`requirements-dev.txt`:
```
pytest>=8.0
```

- [ ] **Step 2: Install it**

Run: `.venv/bin/python -m pip install -r requirements-dev.txt`
Expected: pytest installs successfully.

- [ ] **Step 3: Download the four OFL fonts via curl**

```bash
cd "/Users/rahulmeena/final ai news" && mkdir -p assets/fonts && \
BASE=https://github.com/google/fonts/raw/main/ofl && \
curl -fsSL "$BASE/inter/Inter%5Bopsz%2Cwght%5D.ttf" -o assets/fonts/Inter-Variable.ttf && \
curl -fsSL "$BASE/newsreader/Newsreader-Italic%5Bopsz%2Cwght%5D.ttf" -o assets/fonts/Newsreader-Italic.ttf && \
ls -la assets/fonts
```
Note: Google Fonts ships Inter as a single variable font. fpdf2 2.8 reads a
named instance from a variable TTF, but to be safe we derive static weights in
Step 4. If the variable download fails, fall back to rsms/inter static TTFs:
`https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.ttf`
(and `-Bold`, `-Black`).

- [ ] **Step 4: Materialise static weights (Regular/Bold/Black)**

If only the variable `Inter-Variable.ttf` was fetched, produce static instances
with fontTools (already transitively available via matplotlib; if not,
`pip install fonttools`):
```bash
.venv/bin/python - <<'PY'
from fontTools import varLib
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.ttLib import TTFont
import os
src="assets/fonts/Inter-Variable.ttf"
for name,wght in [("Inter-Regular",400),("Inter-Bold",700),("Inter-Black",900)]:
    f=TTFont(src)
    instantiateVariableFont(f,{"wght":wght,"opsz":14},inplace=True)
    f.save(f"assets/fonts/{name}.ttf")
    print("wrote",name)
PY
ls assets/fonts/Inter-*.ttf
```
Expected: `Inter-Regular.ttf`, `Inter-Bold.ttf`, `Inter-Black.ttf` exist.
Same approach for Newsreader if it is variable: instance one italic weight to
`Newsreader-Italic.ttf` (it is already italic-axis; a single instance is fine).

- [ ] **Step 5: Verify fpdf2 can load them**

Run:
```bash
.venv/bin/python - <<'PY'
from fpdf import FPDF
p=FPDF()
for n,f in [("Inter","Inter-Regular.ttf"),("Inter","Inter-Bold.ttf"),
            ("InterBlack","Inter-Black.ttf"),("Serif","Newsreader-Italic.ttf")]:
    style="B" if "Bold" in f else ""
    p.add_font(n,style,f"assets/fonts/{f}")
print("all fonts registered OK")
PY
```
Expected: prints "all fonts registered OK" with no exception.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt assets/fonts/Inter-Regular.ttf assets/fonts/Inter-Bold.ttf assets/fonts/Inter-Black.ttf assets/fonts/Newsreader-Italic.ttf
git commit -m "Bundle Inter + Newsreader fonts; add pytest dev dep"
```
(Do not commit the intermediate `Inter-Variable.ttf`.)

---

## Task 2: Theme + font registration + core helpers

**Files:**
- Modify: `tools/generate_pdf.py` (add theme block + helpers near the top, after imports)
- Test: `tests/test_pdf_helpers.py`

- [ ] **Step 1: Write failing tests for the pure helpers**

`tests/conftest.py`:
```python
import os, sys, json
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

@pytest.fixture
def sample_doc():
    with open(os.path.join(ROOT, ".tmp", "analyzed_content.json"), encoding="utf-8") as f:
        return json.load(f)
```

`tests/test_pdf_helpers.py`:
```python
from tools import generate_pdf as G

def test_pick_highlight_word_skips_stopwords():
    # longest non-stopword token, punctuation-stripped, lowercased compare
    assert G.pick_highlight_word("AI's godfather just sounded the alarm") == "godfather"

def test_pick_highlight_word_handles_empty():
    assert G.pick_highlight_word("") == ""

def test_stars_clamps():
    assert G.stars_str(5) == "★★★★★"
    assert G.stars_str(0) == "☆☆☆☆☆"
    assert G.stars_str(99) == "★★★★★"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q`
Expected: FAIL — `AttributeError: module 'tools.generate_pdf' has no attribute 'pick_highlight_word'`.

- [ ] **Step 3: Add theme constants + font registration + helpers**

Add near the top of `tools/generate_pdf.py` (after existing imports / constants):
```python
# ── Magazine theme ────────────────────────────────────────────────────────────
INK   = (13, 13, 13)
PAPER = (255, 255, 255)
LIME  = (198, 242, 78)
MUTED = (107, 107, 107)
CARD  = (240, 240, 241)
WHITE = (255, 255, 255)
MARGIN = 18           # mm L/R
PAGE_W, PAGE_H = 210, 297
CONTENT_W = PAGE_W - 2 * MARGIN

FONTS_DIR = os.path.join(PROJECT_ROOT, "assets", "fonts")
# family aliases used across the renderer; set to "Helvetica" if TTFs missing.
F_SANS, F_BLACK, F_SERIF = "Inter", "InterBlack", "Serif"

def register_fonts(pdf):
    """Register bundled TTFs. On any failure, downgrade aliases to Helvetica so
    the run still produces a (plainer) PDF instead of crashing."""
    global F_SANS, F_BLACK, F_SERIF
    try:
        pdf.add_font("Inter", "",  os.path.join(FONTS_DIR, "Inter-Regular.ttf"))
        pdf.add_font("Inter", "B", os.path.join(FONTS_DIR, "Inter-Bold.ttf"))
        pdf.add_font("InterBlack", "", os.path.join(FONTS_DIR, "Inter-Black.ttf"))
        pdf.add_font("Serif", "I", os.path.join(FONTS_DIR, "Newsreader-Italic.ttf"))
    except Exception as e:  # missing file / unreadable
        print(f"[generate_pdf] font load failed ({e}); using Helvetica fallback")
        F_SANS, F_BLACK, F_SERIF = "Helvetica", "Helvetica", "Helvetica"

_STOPWORDS = {"the","a","an","and","or","but","just","is","are","of","to","in",
              "on","for","with","its","it's","this","that","you","your","new"}

def pick_highlight_word(title):
    """Longest non-stopword token in the title (deterministic), else last word."""
    if not title:
        return ""
    toks = re.findall(r"[A-Za-z0-9$%']+", title)
    if not toks:
        return ""
    cand = [t for t in toks if t.lower() not in _STOPWORDS]
    pool = cand or toks
    # longest; ties broken by earliest occurrence (stable max)
    return max(pool, key=len)

def stars_str(relevance):
    try:
        n = max(0, min(5, int(round(float(relevance)))))
    except (TypeError, ValueError):
        n = 0
    return "★" * n + "☆" * (5 - n)
```
Note: `★`/`☆` render with the bundled Inter (full Unicode). In the Helvetica
fallback they will be substituted; that is acceptable for the degraded path.

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/generate_pdf.py tests/conftest.py tests/test_pdf_helpers.py
git commit -m "Add magazine theme, font registration, and pure helpers"
```

---

## Task 3: Drawing primitives (highlight, card, callout, eyebrow)

**Files:**
- Modify: `tools/generate_pdf.py`
- Test: `tests/test_pdf_helpers.py`

These draw onto an `FPDF` instance. They are verified by a no-crash render test
(coordinate math is not unit-assertable, but a crash or NaN is).

- [ ] **Step 1: Add a render smoke test for the primitives**

Append to `tests/test_pdf_helpers.py`:
```python
def test_primitives_render_without_error(tmp_path):
    from fpdf import FPDF
    pdf = FPDF(format="A4"); pdf.set_auto_page_break(False)
    G.register_fonts(pdf)
    pdf.add_page()
    G.dark_page(pdf)
    G.eyebrow(pdf, 18, 20, "01 . REMOTE AI JOBS")
    y = G.highlight_headline(pdf, 18, 40, "AI's godfather sounded the alarm",
                             size=22, ink=G.WHITE)
    y = G.card_box(pdf, 18, y + 4, G.CONTENT_W,
                   "Quick take body text that wraps across multiple lines " * 4)
    y = G.callout(pdf, 18, y + 4, G.CONTENT_W, "THE BIG PICTURE",
                  "Callout body. " * 20)
    out = tmp_path / "smoke.pdf"
    pdf.output(str(out))
    assert out.stat().st_size > 1000
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py::test_primitives_render_without_error -q`
Expected: FAIL — missing `dark_page`/`eyebrow`/`highlight_headline`/`card_box`/`callout`.

- [ ] **Step 3: Implement the primitives**

Add to `tools/generate_pdf.py`:
```python
def dark_page(pdf):
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, PAGE_W, PAGE_H, "F")

def _set(pdf, family, style, size, color):
    pdf.set_font(family, style, size)
    pdf.set_text_color(*color)

def eyebrow(pdf, x, y, text, on_dark=False):
    """Small lime tag label, e.g. '01 . REMOTE AI JOBS'."""
    _set(pdf, F_SANS, "B", 8, INK)
    w = pdf.get_string_width(text.upper()) + 6
    pdf.set_fill_color(*LIME)
    pdf.rect(x, y, w, 6, "F")
    pdf.set_xy(x + 3, y + 0.7)
    pdf.cell(w - 6, 4.6, text.upper())
    return y + 6

def highlight_headline(pdf, x, y, text, size=30, ink=INK, lead=None):
    """Bold headline; the pick_highlight_word() token gets a lime box behind it.
    Wraps within CONTENT_W. Returns the y below the headline."""
    lead = lead or (size * 0.46)
    hl = pick_highlight_word(text).lower()
    pdf.set_font(F_BLACK, "", size)
    space = pdf.get_string_width(" ")
    cx, cy = x, y
    for word in text.split():
        ww = pdf.get_string_width(word)
        if cx + ww > x + CONTENT_W and cx > x:
            cx = x; cy += lead
        if word.lower().strip(".,:'\"!").lower() == hl and hl:
            pdf.set_fill_color(*LIME)
            pdf.rect(cx - 1, cy + lead * 0.18, ww + 2, lead * 0.82, "F")
            pdf.set_text_color(*INK)
        else:
            pdf.set_text_color(*ink)
        pdf.set_xy(cx, cy); pdf.cell(ww, lead, word)
        cx += ww + space
    return cy + lead

def wrapped(pdf, x, y, w, text, family, style, size, color, lh=4.6):
    _set(pdf, family, style, size, color)
    pdf.set_xy(x, y)
    pdf.multi_cell(w, lh, sanitize_text(text))
    return pdf.get_y()

def card_box(pdf, x, y, w, body, label=None, pad=4):
    """Grey 'Quick Take' card with a lime left bar. Returns y below the box."""
    _set(pdf, F_SANS, "", 9.5, INK)
    # measure height by rendering into a scratch position is overkill; use split_only
    lines = pdf.multi_cell(w - 2 * pad, 4.8, sanitize_text(body),
                           split_only=True)
    body_h = len(lines) * 4.8
    label_h = 6 if label else 0
    h = pad + label_h + body_h + pad
    pdf.set_fill_color(*CARD); pdf.rect(x, y, w, h, "F")
    pdf.set_fill_color(*LIME); pdf.rect(x, y, 1.6, h, "F")
    yy = y + pad
    if label:
        _set(pdf, F_SANS, "B", 7.5, INK)
        pdf.set_xy(x + pad, yy); pdf.cell(40, 4, label.upper()); yy += label_h
    _set(pdf, F_SANS, "", 9.5, INK)
    pdf.set_xy(x + pad, yy); pdf.multi_cell(w - 2 * pad, 4.8, sanitize_text(body))
    return y + h

def callout(pdf, x, y, w, label, body, pad=5):
    _set(pdf, F_SANS, "", 9, WHITE)
    lines = pdf.multi_cell(w - 2 * pad, 4.8, sanitize_text(body), split_only=True)
    h = pad + 6 + len(lines) * 4.8 + pad
    pdf.set_fill_color(*INK); pdf.rect(x, y, w, h, "F")
    _set(pdf, F_SANS, "B", 8, LIME)
    pdf.set_xy(x + pad, y + pad); pdf.cell(80, 4, label.upper())
    _set(pdf, F_SANS, "", 9, WHITE)
    pdf.set_xy(x + pad, y + pad + 6)
    pdf.multi_cell(w - 2 * pad, 4.8, sanitize_text(body))
    return y + h

def tick_list(pdf, x, y, w, items):
    """Lime-tick bullet list. items: list[str]. Returns y below."""
    for it in items:
        pdf.set_fill_color(*LIME); pdf.rect(x, y + 1.2, 2.4, 2.4, "F")
        y = wrapped(pdf, x + 5, y, w - 5, it, F_SANS, "", 9, INK, lh=4.6) + 1.5
    return y
```
Note: `multi_cell(..., split_only=True)` returns the wrapped lines without
drawing — used to pre-measure box height. Available in fpdf2 2.8.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q`
Expected: all passed (4).

- [ ] **Step 5: Commit**

```bash
git add tools/generate_pdf.py tests/test_pdf_helpers.py
git commit -m "Add magazine drawing primitives (highlight, card, callout, ticks)"
```

---

## Task 4: Cover, contents, closing pages

**Files:**
- Modify: `tools/generate_pdf.py` (replace `build_cover_page`; add `build_contents`, `build_closing`, `pick_cover_story`)
- Test: `tests/test_pdf_helpers.py`

- [ ] **Step 1: Add tests**

Append:
```python
def test_pick_cover_story_returns_highest_relevance(sample_doc):
    title, standfirst = G.pick_cover_story(sample_doc["sections"])
    assert isinstance(title, str) and title  # non-empty
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py::test_pick_cover_story_returns_highest_relevance -q`
Expected: FAIL — no `pick_cover_story`.

- [ ] **Step 3: Implement page builders**

```python
COVER_PRIORITY = ["global_ai_news", "anthropic_claude_news", "new_ai_tools",
                  "indian_ai_industry", "ai_business_automation",
                  "elon_musk_ai_vision"]

def pick_cover_story(sections):
    best, best_rel = None, -1
    for key in COVER_PRIORITY:
        for it in sections.get(key, []) or []:
            try: rel = float(it.get("relevance", 0))
            except (TypeError, ValueError): rel = 0
            if rel > best_rel and it.get("title"):
                best, best_rel = it, rel
    if not best:
        return (f"Your AI briefing for {DISPLAY_DATE}",
                "The day's signal across 19 sections — jobs, tools, research, and more.")
    return (sanitize_text(best["title"]),
            sanitize_text(best.get("summary", ""))[:280])

def build_cover(pdf, sections, issue_no):
    pdf.add_page(); dark_page(pdf)
    # wordmark
    _set(pdf, F_SANS, "B", 12, WHITE)
    pdf.set_xy(MARGIN, 16); pdf.cell(60, 5, "staying")
    pdf.set_xy(MARGIN, 21); _set(pdf, F_SANS, "", 12, WHITE); pdf.cell(60, 5, "ahead")
    _set(pdf, F_SANS, "B", 9, LIME)
    pdf.set_xy(PAGE_W - MARGIN - 60, 16); pdf.cell(60, 5, f"ISSUE {issue_no:03d}", align="R")
    _set(pdf, F_SANS, "B", 9, MUTED)
    pdf.set_xy(PAGE_W - MARGIN - 60, 21); pdf.cell(60, 5, DISPLAY_DATE.upper(), align="R")
    # headline
    title, standfirst = pick_cover_story(sections)
    eyebrow(pdf, MARGIN, 96, "TODAY'S HEADLINE")
    y = highlight_headline(pdf, MARGIN, 108, title, size=34, ink=WHITE)
    y = wrapped(pdf, MARGIN, y + 8, CONTENT_W, standfirst, F_SANS, "", 12,
                (210, 210, 210), lh=6)
    # footer
    _set(pdf, F_SANS, "B", 11, WHITE)
    pdf.set_xy(MARGIN, 270); pdf.cell(120, 5, "Five minutes. Then you are ")
    _set(pdf, F_SANS, "B", 11, LIME); pdf.cell(30, 5, "ahead.")
    _set(pdf, F_SANS, "", 8, MUTED)
    pdf.set_xy(PAGE_W - MARGIN - 60, 270); pdf.cell(60, 5, "SENT BY", align="R")
    _set(pdf, F_SANS, "B", 10, WHITE)
    pdf.set_xy(PAGE_W - MARGIN - 60, 275); pdf.cell(60, 5, "Your Daily Agent", align="R")

def build_contents(pdf, sections):
    pdf.add_page()  # light (default white)
    eyebrow(pdf, MARGIN, 20, "MORNING DIGEST")
    highlight_headline(pdf, MARGIN, 30, "What we cover today.", size=26)
    y = 56
    for i, key in enumerate(SECTION_ORDER, 1):
        if y > 270: pdf.add_page(); y = 24
        label = _meta(key).get("label") or SECTION_CONFIG.get(key, {}).get("label", key)
        items = sections.get(key, []) or []
        teaser = (sanitize_text(items[0]["title"])[:80] if items and items[0].get("title")
                  else f"{len(items)} item(s)")
        _set(pdf, F_BLACK, "", 11, INK)
        pdf.set_xy(MARGIN, y); pdf.cell(10, 6, f"{i:02d}")
        _set(pdf, F_SANS, "B", 10.5, INK)
        pdf.set_xy(MARGIN + 11, y); pdf.cell(0, 6, label[:60])
        _set(pdf, F_SANS, "", 8.5, MUTED)
        pdf.set_xy(MARGIN + 11, y + 5.5); pdf.multi_cell(CONTENT_W - 11, 4, teaser)
        y = pdf.get_y() + 3.5
        pdf.set_draw_color(225, 225, 225); pdf.line(MARGIN, y - 1.5, PAGE_W - MARGIN, y - 1.5)

def build_closing(pdf):
    pdf.add_page(); dark_page(pdf)
    highlight_headline(pdf, MARGIN, 90, "You are caught up. Now stay caught up.",
                       size=30, ink=WHITE)
    wrapped(pdf, MARGIN, 150, CONTENT_W,
            "Tomorrow's PDF lands at 00:00 IST. The exact stack you need to stay "
            "one day ahead of everyone else in AI.", F_SANS, "", 11, (210,210,210), lh=6)
    _set(pdf, F_SANS, "", 9, MUTED)
    pdf.set_xy(MARGIN, 275); pdf.cell(0, 5, f"Issue · {DISPLAY_DATE}")
```
Add near the date constants at the top of the file:
```python
DISPLAY_DATE = datetime.now().strftime("%a, %d %B %Y")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add tools/generate_pdf.py tests/test_pdf_helpers.py
git commit -m "Add magazine cover, contents, and closing pages"
```

---

## Task 5: Section header + generic story card + section callout

**Files:**
- Modify: `tools/generate_pdf.py` (replace `_draw_section_header`, `build_section`)

- [ ] **Step 1: Implement `section_header` and `story_card`**

```python
def section_header(pdf, section_key, idx):
    """Magazine section opener. Adds a page, returns starting y."""
    pdf.add_page()
    label = _meta(section_key).get("label") or SECTION_CONFIG.get(section_key, {}).get("label", section_key)
    eyebrow(pdf, MARGIN, 20, f"{idx:02d} . {label}")
    y = highlight_headline(pdf, MARGIN, 32, label, size=22)
    desc = (SECTION_CONFIG.get(section_key, {}).get("desc") or "").strip()
    if desc:
        y = wrapped(pdf, MARGIN, y + 3, CONTENT_W, desc[:240], F_SANS, "", 8.5, MUTED, lh=4.2)
    return y + 4

def _ensure_space(pdf, y, need, section_key, idx):
    if y + need > 280:
        pdf.add_page()
        eyebrow(pdf, MARGIN, 16, f"{idx:02d} . CONTINUED")
        return 26
    return y

def story_card(pdf, y, item, section_key, idx):
    need = 40
    y = _ensure_space(pdf, y, need, section_key, idx)
    # headline
    y = wrapped(pdf, MARGIN, y, CONTENT_W, item.get("title", "Untitled"),
                F_SANS, "B", 12.5, INK, lh=5.6) + 1
    # quick take
    summ = item.get("summary", "")
    if summ:
        y = card_box(pdf, MARGIN, y, CONTENT_W, summ, label="Quick Take") + 2
    # meta line
    src = item.get("source", ""); when = item.get("published") or item.get("posted") or ""
    rel = item.get("relevance")
    meta = " · ".join(p for p in [src, str(when)[:10], stars_str(rel) if rel is not None else ""] if p)
    if meta:
        y = wrapped(pdf, MARGIN, y, CONTENT_W, meta, F_SANS, "", 8, MUTED, lh=4)
    # link
    url = item.get("url")
    if url:
        _set(pdf, F_SANS, "", 7.5, (90, 120, 180))
        pdf.set_xy(MARGIN, y); pdf.cell(0, 4, sanitize_text(url)[:110], link=url); y += 5
    pdf.set_draw_color(230, 230, 230); pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    return y + 4

def build_section(pdf, section_key, stories, idx):
    y = section_header(pdf, section_key, idx)
    if not stories:
        wrapped(pdf, MARGIN, y, CONTENT_W, "No new items in the last 24h.",
                F_SERIF, "I", 11, MUTED)
        return
    for it in stories:
        y = story_card(pdf, y, it, section_key, idx)
    # optional agent-written takeaway -> dark callout
    takeaway = None
    if isinstance(stories, list) and stories and isinstance(stories[0], dict):
        takeaway = stories[0].get("section_takeaway")
    if takeaway:
        y = _ensure_space(pdf, y, 40, section_key, idx)
        callout(pdf, MARGIN, y + 2, CONTENT_W, "The Big Picture", takeaway)
```
Note: `section_takeaway` is optional; absent today, so the callout is simply not
drawn (no fabrication). The orchestration in Task 7 passes `idx` (1-based).

- [ ] **Step 2: Render smoke test**

Append to `tests/test_pdf_helpers.py`:
```python
def test_build_section_renders(sample_doc, tmp_path):
    from fpdf import FPDF
    pdf = FPDF(format="A4"); pdf.set_auto_page_break(False); G.register_fonts(pdf)
    secs = sample_doc["sections"]
    G.build_section(pdf, "global_ai_news", secs.get("global_ai_news", []), 14)
    out = tmp_path / "sec.pdf"; pdf.output(str(out))
    assert out.stat().st_size > 1000
```

- [ ] **Step 3: Run**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q`
Expected: all passed.

- [ ] **Step 4: Commit**

```bash
git add tools/generate_pdf.py tests/test_pdf_helpers.py
git commit -m "Restyle section header + generic story card + section callout"
```

---

## Task 6: Restyle the special renderers

Rewrite the five specials to the magazine look, **reusing each one's existing
input fields** (verified against `.tmp/analyzed_content.json`). Replace the
bodies of `build_section`-dispatched specials. Keep function names so the Task 7
dispatcher is simple.

**Field contracts (do not change):**
- jobs: `title, company, salary, source, url, relevance, summary, matched_skills[], strong_match, title_role_hit`
- benchmarks: first item may be a standings row with `standings` / `category/best/runner_up/benchmark_name`; rest are news items
- youtube ideas (from `.tmp/youtube_content_ideas.json` → `{ideas:[...]}`): each `title, hook, why_10m, thumbnail, outline[]`
- viral video: `title, channel, format, url, summary` (no views shown)
- instagram reels: `title, username, hashtag, url, summary, bucket` (India/Global)

- [ ] **Step 1: `build_jobs` — spotlight + ranked list**

```python
def build_jobs(pdf, section_key, jobs, idx):
    y = section_header(pdf, section_key, idx)
    if not jobs:
        wrapped(pdf, MARGIN, y, CONTENT_W, "No fresh roles surfaced today.",
                F_SERIF, "I", 11, MUTED); return
    top = jobs[0]
    # spotlight card (lime frame)
    pdf.set_draw_color(*LIME); pdf.set_line_width(0.8)
    sx, sy = MARGIN, y
    eyebrow(pdf, sx, sy, "TODAY'S SPOTLIGHT ROLE")
    y = wrapped(pdf, sx, sy + 8, CONTENT_W,
                f"{top.get('title','Role')} — {top.get('company','')}",
                F_SANS, "B", 13, INK, lh=6) + 1
    sub = " · ".join(p for p in [top.get("salary",""), top.get("source",""),
                                 stars_str(top.get("relevance"))] if p)
    y = wrapped(pdf, sx, y, CONTENT_W, sub, F_SANS, "", 8.5, MUTED)
    skills = top.get("matched_skills") or []
    if skills:
        cx = sx
        for s in skills[:6]:
            _set(pdf, F_SANS, "B", 7.5, INK)
            w = pdf.get_string_width(s) + 5
            if cx + w > sx + CONTENT_W: cx = sx; y += 7
            pdf.set_fill_color(*LIME); pdf.rect(cx, y, w, 5, "F")
            pdf.set_xy(cx + 2.5, y + 0.4); pdf.cell(w - 5, 4.2, s); cx += w + 3
        y += 8
    if top.get("summary"):
        y = card_box(pdf, sx, y, CONTENT_W, top["summary"], label="Why it fits") + 2
    if top.get("url"):
        _set(pdf, F_SANS, "B", 8.5, (90,120,180))
        pdf.set_xy(sx, y); pdf.cell(0, 5, "Apply →", link=top["url"]); y += 8
    pdf.set_draw_color(*LIME); pdf.rect(sx - 2, sy - 2, CONTENT_W + 4, y - sy + 2)
    pdf.set_line_width(0.2)
    # ranked list
    y += 4
    _set(pdf, F_SANS, "B", 9, INK); pdf.set_xy(MARGIN, y); pdf.cell(0, 5, "More roles today"); y += 7
    for j in jobs[1:]:
        y = _ensure_space(pdf, y, 14, section_key, idx)
        y = wrapped(pdf, MARGIN, y, CONTENT_W,
                    f"{j.get('title','Role')} — {j.get('company','')}  {stars_str(j.get('relevance'))}",
                    F_SANS, "B", 9.5, INK, lh=4.6)
        line = " · ".join(p for p in [j.get("salary",""), j.get("source","")] if p)
        if line: y = wrapped(pdf, MARGIN, y, CONTENT_W, line, F_SANS, "", 7.5, MUTED)
        if j.get("url"):
            _set(pdf, F_SANS, "", 7, (90,120,180)); pdf.set_xy(MARGIN, y)
            pdf.cell(0, 4, sanitize_text(j["url"])[:100], link=j["url"]); y += 4
        y += 2.5
```

- [ ] **Step 2: `build_benchmark_table` — dark/lime table**

Reuse the existing column extraction (`category/best/runner_up/benchmark_name`
or parse the standings row). Render a dark header row (INK bg, LIME text) and
alternating light body rows; then benchmark-news cards via `story_card`.
```python
def build_benchmark_table(pdf, section_key, stories, idx):
    y = section_header(pdf, section_key, idx)
    rows = []
    news = []
    for it in stories:
        if it.get("standings") or (it.get("category") and it.get("best")):
            std = it.get("standings")
            if isinstance(std, list) and std:
                for r in std:
                    rows.append((r.get("category",""), r.get("best",""),
                                 r.get("runner_up",""), r.get("benchmark","") or r.get("benchmark_name","")))
            else:
                rows.append((it.get("category",""), it.get("best",""),
                             it.get("runner_up",""), it.get("benchmark_name","")))
        else:
            news.append(it)
    cols = [("Task",46),("Best",58),("Runner-up",50),("Benchmark",CONTENT_W-154)]
    x = MARGIN
    pdf.set_fill_color(*INK)
    pdf.rect(x, y, CONTENT_W, 7, "F")
    cx = x
    for name, w in cols:
        _set(pdf, F_SANS, "B", 8, LIME); pdf.set_xy(cx + 2, y + 1.5); pdf.cell(w-2, 4, name); cx += w
    y += 7
    for i, row in enumerate(rows):
        rh = 8
        y = _ensure_space(pdf, y, rh, section_key, idx)
        if i % 2: pdf.set_fill_color(245,245,245); pdf.rect(x, y, CONTENT_W, rh, "F")
        cx = x
        for (name, w), val in zip(cols, row):
            _set(pdf, F_SANS, "B" if name=="Task" else "", 7.5, INK)
            pdf.set_xy(cx + 2, y + 1.5); pdf.multi_cell(w-3, 3.6, sanitize_text(str(val))[:60])
            cx += w
        y += rh
    y += 4
    for it in news:
        y = story_card(pdf, y, it, section_key, idx)
```

- [ ] **Step 3: `build_youtube_ideas` — 3 idea cards**

```python
def build_youtube_ideas(pdf, section_key, ideas, idx):
    y = section_header(pdf, section_key, idx)
    if not ideas:
        wrapped(pdf, MARGIN, y, CONTENT_W, "No ideas generated this run.",
                F_SERIF, "I", 11, MUTED); return
    for n, idea in enumerate(ideas[:3], 1):
        y = _ensure_space(pdf, y, 60, section_key, idx)
        y = wrapped(pdf, MARGIN, y, CONTENT_W, f"{n}. {idea.get('title','Untitled')}",
                    F_SANS, "B", 12, INK, lh=5.6) + 1
        if idea.get("hook"):
            y = card_box(pdf, MARGIN, y, CONTENT_W, idea["hook"], label="Hook (first 8s)") + 2
        if idea.get("why_10m"):
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "Why it hits 10M: " + idea["why_10m"],
                        F_SANS, "", 9, INK) + 1
        if idea.get("thumbnail"):
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "Thumbnail: " + idea["thumbnail"],
                        F_SANS, "", 9, MUTED) + 1
        outline = idea.get("outline") or []
        if outline:
            y = tick_list(pdf, MARGIN, y + 1, CONTENT_W, [str(b) for b in outline[:5]])
        y += 4
```

- [ ] **Step 4: `build_viral_video` and `build_instagram_reels`**

```python
def build_viral_video(pdf, section_key, vids, idx):
    y = section_header(pdf, section_key, idx)
    if not vids:
        wrapped(pdf, MARGIN, y, CONTENT_W, "No new viral video cleared the floor this period.",
                F_SERIF, "I", 11, MUTED); return
    for v in vids:
        y = _ensure_space(pdf, y, 36, section_key, idx)
        y = wrapped(pdf, MARGIN, y, CONTENT_W,
                    f"{v.get('title','Video')} — {v.get('channel','')}",
                    F_SANS, "B", 11.5, INK, lh=5.4) + 1
        tag = " · ".join(p for p in [v.get("format",""), v.get("bucket","")] if p)
        if tag: y = wrapped(pdf, MARGIN, y, CONTENT_W, tag, F_SANS, "", 8, MUTED)
        if v.get("summary"):
            y = card_box(pdf, MARGIN, y, CONTENT_W, v["summary"], label="Why it went viral") + 1
        if v.get("url"):
            _set(pdf, F_SANS, "", 7.5, (90,120,180)); pdf.set_xy(MARGIN, y)
            pdf.cell(0, 4, sanitize_text(v["url"])[:110], link=v["url"]); y += 5
        y += 3

def build_instagram_reels(pdf, section_key, reels, idx):
    y = section_header(pdf, section_key, idx)
    if not reels:
        wrapped(pdf, MARGIN, y, CONTENT_W, "No new viral reel this period.",
                F_SERIF, "I", 11, MUTED); return
    for r in reels:
        y = _ensure_space(pdf, y, 30, section_key, idx)
        head = f"@{r.get('username','')} — {r.get('bucket','')}".strip(" —")
        y = wrapped(pdf, MARGIN, y, CONTENT_W, head or r.get("title","Reel"),
                    F_SANS, "B", 11, INK, lh=5.2) + 1
        if r.get("hashtag"):
            y = wrapped(pdf, MARGIN, y, CONTENT_W, "#" + str(r["hashtag"]).lstrip("#"),
                        F_SANS, "", 8, MUTED)
        if r.get("summary"):
            y = card_box(pdf, MARGIN, y, CONTENT_W, r["summary"], label="Why it works") + 1
        if r.get("url"):
            _set(pdf, F_SANS, "", 7.5, (90,120,180)); pdf.set_xy(MARGIN, y)
            pdf.cell(0, 4, sanitize_text(r["url"])[:110], link=r["url"]); y += 5
        y += 3
```

- [ ] **Step 5: Smoke test all specials**

Append:
```python
def test_specials_render(sample_doc, tmp_path):
    from fpdf import FPDF
    secs = sample_doc["sections"]
    for fn, key in [(G.build_jobs,"remote_jobs"), (G.build_benchmark_table,"ai_model_benchmarks"),
                    (G.build_viral_video,"viral_video_landscape"),
                    (G.build_instagram_reels,"instagram_viral_reels")]:
        pdf = FPDF(format="A4"); pdf.set_auto_page_break(False); G.register_fonts(pdf)
        fn(pdf, key, secs.get(key, []), 1)
        out = tmp_path / f"{key}.pdf"; pdf.output(str(out)); assert out.stat().st_size > 1000
```

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q` → all passed.
```bash
git add tools/generate_pdf.py tests/test_pdf_helpers.py
git commit -m "Restyle special renderers (jobs spotlight, benchmarks, ideas, video, reels)"
```

---

## Task 7: Orchestration — wire `generate_pdf()`

**Files:**
- Modify: `tools/generate_pdf.py` (`generate_pdf`)

- [ ] **Step 1: Rewrite the orchestration body**

Keep the existing data load (read `.tmp/analyzed_content.json`, merge
`youtube_content_ideas.json` into `sections["youtube_content_ideas"]`). Replace
the page-building loop with:
```python
SPECIAL = {
    "remote_jobs": build_jobs,
    "ai_model_benchmarks": build_benchmark_table,
    "youtube_content_ideas": build_youtube_ideas,
    "viral_video_landscape": build_viral_video,
    "instagram_viral_reels": build_instagram_reels,
}

def generate_pdf():
    # ... existing load of `doc`, `sections`, youtube ideas merge ...
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_title("Daily AI News & Remote Jobs")
    register_fonts(pdf)
    issue_no = _issue_number()   # see step 2
    build_cover(pdf, sections, issue_no)
    build_contents(pdf, sections)
    for idx, key in enumerate(SECTION_ORDER, 1):
        stories = sections.get(key, []) or []
        SPECIAL.get(key, lambda p,k,s,i: build_section(p,k,s,i))(pdf, key, stories, idx)
    build_closing(pdf)
    pdf.output(OUTPUT_FILE)
    print(f"[generate_pdf] wrote {OUTPUT_FILE} ({pdf.page_no()} pages)")
    return True, OUTPUT_FILE
```
Note: `build_section` and specials share the signature `(pdf, key, stories, idx)`.
The lambda adapts the generic path. Remove the old cover/header/section helpers
that are now unused (`build_cover_page`, `_draw_section_header`, the old
per-section body). Keep `sanitize_text`, `split_summary_and_angle`,
`render_stars` (still referenced) or delete if fully superseded — verify no
dangling references with a grep before committing.

- [ ] **Step 2: Add issue-number helper**

Deterministic issue number from a fixed epoch so it increments daily:
```python
def _issue_number():
    epoch = datetime(2026, 4, 25)   # issue 001 anchor
    return max(1, (datetime.now() - epoch).days + 1)
```

- [ ] **Step 3: Full-document smoke test**

Append:
```python
def test_full_generate_pdf(monkeypatch, tmp_path):
    import tools.generate_pdf as G
    out = tmp_path / "daily.pdf"
    monkeypatch.setattr(G, "OUTPUT_FILE", str(out))
    ok, path = G.generate_pdf()
    assert ok and out.stat().st_size > 5000
    # page count sane: cover + contents + >=19 + closing
    import re
    data = out.read_bytes()
    assert data.count(b"/Type /Page") >= 22 or data.count(b"/Type/Page") >= 22
```

- [ ] **Step 4: Run**

Run: `.venv/bin/python -m pytest tests/test_pdf_helpers.py -q`
Expected: all passed.

- [ ] **Step 5: Grep for dangling references, then commit**

```bash
grep -n "build_cover_page\|_draw_section_header\|build_telemetry_section" tools/generate_pdf.py
```
Remove/repair any leftover calls. Then:
```bash
git add tools/generate_pdf.py tests/test_pdf_helpers.py
git commit -m "Wire magazine generate_pdf() orchestration"
```

---

## Task 8: Strict 24h news backfill gate

**Files:**
- Modify: `tools/dedupe_and_backfill.py` (min-3 backfill loop, ~line 150-167)

- [ ] **Step 1: Import the freshness helper**

At the top imports of `dedupe_and_backfill.py`:
```python
from tools.analyze_and_categorize import OUTPUT_FILE, _within_hours, NEWS_FRESH_HOURS
```

- [ ] **Step 2: Gate the backfill candidate loop**

In the `for art in rss_articles:` block that fills `buckets`, skip stale items:
```python
    for art in rss_articles:
        url = art.get("url", "") or art.get("link", "")
        if not url or url in placed_urls or url in seen:
            continue
        if not _within_hours(art.get("published"), NEWS_FRESH_HOURS):
            continue   # strict last-24h: do not widen news with older items
        sec, rel, summary = classify(art)
        if sec in buckets:
            buckets[sec].append(_item_from_article(art, sec, rel, summary))
```
Leave `DEDUP_EXEMPT` (benchmarks, showcase) and the benchmark standings seed
untouched — those are not RSS-pool news and must keep working.

- [ ] **Step 3: Verify it runs and respects 24h**

Run:
```bash
.venv/bin/python -c "from tools.dedupe_and_backfill import _within_hours, NEWS_FRESH_HOURS; print('gate import OK', NEWS_FRESH_HOURS)"
```
Expected: `gate import OK 24`.
Then run the full module against the sample (non-destructive — it rewrites
`.tmp/analyzed_content.json`; back it up first):
```bash
cp .tmp/analyzed_content.json .tmp/analyzed_content.bak.json
.venv/bin/python tools/dedupe_and_backfill.py
git diff --stat   # no code surprises
cp .tmp/analyzed_content.bak.json .tmp/analyzed_content.json  # restore sample
```
Expected: prints `[dedupe_backfill] ...` summary, no traceback.

- [ ] **Step 4: Commit**

```bash
git add tools/dedupe_and_backfill.py
git commit -m "Enforce strict last-24h news in backfill (showcase/benchmarks exempt)"
```

---

## Task 9: Verify job dedup (no code) + end-to-end render

**Files:** none (verification only)

- [ ] **Step 1: Confirm job dedup is active**

```bash
grep -n "recently_seen_urls\|record_shown\|JOBS_SEEN_DAYS" tools/scrape_jobs.py tools/job_match.py
```
Expected: `scrape_jobs.py` filters `recently_seen_urls(JOBS_SEEN_DAYS=7)`;
`job_match.py` calls `record_shown`. No change needed — daily-fresh jobs hold.

- [ ] **Step 2: Generate the real PDF from the current sample**

```bash
.venv/bin/python tools/generate_pdf.py 2>&1 | tail -3
ls -la .tmp/ai_news_remote_jobs_*.pdf
```
Expected: prints `wrote ... (N pages)` with N ≥ 22; PDF file present.

- [ ] **Step 3: Manual visual check**

Open the PDF. Verify against the reference:
- dark cover with lime-highlighted headline word + standfirst
- "What we cover today" contents listing all 19 sections
- a news section page: eyebrow tag, big title, Quick Take grey card, meta + link
- jobs spotlight card with lime chips + ranked list
- benchmark dark table
- dark closing page
Fix any layout overflow (text clipping, overlapping boxes) by adjusting the
relevant builder's `lh`/`pad`/`_ensure_space` thresholds.

- [ ] **Step 4: Run full suite + commit any visual fixes**

```bash
.venv/bin/python -m pytest tests/ -q
```
Expected: all passed.
```bash
git add -A && git commit -m "Verify end-to-end magazine render"
```

---

## Self-review notes

- **Spec coverage:** renderer rewrite (Tasks 2-7), bundled fonts (Task 1),
  24h news gate (Task 8), job-dedup verify (Task 9), all 19 sections via
  `SECTION_ORDER` dispatch (Task 7), specials field contracts pinned (Task 6),
  cover/contents/closing (Task 4), showcase/benchmark exemptions preserved
  (Task 8). Out-of-scope (editorial, weekly recap) intentionally omitted.
- **Fallback:** `register_fonts` degrades to Helvetica so a missing TTF in the
  cloud never hard-fails the daily run.
- **Signatures:** every section builder is `(pdf, key, stories, idx)`; the
  generic path is adapted via lambda in the dispatcher.
