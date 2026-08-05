"""Thin client for the Rhombus API endpoints this app needs.

Auth matches the original script: x-auth-scheme: api-token + x-auth-apikey.
The API key is only ever sent as a header to api2.rhombussystems.com; media
downloads authenticate with a short-lived federated session token instead.
"""
import logging
from typing import Dict, List, Optional

import requests
import urllib3

from .errors import FriendlyError, friendly_http_error, friendly_exception, MSG_NO_CAMERAS

# LAN cameras serve self-signed certificates; media requests can't verify.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_log = logging.getLogger("rhombus.api")

API_BASE = "https://api2.rhombussystems.com"
TIMEOUT = 30  # seconds per API request


class RhombusClient:
    def __init__(self, api_key: str):
        self._sess = requests.Session()
        self._sess.headers.update(
            {
                "accept": "application/json",
                "content-type": "application/json",
                "x-auth-scheme": "api-token",
                "x-auth-apikey": api_key,
            }
        )

    # -- internals ---------------------------------------------------------
    def _post(self, path: str, body: Optional[dict] = None) -> dict:
        try:
            resp = self._sess.post(API_BASE + path, json=body or {}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise friendly_exception(exc, use_wan=True)
        if resp.status_code != 200:
            raise friendly_http_error(resp.status_code, path)
        try:
            return resp.json()
        except ValueError:
            raise FriendlyError(
                "Rhombus sent back an unexpected response. Try again in a minute.",
                "non-JSON body from {}".format(path),
            )

    # -- org / validation ----------------------------------------------------
    def get_org_name(self) -> Optional[str]:
        """Best-effort org name for the 'connected!' message; None if unavailable."""
        for path, extract in (
            ("/api/org/getOrgV2", lambda d: (d.get("org") or {}).get("name")),
            ("/api/org/getUserOrgs", lambda d: (d.get("orgs") or [{}])[0].get("name")),
        ):
            try:
                name = extract(self._post(path))
                if name:
                    return name
            except FriendlyError as exc:
                _log.debug("org name via %s failed: %s", path, exc.technical)
        return None

    # -- devices -------------------------------------------------------------
    def get_cameras(self, include_offline: bool = True) -> List[dict]:
        """[{uuid, name, locationUuid, online}] for every camera in the org."""
        data = self._post("/api/camera/getMinimalCameraStateList")
        cams = []
        for cam in data.get("cameraStates", []):
            online = cam.get("connectionStatus") != "RED"
            if not online and not include_offline:
                continue
            cams.append(
                {
                    "uuid": cam.get("uuid"),
                    "name": cam.get("name") or "Unnamed camera",
                    "locationUuid": cam.get("locationUuid"),
                    "online": online,
                }
            )
        return cams

    def get_locations(self) -> Dict[str, str]:
        """{locationUuid: name}; empty dict if the endpoint is unavailable."""
        try:
            data = self._post("/api/location/getLocations")
        except FriendlyError as exc:
            _log.debug("getLocations failed: %s", exc.technical)
            return {}
        return {
            loc.get("uuid"): loc.get("name") or "Unnamed location"
            for loc in data.get("locations", [])
            if loc.get("uuid")
        }

    def get_audio_gateway_map(self) -> Dict[str, str]:
        """{cameraUuid: audioGatewayUuid} for cameras with a paired audio device."""
        try:
            data = self._post("/api/audiogateway/getMinimalAudioGatewayStateList")
        except FriendlyError as exc:
            _log.debug("audio gateway list failed (org may have none): %s", exc.technical)
            return {}
        mapping = {}
        for gw in data.get("audioGatewayStates", []):
            for cam_uuid in gw.get("associatedCameras") or []:
                mapping[cam_uuid] = gw.get("uuid")
        return mapping

    # -- media ---------------------------------------------------------------
    def generate_session_token(self, duration_sec: int = 3600) -> str:
        """Federated session token so the API key never appears in media URLs."""
        data = self._post("/api/org/generateFederatedSessionToken", {"durationSec": duration_sec})
        token = data.get("federatedSessionToken")
        if not token:
            raise FriendlyError(
                "Rhombus didn't give us a session for downloading video. Try again.",
                "empty federatedSessionToken",
            )
        return token

    def get_camera_mpd_template(self, camera_uuid: str, use_wan: bool) -> str:
        data = self._post("/api/camera/getMediaUris", {"cameraUuid": camera_uuid})
        return self._pick_template(data, use_wan)

    def get_audio_mpd_template(self, gateway_uuid: str, use_wan: bool) -> str:
        data = self._post("/api/audiogateway/getMediaUris", {"gatewayUuid": gateway_uuid})
        return self._pick_template(data, use_wan)

    @staticmethod
    def _pick_template(data: dict, use_wan: bool) -> str:
        if use_wan:
            template = data.get("wanVodMpdUriTemplate")
        else:
            lan = data.get("lanVodMpdUrisTemplates") or []
            template = lan[0] if lan else None
        if not template:
            raise FriendlyError(
                "This device didn't provide a video address for the selected "
                "network mode. Try toggling 'This computer is on the same "
                "network as the cameras' in Settings.",
                "missing mpd template (use_wan={})".format(use_wan),
            )
        return template

    # -- one-shot validation for the wizard -----------------------------------
    def test_connection(self) -> dict:
        """Validate the key; returns {orgName, cameraCount, onlineCount}."""
        cams = self.get_cameras(include_offline=True)
        online = [c for c in cams if c["online"]]
        if not cams:
            raise FriendlyError(MSG_NO_CAMERAS, "0 cameras in getMinimalCameraStateList")
        return {
            "orgName": self.get_org_name() or "your organization",
            "cameraCount": len(cams),
            "onlineCount": len(online),
        }


def media_session(api_key: str) -> requests.Session:
    """Session for downloading segments.

    Matches the original script: the API key rides as headers alongside the
    federated-session cookie - the WAN media edge (dash.rhombussystems.com)
    returns 403 without them, while LAN cameras accept the cookie alone.
    The key is never part of the URL. verify=False because LAN cameras use
    self-signed certs (same behavior as the original script)."""
    sess = requests.Session()
    sess.verify = False
    sess.headers.update({"x-auth-scheme": "api-token", "x-auth-apikey": api_key})
    return sess
