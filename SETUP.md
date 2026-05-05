# Setup — Required GitHub Secrets

The pipeline runs on **GitHub Actions** (`.github/workflows/daily.yml`) at 01:30 UTC = 07:00 IST daily, plus manual `workflow_dispatch`. GitHub runners have unrestricted network so scrapers don't get blocked.

The PDF is sent to your Slack DM. **Drive is not used.**

## Three secrets to add

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key (sections 15, 16) |
| `SLACK_BOT_TOKEN` | Bot User OAuth Token from your Slack app, starts with `xoxb-` |
| `SLACK_USER_ID` | Your Slack member ID, starts with `U` (e.g. `U01ABCDEFGH`) |

## Slack app setup

1. https://api.slack.com/apps → **Create New App → From scratch** → name "AI News Bot" → pick your workspace.
2. Sidebar → **OAuth & Permissions** → **Bot Token Scopes** → add:
   - `chat:write` — post failure messages
   - `files:write` — upload the PDF
   - `im:write` — open the DM with you
3. Top of same page → **Install to Workspace** → Allow.
4. Copy the **Bot User OAuth Token** (starts `xoxb-`) → that's `SLACK_BOT_TOKEN`.

## Your Slack user ID

In Slack desktop → click your name/avatar → **Profile** → **More (⋯)** → **Copy member ID**. Looks like `U01ABCDEFGH`. That's `SLACK_USER_ID`.

The bot will DM you directly — no channel needed.

## Trigger now

After secrets are in place: **Actions → Daily AI News + Remote Jobs → Run workflow**.

## Failure behavior

The bot DMs you on:
- All scrapers fail
- Categorizer fails
- PDF generation fails
- Slack PDF send fails (then it falls through to the GH Actions-level catch)
- The job exits non-zero for any other reason

Silence = success.
