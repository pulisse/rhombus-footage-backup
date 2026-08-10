"""Sign in with Rhombus: OAuth 2.0 Authorization Code + PKCE, ending in a
freshly minted permanent API key - so users never touch the Console.

Flow (per https://apidocs.rhombussystems.com "Sign in with Rhombus"):
  1. Open the system browser at console.rhombussystems.com/oauth/authorize
     with a PKCE challenge and a state value; redirect_uri is a loopback
     HTTP server this module runs on 127.0.0.1.
  2. The callback delivers an authorization code; state must match.
  3. Exchange the code at auth-web.rhombussystems.com/oauth/token
     (form-encoded) for a short-lived access token.
  4. Use the access token (x-auth-scheme: api-oauth-token) to call
     /api/integrations/org/submitApiTokenApplication and mint a permanent
     API key named after this app and computer.

The app's OAuth client credentials come from oauth_client.json (bundled or in
the app data dir) or RHOMBUS_OAUTH_CLIENT_ID/_SECRET env vars. Without them,
the sign-in button is hidden and the paste-a-key flow remains.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import paths
from .errors import FriendlyError

_log = logging.getLogger("rhombus.oauth")

AUTHORIZE_URL = "https://console.rhombussystems.com/oauth/authorize"
TOKEN_URL = "https://auth-web.rhombussystems.com/oauth/token"
MINT_URL = "https://api2.rhombussystems.com/api/integrations/org/submitApiTokenApplication"
CALLBACK_PORT = 53859  # must match the redirect URI registered for the app
REDIRECT_URI = "http://localhost:{}/callback".format(CALLBACK_PORT)
FLOW_TIMEOUT_SEC = 300

SUCCESS_PAGE = b"""<!DOCTYPE html><html><body style="font-family:sans-serif;
text-align:center;padding-top:80px;background:#f4f6f9">
<h2>&#10003; You're signed in</h2>
<p>You can close this tab and return to Rhombus Backup Buddy.</p></body></html>"""
FAILURE_PAGE = b"""<!DOCTYPE html><html><body style="font-family:sans-serif;
text-align:center;padding-top:80px;background:#f4f6f9">
<h2>Sign-in didn't complete</h2>
<p>Close this tab and try again from Rhombus Backup Buddy.</p></body></html>"""


def client_config() -> Optional[dict]:
    """{clientId, clientSecret} for this app's registered OAuth client, or None."""
    cid = os.environ.get("RHOMBUS_OAUTH_CLIENT_ID")
    sec = os.environ.get("RHOMBUS_OAUTH_CLIENT_SECRET")
    if cid and sec:
        return {"clientId": cid, "clientSecret": sec}
    for candidate in (
        paths.config_dir() / "oauth_client.json",
        paths.bundle_dir() / "oauth_client.json",          # frozen bundle root
        paths.bundle_dir().parent / "oauth_client.json",   # dev: project root
    ):
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if data.get("clientId") and data.get("clientSecret"):
                    return {"clientId": data["clientId"], "clientSecret": data["clientSecret"]}
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("Ignoring unreadable %s: %s", candidate, exc)
    return None


