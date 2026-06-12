# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to pull data from a website, don't attempt it directly. Read `workflows/scrape_website.md`, figure out the required inputs, then execute `tools/scrape_single_site.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## File Structure

**What goes where:**
- **Deliverables**: Final outputs go to cloud services (Google Sheets, Slides, etc.) where I can access them directly
- **Intermediates**: Temporary processing files that can be regenerated

**Directory layout:**
```
.tmp/           # Temporary files (scraped data, intermediate exports). Regenerated as needed.
tools/          # Python scripts for deterministic execution
workflows/      # Markdown SOPs defining what to do and how
.env            # API keys and environment variables (NEVER store secrets anywhere else)
credentials.json, token.json  # Google OAuth (gitignored)
```

**Core principle:** Local files are just for processing. Anything I need to see or use lives in cloud services. Everything in `.tmp/` is disposable.

## Bottom Line

You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.

## How I Work With You (User Personality)

- Low-talk, direct. Skip preambles, summaries, encouragement.
- Drop the job, finish the job. No status narration unless I ask.
- Confirm only on irreversible/destructive actions or paid API spend.
- Short answers. Fragments fine. Code/file paths exact.
- Default: do the work, then report file path + 1 line.

## Project Goals

- **Primary**: land a worldwide-remote AI Automation job (no prior experience, portfolio-based). Built with Claude Code.
- **Secondary**: launch a YouTube channel teaching AI automation methods.
- **Daily ritual**: 20-section AI news + remote jobs PDF delivered (Slack DM + GitHub dated branch) at **00:00 IST** every day, running in the cloud via a **claude.ai scheduled agent** — independent of laptop state.

## Cloud schedule failure rule (always-on)

If a cloud-scheduled run of this pipeline fails (non-zero exit from `run_daily_pipeline.py`, missing PDF, Drive upload error, or every scraper failed), the agent **must** send a Slack message via the connected Slack connector before exiting. The user has Slack wired up in claude.ai connectors. Format + full rules: see `workflows/daily_ai_news_remote.md` → "Slack failure rule (cloud schedule)". Silence = success; only notify on failure.

## The 19 Sections (PDF order)

Order is enforced by `SECTION_ORDER` in `tools/generate_pdf.py`. **News is last-24h only** (RSS cutoff = 24h); low-volume sections widen to ≤7 days via backfill only when below the per-section minimum.

1. Remote AI Jobs — **worldwide-remote, AI-only, entry-level / junior**. Ranked against workflows/user_profile.md (n8n / Voiceflow / Relevance AI / Claude Code). Senior/lead/principal + region-locked dropped. Greenhouse + Lever + Ashby + Remotive + RemoteOK + WWR + Himalayas + HN.
2. AI Product Showcase Opportunities — AI hackathons & competitions **plus accelerators / incubators / acceleration programs** (incl. govt/India schemes like "IndiaAI Startups Global"). Each item must carry a direct apply link + deadline.
3. YouTube Content Ideas — 3 video pitches the Claude agent writes after synthesising the rest of this PDF, engineered to plausibly hit 10M views. Title + 8-second hook + why-it-hits-10M + thumbnail concept + 5-beat outline per idea.
4. Viral AI on YouTube (Last 7 Days) — **merged YouTube section.** 2 long videos (Global + India AI) + 1 Global AI Short, last-7-days only, virality floors (long ≥ 100K, short ≥ 500K), URL HEAD-verified. Must be **fresh vs. recent runs** — if no new video clears the floor, print a "no new viral this period" note rather than repeat. Agent-written landscape + patterns + gaps + per-video "why it went viral". **No view counts. No automation angle.**
5. Viral Instagram Reels (AI) — 1 viral AI reel India + 1 Global, max engagement (likes+comments) in last 24h, RapidAPI sourced. Fresh vs. recent runs; "no new reel" note if none.
6. Quantum + AI.
7. AI Self-Improvement / RSI.
8. Elon Musk's AI Vision — all **Grok** product updates + Elon's stated views on AI (xAI direction, AGI/safety takes, notable statements).
9. AI Model Benchmarks — **top model per category as a TABLE** (Task | Best | Runner-up | Benchmark: Text/LLM, Coding, Image, Video, Music/Audio, Reasoning) + benchmark news below.
10. New AI Tools — bias to the user's stack: **Claude Code / n8n / Voiceflow / Relevance AI / MCP / agent builders** first, with cost/feature notes.
11. Indian AI Industry — **AI-only** India news.
12. Anthropic & Claude Code Updates — Anthropic company news + Claude Code product updates.
13. AI Automation & Businesses — **how AI automation is changing work across industries** (not just tool launches): real deployments, ROI, sector-by-sector updates.
14. Global AI News — **AI-only** worldwide news (no general tech).
15. What People in AI Are Searching For — hottest AI topics now: Google Trends rising queries (global + India) + Hacker News + Reddit AI subreddits, last 24h.
16. Unaddressed AI Problems — **real problems people hit with AI that no one is solving** (gaps/pain points), not generic deepfake headlines.
17. AI Business Opportunities — concrete businesses the user could start now + top current global opportunities.
18. Copyright & Laws in AI Music Business.
19. General News (non-AI) — **top worldwide trending headlines** (broad world coverage, not region-narrow).
