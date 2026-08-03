"""Sign in with Rhombus: PKCE, callback validation, token/mint calls (mocked)."""
import base64
import hashlib
import re
from unittest import mock

import pytest

from rhombus_backup.core import oauth
from rhombus_backup.core.errors import FriendlyError


def test_pkce_pair_is_valid_s256():
    verifier, challenge = oauth.generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9_-]+", verifier)      # url-safe, no padding
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected


def test_pkce_is_random():
    assert oauth.generate_pkce() != oauth.generate_pkce()


def test_authorize_url_contains_required_params():
    url = oauth.build_authorize_url("client123", "chal", "st4te")
    assert url.startswith(oauth.AUTHORIZE_URL + "?")
    for fragment in (
        "client_id=client123", "response_type=code", "state=st4te",
        "code_challenge=chal", "code_challenge_method=S256",
        "redirect_uri=http%3A%2F%2Flocalhost%3A53859%2Fcallback",
    ):
        assert fragment in url


def test_parse_callback_happy_path():
    assert oauth.parse_callback("/callback?code=abc&state=xyz", "xyz") == "abc"


def test_parse_callback_state_mismatch_rejected():
    with pytest.raises(FriendlyError) as e:
        oauth.parse_callback("/callback?code=abc&state=WRONG", "xyz")
    assert "safety" in str(e.value)


def test_parse_callback_error_param():
    with pytest.raises(FriendlyError) as e:
        oauth.parse_callback("/callback?error=access_denied&state=xyz", "xyz")
    assert "didn't approve" in str(e.value)


def test_parse_callback_missing_code():
    with pytest.raises(FriendlyError):
        oauth.parse_callback("/callback?state=xyz", "xyz")


def _flow():
    return oauth.SignInFlow(cfg={"clientId": "cid", "clientSecret": "sec"})


def test_exchange_code_form_encoded():
    flow = _flow()
    ok = mock.Mock(status_code=200)
    ok.json.return_value = {"access_token": "AT"}
    with mock.patch.object(oauth.requests, "post", return_value=ok) as post:
        assert flow._exchange_code("thecode", "ver") == "AT"
    _, kwargs = post.call_args
    assert post.call_args.args[0] == oauth.TOKEN_URL
    data = kwargs["data"]
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "thecode"
    assert data["code_verifier"] == "ver"
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_exchange_failure_is_friendly():
    flow = _flow()
    bad = mock.Mock(status_code=400, text="invalid_grant")
    with mock.patch.object(oauth.requests, "post", return_value=bad):
        with pytest.raises(FriendlyError) as e:
            flow._exchange_code("c", "v")
    assert "rejected the sign-in" in str(e.value)


def test_mint_uses_oauth_headers_and_returns_key():
    flow = _flow()
    ok = mock.Mock(status_code=200)
    ok.json.return_value = {"apiKey": "NEWKEY"}
    with mock.patch.object(oauth.requests, "post", return_value=ok) as post:
        assert flow._mint_api_key("AT") == "NEWKEY"
    _, kwargs = post.call_args
    assert post.call_args.args[0] == oauth.MINT_URL
    assert kwargs["headers"]["x-auth-scheme"] == "api-oauth-token"
    assert kwargs["headers"]["x-auth-access-token"] == "AT"
    assert kwargs["json"]["authType"] == "API_TOKEN"
    assert "Rhombus Backup Buddy" in kwargs["json"]["displayName"]


def test_mint_permission_failure_is_friendly():
    flow = _flow()
    bad = mock.Mock(status_code=403, text="forbidden")
    bad.json.return_value = {}
    with mock.patch.object(oauth.requests, "post", return_value=bad):
        with pytest.raises(FriendlyError) as e:
            flow._mint_api_key("AT")
    assert "administrator" in str(e.value)


def test_flow_without_client_config_fails_friendly():
    flow = oauth.SignInFlow(cfg=None)
    with mock.patch.object(oauth, "client_config", return_value=None):
        flow.cfg = None
        with pytest.raises(FriendlyError) as e:
            flow.run(open_browser=lambda url: None)
    assert "Paste an API key instead" in str(e.value)
    assert flow.state == "failed"
