from unittest import mock

from rhombus_backup.core import notify
from rhombus_backup.core.config import AppConfig


SNAP_OK = {
    "state": "done", "error": "", "startEpoch": 1785900000, "durationSec": 3600,
    "bytes": 450 * 1024 ** 2,
    "cameras": [
        {"name": "Front Door", "status": "done", "error": ""},
        {"name": "Dock", "status": "done", "error": ""},
    ],
}
SNAP_PARTIAL = {
    **SNAP_OK,
    "cameras": [
        {"name": "Front Door", "status": "done", "error": ""},
        {"name": "Dock", "status": "failed", "error": "Network timeout"},
    ],
}


def test_summary_success():
    msg = notify.build_summary(SNAP_OK)
    assert "✅" in msg["subject"] and "2 cameras" in msg["subject"]
    assert "Front Door" in msg["text"] and "450.0 MB" in msg["text"]


def test_summary_partial_lists_failures():
    msg = notify.build_summary(SNAP_PARTIAL)
    assert "⚠️" in msg["subject"]
    assert "FAILED - Dock: Network timeout" in msg["text"]


def test_should_notify_modes():
    assert not notify.should_notify(AppConfig(notify_mode="never"), SNAP_PARTIAL)
    assert notify.should_notify(AppConfig(notify_mode="always"), SNAP_OK)
    assert not notify.should_notify(AppConfig(notify_mode="failures"), SNAP_OK)
    assert notify.should_notify(AppConfig(notify_mode="failures"), SNAP_PARTIAL)
    cancelled = {**SNAP_OK, "state": "cancelled"}
    assert notify.should_notify(AppConfig(notify_mode="failures"), cancelled)


def test_send_all_posts_to_each_webhook():
    cfg = AppConfig(
        slack_webhook="https://hooks.slack.com/x",
        teams_webhook="https://outlook.office.com/y",
        gchat_webhook="https://chat.googleapis.com/z",
    )
    ok = mock.Mock(status_code=200)
    with mock.patch.object(notify.requests, "post", return_value=ok) as post:
        errors = notify.send_all(cfg, "subj", "body")
    assert errors == []
    urls = [c.args[0] for c in post.call_args_list]
    assert urls == [cfg.slack_webhook, cfg.teams_webhook, cfg.gchat_webhook]
    slack_json, teams_json, gchat_json = [c.kwargs["json"] for c in post.call_args_list]
    assert slack_json == {"text": "body"}
    assert gchat_json == {"text": "body"}
    # Teams (Power Automate "Workflows") requires an Adaptive Card message
    assert teams_json["type"] == "message"
    card = teams_json["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["body"][0]["text"] == "body"
    assert card["body"][0]["wrap"] is True


def test_webhook_failure_reported_not_raised():
    cfg = AppConfig(slack_webhook="https://hooks.slack.com/x")
    bad = mock.Mock(status_code=404)
    with mock.patch.object(notify.requests, "post", return_value=bad):
        errors = notify.send_all(cfg, "s", "b")
    assert errors and "Slack" in errors[0] and "404" in errors[0]


def test_email_requires_minimum_config():
    err = notify._send_email(AppConfig(email_to="a@b.com"), "s", "b")
    assert "mail server" in err


def test_notify_run_finished_never_raises():
    cfg = AppConfig(notify_mode="always", slack_webhook="https://hooks.slack.com/x")
    with mock.patch.object(notify.requests, "post", side_effect=RuntimeError("boom")):
        notify.notify_run_finished(cfg, SNAP_OK)  # must not raise


def test_channels_configured():
    assert notify.channels_configured(AppConfig()) == []
    cfg = AppConfig(slack_webhook="https://x", email_to="a@b.c", smtp_host="smtp.b.c")
    assert notify.channels_configured(cfg) == ["Slack", "Email"]


def test_config_validation_rejects_http_webhook():
    cfg = AppConfig(slack_webhook="http://insecure.example.com")
    assert any("https" in p for p in cfg.validate())
