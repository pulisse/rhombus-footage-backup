"""Retention cleanup: delete backup date-folders older than N days.

Safety rules - we only ever delete:
  * directories directly under the destination whose name is a YYYY-MM-DD date
  * AND that contain a marker/manifest written by this app (so we never touch
    a folder that happens to be named like a date but wasn't created by us)
"""
import logging
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

_log = logging.getLogger("rhombus.retention")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKER_GLOB = "manifest_*.json"


def _parse_date(name: str) -> Optional[date]:
    if not _DATE_RE.match(name):
        return None
    try:
        return datetime.strptime(name, "%Y-%m-%d").date()
    except ValueError:
        return None


def find_expired(destination: str, retention_days: int, today: Optional[date] = None) -> List[Path]:
    """Return date-folders eligible for deletion (does not delete)."""
    today = today or date.today()
    cutoff = today - timedelta(days=retention_days)
    root = Path(destination)
    if not root.is_dir():
        return []
    expired = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        d = _parse_date(child.name)
        if d is None or d >= cutoff:
            continue
        if not any(child.glob(MARKER_GLOB)):
            _log.info("Skipping %s: no app manifest found, not touching it", child)
            continue
        expired.append(child)
    return sorted(expired)


def cleanup(destination: str, retention_days: int, today: Optional[date] = None) -> List[Path]:
    """Delete expired folders; returns the list actually removed."""
    removed = []
    for folder in find_expired(destination, retention_days, today):
        try:
            shutil.rmtree(folder)
            removed.append(folder)
            _log.info("Retention: removed %s", folder)
        except OSError as exc:
            _log.warning("Retention: could not remove %s: %s", folder, exc)
    return removed
