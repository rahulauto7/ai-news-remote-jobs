# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A daily automated pipeline that scrapes AI news + worldwide-remote AI jobs, categorizes them into
19 fixed sections, and delivers a rendered PDF to the user's Slack DM at 00:00 IST — running in the
cloud, independent of laptop state.

Repo: `https://github.com/rahulauto7/ai-news-remote-jobs` (owner was renamed from `rahulaachaaaaa`;
stale URLs in docs/prompts are a recurring breakage source).

## Commands

```bash
# One-time / idempotent setup. ALWAYS use .venv/bin/python afterwards, never system python.
./bootstrap.sh

# Full pipeline: scrape -> analyze -> dedup -> PDF. Writes .tmp/ai_news_remote_jobs_<DATE>.pdf
.venv/bin/python tools/run_daily_pipeline.py
.venv/bin/python tools/run_daily_pipeline.py --dry-run          # skip Slack send
.venv/bin/python tools/run_daily_pipeline.py --analyzer deepseek # opt into paid DeepSeek analysis
.venv/bin/python tools/run_daily_pipeline.py --no-agent          # force keyword-only categorizer

# Any single stage can be run standalone against the existing .tmp/ state:
.venv/bin/python tools/scrape_rss_feeds.py       # -> .tmp/rss_articles.json
.venv/bin/python tools/scrape_jobs.py            # -> .tmp/jobs.json, .tmp/jobs.csv
.venv/bin/python tools/job_match.py              # -> .tmp/jobs_ranked.json
.venv/bin/python tools/dedupe_and_backfill.py --sanitize-only   # re-apply strict 24h + AI-only gate
.venv/bin/python tools/generate_pdf.py           # -> .tmp/ai_news_remote_jobs_<DATE>.pdf
.venv/bin/python -m tools.recover_empty_sections quantum_ai_research ai_self_improvement_rsi

# Tests (pip install -r requirements-dev.txt first)
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pytest tests/test_pdf_helpers.py -q                              # one file
.venv/bin/python -m pytest tests/test_pdf_helpers.py::test_stars_clamps -q           # one test
.venv/bin/python -m pytest tests/ -q -k emoji                                        # by name
```

`bootstrap.sh` exists because the cloud sandbox (and some Debian hosts) ship a patched system Python
whose `setuptools` is broken — `pip install -r requirements.txt` aborts mid-build on feedparser's
`sgmllib3k` and leaves the pipeline half-installed. GitHub Actions is unaffected (`setup-python`
gives a clean 3.11). The local `.venv` is Python 3.9; CI runs 3.11 — modules use
`from __future__ import annotations` for PEP 585 generics, keep that when adding type hints.

`tests/conftest.py` puts the repo root on `sys.path`; there is no pytest config file. The
`sample_doc` fixture reads `.tmp/analyzed_content.json` and skips if absent.

## Architecture: three stages, split by network egress

This is the single most important thing to understand. **Scraping cannot run in the claude.ai cloud
sandbox** — its egress proxy 403s almost every scraper host and TLS-MITMs Python HTTPS. So the daily
run is split across three executors, each picked for what it is allowed to reach:

| Stage | Where | When | Does | Can reach |
|---|---|---|---|---|
| 1 | `.github/workflows/daily.yml` (Actions) | cron `0 17 * * *` = 22:30 IST | full pipeline: scrape → analyze → dedup → fallback PDF; publishes `.tmp/*.json` + PDF to the rolling `pipeline-state` branch; commits dedup state to `main` | everything |
| 2 | claude.ai scheduled routine (`trig_018UFpSohtbZ9fvHQRJmaPtR`) | cron `30 18 * * *` = 00:00 IST | **no scraping.** Pulls `pipeline-state`, runs AGENT ENRICHMENT on the JSON, regenerates YouTube ideas + PDF, pushes `daily/<YYYY-MM-DD>` | github.com + Anthropic API only |
| 3 | `.github/workflows/deliver.yml` (Actions) | on push to `daily/**` | uploads the real PDF + jobs.csv to the Slack DM via `files_upload_v2` | everything |