def generate_pkce():
    """(verifier, challenge) per RFC 7636, S256, no '=' padding."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def build_authorize_url(client_id: str, challenge: str, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def parse_callback(path: str, expected_state: str) -> str:
    """Extract and validate the authorization code from the callback request path."""
    query = parse_qs(urlparse(path).query)
    if query.get("error"):
        desc = (query.get("error_description") or query["error"])[0]
        raise FriendlyError(
            "Rhombus didn't approve the sign-in ({}). Try again.".format(desc),
            "oauth callback error: {}".format(query),
        )
    state = (query.get("state") or [""])[0]
    if state != expected_state:
        raise FriendlyError(
            "The sign-in response didn't match this app's request, so it was "
            "ignored for your safety. Try signing in again.",
            "state mismatch",
        )
    code = (query.get("code") or [""])[0]
    if not code:
        raise FriendlyError("The sign-in didn't return a code. Try again.", "no code in callback")
    return code


class SignInFlow:
    """One sign-in attempt. Thread-safe status for UI polling."""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or client_config()
        self.state = "idle"       # idle|waiting|exchanging|minting|done|failed
        self.error = ""
        self.api_key: Optional[str] = None
        self.auth_url: Optional[str] = None
        self._lock = threading.Lock()
        self._server: Optional[HTTPServer] = None

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "error": self.error, "authUrl": self.auth_url}

    def _set(self, state: str, error: str = ""):
        with self._lock:
            self.state = state
            self.error = error

    def cancel(self):
        srv = self._server
        if srv:
            try:
                srv.shutdown()
            except Exception:  # noqa: BLE001
                pass

    # -- the blocking flow (run on a worker thread) -------------------------
    def run(self, open_browser=None) -> str:
        """Runs the whole flow; returns the minted API key."""
        import webbrowser

        open_browser = open_browser or webbrowser.open
        if not self.cfg:
            self._set("failed", "Sign-in isn't configured in this build. Paste an API key instead.")
            raise FriendlyError(self.error)

        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(24)
        result = {}
        got_callback = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):  # noqa: N805
                if urlparse(inner.path).path != "/callback":
                    inner.send_response(404)
                    inner.end_headers()
                    return
                try:
                    result["code"] = parse_callback(inner.path, state)
                    page, status = SUCCESS_PAGE, 200
                except FriendlyError as exc:
                    result["error"] = exc
                    page, status = FAILURE_PAGE, 400
                inner.send_response(status)
                inner.send_header("Content-Type", "text/html")
                inner.end_headers()
                inner.wfile.write(page)
                got_callback.set()

            def log_message(inner, *args):  # silence request logging
                pass

        try:
            server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
        except OSError:
            self._set(
                "failed",
                "Another program is using the sign-in port on this computer. "
                "Close other copies of this app and try again.",
            )
            raise FriendlyError(self.error)
        self._server = server
        threading.Thread(target=server.serve_forever, daemon=True, name="oauth-cb").start()

        try:
            url = build_authorize_url(self.cfg["clientId"], challenge, state)
            with self._lock:
                self.auth_url = url
            self._set("waiting")
            open_browser(url)

            if not got_callback.wait(FLOW_TIMEOUT_SEC):
                raise FriendlyError(
                    "Sign-in timed out. A browser tab should have opened - "
                    "finish signing in there, then try again."
                )
            if "error" in result:
                raise result["error"]

            self._set("exchanging")
            token = self._exchange_code(result["code"], verifier)

            self._set("minting")
            api_key = self._mint_api_key(token)
            with self._lock:
                self.api_key = api_key
                self.state = "done"
            return api_key
        except FriendlyError as exc:
            self._set("failed", str(exc))
            _log.warning("Sign-in failed: %s (%s)", exc, exc.technical or "no detail")
            raise
        except requests.RequestException as exc:
            self._set("failed", "Couldn't reach Rhombus to finish signing in. "
                                "Check your internet connection and try again.")
            _log.warning("OAuth network failure: %r", exc)
            raise FriendlyError(self.error, repr(exc))
        finally:
            server.shutdown()
            self._server = None

    def _exchange_code(self, code: str, verifier: str) -> str:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": self.cfg["clientId"],
                "client_secret": self.cfg["clientSecret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise FriendlyError(
                "Rhombus rejected the sign-in. Try again; if it keeps failing, "
                "paste an API key instead (Settings > API key).",
                "token exchange HTTP {}: {}".format(resp.status_code, resp.text[:300]),
            )
        token = resp.json().get("access_token")
        if not token:
            raise FriendlyError(
                "Rhombus didn't return a sign-in token. Try again.",
                "no access_token in token response",
            )
        return token

    def _mint_api_key(self, access_token: str) -> str:
        display = "Rhombus Backup Buddy ({})".format(socket.gethostname() or "this computer")
        resp = requests.post(
            MINT_URL,
            json={"displayName": display[:64], "authType": "API_TOKEN"},
            headers={
                "x-auth-scheme": "api-oauth-token",
                "x-auth-access-token": access_token,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code != 200 or not resp.json().get("apiKey"):
            detail = "mint HTTP {}: {}".format(resp.status_code, resp.text[:300])
            raise FriendlyError(
                "Signed in OK, but Rhombus wouldn't create an access key for "
                "this app. Your Rhombus account may not have permission to "
                "create API keys - ask your Rhombus administrator, or paste "
                "an existing key instead.",
                detail,
            )
        return resp.json()["apiKey"]
