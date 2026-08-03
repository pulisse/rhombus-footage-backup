"""Server-side folder browsing for the built-in folder picker.

Used when the native OS dialog isn't available (browser mode) or fails.
Only lists directories, never file contents; paths never leave localhost.
"""
import os
import string
import sys
from pathlib import Path
from typing import List, Optional

from . import space


def default_places() -> List[dict]:
    """Quick-access shortcuts: home dirs plus mounted drives."""
    places = []
    home = Path.home()
    for name, p in (
        ("Home", home),
        ("Desktop", home / "Desktop"),
        ("Documents", home / "Documents"),
    ):
        if p.is_dir():
            places.append({"name": name, "path": str(p)})
    if sys.platform == "darwin":
        volumes = Path("/Volumes")
        if volumes.is_dir():
            for v in sorted(volumes.iterdir()):
                if v.is_dir() and not v.name.startswith("."):
                    places.append({"name": "Drive: " + v.name, "path": str(v)})
    elif os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(letter + ":\\")
            if drive.exists():
                places.append({"name": "Drive " + letter + ":", "path": str(drive)})
    else:
        for base in (Path("/mnt"), Path("/media"), Path("/media") / os.environ.get("USER", "")):
            if base.is_dir():
                for v in sorted(base.iterdir()):
                    if v.is_dir():
                        places.append({"name": "Drive: " + v.name, "path": str(v)})
    return places


def list_folders(path: Optional[str]) -> dict:
    """Contents of one directory for the picker UI.

    Returns {current, parent, folders: [{name, path}], freeHuman, writable, error}.
    Falls back to the home directory when path is missing/invalid.
    """
    p = Path(path).expanduser() if path else Path.home()
    error = ""
    if not p.is_dir():
        error = "That folder doesn't exist anymore - showing your home folder instead."
        p = Path.home()
    try:
        p = p.resolve()
    except OSError:
        p = Path.home()

    folders = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            try:
                if child.is_dir() and not child.name.startswith("."):
                    folders.append({"name": child.name, "path": str(child)})
            except OSError:
                continue  # unreadable entry; skip it
    except PermissionError:
        error = "You don't have permission to open that folder."
    except OSError as exc:
        error = "Couldn't open that folder ({}).".format(exc.__class__.__name__)

    parent = str(p.parent) if p.parent != p else None
    return {
        "current": str(p),
        "parent": parent,
        "folders": folders,
        "freeHuman": space.human(space.free_bytes(str(p))),
        "writable": os.access(str(p), os.W_OK),
        "error": error,
        "places": default_places(),
    }


def create_folder(parent: str, name: str) -> dict:
    """Create a subfolder; returns {ok, path?, error?}. Name is sanitized lightly."""
    name = (name or "").strip().strip(".")
    if not name or any(ch in name for ch in '<>:"/\\|?*'):
        return {"ok": False, "error": "That folder name contains characters that aren't allowed."}
    target = Path(parent) / name
    try:
        target.mkdir(parents=False, exist_ok=True)
    except PermissionError:
        return {"ok": False, "error": "You don't have permission to create a folder here."}
    except OSError as exc:
        return {"ok": False, "error": "Couldn't create the folder ({}).".format(exc.__class__.__name__)}
    return {"ok": True, "path": str(target)}
