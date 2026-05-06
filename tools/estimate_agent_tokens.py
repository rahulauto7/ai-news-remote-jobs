"""
Best-effort token estimator for the cloud routine agent.

Background
----------
claude.ai routines run as a single Claude session. The runtime does not expose
per-turn usage counters back to the agent in-band, so the agent itself cannot
look up how many tokens it has consumed mid-run. To still surface a
meaningful "how much did this run cost" number on the daily PDF, we estimate
tokens from observable artifacts:

  - Bytes the agent had to read in (.tmp/*.json scraper outputs, the routine
    prompt itself, this repo's CLAUDE.md / workflows/) feed input tokens.
  - Bytes the agent wrote out (.tmp/analyzed_content.json, .tmp/agent_log.txt
    if it exists) feed output tokens.
  - A fixed thinking-overhead is added (long routines do a lot of internal
    reasoning that doesn't show up in any file).

Everything is tagged "estimate" so the user knows it is not a billing-grade
counter — it's a "did the run actually do work?" sanity number.

Output
------
Writes .tmp/agent_tokens.json in the same shape generate_pdf.py expects.

Cadence checkpoints
-------------------
The agent is also instructed (in ROUTINE_PROMPT.md) to APPEND a one-line
checkpoint to .tmp/agent_checkpoints.jsonl after each major step:

    {"t": "<iso>", "step": "scrape_jobs", "in": 0, "out": 0, "note": "..."}

If checkpoints exist, they are summed and override the bytes-based estimate.
This way the cloud agent's own self-report wins; the bytes heuristic is the
fallback when checkpoints are missing.
"""

import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
CHECKPOINTS = os.path.join(TMP_DIR, "agent_checkpoints.jsonl")
OUTPUT = os.path.join(TMP_DIR, "agent_tokens.json")

# Empirical: ~4 chars per token for English+JSON. We use 4.0.
CHARS_PER_TOKEN = 4.0
# Routine system prompt + workflow doc + CLAUDE.md the agent has to read once.
SYSTEM_PROMPT_OVERHEAD_TOKENS = 6000
# Reasoning overhead per minute the agent runs (rough estimate).
THINKING_TOKENS_PER_MIN = 1500


def _bytes(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _estimate_from_files():
    """Estimate tokens by summing bytes of files the agent read/wrote."""
    inputs_read = [
        os.path.join(TMP_DIR, "jobs.json"),
        os.path.join(TMP_DIR, "rss_articles.json"),
        os.path.join(TMP_DIR, "youtube_verified.json"),
        os.path.join(TMP_DIR, "youtube_trending.json"),
        os.path.join(PROJECT_ROOT, "CLAUDE.md"),
        os.path.join(PROJECT_ROOT, "workflows", "daily_ai_news_remote.md"),
        os.path.join(PROJECT_ROOT, "ROUTINE_PROMPT.md"),
    ]
    outputs_written = [
        os.path.join(TMP_DIR, "analyzed_content.json"),
    ]

    in_chars = sum(_bytes(p) for p in inputs_read)
    out_chars = sum(_bytes(p) for p in outputs_written)

    in_tok = int(in_chars / CHARS_PER_TOKEN) + SYSTEM_PROMPT_OVERHEAD_TOKENS
    out_tok = int(out_chars / CHARS_PER_TOKEN)
    return in_tok, out_tok


def _estimate_from_checkpoints():
    """If the agent self-reported per-step token usage, sum it. Returns None
    when no checkpoints exist."""
    if not os.path.exists(CHECKPOINTS):
        return None
    in_tok = out_tok = cr_tok = cc_tok = 0
    n = 0
    with open(CHECKPOINTS, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            in_tok += int(row.get("in", 0) or 0)
            out_tok += int(row.get("out", 0) or 0)
            cr_tok += int(row.get("cache_read", 0) or 0)
            cc_tok += int(row.get("cache_creation", 0) or 0)
            n += 1
    if n == 0:
        return None
    return in_tok, out_tok, cr_tok, cc_tok, n


def _runtime_minutes():
    """Read run_telemetry.json (if present) for total elapsed; else return 5."""
    p = os.path.join(TMP_DIR, "run_telemetry.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            return max(1.0, float(d.get("total_elapsed_s", 300)) / 60.0)
        except Exception:
            pass
    return 5.0


def main():
    os.makedirs(TMP_DIR, exist_ok=True)

    cps = _estimate_from_checkpoints()
    if cps is not None:
        in_tok, out_tok, cr_tok, cc_tok, n = cps
        notes = (
            f"Self-reported by agent across {n} checkpoints in agent_checkpoints.jsonl. "
            f"Includes start-to-end usage (scraping, categorizing, PDF, push, Slack)."
        )
    else:
        in_tok, out_tok = _estimate_from_files()
        cr_tok = 0
        cc_tok = 0
        # Add thinking overhead based on runtime
        mins = _runtime_minutes()
        thinking = int(mins * THINKING_TOKENS_PER_MIN)
        in_tok += thinking
        notes = (
            "Estimate (no agent_checkpoints.jsonl found). "
            f"Computed from .tmp/ file sizes + {THINKING_TOKENS_PER_MIN}/min thinking overhead "
            f"over {mins:.1f} min runtime. Real billed usage may differ; treat as a sanity number."
        )

    payload = {
        "model": os.environ.get("AGENT_MODEL", "claude-opus-4-7"),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cache_read_tokens": cr_tok,
        "cache_creation_tokens": cc_tok,
        "estimated_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    total = in_tok + out_tok + cr_tok + cc_tok
    print(f"[estimate_agent_tokens] wrote {OUTPUT}")
    print(f"  input={in_tok:,}  output={out_tok:,}  "
          f"cache_read={cr_tok:,}  cache_creation={cc_tok:,}  total={total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
