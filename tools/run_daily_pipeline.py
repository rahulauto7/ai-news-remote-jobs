"""
Master orchestrator for the daily AI News + Remote Jobs pipeline.

Runs in sequence:
  1. scrape jobs (section 0)
  2. scrape RSS feeds (sections 1-14, 17)
  3. verify viral YouTube videos (section 15)
  4. scrape YouTube trending (section 16)
  5. analyze + categorize (agent does this; fallback = keyword rules)
  6. generate PDF
  7. upload to Drive

Each step is wrapped in try/except — failures don't kill the run.
Use --dry-run to skip the Drive upload step.
Use --no-agent to force the deterministic categorizer.
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
LOG_FILE = os.path.join(TMP_DIR, "pipeline.log")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def step(name, fn, telemetry=None):
    log(f"START: {name}")
    t0 = time.time()
    try:
        result = fn()
        elapsed = time.time() - t0
        log(f"OK   : {name} ({elapsed:.1f}s)")
        if telemetry is not None:
            telemetry[name] = {"ok": True, "elapsed_s": round(elapsed, 2)}
        return True, result
    except SystemExit as e:
        elapsed = time.time() - t0
        log(f"FAIL : {name} (exit {e.code}, {elapsed:.1f}s)")
        if telemetry is not None:
            telemetry[name] = {"ok": False, "elapsed_s": round(elapsed, 2), "error": f"exit {e.code}"}
        return False, None
    except Exception as e:
        elapsed = time.time() - t0
        log(f"FAIL : {name}: {e} ({elapsed:.1f}s)")
        traceback.print_exc()
        if telemetry is not None:
            telemetry[name] = {"ok": False, "elapsed_s": round(elapsed, 2), "error": str(e)[:200]}
        return False, None


def _scraper_count(filename, key):
    """Read a .tmp scraper output file and return number of items under `key`."""
    p = os.path.join(TMP_DIR, filename)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        v = d.get(key)
        return len(v) if isinstance(v, list) else None
    except Exception:
        return None


def _write_telemetry(telemetry_steps, started_iso, pipeline_t0):
    """Merge agent_tokens.json + scraper counts and write run_telemetry.json."""
    # Attach item counts to scraper steps
    counts = {
        "Scrape Jobs": _scraper_count("jobs.json", "jobs"),
        "Scrape RSS Feeds": _scraper_count("rss_articles.json", "articles"),
        "YouTube Viral Verify": _scraper_count("youtube_verified.json", "videos"),
        "Scrape YouTube Trending": _scraper_count("youtube_trending.json", "videos"),
    }
    for name, n in counts.items():
        if name in telemetry_steps and n is not None:
            telemetry_steps[name]["items"] = n

    # Agent tokens
    agent_path = os.path.join(TMP_DIR, "agent_tokens.json")
    agent_tokens = {"available": False, "reason": "agent did not write .tmp/agent_tokens.json"}
    if os.path.exists(agent_path):
        try:
            with open(agent_path, "r", encoding="utf-8") as f:
                agent_tokens = json.load(f)
        except Exception as e:
            agent_tokens = {"available": False, "reason": f"failed to parse agent_tokens.json: {e}"}

    payload = {
        "started_at": started_iso,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "total_elapsed_s": round(time.time() - pipeline_t0, 2),
        "steps": telemetry_steps,
        "agent_tokens": agent_tokens,
    }
    out = os.path.join(TMP_DIR, "run_telemetry.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    log(f"Telemetry written → {out}")


def run(dry_run=False, force_fallback=False):
    os.makedirs(TMP_DIR, exist_ok=True)
    log("=" * 60)
    log(f"DAILY PIPELINE START   dry_run={dry_run}  force_fallback={force_fallback}")
    log("=" * 60)
    pipeline_t0 = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()
    results = {}
    telemetry_steps = {}

    from tools.scrape_jobs import scrape_all_jobs
    ok, _ = step("Scrape Jobs", scrape_all_jobs, telemetry_steps)
    results["jobs"] = ok

    from tools.scrape_rss_feeds import scrape_all_feeds
    ok, _ = step("Scrape RSS Feeds", scrape_all_feeds, telemetry_steps)
    results["rss"] = ok

    from tools.youtube_viral_verify import run as run_viral
    ok, _ = step("YouTube Viral Verify", run_viral, telemetry_steps)
    results["viral"] = ok

    from tools.scrape_youtube_trending import scrape_youtube
    ok, _ = step("Scrape YouTube Trending", scrape_youtube, telemetry_steps)
    results["yt_trending"] = ok

    if not any([results["jobs"], results["rss"], results["viral"], results["yt_trending"]]):
        log("ABORT: every scraper failed")
        from tools.notify_slack import notify, tail_log
        notify("All scrapers", "Every scraper returned 0 results / errored", tail_log(LOG_FILE))
        return False

    analyzed_file = os.path.join(TMP_DIR, "analyzed_content.json")
    if not force_fallback and os.path.exists(analyzed_file):
        log("Analysis: using agent-produced analyzed_content.json")
        results["analyze"] = True
    else:
        log("Analysis: running deterministic fallback (keyword rules)")
        try:
            from tools.analyze_and_categorize import (
                load_scraped_data, save_analyzed_content, auto_categorize_fallback,
            )
            loaded = load_scraped_data()
            sections = auto_categorize_fallback(loaded)
            total = sum(len(loaded[k]) for k in loaded)
            save_analyzed_content(sections, total)
            results["analyze"] = True
        except Exception as e:
            log(f"FAIL: fallback categorizer: {e}")
            traceback.print_exc()
            results["analyze"] = False
            from tools.notify_slack import notify, tail_log
            notify("Categorizer", str(e), tail_log(LOG_FILE))
            return False

    # Write telemetry BEFORE PDF generation so the PDF can render it.
    _write_telemetry(telemetry_steps, started_iso, pipeline_t0)

    from tools.generate_pdf import generate_pdf
    ok, _ = step("Generate PDF", generate_pdf, telemetry_steps)
    results["pdf"] = ok
    if not ok:
        log("ABORT: PDF generation failed")
        from tools.notify_slack import notify, tail_log
        notify("Generate PDF", "PDF generation failed — see logs", tail_log(LOG_FILE))
        return False

    if dry_run:
        log("DRY RUN: skipping Slack send")
        results["upload"] = "skipped"
    else:
        from tools.send_to_slack import send_pdf
        from datetime import datetime as _dt
        today = _dt.now().strftime("%Y-%m-%d")
        pdf_path = os.path.join(TMP_DIR, f"ai_news_remote_jobs_{today}.pdf")
        csv_path = os.path.join(TMP_DIR, "jobs.csv")
        ok, res = step("Send PDF to Slack", lambda: send_pdf(pdf_path, csv_path), telemetry_steps)
        results["upload"] = ok and res is not None
        if not results["upload"]:
            from tools.notify_slack import notify, tail_log
            notify("Slack PDF send", "files_upload_v2 failed — check SLACK_BOT_TOKEN / SLACK_USER_ID / scopes", tail_log(LOG_FILE))

    elapsed = time.time() - pipeline_t0
    log("-" * 60)
    log("SUMMARY:")
    for k, v in results.items():
        log(f"  [{v}] {k}")
    log(f"Total: {elapsed:.1f}s")
    log("=" * 60)
    return all(v is True or v == "skipped" for v in results.values())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Skip Drive upload")
    p.add_argument("--no-agent", dest="force_fallback", action="store_true", help="Force deterministic categorizer")
    args = p.parse_args()
    success = run(dry_run=args.dry_run, force_fallback=args.force_fallback)
    sys.exit(0 if success else 1)
