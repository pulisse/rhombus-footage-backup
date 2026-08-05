"""RhombusClient behavior against a mocked API (no network)."""
from unittest import mock

import pytest

from rhombus_backup.core.api import RhombusClient
from rhombus_backup.core.errors import FriendlyError


def fake_response(status=200, payload=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    return resp


def client_with(post_side_effect):
    c = RhombusClient("test-key")
    c._sess = mock.Mock()
    c._sess.post.side_effect = post_side_effect
    return c


CAMS = {
    "cameraStates": [
        {"uuid": "c1", "name": "Front Door", "locationUuid": "L1", "connectionStatus": "GREEN"},
        {"uuid": "c2", "name": "Dock", "locationUuid": "L1", "connectionStatus": "RED"},
    ]
}


def test_auth_headers_match_original_script():
    c = RhombusClient("sekret")
    assert c._sess.headers["x-auth-scheme"] == "api-token"
    assert c._sess.headers["x-auth-apikey"] == "sekret"


def test_media_session_carries_auth_headers():
    # The WAN media edge 403s without the API key headers (found in the wild);
    # the original script always sent them on the media session too.
    from rhombus_backup.core.api import media_session
    s = media_session("sekret")
    assert s.headers["x-auth-scheme"] == "api-token"
    assert s.headers["x-auth-apikey"] == "sekret"
    assert s.verify is False


def test_get_cameras_marks_offline():
    c = client_with([fake_response(200, CAMS)])
    cams = c.get_cameras(include_offline=True)
    assert [x["online"] for x in cams] == [True, False]
    c2 = client_with([fake_response(200, CAMS)])
    assert [x["uuid"] for x in c2.get_cameras(include_offline=False)] == ["c1"]


def test_401_becomes_friendly():
    c = client_with([fake_response(401)])
    with pytest.raises(FriendlyError) as e:
        c.get_cameras()
    assert "API key was rejected" in str(e.value)


def test_test_connection_zero_cameras():
    c = client_with([fake_response(200, {"cameraStates": []})])
    with pytest.raises(FriendlyError) as e:
        c.test_connection()
    assert "No cameras are reachable" in str(e.value)


def test_session_token_extracted():
    c = client_with([fake_response(200, {"federatedSessionToken": "tok123"})])
    assert c.generate_session_token() == "tok123"
    body = c._sess.post.call_args.kwargs["json"]
    assert body == {"durationSec": 3600}


def test_mpd_template_lan_vs_wan():
    payload = {
        "lanVodMpdUrisTemplates": ["https://lan/clip.mpd?start={START_TIME}&dur={DURATION}"],
        "wanVodMpdUriTemplate": "https://wan/clip.mpd?start={START_TIME}&dur={DURATION}",
    }
    c = client_with([fake_response(200, payload), fake_response(200, payload)])
    assert c.get_camera_mpd_template("c1", use_wan=False).startswith("https://lan/")
    assert c.get_camera_mpd_template("c1", use_wan=True).startswith("https://wan/")


def test_missing_lan_template_is_friendly():
    c = client_with([fake_response(200, {"wanVodMpdUriTemplate": "x"})])
    with pytest.raises(FriendlyError) as e:
        c.get_camera_mpd_template("c1", use_wan=False)
    assert "same network" in str(e.value)


def test_audio_gateway_map():
    payload = {"audioGatewayStates": [{"uuid": "g1", "associatedCameras": ["c1"]}]}
    c = client_with([fake_response(200, payload)])
    assert c.get_audio_gateway_map() == {"c1": "g1"}
