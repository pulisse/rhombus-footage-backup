"""Flask JSON API + static UI. All state lives in core.service.AppService."""
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .. import __version__, APP_DISPLAY_NAME
from ..core import config as config_mod
from ..core import history, os_sched, space
from ..core.api import RhombusClient
from ..core.config import SCHEDULE_CHOICES
from ..core.errors import FriendlyError, friendly_exception
from ..core.ffmpeg_utils import find_ffmpeg, ensure_ffmpeg
from ..core.service import AppService

_log = logging.getLogger("rhombus.server")
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Set by the desktop shell when running inside pywebview (enables the native
# folder picker); stays None in plain-browser mode.
webview_window = None


def create_app(service: AppService) -> Flask:
    app = Flask(__name__, static_folder=None)

    # The UI runs on 127.0.0.1 only; refuse cross-origin browsers just in case.
    @app.after_request
    def no_cors(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    def fail(exc: Exception, code: int = 400):
        fe = exc if isinstance(exc, FriendlyError) else friendly_exception(exc, service.cfg.use_wan)
        if fe.technical:
            _log.warning("API error: %s (%s)", fe, fe.technical)
        return jsonify({"ok": False, "error": str(fe)}), code

    # ---- static UI -----------------------------------------------------------
    @app.route("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    # ---- app state -------------------------------------------------------------
    @app.route("/api/state")
    def state():
        cfg = service.cfg
        return jsonify({
            "ok": True,
            "appName": APP_DISPLAY_NAME,
            "version": __version__,
            "setupComplete": cfg.setup_complete,
            "hasApiKey": bool(service.api_key()),
            "ffmpegOk": find_ffmpeg() is not None,
            "scheduleChoices": [{"value": v, "label": l} for v, l in SCHEDULE_CHOICES],
            "config": {
                "destination": cfg.destination,
                "cameraUuids": cfg.camera_uuids,
                "schedule": cfg.schedule,
                "retentionDays": cfg.retention_days,
                "useWan": cfg.use_wan,
                "threads": cfg.threads,
                "osScheduleEnabled": cfg.os_schedule_enabled,
            },
            "osScheduleRegistered": os_sched.is_registered(),
        })

    # ---- wizard ---------------------------------------------------------------
    @app.route("/api/test-key", methods=["POST"])
    def test_key():
        key = (request.json or {}).get("apiKey", "").strip()
        if not key:
            return jsonify({"ok": False, "error": "Paste your API key first."}), 400
        try:
            result = RhombusClient(key).test_connection()
        except Exception as exc:  # noqa: BLE001
            return fail(exc)
        return jsonify({"ok": True, **result})

    @app.route("/api/cameras", methods=["POST"])
    def cameras():
        key = (request.json or {}).get("apiKey") or service.api_key()
        if not key:
            return jsonify({"ok": False, "error": "No API key available."}), 400
        try:
            client = RhombusClient(key)
            cams = client.get_cameras(include_offline=True)
            locations = client.get_locations()
        except Exception as exc:  # noqa: BLE001
            return fail(exc)
        groups = {}
        for c in cams:
            loc_name = locations.get(c["locationUuid"], "All cameras")
            groups.setdefault(loc_name, []).append(c)
        return jsonify({
            "ok": True,
            "groups": [
                {"location": loc, "cameras": sorted(cam_list, key=lambda c: c["name"].lower())}
                for loc, cam_list in sorted(groups.items())
            ],
        })

    @app.route("/api/browse-folder", methods=["POST"])
    def browse_folder():
        if webview_window is None:
            return jsonify({"ok": True, "unsupported": True})
        try:
            import webview  # type: ignore
            result = webview_window.create_file_dialog(webview.FOLDER_DIALOG)
            folder = result[0] if result else None
        except Exception as exc:  # noqa: BLE001
            _log.warning("Folder dialog failed: %s", exc)
            return jsonify({"ok": True, "unsupported": True})
        return jsonify({"ok": True, "folder": folder})

    @app.route("/api/freespace", methods=["POST"])
    def freespace():
        path = (request.json or {}).get("path", "")
        free = space.free_bytes(path) if path else None
        return jsonify({"ok": True, "free": free, "freeHuman": space.human(free)})

    @app.route("/api/config", methods=["POST"])
    def save_config():
        body = request.json or {}
        api_key = body.pop("apiKey", None)
        mapping = {
            "destination": "destination", "cameraUuids": "camera_uuids",
            "schedule": "schedule", "retentionDays": "retention_days",
            "useWan": "use_wan", "threads": "threads",
            "osScheduleEnabled": "os_schedule_enabled",
            "setupComplete": "setup_complete",
        }
        updates = {mapping[k]: v for k, v in body.items() if k in mapping}
        try:
            problems = service.save_config(updates, api_key=api_key)
        except Exception as exc:  # noqa: BLE001
            return fail(exc)
        if problems:
            return jsonify({"ok": False, "error": " ".join(problems)}), 400
        return jsonify({"ok": True})

    # ---- backups ---------------------------------------------------------------
    @app.route("/api/estimate", methods=["POST"])
    def estimate():
        body = request.json or {}
        n = int(body.get("cameraCount") or len(service.cfg.camera_uuids) or 0)
        duration = int(body.get("durationSec", 3600))
        pre = space.preflight(service.cfg.destination or ".", n, duration)
        pre["estimateHuman"] = space.human(pre["estimate"])
        pre["freeHuman"] = space.human(pre["free"])
        return jsonify({"ok": True, **pre})

    @app.route("/api/backup", methods=["POST"])
    def backup():
        body = request.json or {}
        try:
            start_epoch, duration = _resolve_range(body)
            snap = service.start_backup(start_epoch, duration, body.get("cameraUuids"))
        except Exception as exc:  # noqa: BLE001
            return fail(exc)
        return jsonify({"ok": True, "run": snap})

    @app.route("/api/cancel", methods=["POST"])
    def cancel():
        service.cancel_backup()
        return jsonify({"ok": True})

    @app.route("/api/status")
    def status():
        return jsonify({"ok": True, **service.status()})

    @app.route("/api/history")
    def get_history():
        return jsonify({"ok": True, "entries": history.read(limit=50)})

    @app.route("/api/install-ffmpeg", methods=["POST"])
    def install_ffmpeg():
        try:
            path = ensure_ffmpeg()
        except Exception as exc:  # noqa: BLE001
            return fail(exc)
        return jsonify({"ok": True, "path": path})

    @app.route("/api/quit", methods=["POST"])
    def quit_app():
        def _die():
            time.sleep(0.3)
            import os
            os._exit(0)
        threading.Thread(target=_die, daemon=True).start()
        return jsonify({"ok": True})

    return app


def _resolve_range(body: dict):
    """Turn UI-friendly time choices into (start_epoch, duration_sec).

    Presets: lastHour | last24h | custom (with startLocal/endLocal ISO strings
    in the user's local timezone - epoch math stays internal).
    """
    preset = body.get("preset", "lastHour")
    now = datetime.now()
    if preset == "lastHour":
        return int(now.timestamp()) - 3600, 3600
    if preset == "last24h":
        return int(now.timestamp()) - 86400, 86400
    if preset == "custom":
        try:
            start = datetime.fromisoformat(body["startLocal"])
            end = datetime.fromisoformat(body["endLocal"])
        except (KeyError, ValueError):
            raise FriendlyError("Pick a valid start and end date/time.")
        if end <= start:
            raise FriendlyError("The end time must be after the start time.")
        if end > now:
            end = now
        duration = int((end - start).total_seconds())
        if duration > 7 * 86400:
            raise FriendlyError(
                "That range is longer than 7 days. Break it into smaller "
                "backups so each one can finish reliably."
            )
        return int(start.timestamp()), duration
    raise FriendlyError("Unknown time range choice.")
