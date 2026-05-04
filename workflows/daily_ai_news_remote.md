# Workflow: Daily AI News + Remote Jobs

## Objective

Every day at **00:00 IST** (laptop off OK — runs as Claude Code scheduled remote agent), produce an 18-section PDF summarizing the last 24 hours of AI news + currently-open remote AI Automation jobs (India-eligible), and upload it to Google Drive.

## Inputs

- Cloned repo at agent's `cwd`
- Env: `YOUTUBE_API_KEY` (passed via routine prompt or env_file)
- Google Drive MCP connector attached to the routine (for upload)

## The 18 Sections

| # | Key | Source |
|---|---|---|
| 0 | `remote_jobs` | LinkedIn + Wellfound + Indeed + Naukri + X (Nitter) |
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
   - Section 0: pass through `jobs` (cap 25, sort by recency + keyword score)
   - Section 15: pass through `youtube_verified` videos as-is (already 3 buckets)
   - Sections 1-14, 17: route RSS by topic; aim for 3-8 stories each
   - Section 16: top 10 YouTube trending
7. Run `python tools/generate_pdf.py` → `.tmp/ai_news_remote_jobs_YYYY-MM-DD.pdf`
8. Upload PDF + `jobs.csv` to Google Drive via the Drive MCP, into folder "AI News Daily"
9. Report Drive link in the routine output

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
- If all scrapers fail, abort with non-zero exit and notify
- If YouTube API quota is exhausted, sections 15 & 16 are emitted empty with a note
- If Drive upload fails, the PDF stays in `.tmp/`; agent must report failure

## Manual trigger

```bash
# Full pipeline with Drive upload
python tools/run_daily_pipeline.py

# Local test, no Drive upload, force keyword categorization
python tools/run_daily_pipeline.py --dry-run --no-agent
```

## Update procedure

When a scraper rate-limits / blocks, update its function in `tools/scrape_jobs.py` (or RSS feed list in `scrape_rss_feeds.py`). Document the fix here.
