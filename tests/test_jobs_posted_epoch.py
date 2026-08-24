"""Jobs `posted` field must survive non-string dates.

2026-08-24 Stage 1: Himalayas returns `pubDate` as an epoch INTEGER, which flowed
straight into the job dict. `_posted_dt` then ran `(job.get("posted") or "").strip()`
and raised ``'int' object has no attribute 'strip'``, aborting the whole jobs step
after every scraper had already run — the PDF shipped with an empty Remote AI Jobs
section. `normalize_posted()` now coerces at the source and `_posted_dt` accepts
epochs defensively.
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs as sj


def test_normalize_posted_epoch_seconds():
    iso = sj.normalize_posted(1756000000)
    assert iso.startswith("2025-")
    assert datetime.fromisoformat(iso).tzinfo is not None


def test_normalize_posted_epoch_milliseconds():
    secs = sj.normalize_posted(1756000000)
    millis = sj.normalize_posted(1756000000000)
    assert secs == millis


def test_normalize_posted_passes_iso_through():
    assert sj.normalize_posted("2026-08-24T09:30:00+00:00") == "2026-08-24T09:30:00+00:00"


def test_normalize_posted_handles_empty_and_none():
    assert sj.normalize_posted(None) == ""
    assert sj.normalize_posted("") == ""
    assert sj.normalize_posted(0) == ""


def test_posted_dt_accepts_int_without_raising():
    """The exact 2026-08-24 crash: an int `posted` must not blow up."""
    dt = sj._posted_dt({"posted": 1756000000})
    assert dt is not None and dt.tzinfo is not None


def test_posted_dt_accepts_digit_string():
    assert sj._posted_dt({"posted": "1756000000"}) == sj._posted_dt({"posted": 1756000000})


def test_posted_dt_still_parses_iso_and_rfc822():
    assert sj._posted_dt({"posted": "2026-08-24T09:30:00Z"}) == datetime(
        2026, 8, 24, 9, 30, tzinfo=timezone.utc)
    assert sj._posted_dt({"posted": "Mon, 24 Aug 2026 09:30:00 +0000"}) == datetime(
        2026, 8, 24, 9, 30, tzinfo=timezone.utc)


def test_posted_dt_none_for_missing_or_garbage():
    assert sj._posted_dt({}) is None
    assert sj._posted_dt({"posted": ""}) is None
    assert sj._posted_dt({"posted": "not a date"}) is None


def test_freshness_pass_survives_int_posted():
    """apply_freshness_and_dedup is where the crash surfaced — it must not raise."""
    now = datetime.now(timezone.utc).timestamp()
    jobs = [
        {"title": "AI Automation Engineer", "company": "Acme",
         "url": "https://example.com/a", "posted": int(now), "source": "Himalayas"},
        {"title": "LLM Engineer", "company": "Beta",
         "url": "https://example.com/b", "posted": "", "source": "Lever"},
    ]
    out = sj.apply_freshness_and_dedup(jobs)
    assert isinstance(out, list)
