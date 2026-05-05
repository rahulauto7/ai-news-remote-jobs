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
import os
import sys
import time
import traceback
from datetime import datetime

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


def step(name, fn):
    log(f"START: {name}")
    t0 = time.time()
    try:
        result = fn()
        log(f"OK   : {name} ({time.time() - t0:.1f}s)")
        return True, result
    except SystemExit as e:
        log(f"FAIL : {name} (exit {e.code}, {time.time() - t0:.1f}s)")
        return False, None
    except Exception as e:
        log(f"FAIL : {name}: {e} ({time.time() - t0:.1f}s)")
        traceback.print_exc()
        return False, None


def run(dry_run=False, force_fallback=False):
    os.makedirs(TMP_DIR, exist_ok=True)
    log("=" * 60)
    log(f"DAILY PIPELINE START   dry_run={dry_run}  force_fallback={force_fallback}")
    log("=" * 60)
    pipeline_t0 = time.time()
    results = {}

    from tools.scrape_jobs import scrape_all_jobs
    ok, _ = step("Scrape Jobs", scrape_all_jobs)
    results["jobs"] = ok

    from tools.scrape_rss_feeds import scrape_all_feeds
    ok, _ = step("Scrape RSS Feeds", scrape_all_feeds)
    results["rss"] = ok

    from tools.youtube_viral_verify import run as run_viral
    ok, _ = step("YouTube Viral Verify", run_viral)
    results["viral"] = ok

    from tools.scrape_youtube_trending import scrape_youtube
    ok, _ = step("Scrape YouTube Trending", scrape_youtube)
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

    from tools.generate_pdf import generate_pdf
    ok, _ = step("Generate PDF", generate_pdf)
    results["pdf"] = ok
    if not ok:
        log("ABORT: PDF generation failed")
        from tools.notify_slack import notify, tail_log
        notify("Generate PDF", "PDF generation failed — see logs", tail_log(LOG_FILE))
        return False

    if dry_run:
        log("DRY RUN: skipping Drive upload")
        results["upload"] = "skipped"
    else:
        from tools.upload_to_drive import upload_daily_outputs
        ok, res = step("Upload to Drive", upload_daily_outputs)
        results["upload"] = ok
        if not ok or res is None:
            from tools.notify_slack import notify, tail_log
            notify("Drive upload", "Upload returned no link — check service-account / folder ID", tail_log(LOG_FILE))

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
