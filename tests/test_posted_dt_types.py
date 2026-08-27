"""`_posted_dt` must survive every `posted` shape the job sources actually emit.

Regression for 2026-08-27: Arbeitnow returns `created_at` as a bare int epoch,
so `(job.get("posted") or "").strip()` raised
`AttributeError: 'int' object has no attribute 'strip'` inside
apply_freshness_and_dedup. That aborted the ENTIRE jobs scrape after filtering
had already produced 50 worldwide-remote entry-level roles, and the PDF shipped
with an empty Remote AI Jobs section.
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs, job_history

EPOCH = 1787000000  # 2026-08-17T20:53:20Z


def test_int_epoch_parses_and_does_not_raise():
    assert scrape_jobs._posted_dt({"posted": EPOCH}) == datetime.fromtimestamp(
        EPOCH, tz=timezone.utc)


def test_numeric_string_epoch_parses():
    assert scrape_jobs._posted_dt({"posted": str(EPOCH)}) == datetime.fromtimestamp(
        EPOCH, tz=timezone.utc)


def test_iso_and_rfc822_still_parse():
    iso = scrape_jobs._posted_dt({"posted": "2026-08-27T10:00:00Z"})
    rfc = scrape_jobs._posted_dt({"posted": "Thu, 27 Aug 2026 10:00:00 GMT"})
    assert iso == datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
    assert rfc == datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)


def test_missing_empty_and_unparseable_return_none():
    for value in ({}, {"posted": ""}, {"posted": None}, {"posted": "not a date"}):
        assert scrape_jobs._posted_dt(value) is None


def test_bool_is_not_read_as_an_epoch():
    # True is an int subclass; treating it as epoch 1970 would silently age a job out.
    assert scrape_jobs._posted_dt({"posted": True}) is None


def test_freshness_pass_survives_an_int_posted(monkeypatch):
    monkeypatch.setenv("JOBS_FRESH_DAYS", "36500")
    monkeypatch.setenv("JOBS_SEEN_DAYS", "0")
    monkeypatch.setenv("JOBS_MIN_POOL", "0")
    monkeypatch.setattr(job_history, "recently_seen_urls", lambda days: set())
    monkeypatch.setattr(job_history, "load_history", lambda: {})

    jobs = [
        {"url": "https://x/1", "title": "AI Engineer", "company": "Acme", "posted": EPOCH},
        {"url": "https://x/2", "title": "ML Engineer", "company": "Acme",
         "posted": "2026-08-27T10:00:00Z"},
    ]
    assert len(scrape_jobs.apply_freshness_and_dedup(jobs)) == 2
