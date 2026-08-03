#!/usr/bin/env python3
"""One-time setup (developer/admin only): register this app as a Rhombus OAuth
application so end users get the "Sign in with Rhombus" button.

Usage:
    python scripts/register_oauth_app.py

You'll be prompted for an existing Rhombus API key (create one in the Console
under Settings > API Management - only needed for this registration, not by
end users). The resulting client credentials are written to oauth_client.json
in the project root; the build scripts bundle that file into the app.

NOTE: distributing an app to end users may require Rhombus review of the
OAuth application (see the "Sign in with Rhombus" developer docs).
"""
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from rhombus_backup.core.oauth import REDIRECT_URI  # noqa: E402

SUBMIT_URL = "https://api2.rhombussystems.com/api/oauth/submitApplication"


def main() -> int:
    print("Register 'Rhombus Backup Buddy' as an OAuth app for your org.\n")
    api_key = getpass.getpass("Existing Rhombus API key (input hidden): ").strip()
    if not api_key:
        print("No key given; aborting.")
        return 1
    email = input("Contact email for the application: ").strip()

    resp = requests.post(
        SUBMIT_URL,
        json={
            "name": "Rhombus Backup Buddy",
            "description": "Desktop app that backs up camera footage to local storage.",
            "contactEmail": email,
            "redirectUri": REDIRECT_URI,
        },
        headers={
            "x-auth-scheme": "api-token",
            "x-auth-apikey": api_key,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print("Registration failed: HTTP {} {}".format(resp.status_code, resp.text[:400]))
        return 1
    data = resp.json()
    if not data.get("clientId"):
        print("Registration failed: {}".format(data.get("errorMsg") or data))
        return 1

    out = Path(__file__).resolve().parent.parent / "oauth_client.json"
    out.write_text(
        json.dumps({"clientId": data["clientId"], "clientSecret": data["clientSecret"]}, indent=2),
        encoding="utf-8",
    )
    print("\nSuccess! Wrote {}".format(out))
    print("Redirect URI registered: {}".format(REDIRECT_URI))
    print("Keep this file out of source control (already in .gitignore); the")
    print("build scripts bundle it so end users just click 'Sign in with Rhombus'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
