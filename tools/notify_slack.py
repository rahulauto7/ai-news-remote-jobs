"""Post a failure notification to the user's Slack DM via Bot Token.

Reuses SLACK_BOT_TOKEN + SLACK_USER_ID (same secrets used by send_to_slack.py).
Silent no-op if either is unset so local dev doesn't blow up.
"""
import os
import sys
from datetime import datetime


def notify(step: str, error: str, log_tail: str = "") -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    user_id = os.environ.get("SLACK_USER_ID", "").strip()
    if not token or not user_id:
        print("[slack] SLACK_BOT_TOKEN or SLACK_USER_ID not set; skipping notification")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    text = (
        f":rotating_light: Daily AI News pipeline FAILED — {today}\n"
        f"*Step that failed:* {step}\n"
        f"*Error:* {error}\n"
    )
    if log_tail:
        text += f"*Last log lines:*\n```\n{log_tail.strip()}\n```"

    try:
        from slack_sdk import WebClient
        client = WebClient(token=token)
        resp = client.chat_postMessage(channel=user_id, text=text)
        print(f"[slack] posted ({resp.get('ok')})")
        return bool(resp.get("ok"))
    except Exception as e:
        print(f"[slack] notify failed: {e}")
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
