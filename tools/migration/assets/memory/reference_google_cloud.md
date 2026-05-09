---
name: Google Cloud setup
description: Google Cloud project details, OAuth credentials, account ownership
type: reference
---

**Google Cloud Project:** `singular-antler-487718-u8` (named "My First Project")
**Owner account:** `ops.bluemarlindemo@gmail.com`

**OAuth2 Client:** BlueMarlin Dashboard (Web application)
- Client ID: `276505825375-fsha6iob8kbrhg2tsabu79p2h3c4l96c.apps.googleusercontent.com`
- Client Secret: stored in VPS env as `GOOGLE_OAUTH_CLIENT_SECRET`
- Redirect URI: `https://api.wetakeyourjob.com/dashboard/api/google/callback`
- Scopes: `drive.readonly`

**OAuth consent screen:**
- Publishing status: Testing (100 user cap)
- User type: External
- Test user: `butlerbensonagent@gmail.com`

**APIs enabled:** Google Calendar, Google Sheets, Google Drive

**VPS env vars:**
- `GOOGLE_OAUTH_CLIENT_ID` — set
- `GOOGLE_OAUTH_CLIENT_SECRET` — set

**Service account** (for Calendar/Sheets): already exists in `config/credentials/` on VPS
