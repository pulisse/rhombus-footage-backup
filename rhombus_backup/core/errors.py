"""Map raw failures to friendly, actionable messages for non-technical users."""
from typing import Optional

import requests


class FriendlyError(Exception):
    """An error whose str() is safe and helpful to show to an end user."""

    def __init__(self, message: str, technical: Optional[str] = None):
        super().__init__(message)
        self.technical = technical  # kept for the log file, never shown raw in UI


MSG_BAD_KEY = (
    "Your API key was rejected. Open the Rhombus Console, create a new API key "
    "(Settings > API Management), and paste it in Settings here."
)
# Rhombus returns 403 (not 401) for unknown keys, so cover both causes here.
MSG_FORBIDDEN = (
    "Your API key was rejected or doesn't have permission. Open the Rhombus "
    "Console, create a new API key with video access (Settings > API "
    "Management), and paste it in Settings here."
)
MSG_RATE_LIMITED = (
    "Rhombus is asking us to slow down. The app will retry automatically; "
    "if this keeps happening, lower 'Simultaneous downloads' in Advanced settings."
)
MSG_NO_CAMERAS = (
    "No cameras are reachable. Check that your cameras show Online in the "
    "Rhombus Console."
)
MSG_TIMEOUT_LAN = (
    "Couldn't reach the cameras on your local network. If this computer is NOT "
    "on the same network as the cameras, turn OFF 'This computer is on the same "
    "network as the cameras' in Settings and try again."
)
MSG_TIMEOUT_WAN = (
    "The connection to Rhombus timed out. Check this computer's internet "
    "connection and try again."
)
MSG_OFFLINE = (
    "Couldn't reach Rhombus. Check this computer's internet connection and try again."
)
MSG_DISK_FULL = (
    "The backup drive is out of space. Free up space or choose a different "
    "destination folder in Settings, then run the backup again."
)
MSG_FFMPEG_MISSING = (
    "A required video component (FFmpeg) is missing. Open Settings > Help to "
    "install it with one click - no technical steps needed."
)
MSG_SERVER_ERROR = (
    "Rhombus had a temporary problem on their end. The app retried but it "
    "didn't clear up. Please try again in a few minutes."
)


def friendly_http_error(status_code: int, context: str = "") -> FriendlyError:
    tech = "HTTP {} {}".format(status_code, context).strip()
    if status_code == 401:
        return FriendlyError(MSG_BAD_KEY, tech)
    if status_code == 403:
        return FriendlyError(MSG_FORBIDDEN, tech)
    if status_code == 429:
        return FriendlyError(MSG_RATE_LIMITED, tech)
    if 500 <= status_code < 600:
        return FriendlyError(MSG_SERVER_ERROR, tech)
    return FriendlyError(
        "Something unexpected went wrong talking to Rhombus (code {}). "
        "Try again; if it persists, contact support with the log file.".format(status_code),
        tech,
    )


def friendly_exception(exc: Exception, use_wan: bool = False) -> FriendlyError:
    """Convert any exception into a FriendlyError (idempotent)."""
    if isinstance(exc, FriendlyError):
        return exc
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return friendly_http_error(exc.response.status_code, exc.response.url or "")
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return FriendlyError(MSG_TIMEOUT_WAN if use_wan else MSG_TIMEOUT_LAN, repr(exc))
    if isinstance(exc, requests.exceptions.ConnectionError):
        return FriendlyError(MSG_OFFLINE if use_wan else MSG_TIMEOUT_LAN, repr(exc))
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:  # ENOSPC
        return FriendlyError(MSG_DISK_FULL, repr(exc))
    return FriendlyError(
        "Something unexpected went wrong: {}. Details were saved to the log file.".format(
            exc.__class__.__name__
        ),
        repr(exc),
    )
