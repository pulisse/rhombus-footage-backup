"""Run history: append-only JSONL in the app data dir, newest-first reads."""
import json
import logging
from pathlib import Path
from typing import List, Optional

from . import paths

_log = logging.getLogger("rhombus.history")
MAX_ENTRIES = 500


def append(entry: dict, path: Optional[Path] = None) -> None:
    path = path or paths.history_file()
    try:
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry) + "\n")
    except OSError as exc:
        _log.warning("Could not write history: %s", exc)


def read(limit: int = 50, path: Optional[Path] = None) -> List[dict]:
    path = path or paths.history_file()
    if not path.exists():
        return []
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return list(reversed(entries[-max(limit, 0):]))


def trim(path: Optional[Path] = None) -> None:
    """Keep the file from growing forever."""
    path = path or paths.history_file()
    entries = read(limit=MAX_ENTRIES, path=path)
    if not entries:
        return
    try:
        with open(path, "w", encoding="utf-8") as fp:
            for e in reversed(entries):
                fp.write(json.dumps(e) + "\n")
    except OSError:
        pass
