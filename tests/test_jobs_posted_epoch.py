"""Regression: a numeric `posted` must not abort the whole jobs scrape.

Stage 1 on 2026-08-30 failed with "'int' object has no attribute 'strip'" and
shipped a PDF whose Remote AI Jobs section was empty. Some boards (Himalayas
`pubDate`) return the publish time as a JSON *number*, and _posted_dt called
.strip() on it. It now accepts epoch seconds and milliseconds, and the dedup
pass str()s the fields a board could also return as numbers.
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs


def test_posted_epoch_seconds():
    ts = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    got = scrape_jobs._posted_dt({"posted": int(ts.timestamp())})
    assert got == ts


def test_posted_epoch_milliseconds():
    ts = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    got = scrape_jobs._posted_dt({"posted": int(ts.timestamp()) * 1000})
    assert got == ts


def test_posted_numeric_string():
    ts = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    got = scrape_jobs._posted_dt({"posted": str(int(ts.timestamp()))})
    assert got == ts


def test_posted_iso_and_rfc822_still_parse():
    assert scrape_jobs._posted_dt(
        {"posted": "2026-08-30T12:00:00Z"}
    ) == datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert scrape_jobs._posted_dt(
        {"posted": "Sun, 30 Aug 2026 12:00:00 +0000"}
    ) == datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def test_posted_missing_or_junk_is_none():
    for raw in (None, "", "   ", "not a date", 0, True):
        assert scrape_jobs._posted_dt({"posted": raw}) is None


def test_dedup_survives_numeric_fields():
    jobs = [
        {"url": 12345, "title": 678, "company": 9},
        {"url": 12345, "title": 678, "company": 9},
        {"url": "https://example.com/a", "title": "AI Engineer", "company": "Acme"},
    ]
    out = scrape_jobs.dedupe(jobs)
    assert len(out) == 2
