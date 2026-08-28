"""Numeric `posted` fields must not crash the jobs scrape.

Regression for the 2026-08-28 Stage 1 failure: Himalayas returns `pubDate` as a
Unix epoch **int**, which reached `_posted_dt`'s `.strip()` and aborted the whole
"Scrape Jobs" step with `'int' object has no attribute 'strip'` — shipping a PDF
with an empty Remote AI Jobs section (PDF section 1).
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import job_match, scrape_jobs

EPOCH_S = 1787956915                      # 2026-08-28T22:41:55Z
EXPECTED = datetime.fromtimestamp(EPOCH_S, tz=timezone.utc)


def test_posted_dt_accepts_int_epoch_seconds():
    assert scrape_jobs._posted_dt({"posted": EPOCH_S}) == EXPECTED


def test_posted_dt_accepts_int_epoch_milliseconds():
    assert scrape_jobs._posted_dt({"posted": EPOCH_S * 1000}) == EXPECTED


def test_posted_dt_accepts_digit_string_epoch():
    assert scrape_jobs._posted_dt({"posted": str(EPOCH_S)}) == EXPECTED


def test_posted_dt_still_parses_iso_and_rfc822():
    iso = scrape_jobs._posted_dt({"posted": "2026-08-28T22:41:55Z"})
    assert iso == EXPECTED
    rfc = scrape_jobs._posted_dt({"posted": "Fri, 28 Aug 2026 22:41:55 +0000"})
    assert rfc == EXPECTED


def test_posted_dt_returns_none_for_unusable_values():
    for bad in (None, "", "   ", 0, False, True, "not a date"):
        assert scrape_jobs._posted_dt({"posted": bad}) is None


def test_freshness_pass_survives_a_numeric_posted():
    """The real failure path: one Himalayas-shaped job in the pool."""
    jobs = [
        {"url": "https://himalayas.app/jobs/1", "title": "AI Engineer",
         "company": "Acme", "posted": EPOCH_S},
        {"url": "https://example.com/2", "title": "Automation Engineer",
         "company": "Beta", "posted": "2026-08-28T10:00:00Z"},
    ]
    kept = scrape_jobs.apply_freshness_and_dedup(jobs)
    assert {j["url"] for j in kept} == {j["url"] for j in jobs}


def test_iso_posted_normalises_epoch_to_string():
    assert scrape_jobs._iso_posted(EPOCH_S) == EXPECTED.isoformat()
    assert scrape_jobs._iso_posted(EPOCH_S * 1000) == EXPECTED.isoformat()
    assert scrape_jobs._iso_posted("2026-08-28T22:41:55Z") == "2026-08-28T22:41:55Z"
    assert scrape_jobs._iso_posted(None) == ""
    assert scrape_jobs._iso_posted(0) == ""


def test_recency_key_sorts_mixed_int_and_str_without_typeerror():
    jobs = [{"posted": EPOCH_S}, {"posted": "2026-08-28T10:00:00Z"}, {}]
    # Raised TypeError: '<' not supported between 'int' and 'str' before the fix.
    sorted(jobs, key=job_match._recency_key, reverse=True)
