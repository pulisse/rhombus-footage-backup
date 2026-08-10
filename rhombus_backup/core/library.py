"""Browse backed-up footage: scan run manifests into a clip index and safely
resolve clip files for playback.

The backup layout (see naming.py) is:
    <destination>/<YYYY-MM-DD>/<CameraName>/CameraName_YYYY-MM-DD_HH-MM.mp4
    <destination>/<YYYY-MM-DD>/manifest_<runid>.json

Manifests are the source of truth: they carry the exact time range of each
run and the final path of every camera's clip, so the Library never has to
parse filenames.
"""
import json
import logging
import re
from pathlib import Path

from .errors import FriendlyError

_log = logging.getLogger("rhombus.library")

_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def scan(destination: str) -> dict:
    """Build the clip index for the Library tab.

    Returns {"cameras": [names...], "days": [{"date", "clips": [...]}]} with
    days newest-first and clips sorted by camera then start time. Clips whose
    file has been deleted (e.g. by retention) are skipped.
    """
    root = Path(destination)
    cameras = set()
    days = []
    if not destination or not root.is_dir():
        return {"cameras": [], "days": []}

    for day_dir in sorted(root.iterdir(), reverse=True):
        if not day_dir.is_dir() or not _DATE_DIR.match(day_dir.name):
            continue
        seen_files = {}  # rel path -> clip dict, so a richer duplicate can win
        clips = []
        for mf in sorted(day_dir.glob("manifest_*.json")):
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                _log.warning("Skipping unreadable manifest %s: %s", mf, exc)
                continue
            time_range = manifest.get("timeRange") or {}
            start = time_range.get("startEpoch")
            duration = time_range.get("durationSec")
            if not isinstance(start, (int, float)) or not isinstance(duration, (int, float)):
                continue
            for cam in manifest.get("cameras", []):
                out = cam.get("file") or ""
                if cam.get("status") != "done" or not out:
                    continue
                path = Path(out)
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    # Manifest from an older destination; only serve files
                    # that actually live under the current backup folder.
                    continue
                rel_posix = rel.as_posix()
                if not path.is_file():
                    continue
                clip = {
                    "camera": cam.get("name") or rel.parts[0],
                    "file": rel_posix,
                    "startEpoch": int(start),
                    "durationSec": int(duration),
                    "bytes": cam.get("bytes") or 0,
                    "events": cam.get("events") or [],
                }
                existing = seen_files.get(rel_posix)
                if existing is not None:
                    # Same file written by more than one run (e.g. the same
                    # range pulled again after an upgrade): keep whichever
                    # manifest carries more event metadata.
                    if len(clip["events"]) > len(existing["events"]):
                        existing.update(clip)
                    continue
                seen_files[rel_posix] = clip
                cameras.add(clip["camera"])
                clips.append(clip)
        if clips:
            clips.sort(key=lambda c: (c["camera"].lower(), c["startEpoch"]))
            days.append({"date": day_dir.name, "clips": clips})

    return {"cameras": sorted(cameras, key=str.lower), "days": days}


def resolve_media(destination: str, rel: str) -> Path:
    """Turn a client-supplied relative clip path into a safe absolute path.

    Refuses anything that escapes the backup destination (absolute paths,
    .. traversal, symlinks pointing outside) or that doesn't exist.
    """
    root = Path(destination).resolve() if destination else None
    if root is None or not root.is_dir():
        raise FriendlyError("No backup folder is configured yet.")
    if not rel or Path(rel).is_absolute():
        raise FriendlyError("That video isn't in your backup folder.")
    candidate = (root / rel).resolve()
    if root not in candidate.parents:
        raise FriendlyError("That video isn't in your backup folder.")
    if not candidate.is_file():
        raise FriendlyError(
            "That video file is missing - it may have been deleted by "
            "retention or the drive isn't connected."
        )
    return candidate


def delete_media(destination: str, rel: str) -> None:
    """Delete a backed-up clip (same safety rules as resolve_media).

    Manifests are left untouched: scan() already skips clips whose file is
    gone, so the clip simply disappears from the Library. Empty camera
    folders left behind are pruned, but day folders are kept because they
    still hold the run manifests.
    """
    path = resolve_media(destination, rel)
    try:
        path.unlink()
    except OSError as exc:
        raise FriendlyError(
            "Couldn't delete that video - check that the drive is connected "
            "and the file isn't open in another app.",
            technical=str(exc),
        ) from exc
    _log.info("Deleted clip %s", path)
    root = Path(destination).resolve()
    cam_dir = path.parent
    if cam_dir != root and cam_dir.is_dir() and not any(cam_dir.iterdir()):
        try:
            cam_dir.rmdir()
        except OSError:
            pass
