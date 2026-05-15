# Sentinel — Google Calendar setup

One-time setup to point Sentinel at a real Google Calendar (your admin
Gmail for testing, or any Google Workspace calendar for prod). After
this, the sidecar's `POST /sentinel/<kind>` endpoints work against
your real calendar instead of the in-memory mock.

Time: ~10 minutes.
You'll do this once. The refresh token persists forever (until revoked).

---

## 1. Create a Google Cloud project

1. Go to https://console.cloud.google.com/
2. Top bar → "Select a project" → "New Project"
3. Name it `Sentinel Concierge` (or whatever). Leave Organization blank if you're using personal Gmail.
4. Click Create. Wait for it to provision (~10 sec).
5. Top bar → make sure the new project is selected.

## 2. Enable the Calendar API

1. Left nav (☰) → "APIs & Services" → "Library"
2. Search for "Google Calendar API"
3. Click it → "Enable". Wait for it to enable (~10 sec).

## 3. Configure OAuth consent screen

This screen is what your Gmail account sees when you grant permission.

1. Left nav → "APIs & Services" → "OAuth consent screen"
2. User Type: pick **External** (works for personal Gmail; required unless you have a Workspace org)
3. Click Create.
4. Fill in the minimum:
   - **App name:** `Sentinel`
   - **User support email:** your Gmail
   - **Developer contact email:** your Gmail
5. Save and Continue.
6. Scopes step: click "Add or Remove Scopes" → search for `calendar` → check `https://www.googleapis.com/auth/calendar` → Update → Save and Continue.
7. Test users step: click "Add Users" → add the Gmail address you want Sentinel to manage. (You must add yourself here even though you own the project — external apps in "Testing" mode only work for listed test users.) Save and Continue.
8. Summary → Back to Dashboard.

Leave the app in **Testing** mode — that's fine for single-tenant use.
Production verification is only needed if you want this to work for
arbitrary Google users (multi-tenant Phase, much later).

## 4. Create OAuth client credentials

1. Left nav → "APIs & Services" → "Credentials"
2. Top → "Create Credentials" → "OAuth client ID"
3. **Application type:** **Desktop app**
4. Name: `Sentinel local`
5. Click Create.
6. A dialog shows your **Client ID** and **Client Secret** — keep this tab open, or click "Download JSON" and save it as `client_secrets.json`.

## 5. Mint the refresh token

On your laptop, from the `hogtron-agents` directory:

```bash
# install Google libs if not already present
pip install -r services/sentinel/requirements.txt

# option A: pass creds via env vars
export GOOGLE_OAUTH_CLIENT_ID="<from step 4>"
export GOOGLE_OAUTH_CLIENT_SECRET="<from step 4>"
python -m services.sentinel.oauth_setup

# option B: drop the downloaded client_secrets.json into services/sentinel/
# and just run:
python -m services.sentinel.oauth_setup
```

The script will:
- Open your browser to Google's consent screen
- You sign in with the Gmail you added as a test user in step 3
- You'll see a "Google hasn't verified this app" warning — click "Advanced" → "Go to Sentinel (unsafe)". This is normal for unverified apps in Testing mode and only applies to the test users you allowlisted.
- Approve the calendar scope
- Browser shows "The authentication flow has completed."
- Your terminal prints the env block you need.

PowerShell variant of the export step:
```powershell
$env:GOOGLE_OAUTH_CLIENT_ID="..."
$env:GOOGLE_OAUTH_CLIENT_SECRET="..."
python -m services.sentinel.oauth_setup
```

## 6. Configure the sidecar

Local dev — create `hogtron-agents/.env` (gitignored) with:

```
SENTINEL_CALENDAR_PROVIDER=google
SENTINEL_API_KEY=any-long-random-string
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...
GOOGLE_CALENDAR_ID=primary
```

Then run:
```bash
python -m services.sentinel.app
```

You should see `provider=google auth=on` in the startup log.

Railway prod — paste the same vars into the Sentinel service's
"Variables" tab. The same `client_secrets.json` is **not** needed in
prod (only the refresh token + client id/secret).

## 7. Verify against your real calendar

Pick a quiet hour on your calendar. From another terminal:

```bash
curl -X POST http://localhost:5055/sentinel/find_slot \
  -H "X-Sentinel-Key: any-long-random-string" \
  -H "Content-Type: application/json" \
  -d '{
    "payload": {
      "business_id": "test",
      "window_start": "2026-05-15T14:00:00+00:00",
      "window_end":   "2026-05-15T18:00:00+00:00",
      "duration_min": 30
    }
  }'
```

You should get a `status: "ok"` response with slots that respect your
real calendar's existing events.

To test book_appointment, point it at a window you're OK with creating
a real event in:
```bash
curl -X POST http://localhost:5055/sentinel/book_appointment \
  -H "X-Sentinel-Key: any-long-random-string" \
  -H "Content-Type: application/json" \
  -d '{
    "payload": {
      "business_id": "test",
      "start": "2026-05-15T15:00:00+00:00",
      "end":   "2026-05-15T15:30:00+00:00",
      "title": "Sentinel test — please ignore",
      "attendee_email": "you@example.com"
    }
  }'
```

A real event should appear on your Google Calendar. The response
includes the `calendar_event_id` — use it to test reschedule/cancel.

## Troubleshooting

- **"access_denied"** in browser → you're signing in with a Gmail that isn't on the OAuth consent screen's test users list. Add it in step 3.
- **No refresh_token returned** → Google only returns refresh tokens on FIRST consent for a given client. Revoke at https://myaccount.google.com/permissions and rerun.
- **"insufficient authentication scopes"** at runtime → the refresh token was minted for a narrower scope. Rerun `oauth_setup.py` to mint a new one.
- **401 from sidecar** → you didn't send `X-Sentinel-Key` header, or it doesn't match `SENTINEL_API_KEY` env var.
