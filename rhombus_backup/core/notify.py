"""Completion notifications: Slack / Microsoft Teams / Google Chat webhooks
and (optionally) email via SMTP.

Design rules:
  * Notification failures are logged, never raised into the backup flow.
  * The SMTP password lives in the OS keyring, mirroring the API key.
  * Webhook URLs are pasted by the user from their chat admin console -
    all three products use a simple {"text": ...} JSON POST.
"""
import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import List, Optional

import requests

from . import space
from .config import AppConfig, get_smtp_password

_log = logging.getLogger("rhombus.notify")
TIMEOUT = 15


# -- message building ----------------------------------------------------------
def build_summary(snap: dict) -> dict:
    """{subject, text} human-readable summary of a finished run."""
    cams = snap.get("cameras", [])
    ok = [c for c in cams if c["status"] == "done"]
    failed = [c for c in cams if c["status"] == "failed"]
    when = datetime.fromtimestamp(snap["startEpoch"]).strftime("%b %d, %I:%M %p")
    hours = snap["durationSec"] / 3600.0
    size = space.human(snap.get("bytes", 0))

    if snap["state"] == "done" and not failed:
        subject = "✅ Rhombus backup finished - {} camera{} ({})".format(
            len(ok), "" if len(ok) == 1 else "s", size
        )
    elif snap["state"] == "done":
        subject = "⚠️ Rhombus backup finished with problems - {} ok, {} failed".format(
            len(ok), len(failed)
        )
    elif snap["state"] == "cancelled":
        subject = "🛑 Rhombus backup was stopped early"
    else:
        subject = "❌ Rhombus backup failed"

    lines = [
        subject,
        "",
        "Footage from: {} ({:.1f}h)".format(when, hours),
        "Downloaded: {}".format(size),
    ]
    if ok:
        lines.append("Backed up: " + ", ".join(c["name"] for c in ok))
    for c in failed:
        lines.append("FAILED - {}: {}".format(c["name"], c["error"]))
    if snap.get("error") and not failed:
        lines.append("Problem: {}".format(snap["error"]))
    return {"subject": subject, "text": "\n".join(lines)}


def should_notify(cfg: AppConfig, snap: dict) -> bool:
    if cfg.notify_mode == "never":
        return False
    had_trouble = snap["state"] != "done" or any(
        c["status"] == "failed" for c in snap.get("cameras", [])
    )
    return had_trouble if cfg.notify_mode == "failures" else True


# -- channels -----------------------------------------------------------------
def _post_webhook(name: str, url: str, text: str) -> Optional[str]:
    """Returns an error string, or None on success."""
    try:
        resp = requests.post(url, json={"text": text}, timeout=TIMEOUT)
        if resp.status_code >= 300:
            return "{} webhook returned HTTP {}".format(name, resp.status_code)
        return None
    except requests.RequestException as exc:
        return "{} webhook unreachable ({})".format(name, exc.__class__.__name__)


def _send_email(cfg: AppConfig, subject: str, text: str) -> Optional[str]:
    if not (cfg.email_to and cfg.smtp_host):
        return "Email isn't fully set up (need a To address and mail server)."
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_user or "rhombus-backup@" + cfg.smtp_host
    msg["To"] = cfg.email_to
    msg.set_content(text)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT) as smtp:
            try:
                smtp.starttls(context=ssl.create_default_context())
            except smtplib.SMTPNotSupportedError:
                pass  # some internal relays are plain; better than not sending
            password = get_smtp_password()
            if cfg.smtp_user and password:
                smtp.login(cfg.smtp_user, password)
            smtp.send_message(msg)
        return None
    except (smtplib.SMTPException, OSError) as exc:
        return "Email couldn't be sent ({})".format(exc.__class__.__name__)


def send_all(cfg: AppConfig, subject: str, text: str) -> List[str]:
    """Send to every configured channel; returns friendly error strings."""
    errors = []
    for name, url in (
        ("Slack", cfg.slack_webhook),
        ("Teams", cfg.teams_webhook),
        ("Google Chat", cfg.gchat_webhook),
    ):
        if url:
            err = _post_webhook(name, url, text)
            if err:
                errors.append(err)
    if cfg.email_to or cfg.smtp_host:
        err = _send_email(cfg, subject, text)
        if err:
            errors.append(err)
    for err in errors:
        _log.warning("Notification problem: %s", err)
    return errors


def notify_run_finished(cfg: AppConfig, snap: dict) -> None:
    """Fire-and-forget entry point used after each backup run."""
    try:
        if not should_notify(cfg, snap):
            return
        msg = build_summary(snap)
        send_all(cfg, msg["subject"], msg["text"])
    except Exception:  # noqa: BLE001 - never let notifications hurt a backup
        _log.exception("Notification dispatch failed")


def channels_configured(cfg: AppConfig) -> List[str]:
    out = []
    if cfg.slack_webhook:
        out.append("Slack")
    if cfg.teams_webhook:
        out.append("Teams")
    if cfg.gchat_webhook:
        out.append("Google Chat")
    if cfg.email_to and cfg.smtp_host:
        out.append("Email")
    return out
