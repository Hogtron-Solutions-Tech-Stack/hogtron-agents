"""One-shot OAuth setup — mint a refresh token for GoogleCalendarProvider.

Run this ONCE on your laptop:
    cd hogtron-agents
    python -m services.sentinel.oauth_setup

It expects two env vars (or a `client_secrets.json` next to this file):
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET

Get those by following services/sentinel/GOOGLE_SETUP.md (create Google
Cloud project, enable Calendar API, create OAuth client credentials).

The script:
  1. Spins up a local loopback server on 127.0.0.1:8765
  2. Opens your browser to Google's consent screen
  3. You log in with the Gmail you want Sentinel to manage
  4. You approve calendar.read/write scope
  5. Google redirects back to localhost with an auth code
  6. We exchange that for a refresh token and print it

Copy the printed values into:
  - .env (for local dev)
  - Railway env vars (for prod)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Auto-load .env so the user only edits one file. Pre-existing env vars win.
from .config import load_dotenv
load_dotenv()

# This script runs outside the Flask process — google libs are required.
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore

SCOPES = ["https://www.googleapis.com/auth/calendar"]
LOOPBACK_PORT = 8765


def _resolve_client_config(args) -> dict:
    """Build the InstalledAppFlow client_config from env vars OR a json file.

    Either form works; env vars take precedence so CI/Railway use stays
    simple. The json file is the format Google Cloud Console hands you
    when you download OAuth credentials.
    """
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    csec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if cid and csec:
        return {
            "installed": {
                "client_id": cid,
                "client_secret": csec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"http://localhost:{LOOPBACK_PORT}/"],
            }
        }

    candidate = Path(args.client_secrets or
                     Path(__file__).parent / "client_secrets.json")
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))

    print("ERROR: need GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET "
          "env vars, OR a client_secrets.json in services/sentinel/ "
          "(or pass --client-secrets <path>).", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="Mint a Google Calendar refresh token for Sentinel.")
    ap.add_argument("--client-secrets", help="Path to Google Cloud OAuth client_secrets.json")
    args = ap.parse_args()

    client_config = _resolve_client_config(args)

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # access_type=offline + prompt=consent forces Google to issue a refresh
    # token even if you've authorized this client before.
    creds = flow.run_local_server(
        host="localhost",
        port=LOOPBACK_PORT,
        open_browser=True,
        access_type="offline",
        prompt="consent",
    )

    if not creds.refresh_token:
        print("ERROR: Google did not return a refresh token. Try revoking the "
              "client at https://myaccount.google.com/permissions and rerun.",
              file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  SUCCESS — refresh token minted. Add these to your env:")
    print("=" * 60)
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_config['installed']['client_id']}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_config['installed']['client_secret']}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print(f"GOOGLE_CALENDAR_ID=primary   # or a specific calendar id")
    print(f"SENTINEL_CALENDAR_PROVIDER=google")
    print("=" * 60)
    print("\nFor local dev: paste these into hogtron-agents/.env")
    print("For Railway:  add them as service env vars in the Sentinel service")
    print("\nKeep the refresh token secret — anyone with it can read/write your calendar.")


if __name__ == "__main__":
    main()
