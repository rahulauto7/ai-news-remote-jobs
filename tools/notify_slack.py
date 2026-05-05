"""Post a failure notification to Slack via incoming webhook.

Reads SLACK_WEBHOOK_URL from env. Silent no-op if unset so local dev
doesn't blow up. Designed to be called from run_daily_pipeline.py at any
terminal failure point (matches the rule in workflows/daily_ai_news_remote.md).
"""
import json
import os
import sys
import urllib.request
from datetime import datetime


def notify(step: str, error: str, log_tail: str = "") -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        print("[slack] SLACK_WEBHOOK_URL not set; skipping notification")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    text = (
        f":rotating_light: Daily AI News pipeline FAILED — {today}\n"
        f"*Step that failed:* {step}\n"
        f"*Error:* {error}\n"
    )
    if log_tail:
        text += f"*Last log lines:*\n```\n{log_tail.strip()}\n```"

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = 200 <= resp.status < 300
            print(f"[slack] posted ({resp.status})" if ok else f"[slack] http {resp.status}")
            return ok
    except Exception as e:
        print(f"[slack] post failed: {e}")
        return False


def tail_log(path: str, n: int = 20) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except Exception:
        return ""


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    err = sys.argv[2] if len(sys.argv) > 2 else "unspecified"
    log_path = sys.argv[3] if len(sys.argv) > 3 else ""
    notify(step, err, tail_log(log_path) if log_path else "")
