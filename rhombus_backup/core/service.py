"""Application service: owns config, the current run, history, and the
in-app scheduler thread. The web layer is a thin shim over this class."""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

from . import config as config_mod
from . import history, notify, os_sched, retention, schedule_calc, space
from .api import RhombusClient
from .config import AppConfig
from .downloader import BackupRun
from .errors import FriendlyError, friendly_exception
from .ffmpeg_utils import find_ffmpeg, ensure_ffmpeg
from .oauth import SignInFlow, client_config as oauth_client_config

_log = logging.getLogger("rhombus.service")


class AppService:
    def __init__(self):
        self.cfg: AppConfig = config_mod.load()
        self.current_run: Optional[BackupRun] = None
        self._run_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self.next_scheduled: Optional[float] = None  # epoch
        # Sign in with Rhombus: minted key parks here until the wizard/settings
        # save it to the keyring - it is never sent to the browser UI.
        self.signin_flow: Optional[SignInFlow] = None
        self.pending_api_key: Optional[str] = None
        self.pending_org: Optional[dict] = None

    # -- Sign in with Rhombus -------------------------------------------------
    @staticmethod
    def signin_available() -> bool:
        return oauth_client_config() is not None

    def start_signin(self) -> dict:
        if self.signin_flow and self.signin_flow.state in ("waiting", "exchanging", "minting"):
            return self.signin_status()
        flow = SignInFlow()
        self.signin_flow = flow
        self.pending_api_key = None
        self.pending_org = None

        def _work():
            try:
                key = flow.run()
                org = RhombusClient(key).test_connection()
                self.pending_api_key = key
                self.pending_org = org
            except FriendlyError:
                pass  # flow.state/error already carry the friendly message
            except Exception as exc:  # noqa: BLE001
                fe = friendly_exception(exc, use_wan=True)
                flow.state, flow.error = "failed", str(fe)
                _log.exception("Sign-in flow crashed")

        threading.Thread(target=_work, daemon=True, name="rhombus-signin").start()
        return self.signin_status()

    def signin_status(self) -> dict:
        if not self.signin_flow:
            return {"state": "idle", "error": "", "org": None}
        snap = self.signin_flow.snapshot()
        # "done" for the UI means the key is validated AND parked, not just minted.
        if snap["state"] == "done" and not self.pending_org:
            snap["state"] = "minting"
        return {"state": snap["state"], "error": snap["error"], "org": self.pending_org}

    def cancel_signin(self):
        if self.signin_flow:
            self.signin_flow.cancel()

    def effective_api_key(self, explicit: Optional[str] = None) -> Optional[str]:
        """Key preference order: caller-supplied > freshly signed-in > saved."""
        return explicit or self.pending_api_key or self.api_key()

    # -- config ------------------------------------------------------------
    def save_config(self, updates: dict, api_key: Optional[str] = None) -> List[str]:
        for k, v in updates.items():
            if hasattr(self.cfg, k):
                setattr(self.cfg, k, v)
        problems = self.cfg.validate()
        if problems:
            return problems
        if api_key:
            config_mod.set_api_key(api_key)
        elif self.pending_api_key:
            # Adopt the key minted by "Sign in with Rhombus".
            config_mod.set_api_key(self.pending_api_key)
            self.pending_api_key = None
            self.pending_org = None
        config_mod.save(self.cfg)
        if self.cfg.os_schedule_enabled:
            try:
                os_sched.register(self.cfg.schedule)
            except FriendlyError as exc:
                self.cfg.os_schedule_enabled = False
                config_mod.save(self.cfg)
                return [str(exc)]
        else:
            os_sched.unregister()
        self._restart_scheduler()
        return []

    def api_key(self) -> Optional[str]:
        return config_mod.get_api_key()

    # -- backup runs ------------------------------------------------------------
    def start_backup(self, start_epoch: int, duration_sec: int,
                     camera_uuids: Optional[List[str]] = None) -> dict:
        with self._lock:
            if self.current_run and self.current_run.state == "running":
                raise FriendlyError("A backup is already running. Let it finish or cancel it first.")

            key = self.api_key()
            if not key:
                raise FriendlyError("No API key saved yet. Finish setup first.")
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                ffmpeg_path = ensure_ffmpeg()  # raises a friendly error if impossible

            client = RhombusClient(key)
            all_cams = client.get_cameras(include_offline=False)
            wanted = set(camera_uuids if camera_uuids is not None else self.cfg.camera_uuids)
            cams = [c for c in all_cams if c["uuid"] in wanted] if wanted else []
            if not cams:
                raise FriendlyError(
                    "None of your selected cameras are online right now. Check "
                    "that cameras show Online in the Rhombus Console."
                )

            pre = space.preflight(self.cfg.destination, len(cams), duration_sec)
            if not pre["ok"]:
                raise FriendlyError(pre["message"])

            run = BackupRun(
                cfg=self.cfg,
                api_key=key,
                cameras=cams,
                start_epoch=start_epoch,
                duration_sec=duration_sec,
                ffmpeg_path=ffmpeg_path,
                audio_map=client.get_audio_gateway_map(),
            )
            self.current_run = run

        def _work():
            snap = run.execute()
            history.append(
                {
                    "finishedAt": time.time(),
                    "runId": snap["runId"],
                    "state": snap["state"],
                    "startEpoch": snap["startEpoch"],
                    "durationSec": snap["durationSec"],
                    "bytes": snap["bytes"],
                    "ok": sum(1 for c in snap["cameras"] if c["status"] == "done"),
                    "failed": sum(1 for c in snap["cameras"] if c["status"] == "failed"),
                    "cameras": [
                        {"name": c["name"], "status": c["status"],
                         "error": c["error"], "output": c["output"], "bytes": c["bytes"]}
                        for c in snap["cameras"]
                    ],
                }
            )
            history.trim()
            notify.notify_run_finished(self.cfg, snap)
            try:
                retention.cleanup(self.cfg.destination, self.cfg.retention_days)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Retention cleanup failed: %s", exc)

        self._run_thread = threading.Thread(target=_work, daemon=True, name="backup-run")
        self._run_thread.start()
        return run.snapshot()

    def cancel_backup(self):
        if self.current_run:
            self.current_run.cancel()

    def status(self) -> dict:
        return {
            "run": self.current_run.snapshot() if self.current_run else None,
            "nextScheduled": self.next_scheduled,
            "ffmpegOk": find_ffmpeg() is not None,
        }

    # -- scheduled/headless entry ------------------------------------------------
    def run_scheduled_backup_blocking(self) -> dict:
        """Used by --run-backup (OS scheduler) and the in-app scheduler."""
        hours = schedule_calc.window_for(
            self.cfg.schedule, datetime.now(), self.cfg.backup_window_hours
        )
        start = datetime.now() - timedelta(hours=hours)
        snap = self.start_backup(int(start.timestamp()), int(hours * 3600))
        while self.current_run and self.current_run.state == "running":
            time.sleep(1)
        if self._run_thread:
            self._run_thread.join(timeout=60)
        return self.current_run.snapshot() if self.current_run else snap

    # -- in-app scheduler ----------------------------------------------------------
    def start_scheduler(self):
        self._restart_scheduler()

    def stop_scheduler(self):
        self._scheduler_stop.set()

    def _restart_scheduler(self):
        self._scheduler_stop.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=2)
        self._scheduler_stop = threading.Event()
        self.next_scheduled = None
        if not self.cfg.setup_complete or self.cfg.schedule == "manual":
            return
        # When the OS scheduler owns the job, don't double-run in-app.
        if self.cfg.os_schedule_enabled:
            nxt = schedule_calc.next_run(self.cfg.schedule, datetime.now())
            self.next_scheduled = nxt.timestamp() if nxt else None
            return

        stop = self._scheduler_stop

        def _loop():
            while not stop.is_set():
                nxt = schedule_calc.next_run(self.cfg.schedule, datetime.now())
                if nxt is None:
                    return
                self.next_scheduled = nxt.timestamp()
                while not stop.is_set() and datetime.now() < nxt:
                    stop.wait(15)
                if stop.is_set():
                    return
                try:
                    self.run_scheduled_backup_blocking()
                except FriendlyError as exc:
                    _log.warning("Scheduled backup failed: %s", exc)
                    history.append({
                        "finishedAt": time.time(), "state": "failed",
                        "error": str(exc), "scheduled": True,
                    })
                except Exception as exc:  # noqa: BLE001
                    fe = friendly_exception(exc, self.cfg.use_wan)
                    _log.exception("Scheduled backup crashed")
                    history.append({
                        "finishedAt": time.time(), "state": "failed",
                        "error": str(fe), "scheduled": True,
                    })

        self._scheduler_thread = threading.Thread(target=_loop, daemon=True, name="scheduler")
        self._scheduler_thread.start()
