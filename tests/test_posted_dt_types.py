"""`posted` arrives in several shapes; none of them may crash the jobs scrape.

Regression for the 2026-08-29 Stage 1 failure: a board returned an int epoch in
`posted`, `_posted_dt` called `.strip()` on it, the AttributeError aborted the
whole jobs step and section 1 of the PDF shipped empty.
"""
from datetime import datetime, timezone

from tools.scrape_jobs import _posted_dt


def test_int_epoch_seconds_does_not_crash():
    ts = int(datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc).timestamp())
    assert _posted_dt({"posted": ts}) == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def test_int_epoch_milliseconds():
    ms = int(datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc).timestamp()) * 1000
    assert _posted_dt({"posted": ms}) == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def test_numeric_string_epoch():
    ts = int(datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc).timestamp())
    assert _posted_dt({"posted": str(ts)}) == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def test_iso_string_still_works():
    got = _posted_dt({"posted": "2026-08-20T12:00:00Z"})
    assert got == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def test_rfc822_string_still_works():
    got = _posted_dt({"posted": "Thu, 20 Aug 2026 12:00:00 +0000"})
    assert got == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def test_missing_and_junk_are_undated_not_errors():
    assert _posted_dt({}) is None
    assert _posted_dt({"posted": ""}) is None
    assert _posted_dt({"posted": None}) is None
    assert _posted_dt({"posted": True}) is None
    assert _posted_dt({"posted": 0}) is None
    assert _posted_dt({"posted": "not a date"}) is None