Consequences that bite if forgotten:

- Stage 1 fires **90 minutes early** to absorb GitHub's scheduled-run latency (often 30–60+ min).
- Stage 2 cannot reach `api.github.com`, so `workflow_dispatch` never works from the routine. Its
  self-recovery re-triggers Stage 1 by **git-pushing** to the `trigger-scrape` branch (`daily.yml`
  also listens `on: push` to that branch).
- Stage 2 cannot reach `slack.com` and the claude.ai Slack connector cannot attach files, so the PDF
  is *never* sent by the routine — only by `deliver.yml`. The connector is used **only** for failure
  alerts.
- `daily.yml`'s Slack alert is gated `if: failure() || cancelled()` — `cancelled()` is required
  because a cancelled job skips `failure()`-gated steps (that's how the 2026-08-06 outage went silent).
- The live routine prompt, not any file in this repo, is what Stage 2 actually executes. When you
  change the two-stage flow, update the routine via the `schedule` skill **in the same change**.

`workflows/daily_ai_news_remote.md` is the source-of-truth SOP: full step list, per-section rules,
the Stage-2 routine prompt, and a lessons-learned log. Read it before changing pipeline behavior.
`workflows/user_profile.md` is a **required runtime input** — `tools/job_match.py:92` raises
`FileNotFoundError` without it. It is human-editable: retune what surfaces in the Jobs section by
editing its weighted-skill and exclusion bullets, no code change needed (the parser depends on the
bullet format documented at the top of that file).

## Data flow and where state lives

```
.tmp/            disposable per-run artifacts (gitignored, force-added to pipeline-state)
                 rss_articles.json, jobs.json, jobs_ranked.json, hackathons.json,
                 youtube_verified.json, instagram_verified.json, ai_trends.json,
                 analyzed_content.json  <- THE central document every later stage mutates
                 youtube_content_ideas.json, youtube_section_analysis.json,
                 agent_tokens.json, run_telemetry.json, ai_news_remote_jobs_<DATE>.pdf
data/            PERSISTENT cross-run state, committed to main
                 content_seen.json  (dedup: namespaces news/youtube/instagram/trends/qrsi)
                 jobs_seen.json, usage_log.json, usage_calibration.json
```

`.tmp/analyzed_content.json` is the spine: the analyzer writes it, hackathon-merge / dedup /
sanitize / agent-enrichment all edit it **in place**, and `generate_pdf.py` renders straight from it.
There are no separate per-section "verified" files feeding the PDF — the verifiers write into
`analyzed_content.json`'s sections.

## Invariants that are easy to break

**Section order** is `SECTION_ORDER` in `tools/generate_pdf.py:114` — the cover TOC, the topic chart,
and the render loop all read it. Adding a section means touching `SECTION_CONFIG` + `SECTION_ORDER`
there, the taxonomy in `tools/analyze_and_categorize.py`, and the SOP table.

**News is strictly last-24h with no minimum floor** (user rule, 2026-06-13). A thin or empty section
on a quiet day is correct; padding it from the older 7-day pool is not. The RSS scrape still collects
~7 days but that pool is used only for dedup bookkeeping. Exceptions live in
`dedupe_and_backfill.SECTION_FRESH_HOURS`: `quantum_ai_research` and `ai_self_improvement_rsi` get
168h (niche research sections).

**The 24h gate runs twice, and the second pass is strict.** Enrichment adds and rewrites items the
pre-enrichment gate never saw, so `dedupe_and_backfill.py --sanitize-only` must run *after* agent
enrichment. Strict means an item without a provable in-window `published` ISO timestamp is dropped —
so enrichment must attach a real timestamp to every item it adds, or the item silently vanishes.

**Quantum/RSI dedup is deferred, not exempt.** Stage 1 always leaves those two sections empty;
enrichment is what populates them. So `tools/finalize_qrsi_dedup.py` runs once after dedup (a no-op
when empty) and again after enrichment (the pass that matters), against a dedicated `qrsi` namespace
so an article that appeared in `global_ai_news` yesterday is still eligible for quantum/RSI treatment.

**Never fabricate to fill a section.** Viral video/reel picks must clear real virality floors
(YouTube long ≥100K, short ≥500K, 7-day window, URL HEAD-verified; Instagram = max likes+comments in
24h). Cross-day freshness is *widen-then-note*: prefer an unseen pick, widen the search once, then
emit a `no_fresh` marker so the PDF prints "no new viral this period" — never repeat, never invent.
Same for quantum/RSI: an honest "No qualifying articles in today's pool" item beats an off-topic one.

**`Automation angle:` suffix.** Every story summary in RSS-routed AI sections ends with a sentence
starting exactly `Automation angle:`. `generate_pdf.split_summary_and_angle` splits on it to render
the callout. Exempt: `remote_jobs`, `general_news`, `youtube_content_ideas`, `viral_video_landscape`.

**Failures are non-fatal by design.** `run_daily_pipeline.step()` wraps every stage in try/except; a
dead scraper leaves a section thin but must not fail the run. Success is defined as "the PDF was
produced". The genuinely fatal conditions return `False` explicitly: every scraper failed, **zero RSS
articles** (the canonical signature of a blocked/broken run, not a quiet news day), analysis failed,
PDF failed. Don't tighten this back into an `all(results)` check.

**Modules load `.env` themselves.** Any module reading env vars calls `load_dotenv()` at import —
don't assume the orchestrator did it. Harmless no-op on Actions, where creds come from secrets.

## Analyzer paths

Three tiers, in order: `tools/agent_analyze.py` (default — Claude agent + deterministic keyword
rules, no paid API), `tools/deepseek_analyze.py` (opt-in via `--analyzer deepseek` / `ANALYZER=deepseek`,
needs `DEEPSEEK_API_KEY`), and `analyze_and_categorize.auto_categorize_fallback` (deterministic
keyword-only last resort so a PDF always ships). Passthrough sections bypass all of them:
`remote_jobs`, `youtube_content_ideas`, `ai_search_trends`, `viral_video_landscape`,
`instagram_viral_reels`.

## Cost telemetry

claude.ai does not expose subscription usage to a routine, so the PDF footer's "% of weekly limit"
is calibrated by hand: `tools/estimate_agent_tokens.py --count-tokens` writes `.tmp/agent_tokens.json`
(free `count_tokens` endpoint when `ANTHROPIC_API_KEY` is set, else a byte heuristic) →
`tools/fill_usage_log_tokens.py` copies that total into today's `data/usage_log.json` entry →
`tools/derive_usage_calibration.py` writes `data/usage_calibration.json` once 3 stable manual
before/after `/usage` samples exist, and refuses to write an unstable constant. Model list prices
live in `generate_pdf.MODEL_PRICING_PER_MTOK`; an unrecognized model is priced as Opus 5 and labeled
as such rather than silently costing $0.

## Working style

- Low-talk and direct. Skip preambles and status narration; report the file path plus one line.
- Confirm only on irreversible/destructive actions or paid API spend (DeepSeek, RapidAPI, YouTube
  quota). YouTube is the tight one: `search.list` costs 100 units/call and
  `scrape_youtube_trending.estimate_quota_units()` currently projects **8,802 of the 10,000-unit free
  daily quota per run** — adding one search query costs 100–200 units, so re-running the scraper
  manually on the same day will exhaust the quota. Check that estimate before adding queries.
- When something breaks: fix the tool, verify, then **update the SOP** in `workflows/` with what you
  learned. The lessons-learned log is what keeps the same outage from recurring — post-rename secret
  breakage has already happened four times.
- **Keep every `.md` file under 200 lines.** This one included. When a doc outgrows the limit, split
  it by concern and link out rather than letting it sprawl — long docs stop getting read and stop
  getting updated.
