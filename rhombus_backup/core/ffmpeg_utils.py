"""Find (or fetch) FFmpeg without the user ever touching PATH.

Search order:
  1. ffmpeg bundled next to the app executable / inside the PyInstaller bundle
  2. ffmpeg already on PATH
  3. common install locations (Homebrew, /usr/local)
  4. the `imageio-ffmpeg` wheel, if installed (ships a static binary)

`ensure_ffmpeg()` powers the one-click guided install: it pip-installs
imageio-ffmpeg into the app's data dir when nothing else is found (dev mode),
or reports a friendly error in a frozen build (where it should be bundled).
"""
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import paths
from .errors import FriendlyError, MSG_FFMPEG_MISSING

_log = logging.getLogger("rhombus.ffmpeg")
_BIN = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def find_ffmpeg() -> Optional[str]:
    candidates = [
        paths.bundle_dir() / "bin" / _BIN,                       # bundled resource
        Path(sys.executable).parent / _BIN,                      # next to frozen exe
        paths.config_dir() / "bin" / _BIN,                       # guided install target
    ]
    for c in candidates:
        if c.is_file() and os.access(str(c), os.X_OK):
            return str(c)
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    for c in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if Path(c).is_file():
            return c
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ensure_ffmpeg() -> str:
    found = find_ffmpeg()
    if found:
        return found
    if not paths.is_frozen():
        # Dev/pip installs: fetch the static binary wheel automatically.
        _log.info("FFmpeg not found; installing imageio-ffmpeg ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "imageio-ffmpeg"]
        )
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    raise FriendlyError(MSG_FFMPEG_MISSING, "ffmpeg not found in any known location")


def merge_av(ffmpeg_path: str, video: Path, audio: Optional[Path], output: Path) -> None:
    """Mux video (+ optional audio) into a clean .mp4 without re-encoding."""
    cmd = [ffmpeg_path, "-y", "-loglevel", "error", "-i", str(video)]
    if audio is not None:
        cmd += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += ["-c", "copy", "-movflags", "+faststart", str(output)]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1800
    )
    if proc.returncode != 0:
        raise FriendlyError(
            "The downloaded footage couldn't be packaged into a playable video "
            "file. The raw download was kept so nothing is lost.",
            "ffmpeg exit {}: {}".format(proc.returncode, proc.stderr[-2000:]),
        )
