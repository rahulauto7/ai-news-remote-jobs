"""Send the daily PDF (and jobs.csv) to a Slack DM via Bot Token.

Auth: SLACK_BOT_TOKEN (xoxb-...). Target: SLACK_USER_ID (e.g. U0123ABCD).
Uses files_upload_v2 — DM is opened automatically when channel=user_id.

If env vars are missing, prints a notice and returns None so the pipeline
doesn't crash on dev machines.
"""
import os
import sys
from datetime import datetime


def send_pdf(pdf_path: str, csv_path: str | None = None):
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

    try:
        pdf_resp = client.files_upload_v2(
            channel=user_id,
            file=pdf_path,
            filename=os.path.basename(pdf_path),
            title=f"AI News + Remote Jobs — {today}",
            initial_comment=f":newspaper: Daily AI News digest for {today}",
        )
        pdf_link = (pdf_resp.get("file") or {}).get("permalink", "")
        print(f"[slack] uploaded PDF: {pdf_link}")
    except SlackApiError as e:
        print(f"[slack] PDF upload failed: {e.response.get('error')}")
        return None

    if csv_path and os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        try:
            client.files_upload_v2(
                channel=user_id,
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
        sys.exit(1)
    send_pdf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
