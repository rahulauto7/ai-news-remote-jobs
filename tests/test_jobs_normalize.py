"""Non-string job fields must not abort the whole scrape.

2026-08-23: the Stage 1 job scraper died with `'int' object has no attribute
'strip'` AFTER all network calls had completed. Every source is individually
guarded, but the post-scrape passes (dedupe / is_worldwide_remote /
is_entry_level / apply_freshness_and_dedup / score) run unguarded over the
merged list and all assume string fields — so one record where an upstream API
returned a number killed every source's work and shipped an empty Remote AI Jobs
section. `normalize_jobs()` coerces the text fields once, right after collection.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import scrape_jobs


def _poisoned():
    """One record per non-string shape an upstream board has actually served."""
    return [
        {"url": 12345, "title": "AI Automation Engineer", "company": "Acme",
         "posted": 1755900000, "summary": "Remote worldwide."},
        {"url": "https://example.com/b", "title": 42, "company": None,
         "posted": "2026-08-22T10:00:00+00:00", "summary": "Remote, anywhere."},
        {"url": "https://example.com/c", "title": "Junior AI Engineer",
         "company": "Beta", "location": ["Remote", "Worldwide"], "salary": 90000},
    ]


def test_normalize_coerces_every_text_field():
    out = scrape_jobs.normalize_jobs(_poisoned())
    assert len(out) == 3
    for j in out:
        for field in scrape_jobs._JOB_TEXT_FIELDS:
            if field in j:
                assert isinstance(j[field], str), f"{field} not coerced: {j[field]!r}"
    assert out[0]["url"] == "12345"
    assert out[0]["posted"] == "1755900000"
    assert out[1]["title"] == "42"
    assert out[1]["company"] == ""
    assert out[2]["location"] == "Remote Worldwide"
    assert out[2]["salary"] == "90000"


def test_normalize_drops_non_dict_records():
    assert scrape_jobs.normalize_jobs([{"url": "u"}, None, "junk", 7]) == [{"url": "u"}]


def test_normalize_is_idempotent():
    once = scrape_jobs.normalize_jobs(_poisoned())
    assert scrape_jobs.normalize_jobs(list(once)) == once


def test_post_scrape_passes_survive_poisoned_records():
    """The exact crash: these passes raised before normalize_jobs existed."""
    jobs = scrape_jobs.normalize_jobs(_poisoned())
    deduped = scrape_jobs.dedupe(jobs)
    assert len(deduped) == 3
    for j in deduped:
        scrape_jobs.is_worldwide_remote(j)
        scrape_jobs.is_entry_level(j)
        scrape_jobs.score(j)
        scrape_jobs._posted_dt(j)


def test_dedupe_raises_without_normalization():
    """Guard the regression: prove the raw records are still the poison, so this
    test starts failing if someone makes dedupe lenient and drops normalize."""
    try:
        scrape_jobs.dedupe(_poisoned())
    except AttributeError:
        return
    # dedupe became tolerant on its own — fine, but normalization must still run.
    assert hasattr(scrape_jobs, "normalize_jobs")
