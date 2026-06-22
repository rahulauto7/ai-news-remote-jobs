"""
Master orchestrator for the daily AI News + Remote Jobs pipeline.

Runs in sequence:
  1. scrape RSS feeds + hackathons + YouTube viral verify + YouTube trending
  2. scrape Instagram reels + verify
  3. scrape AI trends
  4. scrape jobs + rank against user_profile.md
  5. ANALYZE — Claude agent analyzer (default). DeepSeek is opt-in only
     via `--analyzer deepseek` or `ANALYZER=deepseek`. Final fallback is
     the deterministic keyword categorizer.
  6. merge native hackathons into product_showcase_opportunities (no cap)
  7. generate YouTube content ideas + section analysis placeholders
     (cloud agent overwrites them before PDF render)
  8. generate PDF
  9. send PDF to Slack DM (skipped with --dry-run)

Each step is wrapped in try/except — failures don't kill the run.
Use --dry-run to skip the Slack send step.
Use --analyzer deepseek (or env ANALYZER=deepseek) to opt into DeepSeek.
Use --no-agent to force the deterministic keyword fallback only.
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

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

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
        "Rank Jobs (profile-aware)": _scraper_count("jobs_ranked.json", "jobs"),
        "Scrape RSS Feeds": _scraper_count("rss_articles.json", "articles"),
        "Scrape Hackathons": _scraper_count("hackathons.json", "hackathons"),
        "YouTube Viral Verify": _scraper_count("youtube_verified.json", "videos"),
        "Scrape YouTube Trending": _scraper_count("youtube_trending.json", "videos"),
        "Scrape Instagram Reels": _scraper_count("instagram_reels.json", "reels"),
        "Instagram Viral Verify": _scraper_count("instagram_verified.json", "reels"),
        "Scrape AI Trends": _scraper_count("ai_trends.json", "topics"),
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


def run(dry_run=False, force_fallback=False, analyzer="agent"):
    os.makedirs(TMP_DIR, exist_ok=True)
    log("=" * 60)
    log(f"DAILY PIPELINE START   dry_run={dry_run}  force_fallback={force_fallback}  analyzer={analyzer}")
    log("=" * 60)
    pipeline_t0 = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()
    results = {}
    telemetry_steps = {}

    from tools.scrape_rss_feeds import scrape_all_feeds
    ok, _ = step("Scrape RSS Feeds", scrape_all_feeds, telemetry_steps)
    results["rss"] = ok

    from tools.scrape_hackathons import main as scrape_hackathons_main
    ok, _ = step("Scrape Hackathons", scrape_hackathons_main, telemetry_steps)
    results["hackathons"] = ok

    from tools.youtube_viral_verify import run as run_viral
    ok, _ = step("YouTube Viral Verify", run_viral, telemetry_steps)
    results["viral"] = ok

    from tools.scrape_youtube_trending import scrape_youtube
    ok, _ = step("Scrape YouTube Trending", scrape_youtube, telemetry_steps)
    results["yt_trending"] = ok

    from tools.scrape_instagram_reels import scrape_instagram
    ok, _ = step("Scrape Instagram Reels", scrape_instagram, telemetry_steps)
    results["ig_scrape"] = ok

    from tools.instagram_viral_verify import run as run_ig_verify
    ok, _ = step("Instagram Viral Verify", run_ig_verify, telemetry_steps)
    results["ig_verify"] = ok

    from tools.scrape_ai_trends import run as run_ai_trends
    ok, _ = step("Scrape AI Trends", run_ai_trends, telemetry_steps)
    results["ai_trends"] = ok

    from tools.scrape_jobs import scrape_all_jobs
    ok, _ = step("Scrape Jobs", scrape_all_jobs, telemetry_steps)
    results["jobs"] = ok

    from tools.job_match import run as run_job_match
    ok, _ = step("Rank Jobs (profile-aware)", run_job_match, telemetry_steps)
    results["jobs_ranked"] = ok

    if not any([results["jobs"], results["rss"], results["hackathons"], results["viral"], results["yt_trending"]]):
        log("ABORT: every scraper failed")
        return False

    # "No exception thrown" is not the same as "got content". A fully
    # network-blocked run returns empty from every scraper WITHOUT raising, so the
    # any()-based guard above passes while the PDF would ship empty (only the
    # hardcoded accelerator + benchmark seeds survive). RSS is the backbone of 14+
    # sections and pulls a rolling 7-day pool, so rss_articles == 0 is the canonical
    # signature of a blocked/broken run, not a quiet news day. Treat it as fatal so
    # the cloud agent fires the Slack failure alert instead of delivering a hollow PDF.
    rss_n = _scraper_count("rss_articles.json", "articles") or 0
    jobs_n = _scraper_count("jobs.json", "jobs") or 0
    log(f"Content gate: rss_articles={rss_n} jobs={jobs_n}")
    if rss_n == 0:
        log("ABORT: zero RSS articles — network blocked or all feeds dead "
            "(would ship an empty PDF). Failing so the cloud Slack alert fires.")
        return False

    analyzed_file = os.path.join(TMP_DIR, "analyzed_content.json")
    # Drop stale analyzed_content.json so each run is fresh.
    if not force_fallback and os.path.exists(analyzed_file):
        try:
            os.remove(analyzed_file)
        except Exception:
            pass

    # Drop stale YouTube agent artifacts too — otherwise a previous run's empty
    # placeholder (or yesterday's ideas) persists and the PDF section renders
    # blank/stale. The placeholder step below re-creates fresh empties; the cloud
    # agent overwrites them with this run's real content before the PDF stage.
    for fname in ("youtube_content_ideas.json", "youtube_section_analysis.json"):
        fp = os.path.join(TMP_DIR, fname)
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    results["analyze"] = False
    use_deepseek = (analyzer == "deepseek") and not force_fallback
    if use_deepseek and os.environ.get("DEEPSEEK_API_KEY", "").strip():
        from tools.deepseek_analyze import main as deepseek_analyze_main
        rc_holder = {}
        def _run_deepseek():
            rc = deepseek_analyze_main()
            rc_holder["rc"] = rc
            return rc == 0
        ok, _ = step("DeepSeek Analysis", _run_deepseek, telemetry_steps)
        results["analyze"] = ok and os.path.exists(analyzed_file)
        if not results["analyze"]:
            log(f"DeepSeek analysis failed (rc={rc_holder.get('rc')}) — falling back to agent_analyze")
    elif use_deepseek:
        log("--analyzer deepseek requested but DEEPSEEK_API_KEY not set — using agent analyzer")

    # Default analyzer = Claude agent (no paid API calls).
    if not results["analyze"] and not force_fallback:
        from tools.agent_analyze import main as agent_analyze_main
        ok, _ = step("Agent Self-Analysis", agent_analyze_main, telemetry_steps)
        results["analyze"] = ok and os.path.exists(analyzed_file)

    if not results["analyze"]:
        log("Analysis: all LLM/agent paths failed — running keyword fallback")
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
            return False

    # Merge native hackathons into the product_showcase_opportunities section.
    # This is authoritative — native scrapes carry direct apply URLs / deadlines
    # the LLM categorizer can't produce. User explicitly cannot afford to miss
    # any open AI hackathon.
    def _merge_native_hackathons():
        from urllib.parse import urlparse
        hpath = os.path.join(TMP_DIR, "hackathons.json")
        apath = os.path.join(TMP_DIR, "analyzed_content.json")
        if not (os.path.exists(hpath) and os.path.exists(apath)):
            return True
        with open(hpath, "r", encoding="utf-8") as f:
            hpayload = json.load(f)
        with open(apath, "r", encoding="utf-8") as f:
            apayload = json.load(f)

        sections = apayload.get("sections") or {}
        existing = sections.get("product_showcase_opportunities") or []

        # Split native items into hackathons vs accelerators so the PDF can show
        # BOTH as labeled sub-blocks (user must see hackathons AND accelerators).
        native_hackathons, native_accelerators = [], []
        native_urls = set()
        for h in hpayload.get("hackathons", []) or []:
            apply_url = h.get("apply_url") or ""
            if not apply_url:
                continue
            platform = h.get("platform", "") or ""
            is_accel = platform.lower().startswith("accelerator")
            item = {
                "title": h.get("title", "Untitled"),
                "url": apply_url,
                "submission_url": apply_url,
                "platform_type": platform,
                "region": h.get("region", "Worldwide"),
                "deadline_iso": h.get("deadline_iso"),
                "prize_summary": h.get("prize_summary"),
                "eligibility": h.get("eligibility"),
                "benefits": h.get("benefits"),
                "summary": h.get("description", ""),
                "relevance": 5,
                "source": "native_accelerator" if is_accel else "native_hackathon",
                "group": "accelerator" if is_accel else "hackathon",
            }
            (native_accelerators if is_accel else native_hackathons).append(item)
            try:
                native_urls.add(urlparse(apply_url).netloc.lower())
            except Exception:
                pass

        # Drop LLM/news items whose URL host matches a native item (avoid dup).
        # Remaining LLM/news showcase items are event-type → group with hackathons.
        kept_existing = []
        for it in existing:
            u = (it.get("url") or it.get("submission_url") or "").strip()
            host = ""
            if u:
                try:
                    host = urlparse(u).netloc.lower()
                except Exception:
                    host = ""
            if host and host in native_urls:
                continue
            it.setdefault("group", "hackathon")
            kept_existing.append(it)

        # Sort each group by deadline asc (null/rolling last), then concatenate with
        # reserved caps so accelerators always survive instead of being pushed off.
        def _sort_key(it):
            d = it.get("deadline_iso")
            return (1, "") if not d else (0, d)
        hackathons = sorted(native_hackathons + kept_existing, key=_sort_key)
        accelerators = sorted(native_accelerators, key=_sort_key)
        HACK_CAP, ACC_CAP = 15, 8
        merged = hackathons[:HACK_CAP] + accelerators[:ACC_CAP]

        sections["product_showcase_opportunities"] = merged
        apayload["sections"] = sections
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(apayload, f, indent=2, ensure_ascii=False)
        log(f"Merged showcase: hackathons={len(hackathons[:HACK_CAP])} "
            f"accelerators={len(accelerators[:ACC_CAP])} "
            f"(native_hack={len(native_hackathons)} native_accel={len(native_accelerators)} "
            f"kept_existing={len(kept_existing)})")
        return True

    step("Merge Native Hackathons", _merge_native_hackathons, telemetry_steps)

    # Cross-day dedup + min-3 backfill + benchmark standings seed. Drops stories
    # surfaced in the last 7 days (so consecutive PDFs don't repeat), tops up any
    # RSS section below 3 from the unrouted pool, and seeds the "top model per
    # category" standings into ai_model_benchmarks. Must run AFTER analysis +
    # hackathon merge and BEFORE the YouTube-ideas step (which synthesises its
    # fallback pitches from the finalised sections).
    from tools.dedupe_and_backfill import main as dedupe_backfill
    step("Dedup + Backfill Sections", dedupe_backfill, telemetry_steps)

    # Finalize the deferred quantum/RSI dedup (see finalize_qrsi_dedup.py
    # docstring). No AGENT ENRICHMENT runs in this script, so this is the only
    # dedup pass those two sections get when this is the whole pipeline (Stage 1
    # / local runs). The cloud routine (Stage 2) calls this again after its own
    # enrichment step, which is what actually repopulates these sections.
    from tools.finalize_qrsi_dedup import main as finalize_qrsi_dedup
    step("Finalize Quantum/RSI Dedup", finalize_qrsi_dedup, telemetry_steps)

    # Re-run the strict last-24h + AI-only guard. In this script it's a harmless
    # second pass (main() already sanitized), but it's the SAME entry the Stage 2
    # cloud routine must call AFTER its AGENT ENRICHMENT step — enrichment adds/
    # rewrites news items the early sanitize never sees, so without a post-
    # enrichment pass >24h items leak into the PDF. Strict mode drops any news
    # item that can't be proven within 24h (missing/unparseable date included).
    from tools.dedupe_and_backfill import sanitize_only
    step("Re-sanitize (strict 24h)", sanitize_only, telemetry_steps)

    # Ensure YouTube ideas + section analysis files exist before the PDF step.
    # generate_youtube_ideas now writes a deterministic 3-idea fallback from the
    # finalised analyzed_content.json; on cloud runs the Claude agent overwrites
    # these with richer real content BEFORE this script reaches PDF.
    from tools.generate_youtube_ideas import main as gen_youtube_ideas
    step("Generate YouTube Ideas (fallback)", gen_youtube_ideas, telemetry_steps)

    # Write telemetry BEFORE PDF generation so the PDF can render it.
    _write_telemetry(telemetry_steps, started_iso, pipeline_t0)

    from tools.generate_pdf import generate_pdf
    ok, _ = step("Generate PDF", generate_pdf, telemetry_steps)
    results["pdf"] = ok
    if not ok:
        log("ABORT: PDF generation failed")
        return False

    # Slack delivery is handled by the cloud claude.ai agent connector, not local code.
    log("Slack delivery: handled by cloud agent connector — skipping local send")
    results["upload"] = "skipped"

    elapsed = time.time() - pipeline_t0
    log("-" * 60)
    log("SUMMARY:")
    for k, v in results.items():
        log(f"  [{v}] {k}")
    log(f"Total: {elapsed:.1f}s")
    log("=" * 60)
    # Success = the deliverable (PDF) was produced. Optional scrapers failing
    # (e.g. YouTube/Instagram without an API key, a rate-limited job board) leave
    # a section thin but must NOT fail the whole run — every genuinely fatal
    # condition (all scrapers dead, zero RSS, analysis failed, PDF failed) already
    # returned False above. A strict all(results) here wrongly exited 1 on a valid
    # PDF and skipped the publish-state step.
    failed = [k for k, v in results.items() if not (v is True or v == "skipped")]
    if failed:
        log(f"Non-fatal step failures (PDF still shipped): {', '.join(failed)}")
    return results.get("pdf") is True


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Skip Slack send")
    p.add_argument(
        "--analyzer",
        choices=("agent", "deepseek"),
        default=os.environ.get("ANALYZER", "agent"),
        help="Analyzer to use. Default: agent (Claude agent, no paid API). "
             "Pass 'deepseek' to opt into DeepSeek (requires DEEPSEEK_API_KEY).",
    )
    p.add_argument(
        "--no-agent",
        dest="force_fallback",
        action="store_true",
        help="Force deterministic keyword categorizer (skips both analyzers).",
    )
    args = p.parse_args()
    success = run(
        dry_run=args.dry_run,
        force_fallback=args.force_fallback,
        analyzer=args.analyzer,
    )
    sys.exit(0 if success else 1)
