"""Platform-appropriate locations for config, logs, and history."""
import os
import sys
from pathlib import Path

from .. import APP_NAME


def config_dir() -> Path:
    """Per-user application data directory (created on first use)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        base = Path(xdg) / "rhombus-backup"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file() -> Path:
    return config_dir() / "config.json"


def history_file() -> Path:
    return config_dir() / "history.jsonl"


def log_file() -> Path:
    return config_dir() / "app.log"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Directory holding bundled resources (PyInstaller _MEIPASS or source tree)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent
