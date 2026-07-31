"""Register/remove a true OS-level scheduled task so backups run without the app.

The scheduled command is `<app> --run-backup`, the headless CLI mode.
  * Windows: Task Scheduler via schtasks.exe
  * macOS:   a launchd agent in ~/Library/LaunchAgents
  * Linux:   the user's crontab (marker-comment managed)
"""
import logging
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import List

from . import paths
from .errors import FriendlyError
from .schedule_calc import BUSINESS_START_HOUR, BUSINESS_END_HOUR

_log = logging.getLogger("rhombus.os_sched")

TASK_NAME = "RhombusBackupBuddy"
LAUNCHD_LABEL = "com.rhombus.backupbuddy"
CRON_MARKER = "# rhombus-backup-buddy"


def _app_command() -> List[str]:
    """Command that runs a headless backup, valid for frozen and dev installs."""
    if paths.is_frozen():
        return [sys.executable, "--run-backup"]
    return [sys.executable, "-m", "rhombus_backup", "--run-backup"]


def is_registered() -> bool:
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", TASK_NAME],
                capture_output=True, text=True,
            )
            return r.returncode == 0
        if sys.platform == "darwin":
            return _launchd_plist_path().exists()
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return r.returncode == 0 and CRON_MARKER in (r.stdout or "")
    except OSError:
        return False


def register(schedule: str) -> None:
    if schedule == "manual":
        unregister()
        return
    if os.name == "nt":
        _register_windows(schedule)
    elif sys.platform == "darwin":
        _register_macos(schedule)
    else:
        _register_cron(schedule)
    _log.info("OS schedule registered: %s", schedule)


def unregister() -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                capture_output=True, text=True,
            )
        elif sys.platform == "darwin":
            plist = _launchd_plist_path()
            if plist.exists():
                subprocess.run(
                    ["launchctl", "unload", str(plist)], capture_output=True, text=True
                )
                plist.unlink()
        else:
            r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            if r.returncode == 0 and CRON_MARKER in r.stdout:
                kept = [l for l in r.stdout.splitlines() if CRON_MARKER not in l]
                subprocess.run(
                    ["crontab", "-"], input="\n".join(kept) + "\n",
                    capture_output=True, text=True,
                )
    except OSError as exc:
        raise FriendlyError(
            "Couldn't remove the automatic backup schedule from this computer. "
            "You can also remove it manually from the system's task scheduler.",
            repr(exc),
        )


# -- Windows -----------------------------------------------------------------
def _register_windows(schedule: str) -> None:
    cmd_str = " ".join('"{}"'.format(c) if " " in c else c for c in _app_command())
    base = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", cmd_str]
    if schedule == "hourly":
        args = base + ["/SC", "HOURLY"]
    elif schedule == "every4h":
        args = base + ["/SC", "HOURLY", "/MO", "4"]
    elif schedule == "daily_midnight":
        args = base + ["/SC", "DAILY", "/ST", "00:00"]
    elif schedule == "weekdays_business":
        args = base + [
            "/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI",
            "/ST", "{:02d}:00".format(BUSINESS_START_HOUR),
            "/RI", "60", "/DU", "{:02d}:00".format(BUSINESS_END_HOUR - BUSINESS_START_HOUR),
        ]
    else:
        raise FriendlyError("Unknown schedule: {}".format(schedule))
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise FriendlyError(
            "Windows wouldn't accept the scheduled task. Try running the app "
            "as an administrator once, then toggle the schedule again.",
            r.stderr,
        )


# -- macOS ---------------------------------------------------------------------
def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / (LAUNCHD_LABEL + ".plist")


def _register_macos(schedule: str) -> None:
    if schedule == "hourly":
        intervals = [{"Minute": 0}]
    elif schedule == "every4h":
        intervals = [{"Hour": h, "Minute": 0} for h in range(0, 24, 4)]
    elif schedule == "daily_midnight":
        intervals = [{"Hour": 0, "Minute": 0}]
    elif schedule == "weekdays_business":
        intervals = [
            {"Weekday": wd, "Hour": h, "Minute": 0}
            for wd in range(1, 6)  # launchd: 1=Mon ... 5=Fri
            for h in range(BUSINESS_START_HOUR, BUSINESS_END_HOUR + 1)
        ]
    else:
        raise FriendlyError("Unknown schedule: {}".format(schedule))

    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": _app_command(),
        "StartCalendarInterval": intervals,
        "StandardOutPath": str(paths.config_dir() / "scheduled_run.log"),
        "StandardErrorPath": str(paths.config_dir() / "scheduled_run.log"),
    }
    path = _launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
    with open(path, "wb") as fp:
        plistlib.dump(plist, fp)
    r = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise FriendlyError(
            "macOS wouldn't accept the scheduled task. Check System Settings > "
            "General > Login Items for blocked items, then try again.",
            r.stderr,
        )


# -- Linux / NAS -----------------------------------------------------------------
def _register_cron(schedule: str) -> None:
    cmd_str = " ".join(_app_command())
    if schedule == "hourly":
        line = "0 * * * * {} {}".format(cmd_str, CRON_MARKER)
    elif schedule == "every4h":
        line = "0 */4 * * * {} {}".format(cmd_str, CRON_MARKER)
    elif schedule == "daily_midnight":
        line = "0 0 * * * {} {}".format(cmd_str, CRON_MARKER)
    elif schedule == "weekdays_business":
        line = "0 {}-{} * * 1-5 {} {}".format(
            BUSINESS_START_HOUR, BUSINESS_END_HOUR, cmd_str, CRON_MARKER
        )
    else:
        raise FriendlyError("Unknown schedule: {}".format(schedule))

    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = r.stdout if r.returncode == 0 else ""
    kept = [l for l in existing.splitlines() if CRON_MARKER not in l]
    kept.append(line)
    w = subprocess.run(
        ["crontab", "-"], input="\n".join(kept) + "\n", capture_output=True, text=True
    )
    if w.returncode != 0:
        raise FriendlyError(
            "Couldn't add the backup to this computer's schedule (cron). "
            "Your system may not allow user cron jobs.",
            w.stderr,
        )
