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

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
CHECKPOINTS = os.path.join(TMP_DIR, "agent_checkpoints.jsonl")
OUTPUT = os.path.join(TMP_DIR, "agent_tokens.json")

# Empirical: ~4 chars per token for English+JSON. We use 4.0. Fallback only —
# use --count-tokens for a real count via the Messages API count_tokens
# endpoint (free, no subscription usage consumed).
CHARS_PER_TOKEN = 4.0
# Routine system prompt + workflow doc + CLAUDE.md the agent has to read once.
SYSTEM_PROMPT_OVERHEAD_TOKENS = 6000
# Reasoning overhead per minute the agent runs (rough estimate).
THINKING_TOKENS_PER_MIN = 1500

# Same file list as _estimate_from_files(), used by --count-tokens too.
COUNT_TOKENS_MODEL = "claude-opus-5"


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


def _declared_input_paths():
    """Same file list _estimate_from_files() sums by byte size — reused here
    so --count-tokens measures the exact same declared-input set."""
    return [
        os.path.join(TMP_DIR, "jobs.json"),
        os.path.join(TMP_DIR, "rss_articles.json"),
        os.path.join(TMP_DIR, "youtube_verified.json"),
        os.path.join(TMP_DIR, "youtube_trending.json"),
        os.path.join(PROJECT_ROOT, "CLAUDE.md"),
        os.path.join(PROJECT_ROOT, "workflows", "daily_ai_news_remote.md"),
        os.path.join(PROJECT_ROOT, "ROUTINE_PROMPT.md"),
    ]


def _real_token_count():
    """Call the Messages API count_tokens endpoint on the declared input
    files for a real tokenizer count. Free endpoint — does NOT consume
    claude.ai subscription usage (it's a separate API-key-based call).

    Returns (input_tokens, error) — error is None on success, else a string
    explaining why the real count wasn't available (missing package, missing
    key, or an API error) so the caller can fall back to the heuristic.
    """
    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed (pip install anthropic)"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY not set"

    chunks = []
    for path in _declared_input_paths():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                chunks.append(f.read())
        except OSError:
            continue
    if not chunks:
        return None, "no declared input files found on disk"

    text = "\n\n".join(chunks)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.count_tokens(
            model=COUNT_TOKENS_MODEL,
            messages=[{"role": "user", "content": text}],
        )
        return resp.input_tokens, None
    except Exception as e:
        return None, f"count_tokens call failed: {e}"


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count-tokens", action="store_true",
        help="Use the real Messages API count_tokens endpoint for the "
             "declared-input token count instead of the chars/4.0 heuristic. "
             "Free endpoint, does not touch subscription usage. Falls back "
             "to the heuristic (with a note) if anthropic isn't installed "
             "or ANTHROPIC_API_KEY isn't set.",
    )
    args = parser.parse_args()

    os.makedirs(TMP_DIR, exist_ok=True)

    real_input_tokens = None
    real_count_error = None
    if args.count_tokens:
        real_input_tokens, real_count_error = _real_token_count()

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

    if args.count_tokens:
        if real_input_tokens is not None:
            notes += (
                f" Declared-input tokens replaced with real count_tokens() "
                f"result ({real_input_tokens:,}, model={COUNT_TOKENS_MODEL}); "
                f"thinking-overhead/checkpoint portion of input_tokens above "
                f"is heuristic on top of that."
            )
            # Real count covers the declared-input files only; keep whatever
            # overhead (thinking, system prompt) the estimate above already
            # added on top, since count_tokens doesn't know about that.
            heuristic_declared, _ = _estimate_from_files()
            overhead = max(0, in_tok - heuristic_declared)
            in_tok = real_input_tokens + overhead
        else:
            notes += f" --count-tokens requested but unavailable: {real_count_error}."

    payload = {
        "model": os.environ.get("AGENT_MODEL", "claude-opus-5"),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cache_read_tokens": cr_tok,
        "cache_creation_tokens": cc_tok,
        "real_count_tokens_used": args.count_tokens and real_input_tokens is not None,
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
