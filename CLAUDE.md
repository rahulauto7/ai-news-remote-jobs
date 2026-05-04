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

- **Primary**: land a remote AI Automation job from India (no prior experience, portfolio-based). Built with Claude Code.
- **Secondary**: launch a YouTube channel teaching AI automation methods.
- **Daily ritual**: 18-section AI news + remote jobs PDF delivered to Google Drive at **07:00 IST** every day, running in the cloud via a **claude.ai scheduled agent** — independent of laptop state.

## Cloud schedule failure rule (always-on)

If a cloud-scheduled run of this pipeline fails (non-zero exit from `run_daily_pipeline.py`, missing PDF, Drive upload error, or every scraper failed), the agent **must** send a Slack message via the connected Slack connector before exiting. The user has Slack wired up in claude.ai connectors. Format + full rules: see `workflows/daily_ai_news_remote.md` → "Slack failure rule (cloud schedule)". Silence = success; only notify on failure.

## The 18 Sections

0. Remote AI Automation jobs (India-eligible) — LinkedIn, Wellfound/YC, Indeed/Naukri, X/Discord
1. AI Music Business News
2. Copyright & Laws in AI Music Business
3. Global AI News
4. Indian AI Industry
5. AI Product Showcase Opportunities
6. Claude Model Updates
7. Elon Musk's AI Vision
8. Unaddressed AI Problems
9. AI Business Opportunities
10. Quantum + AI
11. New AI Tools (with cost/feature comparisons)
12. AI Model Benchmarks (best per category)
13. AI Automation & Businesses
14. AI Self-Improvement / RSI
15. Viral Video Landscape — exactly 3 videos, **verified via YouTube Data API v3** (URL resolves + 24h view count above threshold)
16. YouTube AI Landscape (trending topics + fastest-growing channels)
17. General News (non-AI) — top world & India headlines
