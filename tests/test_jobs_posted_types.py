"""Job boards are not type-stable: Himalayas returns `pubDate` as a Unix epoch
INT while every other board returns an ISO/RFC822 string. `_posted_dt` called
`.strip()` on it, and the resulting AttributeError killed the whole jobs step —
the 2026-08-21 run shipped a PDF with an empty Remote AI Jobs section.
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs as sj


def test_posted_dt_accepts_epoch_seconds():
    dt = sj._posted_dt({"posted": 1755800000})
    assert dt is not None and dt.tzinfo is not None
    assert dt.year == 2025


def test_posted_dt_accepts_epoch_milliseconds():
    dt = sj._posted_dt({"posted": 1755800000000})
    assert dt is not None and dt.year == 2025


def test_posted_dt_survives_junk_types():
    for junk in (None, "", "not a date", {}, [], True, object()):
        assert sj._posted_dt({"posted": junk}) is None


def test_posted_dt_still_parses_iso_and_rfc822():
    assert sj._posted_dt({"posted": "2026-08-21T10:00:00Z"}).year == 2026
    assert sj._posted_dt({"posted": "Thu, 21 Aug 2026 10:00:00 +0000"}).year == 2026


def test_freshness_pass_does_not_explode_on_int_posted():
    """One badly-typed record must never zero the entire section."""
    jobs = [
        {"title": "AI Automation Engineer", "company": "X", "url": "https://a",
         "posted": 1755800000},
        {"title": "LLM Engineer", "company": "Y", "url": "https://b",
         "posted": "2026-08-21T10:00:00Z"},
    ]
    out = sj.apply_freshness_and_dedup(jobs)
    assert isinstance(out, list)


def test_text_coerces_any_json_value():
    assert sj._text(" hi ") == "hi"
    assert sj._text(None) == ""
    assert sj._text(42) == "42"
    assert sj._text({"a": 1}) == ""
    assert sj._text(True) == ""
