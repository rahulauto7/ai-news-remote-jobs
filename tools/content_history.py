"""Cross-run content de-duplication history (news / videos / reels).

Generalises the jobs-history pattern (see tools/job_history.py) to any content
type so the daily pipeline can rotate the News, Viral YouTube, and Instagram
sections instead of re-showing the same items every day (the 7-day RSS window
otherwise overlaps ~6 of 7 days between consecutive runs).

Stored in data/content_seen.json — NOT .tmp/, which is disposable and wiped
between runs. Top-level namespaces ("news", "youtube", "instagram") each map an
item id (URL / video_id / reel shortcode) -> the last date (YYYY-MM-DD) it was
shown. Entries older than PRUNE_DAYS are dropped on each write so the file stays
small. Jobs keep their own store (data/jobs_seen.json) and are untouched.
"""

import json
import os
from datetime import date, datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "content_seen.json")
PRUNE_DAYS = 30

VALID_NAMESPACES = ("news", "youtube", "instagram")


def _load_all() -> dict:
    """Return the full {namespace: {id: date}} map. Empty dict if missing/invalid."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        seen = d.get("seen") if isinstance(d, dict) else None
        return seen if isinstance(seen, dict) else {}
    except Exception:
        return {}


def load_history(namespace: str) -> dict:
    """Return {id: last_shown_date_iso} for one namespace."""
    ns = _load_all().get(namespace)
    return ns if isinstance(ns, dict) else {}


def recently_seen(namespace: str, days: int) -> set:
    """Set of ids shown within the last `days` days (ISO date compare)."""
    if days <= 0:
        return set()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return {i for i, d in load_history(namespace).items() if d >= cutoff}


def record_shown(namespace: str, ids) -> int:
    """Stamp today's date on each id in `namespace`, prune entries older than
    PRUNE_DAYS across all namespaces, and persist. Returns the number of ids
    retained in this namespace."""
    all_seen = _load_all()
    ns = all_seen.get(namespace)
    if not isinstance(ns, dict):
        ns = {}
    today = date.today().isoformat()
    for i in ids:
        if i:
            ns[i] = today
    all_seen[namespace] = ns

    cutoff = (date.today() - timedelta(days=PRUNE_DAYS)).isoformat()
    pruned = {
        n: {i: d for i, d in items.items() if d >= cutoff}
        for n, items in all_seen.items()
        if isinstance(items, dict)
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": datetime.now().isoformat(), "seen": pruned},
            f, indent=2,
        )
    return len(pruned.get(namespace, {}))
