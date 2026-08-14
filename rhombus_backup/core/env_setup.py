"""One-shot headless setup from environment variables (Docker/NAS).

Lets a container come up fully configured without ever visiting the setup
wizard - needed when the UI port isn't reachable from where you deploy
(e.g. installing on a remote NAS through its cloud portal). See
docs/DOCKER.md.

Runs only while setup is incomplete; once the app is configured, the UI's
settings are the source of truth and the environment is ignored.

  RBB_API_KEY         Rhombus API key (required to auto-complete setup)
  RBB_DESTINATION     backup folder in the container (image default: /backups)
  RBB_SCHEDULE        hourly | every4h | daily_midnight | weekdays_business | manual
  RBB_CAMERAS         "all" (default) or comma-separated camera UUIDs
  RBB_RETENTION_DAYS  days to keep footage (default 30)
  RBB_USE_WAN         "true" if this box is NOT on the cameras' local network
"""
import logging
import os
from pathlib import Path

from . import config as config_mod
from .api import RhombusClient

_log = logging.getLogger("rhombus.envsetup")


def apply_env_setup(cfg) -> bool:
    """Complete first-run setup from the environment. Returns True if done.

    Best-effort: any problem is logged and setup is left for the wizard,
    never raised - the server must still come up.
    """
    key = os.environ.get("RBB_API_KEY", "").strip()
    if key and not config_mod.get_api_key():
        config_mod.set_api_key(key)
        _log.info("API key installed from RBB_API_KEY.")

    if cfg.setup_complete:
        return False
    key = config_mod.get_api_key()
    dest = os.environ.get("RBB_DESTINATION", "").strip()
    if not key or not dest:
        return False  # not enough to auto-configure; the wizard takes over
    if not Path(dest).is_dir():
        _log.warning("Env setup: destination %s doesn't exist (is the volume "
                     "mounted?); finish setup in the UI.", dest)
        return False

    cameras = os.environ.get("RBB_CAMERAS", "all").strip()
    try:
        if cameras.lower() == "all":
            uuids = [c["uuid"] for c in RhombusClient(key).get_cameras()]
        else:
            uuids = [u.strip() for u in cameras.split(",") if u.strip()]
    except Exception as exc:  # noqa: BLE001 - fail soft, wizard still works
        _log.warning("Env setup: couldn't list cameras (%s); finish setup "
                     "in the UI.", exc)
        return False
    if not uuids:
        _log.warning("Env setup: no cameras to back up; finish setup in the UI.")
        return False

    cfg.destination = dest
    cfg.camera_uuids = uuids
    cfg.schedule = os.environ.get("RBB_SCHEDULE", "").strip() or cfg.schedule
    cfg.use_wan = os.environ.get("RBB_USE_WAN", "").strip().lower() in ("1", "true", "yes")
    retention = os.environ.get("RBB_RETENTION_DAYS", "").strip()
    if retention:
        try:
            cfg.retention_days = int(retention)
        except ValueError:
            _log.warning("Env setup: ignoring non-numeric RBB_RETENTION_DAYS=%r.", retention)

    problems = cfg.validate()
    if problems:
        _log.warning("Env setup: invalid settings (%s); finish setup in the UI.",
                     "; ".join(problems))
        return False
    cfg.setup_complete = True
    config_mod.save(cfg)
    _log.info("Setup completed from environment: %d camera(s), schedule=%s, "
              "destination=%s", len(uuids), cfg.schedule, cfg.destination)
    return True
