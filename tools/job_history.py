"""Cross-run job de-duplication history.

Remembers which job URLs were surfaced to the user on which date so the daily
pipeline can rotate the Remote Jobs section instead of showing the same open
roles every day (the company ATS boards + monthly HN thread barely change).

Stored in data/jobs_seen.json — NOT .tmp/, which is disposable and wiped between
runs. Maps job URL -> last date (YYYY-MM-DD) it was shown. Entries older than
PRUNE_DAYS are dropped on each write so the file stays small.
"""

import json
import os
from datetime import date, datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "jobs_seen.json")
PRUNE_DAYS = 30


def load_history() -> dict:
    """Return {url: last_shown_date_iso}. Empty dict if no/invalid history."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        seen = d.get("seen") if isinstance(d, dict) else None
        return seen if isinstance(seen, dict) else {}
    except Exception:
        return {}


def recently_seen_urls(days: int) -> set:
    """Set of job URLs shown within the last `days` days (ISO date compare)."""
    if days <= 0:
        return set()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return {u for u, d in load_history().items() if d >= cutoff}


def record_shown(urls) -> int:
    """Stamp today's date on each URL, prune entries older than PRUNE_DAYS,
    and persist. Returns the number of URLs retained in history."""
    seen = load_history()
    today = date.today().isoformat()
    for u in urls:
        if u:
            seen[u] = today
    cutoff = (date.today() - timedelta(days=PRUNE_DAYS)).isoformat()
    seen = {u: d for u, d in seen.items() if d >= cutoff}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": datetime.now().isoformat(), "seen": seen},
            f, indent=2,
        )
    return len(seen)
