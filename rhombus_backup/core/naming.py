"""Human-readable folder and file naming.

Layout:  <destination>/<YYYY-MM-DD>/<CameraName>/CameraName_YYYY-MM-DD_HH-MM.mp4
Camera UUIDs never appear in filenames; they live in the per-run manifest.
All dates/times are the user's LOCAL time of the footage start.
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    *("COM%d" % i for i in range(1, 10)),
    *("LPT%d" % i for i in range(1, 10)),
}


def sanitize_name(name: str, fallback: str = "Camera") -> str:
    """Make a camera/location name safe as a folder/file component on all OSes."""
    name = unicodedata.normalize("NFKC", name or "").strip()
    name = _INVALID.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name or name.upper() in _RESERVED_WINDOWS:
        name = fallback
    return name[:80]


def date_folder(start_local: datetime) -> str:
    return start_local.strftime("%Y-%m-%d")


def clip_filename(camera_name: str, start_local: datetime, ext: str = "mp4") -> str:
    safe = sanitize_name(camera_name).replace(" ", "")
    return "{}_{}.{}".format(safe, start_local.strftime("%Y-%m-%d_%H-%M"), ext)


def clip_path(destination: str, camera_name: str, start_local: datetime) -> Path:
    """Full output path for one clip; parent dirs NOT created here."""
    return (
        Path(destination)
        / date_folder(start_local)
        / sanitize_name(camera_name)
        / clip_filename(camera_name, start_local)
    )


def dedupe_path(path: Path) -> Path:
    """If path exists, append _2, _3, ... before the extension."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name("{}_{}{}".format(path.stem, n, path.suffix))
        if not candidate.exists():
            return candidate
        n += 1
