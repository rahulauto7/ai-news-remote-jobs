"""
Derive a tokens -> %-of-subscription-limit calibration constant from
data/usage_log.json, and write it to data/usage_calibration.json.

Background
----------
claude.ai does not expose subscription usage (5-hour / weekly rolling
windows) via any API. The only way to know what fraction of the limit a
Stage-2 routine run consumed is to read /usage (or claude.ai > Settings >
Usage) by hand, before and after the run, for a short calibration period.

Each entry in data/usage_log.json looks like:

    {
      "date": "2026-08-17",
      "before": {"five_hour_pct": 12, "weekly_pct": 34, "read_at": "..."},
      "after":  {"five_hour_pct": 31, "weekly_pct": 41, "read_at": "..."},
      "est_tokens": 210000
    }

For each complete entry (both before/after readings present, est_tokens not
null and > 0) we compute:

    pct_per_token_weekly    = (after.weekly_pct    - before.weekly_pct)    / est_tokens
    pct_per_token_five_hour = (after.five_hour_pct - before.five_hour_pct) / est_tokens

We need at least MIN_SAMPLES complete entries, and the samples must agree
within STABILITY_THRESHOLD (relative spread) of each other, or we refuse to
write a constant — an unstable constant is worse than no number, since it
would print a misleadingly precise percentage in the PDF.

Usage
-----
    .venv/bin/python tools/derive_usage_calibration.py

Exit code 0 either way; check the "calibrated" field in the output JSON
(and the printed message) to know whether a usable constant was written.
"""

import json
import os
import statistics
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOG_PATH = os.path.join(DATA_DIR, "usage_log.json")
CALIBRATION_PATH = os.path.join(DATA_DIR, "usage_calibration.json")

MIN_SAMPLES = 3
# Max allowed relative spread (max-min)/mean before we call the constant
# unstable and refuse to write it.
STABILITY_THRESHOLD = 0.30


def _load_log():
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("runs", [])
    except Exception as e:
        print(f"[derive_usage_calibration] failed to read {LOG_PATH}: {e}")
        return []


def _complete_samples(runs):
    samples = []
    for run in runs:
        before = run.get("before") or {}
        after = run.get("after") or {}
        est_tokens = run.get("est_tokens")
        if not est_tokens or est_tokens <= 0:
            continue
        if "weekly_pct" not in before or "weekly_pct" not in after:
            continue
        if "five_hour_pct" not in before or "five_hour_pct" not in after:
            continue
        weekly_delta = after["weekly_pct"] - before["weekly_pct"]
        five_hour_delta = after["five_hour_pct"] - before["five_hour_pct"]
        if weekly_delta < 0 or five_hour_delta < 0:
            # A negative delta means the window rolled over between
            # readings (5-hour window especially) - not usable.
            continue
        samples.append({
            "date": run.get("date"),
            "est_tokens": est_tokens,
            "pct_per_token_weekly": weekly_delta / est_tokens,
            "pct_per_token_five_hour": five_hour_delta / est_tokens,
        })
    return samples


def _relative_spread(values):
    if not values:
        return None
    mean = statistics.mean(values)
    if mean == 0:
        return None
    return (max(values) - min(values)) / mean


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    runs = _load_log()
    samples = _complete_samples(runs)

    result = {
        "_comment": (
            "Written by tools/derive_usage_calibration.py once 3+ stable "
            "samples exist in data/usage_log.json. pct_per_token_weekly * "
            "est_tokens = estimated % of weekly claude.ai subscription "
            "limit consumed by a run. Absent/null fields mean calibration "
            "hasn't completed yet."
        ),
        "calibrated": False,
        "pct_per_token_weekly": None,
        "pct_per_token_five_hour": None,
        "sample_count": len(samples),
        "sample_dates": [s["date"] for s in samples],
        "spread_pct": None,
        "derived_at": datetime.now(timezone.utc).isoformat(),
    }

    if len(samples) < MIN_SAMPLES:
        print(
            f"[derive_usage_calibration] {len(samples)}/{MIN_SAMPLES} complete "
            f"samples in {LOG_PATH} — need more before/after readings. "
            f"Not writing a constant."
        )
        with open(CALIBRATION_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return 0

    weekly_vals = [s["pct_per_token_weekly"] for s in samples]
    five_hour_vals = [s["pct_per_token_five_hour"] for s in samples]
    spread = _relative_spread(weekly_vals)

    if spread is None or spread > STABILITY_THRESHOLD:
        print(
            f"[derive_usage_calibration] {len(samples)} samples but weekly "
            f"pct_per_token spread is {spread if spread is not None else 'n/a'} "
            f"(threshold {STABILITY_THRESHOLD}) — samples disagree too much, "
            f"refusing to write an unstable constant. Extend calibration."
        )
        result["spread_pct"] = spread
        with open(CALIBRATION_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return 0

    result.update({
        "calibrated": True,
        "pct_per_token_weekly": statistics.mean(weekly_vals),
        "pct_per_token_five_hour": statistics.mean(five_hour_vals),
        "spread_pct": spread,
    })
    with open(CALIBRATION_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(
        f"[derive_usage_calibration] wrote {CALIBRATION_PATH} — "
        f"calibrated from {len(samples)} samples, spread={spread:.1%}, "
        f"pct_per_token_weekly={result['pct_per_token_weekly']:.6e}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
