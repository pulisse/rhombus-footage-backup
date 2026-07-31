"""Disk-space estimation and guard rails.

Rule of thumb from the spec: ~1.5 GB per camera per day of footage.
"""
import shutil
from typing import Optional

GB = 1024 ** 3
BYTES_PER_CAMERA_SECOND = 1.5 * GB / 86400.0  # ~18.2 KB/s
MIN_FREE_BYTES = 1 * GB  # stop a run if free space drops below this


def estimate_bytes(camera_count: int, duration_sec: float) -> int:
    return int(camera_count * duration_sec * BYTES_PER_CAMERA_SECOND)


def free_bytes(path: str) -> Optional[int]:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def human(nbytes: Optional[float]) -> str:
    if nbytes is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024 or unit == "TB":
            return "{:.1f} {}".format(nbytes, unit) if unit != "B" else "{} B".format(int(nbytes))
        nbytes /= 1024.0
    return "?"


def preflight(path: str, camera_count: int, duration_sec: float) -> dict:
    """Returns {ok, estimate, free, message}. ok=False means don't start."""
    est = estimate_bytes(camera_count, duration_sec)
    free = free_bytes(path)
    if free is None:
        return {
            "ok": False, "estimate": est, "free": None,
            "message": "The backup folder isn't reachable. Is the drive connected?",
        }
    if free < est + MIN_FREE_BYTES:
        return {
            "ok": False, "estimate": est, "free": free,
            "message": (
                "Not enough space: this backup needs about {} but the drive only "
                "has {} free. Free up space or shorten the time range.".format(
                    human(est), human(free)
                )
            ),
        }
    return {"ok": True, "estimate": est, "free": free, "message": ""}
