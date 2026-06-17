"""Finalize cross-day dedup for Quantum + RSI after AGENT ENRICHMENT.

Why this exists: `dedupe_and_backfill.py` runs BEFORE AGENT ENRICHMENT, but
enrichment is the step that "confirms/repopulates" `quantum_ai_research` and
`ai_self_improvement_rsi` by reasoning over the unrouted pool. Items the agent
adds there were skipping the cross-day seen-history check entirely and never
getting recorded, so they could repeat indefinitely. This script runs the
deferred dedup+record pass for just those two sections, once their contents are
final.

Why a separate "qrsi" namespace (not shared "news"):
Articles qualifying for quantum/RSI frequently appear in global_ai_news first
(Stage 1 routes everything it can't classify there). Sharing the "news" namespace
means those URLs are recorded when they appear in global_ai_news, then blocked
from ever entering quantum/RSI. Using a dedicated "qrsi" namespace means only
articles that have PREVIOUSLY APPEARED IN QUANTUM/RSI are blocked — an article
that appeared in global_ai_news yesterday is still eligible to get proper
treatment in the quantum or RSI section today.

Run this:
  - In `run_daily_pipeline.py`, right after `dedupe_and_backfill.main()` (no
    enrichment happens in that script, so this is a no-op when sections are
    still empty from Stage 1).
  - Again in the Stage 2 cloud routine, after AGENT ENRICHMENT and before the
    YouTube-ideas + PDF steps — this is the call that actually matters, since
    enrichment is what repopulates these sections.

Reads/writes: .tmp/analyzed_content.json (in place)
Reads:        data/content_history.json (via content_history module, "qrsi" namespace)
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tools import content_history

OUTPUT_FILE = os.path.join(PROJECT_ROOT, ".tmp", "analyzed_content.json")

QRSI_NS = "qrsi"
QRSI_DEDUP_DAYS = 7
DEFERRED_DEDUP_SECTIONS = {"quantum_ai_research", "ai_self_improvement_rsi"}


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

    # Articles previously shown IN quantum/RSI sections (own namespace, not shared news).
    seen = content_history.recently_seen(QRSI_NS, QRSI_DEDUP_DAYS)

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

    content_history.record_shown(QRSI_NS, surfaced)

    doc["sections"] = sections
    doc["total_items_analyzed"] = sum(
        len(v) for v in sections.values() if isinstance(v, list)
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(
        f"[finalize_qrsi_dedup] dropped {dropped} repeat(s) from "
        f"{sorted(DEFERRED_DEDUP_SECTIONS)}, recorded {len(set(surfaced))} URL(s) "
        f"in '{QRSI_NS}' history"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
