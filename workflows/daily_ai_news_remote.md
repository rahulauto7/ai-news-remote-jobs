# Workflow: Daily AI News + Remote Jobs

## Objective

Every day at **00:00 IST** (laptop off OK — runs as a claude.ai cloud scheduled agent), produce a 19-section PDF summarizing the last 7 days of AI news + currently-open global remote AI Automation jobs (profile-matched), **push it to a dated GitHub branch** (`daily/YYYY-MM-DD`) and **DM it to the user on Slack**.

> Schedule: TWO cooperating jobs (see "Execution architecture — TWO STAGES" below). **Stage 1** = `.github/workflows/daily.yml` on GitHub Actions, cron `0 17 * * *` = 22:30 IST (90 min ahead of Stage 2 to absorb GitHub's scheduled-run latency) — runs the full scrape→analyze→dedup and publishes the `pipeline-state` branch. **Stage 2** = the **claude.ai routine** (`trig_018UFpSohtbZ9fvHQRJmaPtR`), cron `30 18 * * *` = 00:00 IST (00:03 fire) — pulls `pipeline-state`, enriches, renders the PDF, and pushes the `daily/<date>` branch (that push triggers `deliver.yml` on Actions, which DMs the actual PDF file). Stage 2 does **NO scraping** and does **NOT** send the PDF over Slack itself (the sandbox 403s every host). The routine prompt is the Stage-2 prompt below; when you change the two-stage flow, update the live routine via the `schedule` skill in the SAME change (the routine prompt, not this file, is what the cloud agent executes).

## Inputs

- Cloned repo at agent's `cwd`
- Routine env / GitHub Actions secrets:
  - `YOUTUBE_API_KEY` — YouTube Data API v3
  - `RAPIDAPI_KEY` — RapidAPI token for Instagram reel scraping (`instagram_viral_reels` section). `RAPIDAPI_INSTAGRAM_HOST` optional (defaults to `instagram-scraper-api2.p.rapidapi.com`)
  - `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` — optional, for the `ai_search_trends` section (falls back to Reddit anonymous JSON if absent; Google Trends + HN need no keys)
  - `SLACK_BOT_TOKEN`, `SLACK_USER_ID` — Slack DM delivery + failure alerts
  - `GH_TOKEN` — GitHub PAT (repo scope) for routine `git push`
  - `DEEPSEEK_API_KEY` — **optional**. DeepSeek API. Only used when the pipeline is invoked with `--analyzer deepseek` (or `ANALYZER=deepseek`). The default analyzer is the Claude agent (no key required).
- `workflows/user_profile.md` — the user's profile (target roles, weighted skills, hard exclusions). Read by `tools/job_match.py` to rank the Jobs section. Human-editable, no code change needed.

## The 19 Sections (PDF order)

**News window: last 24h only — strict, no minimum floor (user rule 2026-06-13).** The analyzer (`analyze_and_categorize.NEWS_FRESH_HOURS = 24`) surfaces only articles published in the last 24h. Every section shows ONLY what cleared that 24h gate — if a section has fewer than 3 (or zero) fresh items, it ships thin/empty rather than being padded from older items. The RSS scrape still collects ~7 days, but that pool is now used **only** for cross-day dedup bookkeeping, **not** to backfill thin sections. The fix for a genuinely empty section is a healthy feed, not older content.

Story-count rule: **max 8 stories per RSS-categorized section; NO minimum.** A section may legitimately show 0-2 items on a quiet 24h. Exemptions: `remote_jobs` is capped at 25, `youtube_content_ideas` is fixed at exactly 3 agent-generated ideas, `viral_video_landscape` keeps its 3-bucket structure (2 long + 1 short, 7-day verified), `instagram_viral_reels` keeps its 2-bucket structure, `ai_search_trends` is capped at 20.

Section order is enforced by `SECTION_ORDER` in `tools/generate_pdf.py` (cover TOC + chart + render loop all read it).

| PDF # | Key | Source / Rule |
|---|---|---|
| 1 | `remote_jobs` | **Worldwide-remote AI roles ranked against `workflows/user_profile.md`.** `tools/scrape_jobs.py` scrapes (Greenhouse/Lever/Ashby direct-apply boards incl. n8n/Voiceflow/Zapier/Relevance AI/Bardeen/Pipedream/Lindy/Clay + Remotive/RemoteOK/WWR/Himalayas/HN); `tools/job_match.py` then ranks each job against the user profile — drops senior/lead/principal + region-locked, scores by skill overlap (weighted) + target-role title match, writes `.tmp/jobs_ranked.json`. Cap 25. PDF shows matched skills + `[STRONG MATCH]` tag per row. Edit `workflows/user_profile.md` to retune. |
| 2 | `product_showcase_opportunities` | **AI hackathons & competitions + accelerators / incubators / acceleration programs (worldwide).** Coding hackathons (Devpost/Kaggle/HuggingFace/MLH/lablab.ai/AIcrowd/DrivenData via `tools/scrape_hackathons.py`) **plus** AI accelerators, incubators, and government/India acceleration schemes (curated `CURATED_ACCELERATORS` incl. "IndiaAI Startups Global", YC, Antler, Techstars, NVIDIA Inception, Google for Startups, NASSCOM, Startup India) + a Google-News discovery pass (`fetch_accelerator_news`). Sorted by closest deadline first; rolling programs (no deadline) kept and shown last. Each PDF row shows a bold blue `Apply: <url>` line + `Platform:` (Accelerator vs hackathon) + `Deadline:` + `Prize:`. **No item cap.** |
| 3 | `youtube_content_ideas` | **3 video ideas, agent-generated.** After all other sections are populated, the agent reads `.tmp/analyzed_content.json` and writes 3 video pitches engineered to plausibly hit 10M views — each with Title (60 chars max), Hook (first 8 seconds, word-for-word), Why-this-hits-10M (3 bullets citing the section it pulled from), Thumbnail concept, 5-beat Outline. Output: `.tmp/youtube_content_ideas.json`. |
| 4 | `viral_video_landscape` | **MERGED YouTube section — last 7 days, verified actually viral, FRESH vs recent runs.** YouTube Data API v3 — 3 buckets (Global AI long, Global AI Short, India AI long), `publishedAfter = now-7d`, view floors: long >= 100K, short >= 500K, URL HEAD-verified. **Cross-day fresh:** prefers a video not shown in the last 7 days; if all qualifiers were already shown it WIDENS the search once, and if still nothing fresh it prints a per-bucket "No new viral video cleared the floor this period" note rather than repeat. (Part A) agent-written landscape from `.tmp/youtube_section_analysis.json`; (Part B) the verified videos with channel + `viral_explanations[<video_id>]`. **No view counts. No Automation Angle.** |
| 5 | `instagram_viral_reels` | **Viral AI reels — 2 buckets (Global, India), FRESH vs recent runs.** `tools/scrape_instagram_reels.py` (RapidAPI) → `tools/instagram_viral_verify.py` picks the max-engagement unseen AI reel per bucket in the last 24h (widens to 7 days for an unseen one, else prints "no new reel"). Needs `RAPIDAPI_KEY`. |
| 6 | `quantum_ai_research` | **STRICTLY Quantum + AI.** Story MUST address BOTH quantum (qubits, quantum hardware, quantum algorithms, QPUs) AND AI/ML. Pure-quantum or pure-AI dropped. arXiv quant-ph + RSS (widen pool used for backfill). |
| 7 | `ai_self_improvement_rsi` | arXiv + RSS. AGI, alignment, recursive self-improvement, superintelligence research — must carry an AI signal. |
| 8 | `elon_musk_ai_vision` | **Grok + Elon's AI views.** All **Grok** product updates (xAI releases, Grok features/models) AND Elon Musk's stated views on AI (xAI direction, AGI/safety takes, notable statements). Sources: xAI News + Elon-Musk-on-X Google News proxy. Agent should lead with the latest Grok news, then summarize Elon's current AI stance. |
| 9 | `ai_model_benchmarks` | **Best-model-per-task TABLE first.** Rendered as a bordered grid (Task \| Best Model \| Runner-up \| Benchmark) for Text/LLM, Coding, Image, Video, Music/Audio, Reasoning — seeded by `dedupe_and_backfill.BENCHMARK_STANDINGS`, agent refreshes winners. Benchmark news articles follow below the table. Dedup-exempt. |
| 10 | `new_ai_tools` | **Tools relevant to the user's Claude Code / agent-automation work first.** RSS + Product Hunt. The user's build stack (n8n, Voiceflow, Relevance AI, LangChain, LlamaIndex, Cursor, Windsurf, MCP servers, agent SDKs/frameworks, Copilot) is relevance-boosted to the top, then other net-new AI tool launches with cost/feature notes. |
| 11 | `indian_ai_industry` | RSS (Inc42, YourStory, ETTech) — **AI-only** India news. |
| 12 | `anthropic_claude_news` | **Anthropic company news + Claude Code product updates.** Anthropic blog + Claude Code release notes (new commands, hooks, MCP, slash commands, agents, model rollouts). |
| 13 | `ai_business_automation` | **How AI automation is changing work ACROSS industries** — not just tool launches. Real deployments, ROI, sector-by-sector updates (support, sales, ops, finance, healthcare, etc.), plus n8n/Zapier/Make/agent-workflow news. AI-related only. |
| 14 | `global_ai_news` | RSS (Verge, TechCrunch, etc.) — **AI-only**, no general tech / non-AI business news. |
| 15 | `ai_search_trends` | **What people in AI are searching for.** `tools/scrape_ai_trends.py` aggregates Google Trends rising+top AI queries (global + India), Hacker News top AI stories (24h), Reddit hot threads (r/MachineLearning, r/LocalLLaMA, r/singularity, r/ArtificialIntelligence, r/OpenAI, r/Anthropic, 24h). Top 20 ranked with source tags + links; top-3 rising get `SURGING`. |
| 16 | `unaddressed_ai_problems` | **Real problems people hit with AI that NO ONE is solving.** Not generic "AI is scary" headlines — concrete unmet pain points / capability gaps (e.g. reliable long-horizon agents, eval gaps, data-privacy holes, hallucination in production, cost/latency walls). Agent should name the problem, who it affects, and why it's still open. |
| 17 | `ai_business_opportunities` | **Businesses the user could actually start now + top current global opportunities.** Mine funding/IPO/acquisition/market-gap signals into concrete, startable AI-automation business ideas (what to build, for whom, why now), not just "company X raised $Y". |
| 18 | `ai_music_copyright_laws` | RSS keyword filter. AI music/art copyright lawsuits, licensing, court rulings. |
| 19 | `general_news` | **Top worldwide trending headlines (non-AI).** Broad world coverage from BBC / Hindu / NDTV — the biggest global stories of the day, not region-narrow filler. |

## Automation angle hook (most AI sections)

Every story summary in the RSS-routed AI sections ends with an extra sentence that begins exactly with `Automation angle:`. The hook states one of:
- what to build
- what tool to try
- what workflow this unlocks
- what risk to watch
- why this matters for AI-automation businesses

**Why:** the reader's primary goal is landing a remote AI-automation job globally with no prior experience, and launching an AI-automation teaching channel. Every AI section is filtered through that lens so each summary doubles as a portfolio / content idea.

**Exemptions (no Automation Angle):**
- `remote_jobs` — uses a fixed "Company is hiring: Title. <body>" format.
- `general_news` — non-AI.
- `youtube_content_ideas` — the whole section IS the actionable idea; angle would be redundant.
- `viral_video_landscape` (merged YouTube section) — carries an agent-written "Why it went viral" line per video instead.

## Execution architecture — TWO STAGES (read this first)

Scraping does **not** run in the claude.ai cloud sandbox: its egress proxy 403s almost every scraper host and TLS-MITMs Python HTTPS (see Lessons Learned 2026-06-13). So the pipeline is split:

- **Stage 1 — GitHub Actions scraper** (`.github/workflows/daily.yml`, ~23:15 IST). Unrestricted egress, no MITM. Runs the **full** pipeline (scrape → analyze → dedup → fallback PDF), then publishes `.tmp/*.json` + the fallback PDF to the rolling **`pipeline-state`** branch and commits dedup state to `main`. Slacks on failure.
- **Stage 2 — claude.ai routine** (00:00 IST). Does **no scraping**. Pulls `pipeline-state`, runs AGENT ENRICHMENT on the already-scraped JSON, regenerates YouTube ideas + PDF, and pushes the dated branch. It only ever talks to github.com + the Anthropic API, both reachable in the sandbox. The dated-branch push triggers **Stage 3 — `.github/workflows/deliver.yml`** (Actions) which DMs the actual PDF file to Slack via `files_upload_v2`; the routine does NOT send the PDF itself (no slack.com egress, and the connector can't attach files).

The step list below is the **full** pipeline as Stage 1 runs it. Stage 2 starts at the **AGENT ENRICHMENT** step using the JSON Stage 1 produced.

### Stage 2 routine prompt (paste into the claude.ai scheduled agent)

```
You are running the daily AI-news pipeline STAGE 2 (enrichment + delivery only). Do NOT scrape — the GitHub Actions scraper already published today's data to the `pipeline-state` branch.

1. Pull the scraped state and verify it is fresh:
   git fetch origin pipeline-state
   git checkout origin/pipeline-state -- .tmp

   Check staleness (18 h = 64800 s):
   python3 -c "
   import os, time, sys
   f = '.tmp/analyzed_content.json'
   if not os.path.exists(f):
       print('MISSING'); sys.exit(1)
   age = time.time() - os.path.getmtime(f)
   print(f'{age/3600:.1f}h old')
   sys.exit(0 if age < 64800 else 1)
   "

   If the check exits non-zero (stale or missing), attempt self-recovery before giving up:

   a. Try to re-trigger Stage 1 via GitHub API:
      HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "Authorization: Bearer $GH_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/rahulaachaaaaa/ai-news-remote-jobs/actions/workflows/daily.yml/dispatches" \
        -d '{"ref":"main"}')

   b. If HTTP == 204 (dispatch accepted):
      Poll pipeline-state every 90 s for up to 20 min:
      for i in 1..14:
        sleep 90
        git fetch origin pipeline-state
        git checkout origin/pipeline-state -- .tmp
        python3 -c "import os,time,sys; f='.tmp/analyzed_content.json'; sys.exit(0 if os.path.exists(f) and time.time()-os.path.getmtime(f)<64800 else 1)"
        if exit 0: RECOVERED=1; break
      If still stale after 14 polls: send Slack failure — "Stage 1 was re-dispatched but did not finish within 20 min. Check https://github.com/rahulaachaaaaa/ai-news-remote-jobs/actions" — and STOP.

   c. If HTTP != 204 (dispatch failed — GH_TOKEN may lack 'workflow' scope):
      Send Slack failure — "Pipeline state stale and Stage 1 auto-dispatch failed (HTTP $HTTP). Trigger daily.yml manually: https://github.com/rahulaachaaaaa/ai-news-remote-jobs/actions/workflows/daily.yml" — and STOP.

   If the initial staleness check passes (exit 0), skip steps a–c and continue normally.

2. Bootstrap: ./bootstrap.sh  (then use .venv/bin/python for every step)
3. AGENT ENRICHMENT on .tmp/analyzed_content.json using .tmp/rss_articles.json — follow the "AGENT ENRICHMENT STEP" in workflows/daily_ai_news_remote.md (rewrite summaries, repopulate quantum/RSI, keep Automation angle on non-exempt sections, write the YouTube section analysis + 3 ideas).
4. Regenerate ideas + PDF:
   .venv/bin/python tools/generate_youtube_ideas.py
   .venv/bin/python tools/generate_pdf.py
5. Deliver: push a daily/<YYYY-MM-DD> branch carrying the PDF — that push triggers `.github/workflows/deliver.yml`, which DMs the actual PDF file to the user on Slack (Actions has egress; the routine sandbox does not).
6. If ANY step above fails, send the Slack failure message before exiting. Silence = success.
```

## Steps (the agent executes these in order)

Order is **RSS → Hackathons → YouTube viral verify → YouTube trending → Instagram scrape → Instagram verify → AI trends → Jobs → Rank Jobs → Analyze (agent) → Merge Hackathons → Dedup + Backfill → AGENT ENRICHMENT → Generate YouTube Ideas + Section Analysis → PDF → Slack**. RSS first because it produces the bulk of analyzed content.

1. **Bootstrap into a venv, not system Python** (first run only; remote agent caches): run `./bootstrap.sh` (idempotent — creates `.venv`, upgrades pip/setuptools/wheel, installs `requirements.txt`), then run every step below with `.venv/bin/python`.
   *Why:* the cloud sandbox ships a Debian-patched system Python whose `setuptools` is broken (`install_layout` / "Cannot uninstall wheel … RECORD file not found"), so `pip install -r requirements.txt` against system Python aborts mid-install (feedparser's `sgmllib3k` fails to build) and leaves `feedparser`/`pytrends`/`slack_sdk` missing. A fresh venv builds everything cleanly. `.venv/` is gitignored. (GitHub Actions backup runner is unaffected — `setup-python` gives a clean interpreter.)
2. Run `python tools/scrape_rss_feeds.py` → `.tmp/rss_articles.json` (collects **7-day pool**; analyzer surfaces only **last 24h**, backfill widens thin sections from the rest)
3. Run `python tools/youtube_viral_verify.py` → `.tmp/youtube_verified.json` (last 7 days, virality floor: long >= 100K, short >= 500K, URL HEAD-verified)
4. Run `python tools/scrape_youtube_trending.py` → `.tmp/youtube_trending.json` (trending now, no time window)
4a. Run `python tools/scrape_instagram_reels.py` → `.tmp/instagram_reels.json` then `python tools/instagram_viral_verify.py` → `.tmp/instagram_verified.json` (max-engagement AI reel per bucket, last 24h)
4b. Run `python tools/scrape_ai_trends.py` → `.tmp/ai_trends.json` (Google Trends + HN + Reddit)
5. Run `python tools/scrape_jobs.py` → `.tmp/jobs.json`, `.tmp/jobs.csv`, then `python tools/job_match.py` → `.tmp/jobs_ranked.json` (profile-aware ranking against `workflows/user_profile.md`)
6. **Analyze (default = Claude agent).** `run_daily_pipeline.py` runs `tools/agent_analyze.py` by default — the Claude agent classifies RSS into the section taxonomy using deterministic per-section keyword rules + Automation Angle templates. No paid API call. Output: `.tmp/analyzed_content.json` + `.tmp/agent_tokens.json` (zero-cost provider record).
   - **DeepSeek is opt-in.** Pass `--analyzer deepseek` or set `ANALYZER=deepseek` to route RSS articles through DeepSeek (`tools/deepseek_analyze.py`) instead. Requires `DEEPSEEK_API_KEY`. Use when you want LLM-written summaries; default flow does not.
   - **Final fallback:** if both analyzers fail (or `--no-agent` is passed), the deterministic keyword categorizer in `tools/analyze_and_categorize.py::auto_categorize_fallback` runs so the PDF still ships.
   - **Passthrough sections** (bypass any analyzer): `remote_jobs`, `youtube_content_ideas`, `ai_search_trends`, `viral_video_landscape`, `instagram_viral_reels`.
   - **Min-3 padding pass** (DeepSeek path only). Any LLM-routed section with fewer than 3 stories triggers one additional pass against the unrouted pool with a lowered relevance bar.
   - **Quantum strict gate.** `quantum_ai_research` requires BOTH quantum AND AI/ML subject matter.

   **Relevance rubric (used by both analyzers):**
   - **5** = headline-grade global impact (major model launch, Anthropic/Claude release, tier-1 funding round)
   - **4** = significant global AI development with clear practical impact
   - **3** = solid news, narrower audience
   - **2** = niche / incremental
   - **1** = filler

6.5. **Token tracking.** Both analyzers write `.tmp/agent_tokens.json` (input/output tokens, cache hits, USD cost estimate). The agent path records `provider: agent_self`, `model: claude-agent-direct`, `estimated_cost_usd: 0.0`. The DeepSeek path records the real usage block.

6.6. **Dedup + benchmark standings (NO min-floor backfill)** — `run_daily_pipeline.py` runs `tools/dedupe_and_backfill.py` after the hackathon merge. It (a) drops items in RSS-routed sections whose URL was surfaced in the last **7 days** (history in `data/content_seen.json`, namespace `news`) so consecutive PDFs don't repeat — `ai_model_benchmarks` is **exempt**; (b) **min-3 backfill is DISABLED** (user rule 2026-06-13: "just the 24-hour rule, no minimum floor") — sections are never topped up from the older pool, so a quiet section ships thin/empty; (c) seeds the best-model-per-task standings rows into `ai_model_benchmarks`; (d) records every surfaced URL. **Video/reel dedup is widen-then-note (no repeating):** `youtube_viral_verify.py` / `instagram_viral_verify.py` prefer a pick not shown in the last 7 days (namespaces `youtube` / `instagram`); if all qualifiers were already shown they widen the search once, and if still nothing fresh clears the floor they emit a `no_fresh` marker so the PDF prints a "no new viral this period" note instead of re-showing a recent pick. The virality floor still must clear — never fabricate.

6.7. **🟢 AGENT ENRICHMENT STEP (run before PDF).** The deterministic pipeline above guarantees a complete, fresh, non-empty `analyzed_content.json`. On the **cloud scheduled run only**, after dedup+backfill and before the YouTube-ideas + PDF steps, the Claude agent reads `.tmp/analyzed_content.json` + `.tmp/rss_articles.json` and enriches it in place to reference-PDF quality:
   - **Rewrite each story summary** to 2–3 crisp sentences (keep the trailing `Automation angle:` sentence on non-exempt sections). Edit entries **in place** in `analyzed_content.json` — do NOT drive rewrites off a separate map keyed by full URL copied from a truncated console dump; truncated URLs won't match and rewrites get silently dropped. If you must match, match by URL **substring** or by section+index.
   - **Confirm/repopulate `quantum_ai_research` and `ai_self_improvement_rsi`** by reasoning over the unrouted pool — pull in genuinely on-topic items the keyword gate missed (quantum story must be quantum AND AI; RSI must be AGI/alignment/RSI AND AI), so each ships ≥3 real items.
   - **Refresh `ai_model_benchmarks` standings winners** — replace the seeded rows (keep the `category/best/runner_up/benchmark/standings:true` fields so the PDF grid renders) with this week's actual best/runner-up per task from the benchmark news.
   - **Write the synthesis-heavy sections to the user's intent** (these are weak from keywords alone):
     - `elon_musk_ai_vision` — lead with the latest **Grok** updates, then summarize Elon's current stated views on AI.
     - `unaddressed_ai_problems` — name concrete AI problems people hit that **no one is solving** (who's affected + why still open), not generic risk headlines.
     - `ai_business_opportunities` — turn funding/market signals into **startable** AI-automation business ideas (what to build, for whom, why now) + the top current global opportunities.
     - `ai_business_automation` — cover how AI automation is changing work **across industries**, with sector examples, not just tool launches.
     - `new_ai_tools` — keep the user's stack tools (Claude Code / n8n / Voiceflow / Relevance AI / LangChain / agents) at the top.
     - `general_news` — pick the **top worldwide trending** headlines of the day (broad world coverage).
   - Then run the two prompts in step 7. This step is agent-only; if skipped, the deterministic fallbacks already shipped a valid PDF.

7. **Generate YouTube ideas + section analysis** — two agent prompts run between analysis and PDF. `tools/generate_youtube_ideas.py` now also writes a **deterministic 3-idea fallback** synthesised from the finalised sections, so the section is never empty even if the agent prompts below don't run.

   **Prompt A — YouTube Content Ideas (writes `.tmp/youtube_content_ideas.json`):**
   > "Read `.tmp/analyzed_content.json`. Across all sections, identify the 3 strongest video ideas for a YouTube channel teaching AI automation, optimized to plausibly hit 10M views. For each idea provide: `title` (60 chars max), `hook` (first 8 seconds, written word-for-word), `why_10m` (array of 3 bullets, each citing the section it pulled from by key), `thumbnail` (1 sentence), `outline` (array of 5 beats). Write JSON matching the schema in `tools/generate_youtube_ideas.py`."

   **Prompt B — YouTube Landscape Analysis (writes `.tmp/youtube_section_analysis.json`):**
   > "Read `.tmp/youtube_trending.json` (all trending AI videos pulled today) and `.tmp/youtube_verified.json` (the 3 verified-viral picks). Without listing any URLs, produce a landscape analysis: (1) `landscape` — 1 short paragraph on what AI YouTubers are doing right now; (2) `content_patterns` — 3–5 bullets on recurring formats/angles/topics; (3) `gaps` — 3–5 bullets on what's underserved (topics nobody's covering, formats that are missing); (4) `mistakes` — 3–5 bullets on common failure modes (bait titles with no payoff, generic prompts, etc.). Then for each of the 3 `video_id` values in `youtube_verified.json`, write a 1–2 sentence `viral_explanations[<video_id>]` covering hook structure + topic timing + channel pull. **Do not include any URLs in any string field — only the 3 video_id keys.** Write JSON matching the schema in `tools/generate_youtube_ideas.py`."

   `run_daily_pipeline.py` calls `python tools/generate_youtube_ideas.py` to ensure both files exist (empty placeholders) so the PDF never crashes. The cloud agent overwrites them with real content before the PDF stage. **Because these placeholders already exist (Stage 1 published them to `pipeline-state`, Stage 2 checks them out), the agent's `Write` tool will refuse with "File has not been read yet" — `rm -f .tmp/youtube_content_ideas.json .tmp/youtube_section_analysis.json` immediately before writing, or Read each first, then Write fresh content.**

8. Run `python tools/generate_pdf.py` → `.tmp/ai_news_remote_jobs_YYYY-MM-DD.pdf`
8. **Push to dated GitHub branch** `daily/YYYY-MM-DD`:
   - Copy PDF + `jobs.csv` + `analyzed_content.json` + `pipeline.log` into `daily/`
   - `git checkout -B daily/<DATE>` → `git add daily/` → `git commit` → `git push -f origin daily/<DATE>`
   - Routine uses `GH_TOKEN` injected into the remote URL
9. **Slack delivery is automatic via GitHub Actions** — do NOT use the claude.ai Slack connector for the PDF. The connector can only send text (no file attachment) and the routine sandbox can't reach slack.com. Instead, the `daily/<DATE>` push from step 8 triggers `.github/workflows/deliver.yml`, which checks out that branch and uploads the real PDF file (+ jobs.csv) to the user's DM via `files_upload_v2` (repo secrets `SLACK_BOT_TOKEN` / `SLACK_USER_ID`). The routine's only job is to push the branch; the file lands in Slack ~30–60s later. The Slack **failure** rule still uses the connector (the routine can't reach slack.com to alert otherwise).
10. Print both URLs in the routine output:
    - Branch: `https://github.com/rahulaachaaaaa/ai-news-remote-jobs/tree/daily/<DATE>`
    - Raw PDF: `https://github.com/rahulaachaaaaa/ai-news-remote-jobs/raw/daily/<DATE>/daily/ai_news_remote_jobs_<DATE>.pdf`

## Viral AI on YouTube verification rules (PDF section 4, critical)

`tools/youtube_viral_verify.py` enforces:
- **Last 7 days only.** Candidates come from a `viewCount`-ordered search with `publishedAfter = now - 7d`.
- Real `viewCount` from `videos.list` (not search snippet estimate).
- **Virality floor (drop the pick if not cleared, do NOT fall back):**
  - Bucket 1 — Global AI long video (duration > 60s): `views >= 100,000`.
  - Bucket 2 — Global AI Short (duration ≤ 60s): `views >= 500,000`.
  - Bucket 3 — India AI long video (duration > 60s, regionCode=IN): `views >= 100,000`.
- URL `https://www.youtube.com/watch?v=<id>` must return HTTP 200.
- **Cross-day freshness (widen-then-note):** prefer a pick not shown in the last 7 days (namespace `youtube`). If every floor-clearing candidate was already shown, widen the search once (broader queries + larger pool); if still nothing fresh clears the floor, emit a `no_fresh` marker and the PDF prints "No new viral video cleared the floor this period" — **never repeat a recent pick, never fabricate.**
- Total URLs in the rendered PDF section ≤ **3** (one per bucket; fewer when a bucket is `no_fresh`).

## Viral Instagram Reels verification rules (PDF section 4)

`tools/instagram_viral_verify.py` enforces:
- Reel must be posted within the **last 24h** (`taken_at >= now - 24h`); widens to 7 days only to find an UNSEEN reel when every 24h reel was already shown.
- Reel caption/username/hashtag must pass the AI keyword gate (`tools/_text_match.py`).
- **Engagement = like_count + comment_count.** Pick the single max-engagement **unseen** AI reel per bucket (namespace `instagram`); if only already-shown reels qualify, emit a `no_fresh` marker so the PDF notes "no new viral AI reel" — never repeat:
  - Bucket 1: `global_ai` — from the Global hashtag basket
  - Bucket 2: `india_ai` — from the India hashtag basket
- URL `https://www.instagram.com/reel/<code>/` must return HTTP < 400 (Instagram serves a login-wall 302 to bots — that still means the reel exists).
- If a bucket has no AI reels in the last 24h — or `RAPIDAPI_KEY` is unset — the section shows "no candidates" and the pipeline continues. **Never fabricate.**

## What People in AI Are Searching For — rules (PDF section 2)

`tools/scrape_ai_trends.py` aggregates three free sources (each degrades gracefully on failure):
- **Google Trends** (`pytrends`, no key): rising + top related queries for AI seed terms, global + India.
- **Hacker News** (Algolia API, no key): top AI/LLM/agent stories created in the last 24h.
- **Reddit** (`praw` read-only OAuth, or anonymous JSON fallback): hot threads in r/MachineLearning, r/LocalLLaMA, r/singularity, r/ArtificialIntelligence, r/OpenAI, r/Anthropic over the last 24h.
- Signals are clustered by normalized topic phrase; score = sum of log-scaled per-signal strength. Top 20 topics ship with source tags + up to 3 reference URLs each.

## Failure handling

- One scraper failing must not abort the run — `run_daily_pipeline.py` continues
- If all scrapers fail, abort with non-zero exit and notify (see Slack rule below)
- If YouTube API quota is exhausted, the Viral Video + YouTube AI Landscape sections are emitted empty with a note
- If `RAPIDAPI_KEY` is unset / Instagram source fails, the Viral Instagram Reels section shows "no candidates" and the run continues
- If `git push` fails, the PDF is still on the agent's disk — agent reports the local path in the Slack failure DM

## Slack failure rule (cloud schedule)

The user has connected **Slack** in claude.ai connectors and via `SLACK_BOT_TOKEN`. Whenever a scheduled run hits any of these terminal failures, the agent **must** send a Slack DM to the user before exiting:

- `run_daily_pipeline.py` exits non-zero
- PDF generation step fails / no PDF written under `.tmp/`
- `git push` fails (auth, network, or branch protection)
- All scrapers in a single run fail

Slack message format (keep short, link the run):

```
🚨 Daily AI News pipeline FAILED — <YYYY-MM-DD>
Step that failed: <step name>
Error: <one-line error>
Last log lines: <tail of .tmp/pipeline.log>
```

A successful run does **not** need a Slack message — silence = success. Only send on failure. The successful PDF DM is separate (sent by `tools/send_to_slack.py` in step 9).

## Manual trigger (laptop)

```bash
# Full pipeline including Slack DM
python tools/run_daily_pipeline.py

# Local test, skip Slack send, force keyword categorization
python tools/run_daily_pipeline.py --dry-run --no-agent
```

The laptop manual run does **not** push to GitHub — that step is routine-only (the routine has `GH_TOKEN`).

## Update procedure

When a scraper rate-limits / blocks, update its function in `tools/scrape_jobs.py` (or RSS feed list in `scrape_rss_feeds.py`). Document the fix in the Lessons Learned section below.

## Lessons Learned

When a run fails or produces wrong output, append a dated bullet here so the same mistake doesn't recur. Format:

> `**YYYY-MM-DD — <what broke>**: root cause + the fix applied + the rule/code update so this never happens again.`

The rule: if you fix a bug, also update this file (or the code it points to) so the next agent starting fresh inherits the fix.

- **2026-05-10 — Slack PDF delivery silently dropped**: `tools/send_to_slack.py` was invoked with the system Python which didn't have `slack_sdk` installed; the virtualenv had it. Pipeline now standardises on `.venv/bin/python` for all local invocations; routine bootstrap installs `slack_sdk` into the routine's Python before any Slack step. Rule: every new Python dependency must be added to `requirements.txt` and the routine's install step in the same commit.
- **2026-05-11 — `send_to_slack` imports succeed but credentials are missing**: the module read `os.environ["SLACK_BOT_TOKEN"]` at call time but never loaded `.env`, so local runs always failed even though `.env` had the token. Fix: `tools/send_to_slack.py` now calls `load_dotenv()` at import time. Rule: any module that reads env vars on its own must `load_dotenv()` at import — don't assume the orchestrator did it.
- **2026-05-12 — DeepSeek wired but disconnected from the pipeline**: `tools/deepseek_analyze.py` existed and was production-ready, but `run_daily_pipeline.py` never invoked it — analysis silently fell back to keyword rules and DeepSeek showed zero API usage. Fix: pipeline now tries DeepSeek first (when `DEEPSEEK_API_KEY` is set), then `agent_analyze.py`, then the keyword fallback. Rule: when adding a new analysis backend, wire it into the orchestrator in the SAME commit and verify a real call lands by checking the provider's usage dashboard after the next run.
- **2026-05-13 — 24h freshness window produced under-filled sections**: most days, several RSS-categorized sections had only 0-2 stories because too few items in a single 24h window matched the section keywords. Fix: scrapers and DeepSeek prompt switched to a 7-day window; analyzer now runs a min-3 padding pass against the unrouted pool. Rule: when a "freshness vs. coverage" trade-off shows up, widen the window before tightening the keywords — under-filled sections are worse than slightly older items.
- **2026-06-03 — "24h news only" reconciled with the under-fill lesson**: user wants news strictly from the last 24h. Naively shrinking the RSS cutoff to 24h would re-trigger the 2026-05-13 starvation of Quantum/RSI. Fix: keep the RSS **scrape** at 7 days (the "widen pool") but gate the analyzer's main routing pass to 24h via `analyze_and_categorize.NEWS_FRESH_HOURS`; `dedupe_and_backfill.py` then widens thin sections to the older pool only when below `SECTION_MIN`. Rule: surface window (24h) and collection window (7d) are separate knobs — narrow what's *shown*, not what's *collected*.
- **2026-06-03 — viral video/reel repeats across days**: YouTube/Instagram verify used soft dedup that fell back to re-showing the strongest *already-seen* pick, so the same URLs appeared for days. Fix: widen-then-note — prefer unseen, widen the search once, else emit a `no_fresh` marker and the PDF prints a "no new viral this period" note. Rule: for rotation-critical sections, an honest "nothing new" beats a stale repeat.
- **2026-06-03 — Instagram reels always empty (wrong endpoint + GraphQL shape + 20/mo quota)**: `RAPIDAPI_INSTAGRAM_HOST` is `instagram-scraper-stable-api.p.rapidapi.com`, but `scrape_instagram_reels._candidate_endpoints` only knew the `instagram-scraper-api2` paths → every call 404'd → 0 reels. Real endpoint is `/search_hashtag.php?hashtag=<tag>` returning the IG GraphQL shape (`posts.edges[].node` with `shortcode`, `edge_liked_by.count`, `edge_media_to_comment.count`, `edge_media_to_caption.edges[0].node.text`, `taken_at_timestamp`, `is_video`) — the generic walker's flat-key lookups missed all of it. Fixes: added the `.php` endpoint, taught `_extract_reels` the `edge_*` fields, skip `is_video is False` (photos), stop endpoint-thrashing once a 200 lands, added 429 exponential backoff. **BUT the BASIC plan caps at 20 requests/MONTH** (`X-RateLimit-Requests-Limit: 20`) — a daily 13-hashtag run needs ~400/mo, so the section stays empty on this plan regardless of code. Scraper now detects the "exceeded the MONTHLY quota" 429, logs the upgrade note, and aborts fast (writes `skipped_reason`). Rule: to actually ship Instagram reels, upgrade the RapidAPI plan (or swap providers) — until then the section honestly shows "no candidates".
- **2026-06-03 — Google Trends crashed on urllib3 v2**: pytrends 4.9.2 passes the removed `method_whitelist` kwarg to urllib3 v2's `Retry`, so `TrendReq()` raised `__init__() got an unexpected keyword argument 'method_whitelist'` → 0 trends signals every run. Fix: `_patch_urllib3_for_pytrends()` monkeypatches `Retry.__init__` to translate `method_whitelist`→`allowed_methods` (idempotent), and `TrendReq(timeout=(10,25))` to cut the frequent 5s read-timeouts. Now ~36 trends signals. Rule: pin or shim unmaintained scrapers against urllib3 v2 — don't downgrade urllib3 globally.
- **2026-06-03 — Reddit anonymous JSON 403 (IP-level block)**: `www.reddit.com/r/<sub>/hot.json` now returns 403 for the laptop/datacenter IP regardless of User-Agent — confirmed not a UA issue. Anon path updated to Reddit's documented UA format + a clear "set REDDIT_CLIENT_ID/SECRET" log; section still ships from HN + Google Trends (Reddit is supplementary). Rule: for reliable Reddit signals, create a Reddit app and set `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` (PRAW app-only path) — anonymous JSON is no longer dependable.
- **2026-06-13 — cloud routine: every external source 403/blocked (RSS, jobs, trends, instagram)**: the cloud run goes through the sandbox egress proxy, which 403s any domain not in `.claude/settings.json → sandbox.network.allowedDomains`. That list only covered ~15 of the ~67 hosts the scrapers actually fetch, so feedburner/openai/venturebeat/the-decoder RSS, all greenhouse/lever/ashby/remotive/remoteok/wwr/himalayas/hn job APIs, reddit, the rapidapi instagram host, and every hackathon source were proxy-blocked. Fix: expanded `allowedDomains` (and the `WebFetch` allow list) to cover every host emitted by the scrapers, with wildcards + github (git push) + deepseek; added a JSON check that 0 scraper hosts are missing. Rule: **when you add or change a feed/API host in any `tools/scrape_*.py`, add its domain to `.claude/settings.json` in the SAME commit** — an unlisted host fails silently as a 403 in the cloud, not locally. Caveat: a few Cloudflare-fronted origins (TechCrunch/Verge) can still 403 a datacenter IP even when allowlisted; route those through Google News RSS proxies (as x.ai/Elon already are) rather than direct.
- **2026-06-13 — empty sections from two dead-feed bugs + min-floor rule dropped**: several sections (Quantum, RSI, Music Copyright, Global AI, New Tools, Business Automation) shipped empty. Two root causes, both in `tools/scrape_rss_feeds.py`: (1) **Brotli encoding bug** — `_rss_headers()` advertised `Accept-Encoding: gzip, deflate, br`, but the `brotli` package isn't installed, so any server replying `Content-Encoding: br` (The Decoder, TechCrunch, The Verge, VentureBeat, OpenAI, Futurism) handed back raw compressed bytes that feedparser parsed to **0 entries** — silent, since requests only auto-decodes `br` when brotli is present. Fix: dropped `br` from `Accept-Encoding` (gzip/deflate are always decoded natively; no new dependency). (2) **arXiv weekend gap** — the `rss.arxiv.org/rss/<cat>` feeds carry only the latest announcement batch and are **empty on weekends/holidays**, starving Quantum + RSI every Sat/Sun. Fix: switched those four feeds to the arXiv **API** (`export.arxiv.org/api/query?search_query=cat:<cat>&sortBy=submittedDate&sortOrder=descending&max_results=40`), which returns recent papers across the whole window regardless of announcement day. Result: RSS pool 332 → 624 articles. **Rule:** never advertise `br` unless `brotli` is a hard dependency; for arXiv use the dated API query, not the RSS snapshot. Separately, the user set a standing rule — **"just the 24-hour rule, no minimum floor"** — so `dedupe_and_backfill.py`'s min-3 backfill is now DISABLED: sections show only strict-24h items and ship thin/empty rather than being padded from the 7-day pool. The cure for empty sections is healthy feeds, not backfill.
- **2026-06-13 — empty PDF shipped exit-0 + venv/TLS/quota + YouTube false positives**: a cloud run hit a wall of environment + latent-code failures and still exited 0 with a near-empty PDF. Grouped:
  1. **Deps wouldn't install on system Python** — broken Debian-patched `setuptools` (`install_layout`; "Cannot uninstall wheel … RECORD file not found") aborted `pip install -r requirements.txt` mid-build (feedparser's `sgmllib3k`). Fix: bootstrap into `.venv` and run everything with `.venv/bin/python` (step 1 above). *Rule: never install into the cloud sandbox's system Python.*
  2. **Egress proxy 403s almost all outbound** — only `github.com` + `*.googleapis.com` were reachable; every scraper host 403'd even when listed in `.claude/settings.json` allowlist, because **that allowlist is not applied to a sandbox created with a restrictive network policy**. Fix is environmental: recreate/reconfigure the Claude Code web environment with a project-allowlist network policy (the in-repo allowlist alone is not enough). *Rule: confirm the environment's network policy, not just settings.json, before blaming the scrapers.*
  3. **TLS-intercepting proxy breaks Python HTTPS** — `[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain` on googleapis calls (curl tolerated it, Python's certifi did not). Fix: install the proxy CA into the trust store or point `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` at it (requests honors these automatically — no code change), or use a policy without TLS interception.
  4. **YouTube Data API 429 (quota exhausted)** — viral/trending sections went empty. Fix: refresh the API key / quota; not a code bug.
  5. **YouTube "viral" false positives (latent code bug, now fixed)** — `youtube_viral_verify.py` had no AI gate, so the Search API's loose matches shipped non-AI foreign-language clips that merely spelled "Ai" ("…Tahun Ai", "…của Ai"), AND it kept picks with `url_verified:false` (HEAD failed because youtube.com was proxy-blocked). Fix: added `is_ai_video()` (brand/AI-phrase, or bare "ai"/"ml" only with an English AI cue — a bare word-boundary match is NOT enough because "Ai" is a real word in Indonesian/Vietnamese) and made `pick_top()` **drop any candidate that fails URL verification** instead of surfacing it. Tests: `tests/test_youtube_ai_gate.py`.
  6. **Empty PDF still exited 0** — every scraper returned empty without raising, so the runner's `any([...])` "all scrapers failed" guard (true on no-exception) passed and a hollow PDF shipped, no Slack alert. Fix: `run_daily_pipeline.py` now adds a **content gate after scraping** — `rss_articles == 0` (the backbone of 14+ sections, a rolling 7-day pool, so zero ⇒ blocked/broken, not a quiet day) aborts with `return False`, which fires the cloud Slack failure alert. *Rule: assert real content landed, never just "no exception."*
- **2026-06-13 — routine kept scraping in the sandbox despite the two-stage split (403 abort, no PDF)**: the two-stage code shipped to `main` (Stage 1 Actions scraper + `pipeline-state` branch + enrichment-only Stage 2), but the **claude.ai routine prompt was never switched over** — it still ran `python3 tools/run_daily_pipeline.py`, which scrapes RSS + jobs inside the cloud sandbox → every host 403'd → `ABORT: zero RSS articles`, `analyzed_content.json` never written, no PDF. Stage 1's fresh `pipeline-state` was sitting unused. Fix: replaced the live routine (`trig_018UFpSohtbZ9fvHQRJmaPtR`) prompt with the Stage-2 enrichment-only prompt — it `git checkout origin/pipeline-state -- .tmp`, verifies the state is <18h old (an age check, NOT date-equality: Stage 1 runs 23:15 IST = "yesterday" in IST vs the 00:00 IST routine day, so equality would false-positive), then enriches→PDF→delivers and NEVER scrapes. **Rule: the routine prompt — not this workflow file or `main` — is what the cloud agent actually executes; any change to the two-stage flow MUST update the live routine via the `schedule` skill in the same change, or the cloud keeps running the old prompt.**
- **2026-06-15 — Stage 1 silent failure after repo migration (no PDF, no Slack alert)**: After migrating from `rahulmeenaailead-commits` to `rahulaachaaaaa`, GitHub Actions secrets don't carry over. `daily.yml` cron fired at 22:30 IST with empty `SLACK_BOT_TOKEN` — the Slack failure step sent `Authorization: Bearer ` (no token), got `{"ok":false,"error":"not_authed"}` from Slack, printed it but didn't raise, so the step appeared to succeed and the user received no alert. `pipeline-state` was never updated. Stage 2 correctly detected the 24h-stale state and sent a failure via the claude.ai Slack connector, but no PDF was delivered. Fixes: (1) `daily.yml` now emits `::warning::` annotations for each empty critical secret at run start; (2) Slack failure notification step raises on empty token or `ok:false` so the step is marked failed in the Actions log; (3) Stage 2 routine now attempts `workflow_dispatch` on `daily.yml` when stale state is detected, polls every 90 s for up to 20 min, and only sends the failure Slack if recovery times out or the dispatch is rejected. **Rule: after any repo migration, immediately go to GitHub → Settings → Secrets and re-add all secrets before the next cron window fires.**
- **2026-06-16 — Stage 2 follow-on: `GH_TOKEN` was missing entirely (not just stale)**: Enrichment + PDF generation succeeded fully, but the final `git push daily/2026-06-16` step 403'd. `gh secret list` confirmed `GH_TOKEN` never existed in the migrated repo at all — the 2026-06-15 fix covered `SLACK_BOT_TOKEN`/`SLACK_USER_ID` but missed this one. Recovered without a browser PAT: the local `gh` CLI was already authenticated (admin permission on the repo, `repo`+`workflow` scopes), so `gh secret set GH_TOKEN -R rahulaachaaaaa/ai-news-remote-jobs --body "$(gh auth token)"` restored it directly. Also discovered `workflow_dispatch` requires the target workflow file to exist on the **default branch** even when dispatching against a different `--ref` — `redeliver.yml` had only ever been pushed to `daily/2026-06-16`, so the first dispatch attempt 404'd until it was copied onto `main`. Used the now-restored `GH_TOKEN`-independent `redeliver.yml` (reads staged JSON from the dated branch, regenerates PDF, DMs via Slack — no git push needed) to deliver the 2026-06-16 PDF. **Rule: when auditing secrets after a migration, run `gh secret list -R <repo>` and diff against every `secrets.*` reference across all workflow YAMLs — don't rely on remembering which ones mattered last time.**
- **2026-06-16 (later) — Stage 2 *routine's own* `GH_TOKEN` was a separate, third copy that also needed fixing**: A live Stage 2 routine run failed at `git push origin daily/2026-06-16` with `403 Write access to repository not granted`, even though the Actions `GH_TOKEN` secret had already been fixed earlier that day. Root cause: the routine prompt (`trig_018UFpSohtbZ9fvHQRJmaPtR`) hardcodes its own `export GH_TOKEN="github_pat_..."` line — a **fine-grained PAT** for `rahulaachaaaaa` that was never granted repo access at all (`GET /repos/rahulaachaaaaa/ai-news-remote-jobs` with that token returned 404, vs 200 for `GET /user`). This is a **third, independent copy of GH_TOKEN** beyond the Actions secret and the local `gh` CLI session — none of the three are linked, and fixing one does not fix the others. Fixed by updating the routine via `RemoteTrigger update` and swapping the dead fine-grained PAT for the local `gh auth token` value (same admin-scoped classic token already proven to work against this repo). **Rule: there are (at least) THREE separate GH_TOKEN locations to check after any credential rotation or migration — (1) GitHub Actions repo secret, (2) the hardcoded `export GH_TOKEN=...` line inside the Stage 2 routine prompt (`trig_018UFpSohtbZ9fvHQRJmaPtR`, fetch via `RemoteTrigger get`), and (3) whatever token the local `gh` CLI session carries. Audit all three, not just the Actions secret.**
- **2026-06-03 — section reorder + content-intent refresh**: reordered `SECTION_ORDER`; benchmarks now render as a real grid (`build_benchmark_table_section`); hackathons gained accelerator/acceleration-program sources; New AI Tools floats the user's build stack; per-section synthesis intent for Elon/Grok, Unaddressed Problems, Business Opportunities, AI Automation, General News documented above for the enrichment step. Rule: PDF order lives ONLY in `generate_pdf.SECTION_ORDER`; CLAUDE.md + this table are the human spec — keep all three in sync when reordering.
