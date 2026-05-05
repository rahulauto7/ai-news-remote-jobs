# Setup — Required GitHub Secrets

The pipeline now runs on **GitHub Actions** (`.github/workflows/daily.yml`) at 01:30 UTC = 07:00 IST daily, plus manual `workflow_dispatch`. GitHub runners have unrestricted network so the scrapers don't get blocked.

Add these in **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | What |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key (sections 15, 16) |
| `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT` | Full JSON contents of the service-account key (paste the whole file) |
| `DRIVE_FOLDER_ID` | ID of the "AI News Daily" folder in Drive (the bit after `/folders/` in the URL) |
| `SLACK_WEBHOOK_URL` | Slack incoming-webhook URL — failures DM here |

## Drive setup

1. Google Cloud Console → IAM & Admin → Service Accounts → create one.
2. Generate a JSON key, paste full contents into `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT`.
3. In Drive, **share** your "AI News Daily" folder with the service-account email (`...@...iam.gserviceaccount.com`) as **Editor**. Service accounts have no quota of their own — uploads must go into a folder shared with them, otherwise they vanish.
4. Copy the folder ID from the URL → `DRIVE_FOLDER_ID`.

## Slack setup

1. https://api.slack.com/messaging/webhooks → create incoming webhook for the channel/DM you want.
2. Paste URL into `SLACK_WEBHOOK_URL`.

Failure cases that send Slack:
- All scrapers fail
- Categorizer fails
- PDF generation fails
- Drive upload fails
- The Actions job exits non-zero for any other reason

Silence = success.

## Trigger now

After secrets are set: **Actions → Daily AI News + Remote Jobs → Run workflow**.
