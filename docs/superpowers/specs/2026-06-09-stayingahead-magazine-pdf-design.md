# StayingAhead-style Magazine PDF — Design Spec

**Date:** 2026-06-09
**Status:** Approved (design); pending implementation plan
**Owner:** daily-agent

## 1. Goal

Replace the dense, functional daily PDF with a curated **magazine** that visually
matches the reference newsletter `StayingAhead_Daily_2026_04_30.pdf`:
dark full-bleed covers, oversized bold headlines with a lime highlight behind a
key word, "Quick Take" boxes, lime-tick bullet lists, and dark callout cards.

Keep **all 19 sections** (the user's content stays; only the look changes).
Same data in, same call site — a visual rewrite of the renderer, not a pipeline
re-architecture.

Two content requirements ride along:
- Every **news** section is strictly **last-24h**.
- A **fresh remote job every day** (no repeats across runs).

## 2. Hard constraints

- **Cloud-safe rendering.** The pipeline runs unattended on a claude.ai
  scheduled agent. The renderer must add **no new system dependencies**. We stay
  on **fpdf2** (pure-Python, already proven in the cloud run). weasyprint /
  Chromium are explicitly rejected — they need cairo/pango/headless-chrome that
  the sandbox likely lacks, which would silently break the daily run.
- **Fonts must be bundled**, not system-resolved (the cloud box has no Arial).
- **Same inputs/outputs.** Reads `.tmp/analyzed_content.json` (+ the existing
  side files `youtube_content_ideas.json`). Writes
  `.tmp/ai_news_remote_jobs_<DATE>.pdf`. Called by `run_daily_pipeline.py` via
  `from tools.generate_pdf import generate_pdf` — signature unchanged.
- **Showcase never empty** ([[feedback_showcase_never_empty]]) — survives the
  24h tightening (see §6).
- Latin-1 text safety stays (fpdf2 core fonts are latin-1; bundled TTFs widen
  this but sanitisation remains for safety).

## 3. Visual system

| Token | Value |
| --- | --- |
| Ink (dark pages / text on light) | `#0D0D0D` |
| Paper (light pages) | `#FFFFFF` |
| Accent (highlight, ticks, rules) | lime `#C6F24E` |
| Muted text | `#6B6B6B` |
| Card grey (Quick Take box) | `#F0F0F1` |
| Callout dark | `#0D0D0D` (lime label + white body) |
| Page margin | 18 mm L/R, footer at 285 mm |

**Fonts** (bundled into `assets/fonts/`, OFL-licensed, committed to the repo):
- **Inter** — `Inter-Regular`, `Inter-Bold`, `Inter-Black` (UI labels, body,
  headlines). Registered in fpdf2 via `pdf.add_font()`.
- **Newsreader Italic** — serif italic for the cover's "*stay*"-style accent
  word and editorial pull-quotes.
- Registered font family names: `Inter` (with B), `InterBlack`, `Serif` (italic).

If a bundled font fails to load, fall back to fpdf2 core `Helvetica` so the run
never hard-fails on a missing glyph file (degraded look, still ships).

## 4. Page flow

1. **Cover** — dark page. Top row: triangle logo + "staying / ahead" wordmark
   left, `ISSUE NNN` + date right. Centre/lower: `TODAY'S HEADLINE` lime tag,
   the day's single biggest headline (auto-picked, see §5) in huge Inter-Black
   with one word lime-highlighted, then a 2–3 line standfirst the agent writes.
   Footer: "Five minutes. Then you are ahead." / "SENT BY daily-agent".
2. **Contents** — light page, "What we cover today." Numbered list (`01`…`19`)
   of all sections: section label + a one-line teaser (first item's headline or
   a count, e.g. "13 worldwide-remote AI roles ranked for you").
3. **19 section pages** — see §5. Sections flow continuously (a section may share
   a page or span pages); each starts with its magazine header.
4. **Closing** — dark page. "You're caught up. Now stay caught up." + the date.

**Out of scope (YAGNI):** the "Last week's drops / YouTube recap" page and the
long-form editorial. (Editorial can be added later if requested.)

## 5. Section + card anatomy

### 5.1 Section header (every section)
- Lime/grey eyebrow tag: `NN . SECTION LABEL` (e.g. `01 . REMOTE AI JOBS`).
- Big Inter-Black section title (the human label) with one accent word in a lime
  highlight box (highlight = filled lime rect drawn behind the word, ink text on
  top — the signature StayingAhead move).
- Thin one-line section description (the existing `SECTION_CONFIG[...].desc`,
  trimmed).

### 5.2 Generic story card (most sections)
Input item: `{title, summary, source, url, relevance, published|posted}`.
- **Headline** — Inter-Bold, ink.
- **Quick Take** — grey box (`#F0F0F1`) with lime left-bar: the `summary`
  (the existing summary/angle split is preserved — angle rendered emphasised).
- **Meta line** — muted: `source` · date · ★ relevance (stars from `relevance`).
- **Link** — `url` as a muted clickable line.
- Cards stack; auto page-break with header continuation.

### 5.3 Dark callout card (per section, optional)
A `#0D0D0D` box with a lime label (`THE BIG PICTURE` / `WHY IT MATTERS` /
`WHAT TO WATCH`) + white body. Populated from an agent-written
`section_takeaway` if present in the section payload; **omitted if absent**
(no fabricated callouts). This is additive and degrades cleanly.

### 5.4 Special renderers (restyled, data contract unchanged)
- **Remote Jobs** (`remote_jobs`): top-ranked **spotlight** card (large, lime
  framed) — `title` @ `company`, `salary`, ★`relevance`, `matched_skills` as
  lime chips, `summary`, apply `url`. Below: the rest as a compact ranked list.
  The spotlight job is always one **not shown on a previous day** (see §6).
- **Benchmarks** (`ai_model_benchmarks`): dark table — columns
  `Task | Best | Runner-up | Benchmark` from `category / best / runner_up /
  benchmark_name`. Benchmark-news cards below.
- **YouTube Ideas** (`youtube_content_ideas`, from `youtube_content_ideas.json`
  → `{ideas:[{title, hook, why_10m, thumbnail, outline[]}]}`): 3 idea cards,
  each title + "Hook (8s)" + why-it-hits-10M + thumbnail concept + 5-beat
  outline as lime-tick list.
- **Viral Video** (`viral_video_landscape`): per-video cards
  (`title / channel / format / url / summary`), **no view counts**, "no new
  viral this period" note if empty.
- **Instagram Reel** (`instagram_viral_reels`): India + Global reel cards
  (`title / username / hashtag / url / summary`), "no new reel" note if empty.

All special renderers keep their current input fields (verified against
`.tmp/analyzed_content.json`): jobs carry `company/salary/matched_skills/
strong_match/title_role_hit`; benchmarks carry `category/best/runner_up/
benchmark_name/standings`; reels carry `username/hashtag/like_count/
comment_count/play_count/engagement`; videos carry `channel/format/views/
video_id`.

### 5.5 Cover headline auto-pick
Pick the highest-`relevance` story across the priority news sections
(global_ai_news, anthropic_claude_news, new_ai_tools, indian_ai_industry,
ai_business_automation). Title → cover headline; agent `summary` → standfirst.
One salient word in the headline gets the lime highlight (longest non-stopword,
deterministic). If no story qualifies, fall back to a generic dated headline.

## 6. Content rules

How the pipeline works today (verified):
- `analyze_and_categorize.py` main pass already surfaces **only last-24h** news
  (`NEWS_FRESH_HOURS = 24`); older RSS items stay in an unrouted pool.
- `dedupe_and_backfill.py` then **widens** thin sections (below `SECTION_MIN`)
  by pulling from that pool — and the pool contains items **older than 24h**
  (up to ~7 days). This widening is the only thing that breaks strict-24h.
- `DEDUP_EXEMPT = {ai_model_benchmarks, product_showcase_opportunities}` already
  protects the standings table and the must-never-empty showcase.
- **Job dedup is already implemented** — `scrape_jobs.py` filters
  `recently_seen_urls(JOBS_SEEN_DAYS=7)` (backfilling only if below
  `JOBS_MIN_POOL=15`) and `job_match.py` records surfaced roles via
  `record_shown`. So "a new remote job every day" already holds; this is
  **verify-only**, no new wiring.

Changes required:
- **Strict 24h for news.** In `dedupe_and_backfill.py`, gate the min-3 backfill
  candidate loop with a 24h freshness check (reuse `_within_hours` /
  `NEWS_FRESH_HOURS` from `analyze_and_categorize`). Net effect: backfill may
  still de-duplicate and re-bucket, but it will **only add items published
  within the last 24h**. Niche sections (Quantum / RSI) may fall below
  `SECTION_MIN` — acceptable per the user's explicit "24h only" instruction,
  which overrides the CLAUDE.md "widen to ≤7 days" default.
- **Exemptions preserved:** `product_showcase_opportunities` (deadline-driven,
  never empty) and `ai_model_benchmarks` (standings snapshot) stay in
  `DEDUP_EXEMPT` and are untouched by the 24h gate. `remote_jobs` keeps its own
  existing dedup/backfill (not RSS-pool based).
- Empty news section → the renderer prints a small "No new items in the last
  24h" note (keeps the magazine rhythm; never a blank page).

## 7. Files touched

- `tools/generate_pdf.py` — **rewritten** as the magazine renderer (cover,
  contents, section header, generic card, callout, restyled special renderers,
  closing). The bulk of the work.
- `assets/fonts/` — **new**; bundled Inter + Newsreader Italic TTFs (committed).
- `tools/dedupe_and_backfill.py` — **small change**: 24h freshness gate on the
  min-3 backfill candidate loop (§6).
- No change needed to job dedup (already wired) or `run_daily_pipeline.py`
  (the call site `from tools.generate_pdf import generate_pdf` is unchanged).

## 8. Verification

- **Smoke render:** run `generate_pdf()` against the committed
  `.tmp/analyzed_content.json` sample; assert a PDF is produced and page count
  is sane (≥ 22 pages: cover + contents + 19 sections + closing).
- **Font load:** assert bundled fonts register; force-fallback path tested by
  temporarily renaming a font file (renderer must not crash).
- **Empty-section path:** run with a section emptied; assert the "no new items"
  note renders and no page is blank.
- **Job dedup:** run twice with a seeded `data/jobs_seen.json`; assert the
  spotlight differs and previously-seen URLs are filtered.
- **Visual check:** open the PDF; compare cover, a section page, and closing
  against the reference for layout fidelity.
- No new top-level imports beyond what's already in `requirements.txt` (fpdf2,
  matplotlib, Pillow). Confirm `weasyprint` is **not** introduced.

## 9. Risks

- **Font fidelity** — Inter/Newsreader approximate StayingAhead's exact faces;
  acceptable, and swappable later by dropping different TTFs in `assets/fonts/`.
- **24h thinness** — strict 24h may leave some niche sections sparse; mitigated
  by the "no new items" note and the showcase/jobs exemptions.
- **fpdf2 layout cost** — manual coordinate math for highlight boxes; mitigated
  by small reusable helpers (`highlight_text`, `card_box`, `callout`).
