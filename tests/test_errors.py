import requests

from rhombus_backup.core import errors


def test_401_maps_to_bad_key_message():
    e = errors.friendly_http_error(401)
    assert "API key was rejected" in str(e)
    assert "Rhombus Console" in str(e)


def test_403_429_5xx():
    # Rhombus returns 403 for unknown keys, so 403 must also say "rejected"
    assert "rejected" in str(errors.friendly_http_error(403))
    assert "permission" in str(errors.friendly_http_error(403))
    assert "slow down" in str(errors.friendly_http_error(429))
    assert "their end" in str(errors.friendly_http_error(503))


def test_unknown_status_still_friendly():
    msg = str(errors.friendly_http_error(418))
    assert "418" in msg and "support" in msg


def test_timeout_suggests_lan_wan_toggle():
    exc = requests.exceptions.ConnectTimeout()
    lan = errors.friendly_exception(exc, use_wan=False)
    wan = errors.friendly_exception(exc, use_wan=True)
    assert "same network" in str(lan)          # suggests flipping the toggle
    assert "internet connection" in str(wan)


def test_disk_full_maps_to_enospc():
    e = OSError(28, "No space left on device")
    assert "out of space" in str(errors.friendly_exception(e))


def test_friendly_error_passthrough_is_idempotent():
    original = errors.FriendlyError("hello", "tech")
    assert errors.friendly_exception(original) is original


def test_generic_exception_never_leaks_traceback_jargon():
    msg = str(errors.friendly_exception(ValueError("boom")))
    assert "Traceback" not in msg
    assert "log file" in msg


def test_technical_detail_is_preserved_for_logs():
    e = errors.friendly_http_error(401, "/api/x")
    assert e.technical == "HTTP 401 /api/x"
