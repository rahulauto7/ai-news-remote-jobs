"""
Upload the daily PDF (and jobs.csv) to Google Drive.

Two modes:
  1. Local OAuth (uses credentials.json + token.json from project root)
  2. Service account (CI / remote agent — uses GOOGLE_SERVICE_ACCOUNT_JSON)

When run inside a Claude Code remote agent with Google Drive MCP attached,
this script becomes optional — the agent uploads via MCP directly. This script
is the deterministic fallback.
"""

import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DRIVE_FOLDER_NAME = "AI News Daily"
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _build_service():
    sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    creds_path = os.path.join(PROJECT_ROOT, "credentials.json")
    token_path = os.path.join(PROJECT_ROOT, "token.json")

    from googleapiclient.discovery import build

    if sa_path and os.path.exists(sa_path):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        print("[drive] auth: service account")
    elif os.path.exists(token_path):
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds or not creds.valid:
            from google.auth.transport.requests import Request
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
            else:
                print("[drive] token invalid; re-run OAuth")
                return None
        print("[drive] auth: OAuth user")
    elif os.path.exists(creds_path):
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print("[drive] auth: OAuth (new token saved)")
    else:
        print("[drive] no credentials available")
        return None

    return build("drive", "v3", credentials=creds)


def _ensure_folder(service, name=DRIVE_FOLDER_NAME):
    if DRIVE_FOLDER_ID:
        return DRIVE_FOLDER_ID
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(body={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }, fields="id").execute()
    return folder["id"]


def upload(file_path, folder_id, service):
    from googleapiclient.http import MediaFileUpload
    name = os.path.basename(file_path)
    media = MediaFileUpload(file_path, resumable=True)
    f = service.files().create(body={
        "name": name,
        "parents": [folder_id],
    }, media_body=media, fields="id,webViewLink").execute()
    return f


def upload_daily_outputs():
    today = datetime.now().strftime("%Y-%m-%d")
    pdf = os.path.join(TMP_DIR, f"ai_news_remote_jobs_{today}.pdf")
    csv = os.path.join(TMP_DIR, "jobs.csv")

    if not os.path.exists(pdf):
        print(f"[drive] PDF missing: {pdf}")
        return None

    service = _build_service()
    if not service:
        print("[drive] no service — skipping upload")
        return None

    folder_id = _ensure_folder(service)
    print(f"[drive] folder: {folder_id}")

    pdf_meta = upload(pdf, folder_id, service)
    print(f"[drive] uploaded PDF: {pdf_meta.get('webViewLink')}")

    csv_meta = None
    if os.path.exists(csv):
        csv_meta = upload(csv, folder_id, service)
        print(f"[drive] uploaded CSV: {csv_meta.get('webViewLink')}")

    return {"pdf": pdf_meta, "csv": csv_meta, "folder_id": folder_id}


if __name__ == "__main__":
    upload_daily_outputs()
