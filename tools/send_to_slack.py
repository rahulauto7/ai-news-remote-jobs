"""Send the daily PDF (and jobs.csv) to a Slack DM via Bot Token.

Auth: SLACK_BOT_TOKEN (xoxb-...). Target: SLACK_USER_ID (e.g. U0123ABCD).
Uses files_upload_v2 — DM is opened automatically when channel=user_id.

This is the SUCCESS delivery path. It runs on GitHub Actions (deliver.yml),
which has unrestricted egress to slack.com — the cloud routine sandbox does
NOT (it only reaches github.com + the Anthropic API), and the claude.ai Slack
connector can send text but cannot attach a file. So the actual PDF file is
delivered here, from Actions, after the routine pushes it to a daily/<date>
branch.

load_dotenv() at import (rule, 2026-05-11): any module that reads env vars on
its own must load .env itself — don't assume the orchestrator did. On Actions
there is no .env, so this is a harmless no-op and creds come from secrets.

If env vars are missing, prints a notice and returns None so local/dev runs
don't crash.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def send_pdf(pdf_path: str, csv_path: Optional[str] = None):
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    user_id = os.environ.get("SLACK_USER_ID", "").strip()
    if not token or not user_id:
        print("[slack] SLACK_BOT_TOKEN or SLACK_USER_ID not set; skipping PDF send")
        return None

    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError:
        print("[slack] slack_sdk not installed; skipping PDF send")
        return None

    client = WebClient(token=token)
    today = datetime.now().strftime("%Y-%m-%d")

    if not os.path.exists(pdf_path):
        print(f"[slack] PDF missing: {pdf_path}")
        return None

    # Resolve channel: if SLACK_USER_ID looks like a user (U…), open a DM and
    # use that channel id. files_upload_v2 with channel=U… mostly works but
    # some workspaces require an explicit conversations.open first.
    channel_id = user_id
    if user_id.startswith("U"):
        try:
            conv = client.conversations_open(users=user_id)
            channel_id = conv["channel"]["id"]
        except SlackApiError as e:
            print(f"[slack] conversations.open failed: {e.response.get('error')} — falling back to user_id")

    pdf_link = ""
    last_err = None
    for attempt in (1, 2):
        try:
            pdf_resp = client.files_upload_v2(
                channel=channel_id,
                file=pdf_path,
                filename=os.path.basename(pdf_path),
                title=f"AI News + Remote Jobs — {today}",
                initial_comment=f":newspaper: Daily AI News digest for {today}",
            )
            pdf_link = (pdf_resp.get("file") or {}).get("permalink", "")
            print(f"[slack] uploaded PDF (attempt {attempt}): {pdf_link}")
            break
        except SlackApiError as e:
            last_err = e.response.get("error")
            print(f"[slack] PDF upload attempt {attempt} failed: {last_err}")
            if attempt == 1:
                import time as _t

                _t.sleep(3)
    else:
        print(f"[slack] giving up — last error: {last_err}. "
              f"Check bot scopes (files:write, chat:write, im:write) and that the bot is in the DM.")
        return None

    if csv_path and os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        try:
            client.files_upload_v2(
                channel=channel_id,
                file=csv_path,
                filename=os.path.basename(csv_path),
                title=f"Remote AI jobs — {today}",
            )
            print("[slack] uploaded jobs.csv")
        except SlackApiError as e:
            print(f"[slack] CSV upload failed: {e.response.get('error')}")

    return {"pdf": pdf_link}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: send_to_slack.py <pdf-path> [<csv-path>]")
        sys.exit(2)
    result = send_pdf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    # Exit non-zero on failure so the workflow can branch on $? and fail loudly.
    sys.exit(0 if result else 1)
