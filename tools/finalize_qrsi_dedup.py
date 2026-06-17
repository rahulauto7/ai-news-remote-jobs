"""Finalize cross-day dedup for Quantum + RSI after AGENT ENRICHMENT.

Why this exists: `dedupe_and_backfill.py` runs BEFORE AGENT ENRICHMENT, but
enrichment is the step that "confirms/repopulates" `quantum_ai_research` and
`ai_self_improvement_rsi` by reasoning over the unrouted pool. Items the agent
adds there were skipping the cross-day seen-history check entirely and never
getting recorded, so they could repeat indefinitely. This script runs the
deferred dedup+record pass for just those two sections, once their contents are
final.

Run this:
  - In `run_daily_pipeline.py`, right after `dedupe_and_backfill.main()` (no
    enrichment happens in that script, so this is the only pass those two
    sections get there).
  - Again in the Stage 2 cloud routine, after AGENT ENRICHMENT and before the
    YouTube-ideas + PDF steps — this is the call that actually matters, since
    enrichment is what repopulates these sections.

Safe to call twice in the same day's pipeline: both calls reuse the seen-set
snapshot `dedupe_and_backfill.py` wrote BEFORE it recorded anything, so an
item Stage 1 already kept won't be mistaken for "already seen" by Stage 2's
call just because Stage 1 stamped it minutes earlier.

Reads/writes: .tmp/analyzed_content.json (in place)
Reads:        .tmp/_qrsi_dedup_seen.json (snapshot; falls back to a fresh
              content_history.recently_seen() call if missing)
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tools.dedupe_and_backfill import (
    OUTPUT_FILE, NEWS_NS, DEDUP_DAYS, DEFERRED_DEDUP_SECTIONS, SEEN_SNAPSHOT_FILE,
)
from tools import content_history


def _load_seen_snapshot() -> set:
    if os.path.exists(SEEN_SNAPSHOT_FILE):
        try:
            with open(SEEN_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    # Standalone invocation with no prior dedupe_and_backfill run this session.
    return content_history.recently_seen(NEWS_NS, DEDUP_DAYS)


def main() -> int:
    if not os.path.exists(OUTPUT_FILE):
        print(f"[finalize_qrsi_dedup] no {OUTPUT_FILE} — nothing to do")
        return 0

    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        doc = json.load(f)
    sections = doc.get("sections", {})
    if not isinstance(sections, dict):
        print("[finalize_qrsi_dedup] malformed analyzed_content.json — skipping")
        return 0

    seen = _load_seen_snapshot()

    dropped = 0
    surfaced: list[str] = []
    for sec in DEFERRED_DEDUP_SECTIONS:
        items = sections.get(sec)
        if not isinstance(items, list):
            continue
        kept = [it for it in items if (it.get("url") or "") not in seen]
        dropped += len(items) - len(kept)
        sections[sec] = kept
        surfaced.extend(it.get("url") or "" for it in kept if it.get("url"))

    content_history.record_shown(NEWS_NS, surfaced)

    doc["sections"] = sections
    doc["total_items_analyzed"] = sum(
        len(v) for v in sections.values() if isinstance(v, list)
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(
        f"[finalize_qrsi_dedup] dropped {dropped} repeat(s) from "
        f"{sorted(DEFERRED_DEDUP_SECTIONS)}, recorded {len(set(surfaced))} URL(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
