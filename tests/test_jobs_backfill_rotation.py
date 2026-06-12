"""Part 1: thin-pool job backfill rotates the back-catalog.

When the fresh pool is below JOBS_MIN_POOL, apply_freshness_and_dedup backfills
with recently-seen roles but must surface the LEAST-recently-seen first so the
section rotates instead of replaying the same roles every run.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs, job_history


def _jobs(*urls):
    # No `posted` field -> _posted_dt returns None -> kept as fresh.
    return [{"url": u, "title": f"Job {u}", "company": "Acme"} for u in urls]


def test_backfill_surfaces_oldest_seen_first(monkeypatch):
    monkeypatch.setenv("JOBS_MIN_POOL", "2")
    monkeypatch.setenv("JOBS_SEEN_DAYS", "7")
    monkeypatch.setenv("JOBS_FRESH_DAYS", "45")

    jobs = _jobs("a", "b", "c", "d")  # scrape order a,b,c,d
    # All four were shown recently -> zero "new" jobs -> backfill must fire.
    monkeypatch.setattr(job_history, "recently_seen_urls", lambda days: {"a", "b", "c", "d"})
    monkeypatch.setattr(job_history, "load_history", lambda: {
        "a": "2026-06-10",   # most recently shown
        "b": "2026-06-01",
        "c": "2026-06-05",
        "d": "2026-05-20",   # least recently shown
    })

    out = scrape_jobs.apply_freshness_and_dedup(jobs)

    # min_pool=2 -> two oldest-seen first: d (May 20) then b (Jun 01).
    # Scrape order would have been ["a", "b"]; rotation makes it ["d", "b"].
    assert [j["url"] for j in out] == ["d", "b"]


def test_no_backfill_when_new_meets_min_pool(monkeypatch):
    monkeypatch.setenv("JOBS_MIN_POOL", "2")
    monkeypatch.setenv("JOBS_SEEN_DAYS", "7")
    monkeypatch.setenv("JOBS_FRESH_DAYS", "45")

    jobs = _jobs("a", "b", "c", "d")
    # Only "d" was seen recently; a,b,c are new -> 3 new >= min_pool(2).
    monkeypatch.setattr(job_history, "recently_seen_urls", lambda days: {"d"})
    monkeypatch.setattr(job_history, "load_history", lambda: {"d": "2026-05-20"})

    out = scrape_jobs.apply_freshness_and_dedup(jobs)
    urls = [j["url"] for j in out]

    assert urls == ["a", "b", "c"]   # no repeats added
    assert "d" not in urls


def test_history_import_failure_degrades_gracefully(monkeypatch):
    """If load_history blows up, recent/last_shown degrade to empty and every
    fresh job is treated as new (no crash, no backfill)."""
    monkeypatch.setenv("JOBS_MIN_POOL", "2")

    def _boom(*a, **k):
        raise RuntimeError("history file corrupt")

    jobs = _jobs("a", "b")
    monkeypatch.setattr(job_history, "recently_seen_urls", _boom)
    monkeypatch.setattr(job_history, "load_history", _boom)

    out = scrape_jobs.apply_freshness_and_dedup(jobs)
    assert [j["url"] for j in out] == ["a", "b"]
