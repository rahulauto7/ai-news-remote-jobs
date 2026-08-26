"""Job boards are not type-stable — a numeric field must not kill the section.

Stage 1 on 2026-08-26 aborted the whole "Scrape Jobs" step with
"'int' object has no attribute 'strip'", so the PDF shipped with an empty
Remote AI Jobs section. The cause was `(value or "").strip()` on board-API
fields that can legitimately arrive as ints (RemoteOK epoch dates, numeric ids).
`_as_text` coerces instead of crashing, and `_posted_dt` now understands a bare
Unix epoch rather than discarding it.
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs


def test_as_text_coerces_without_raising():
    assert scrape_jobs._as_text(1756252800) == "1756252800"
    assert scrape_jobs._as_text("  padded  ") == "padded"
    assert scrape_jobs._as_text(None) == ""
    assert scrape_jobs._as_text(True) == ""       # bool is not a real value here
    assert scrape_jobs._as_text(["a"]) == ""
    assert scrape_jobs._as_text({"a": 1}) == ""


def test_posted_dt_parses_epoch_seconds_and_millis():
    expected = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    ts = int(expected.timestamp())
    assert scrape_jobs._posted_dt({"posted": ts}) == expected
    assert scrape_jobs._posted_dt({"posted": str(ts)}) == expected
    assert scrape_jobs._posted_dt({"posted": ts * 1000}) == expected


def test_posted_dt_treats_missing_and_zero_as_undated():
    # 0 means "no date", not 1970 — an undated job is kept, not dropped as stale.
    for value in (0, "0", "", None):
        assert scrape_jobs._posted_dt({"posted": value}) is None


def test_posted_dt_still_parses_iso_and_rfc822():
    assert scrape_jobs._posted_dt({"posted": "2026-08-26T10:00:00Z"}).year == 2026
    assert scrape_jobs._posted_dt(
        {"posted": "Tue, 26 Aug 2026 10:00:00 +0000"}).year == 2026
    assert scrape_jobs._posted_dt({"posted": "not a date"}) is None


def test_dedupe_survives_numeric_rows():
    """The exact crash shape from Stage 1: every field an int."""
    rows = [
        {"title": 123, "company": 456, "url": 789, "posted": 1756252800},
        {"title": 123, "company": 456, "url": 789, "posted": 1756252800},
        {"title": "AI Automation Engineer", "company": "Acme", "url": "https://x/1"},
    ]
    out = scrape_jobs.dedupe(rows)
    assert len(out) == 2          # the duplicate numeric row is collapsed
