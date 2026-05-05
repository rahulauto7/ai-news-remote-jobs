# Workflow: Daily AI News + Remote Jobs

## Objective

Every day at **00:00 IST** (laptop off OK — runs as a claude.ai cloud scheduled agent), produce an 18-section PDF summarizing the last 24 hours of AI news + currently-open global remote AI Automation jobs, **push it to a dated GitHub branch** (`daily/YYYY-MM-DD`) and **DM it to the user on Slack**.

> Schedule: configured in **claude.ai → Routines** (cloud-side, independent of laptop). Trigger time: 00:00 IST = 18:30 UTC. The schedule prompt instructs the agent to execute this workflow end-to-end. The same time is mirrored in `.github/workflows/daily.yml` (cron `30 18 * * *`) as a backup runner.

## Inputs

- Cloned repo at agent's `cwd`
- Routine env / GitHub Actions secrets:
  - `YOUTUBE_API_KEY` — YouTube Data API v3
  - `SLACK_BOT_TOKEN`, `SLACK_USER_ID` — Slack DM delivery + failure alerts
  - `GH_TOKEN` — GitHub PAT (repo scope) for routine `git push`

## The 18 Sections

| # | Key | Source |
|---|---|---|
| 0 | `remote_jobs` | LinkedIn + Wellfound + Indeed + Remotive + We Work Remotely + Himalayas + RemoteOK + HN + X (Nitter) |
| 1 | `ai_music_business_news` | RSS (MBW, DMN, Hypebot, etc.) |
| 2 | `ai_music_copyright_laws` | RSS keyword filter |
| 3 | `global_ai_news` | RSS (Verge, TechCrunch, etc.) |
| 4 | `indian_ai_industry` | RSS (Inc42, YourStory, ETTech) |
| 5 | `product_showcase_opportunities` | RSS (Product Hunt) + curated list |
| 6 | `anthropic_claude_news` | Anthropic blog + RSS keyword |
| 7 | `elon_musk_ai_vision` | xAI blog + Google News proxy |
| 8 | `unaddressed_ai_problems` | RSS keyword filter |
| 9 | `ai_business_opportunities` | RSS keyword filter |
| 10 | `quantum_ai_research` | arXiv quant-ph + RSS |
| 11 | `new_ai_tools` | Product Hunt + RSS |
| 12 | `ai_model_benchmarks` | RSS keyword |
| 13 | `ai_business_automation` | RSS keyword |
| 14 | `ai_self_improvement_rsi` | arXiv + RSS keyword |
| 15 | `viral_video_landscape` | YouTube Data API v3 — verified |
| 16 | `youtube_ai_landscape` | YouTube Data API v3 |
| 17 | `general_news` | BBC, Hindu, NDTV |

## Steps (the agent executes these in order)

1. `pip install -r requirements.txt` (first run only; remote agent caches)
2. Run `python tools/scrape_jobs.py` → `.tmp/jobs.json`, `.tmp/jobs.csv`
3. Run `python tools/scrape_rss_feeds.py` → `.tmp/rss_articles.json`
4. Run `python tools/youtube_viral_verify.py` → `.tmp/youtube_verified.json`
5. Run `python tools/scrape_youtube_trending.py` → `.tmp/youtube_trending.json`
6. **Read** all four scraped files. **Reason** about which RSS articles belong to which section. **Write** `.tmp/analyzed_content.json` using `tools.analyze_and_categorize.save_analyzed_content(sections, total)`.
   - Section 0: pass through `jobs` (cap 25, sort by recency + keyword score). For `summary`, write a one-line sentence: who's hiring, role, key tech (e.g. "CloudHire is hiring a Junior AI Automation Engineer — Python + LLM APIs, fully remote, US-friendly.") — never just `Search: AI automation`.
   - Section 15: pass through `youtube_verified` videos as-is (already 3 buckets).
   - Sections 1–14, 17: route RSS by topic; aim for 3–8 stories each. **Do not copy raw RSS text.** For each story, write a fresh **1–2 sentence summary in plain English** that states what happened and why it matters — no HTML, no `<p>`, `<a>`, `<img>`, `<h4>` tags, no `Source:` prefixes, no truncated mid-sentence dumps. If the RSS body is paywalled or empty, write the summary from the title alone (do not leave it blank or HTML-stuffed).
   - Section 16: top 10 YouTube trending.

   **Relevance scoring (`relevance` 1–5)** — must be differentiated, not all 5s. Use this rubric:
   - **5** = headline-grade, directly affecting the user's remote-job goals (e.g. top-tier global remote AI Automation role, Anthropic/Claude release, major model launch)
   - **4** = significant global AI development with clear practical impact
   - **3** = solid news, narrower audience
   - **2** = niche / incremental
   - **1** = filler that only made it in because the section was thin

   Drop arXiv abstracts and pure academic papers from sections 8 (Unaddressed Problems), 11 (New AI Tools), 12 (Benchmarks), 13 (Automation), 14 (RSI) unless they propose a working product/benchmark — these sections are for industry news, not raw research dumps.

6.5. **Write `.tmp/agent_tokens.json`** with the agent's own session token usage so the PDF can render a "Run Telemetry" section. Schema:
   ```json
   {
     "model": "claude-opus-4-7",
     "input_tokens": 0,
     "output_tokens": 0,
     "cache_read_tokens": 0,
     "cache_creation_tokens": 0,
     "notes": "optional free text"
   }
   ```
   If the runtime does not expose session usage, write `{ "available": false, "reason": "<why>" }` instead. The `run_daily_pipeline.py` orchestrator merges this file into `.tmp/run_telemetry.json` before PDF generation; if the file is missing, the PDF will note that token usage was unavailable.

7. Run `python tools/generate_pdf.py` → `.tmp/ai_news_remote_jobs_YYYY-MM-DD.pdf`
8. **Push to dated GitHub branch** `daily/YYYY-MM-DD`:
   - Copy PDF + `jobs.csv` + `analyzed_content.json` + `pipeline.log` into `daily/`
   - `git checkout -B daily/<DATE>` → `git add daily/` → `git commit` → `git push -f origin daily/<DATE>`
   - Routine uses `GH_TOKEN` injected into the remote URL
9. **DM the PDF to user on Slack** via `tools/send_to_slack.py`
10. Print both URLs in the routine output:
    - Branch: `https://github.com/rahulmeenaailead-commits/ai-news-remote-jobs/tree/daily/<DATE>`
    - Raw PDF: `https://github.com/rahulmeenaailead-commits/ai-news-remote-jobs/raw/daily/<DATE>/daily/ai_news_remote_jobs_<DATE>.pdf`

## Section 15 verification rules (critical)

`tools/youtube_viral_verify.py` enforces:
- Each candidate must have `publishedAfter = now - 24h`
- Real `viewCount` from `videos.list` (not search snippet estimate)
- Bucket A: global automation, **>= 100,000 views**
- Bucket B: India automation (regionCode=IN), **>= 25,000 views**
- Bucket C: global Short, duration ≤ 60s, **>= 250,000 views**
- URL `https://www.youtube.com/watch?v=<id>` must return HTTP 200
- If a bucket has no qualifying video, the section notes "no verified viral video in last 24h" — never fabricate.

## Failure handling

- One scraper failing must not abort the run — `run_daily_pipeline.py` continues
- If all scrapers fail, abort with non-zero exit and notify (see Slack rule below)
- If YouTube API quota is exhausted, sections 15 & 16 are emitted empty with a note
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

When a scraper rate-limits / blocks, update its function in `tools/scrape_jobs.py` (or RSS feed list in `scrape_rss_feeds.py`). Document the fix here.
