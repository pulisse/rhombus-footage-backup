import json

import pytest

from rhombus_backup.core import library
from rhombus_backup.core.errors import FriendlyError


def _make_backup(root, date="2026-08-05", camera="Front Door", run_id="abc123",
                 start=1754400000, duration=3600, status="done"):
    day = root / date
    cam_dir = day / camera
    cam_dir.mkdir(parents=True, exist_ok=True)
    clip = cam_dir / "FrontDoor_{}_14-00.mp4".format(date)
    clip.write_bytes(b"\x00" * 64)
    manifest = {
        "app": "Rhombus Backup Buddy",
        "runId": run_id,
        "state": "done",
        "timeRange": {"startEpoch": start, "durationSec": duration},
        "cameras": [{
            "uuid": "u" * 22, "name": camera, "status": status,
            "file": str(clip), "bytes": 64, "error": "",
        }],
        "totalBytes": 64,
    }
    (day / "manifest_{}.json".format(run_id)).write_text(json.dumps(manifest))
    return clip


def test_scan_empty_and_missing(tmp_path):
    assert library.scan("") == {"cameras": [], "days": []}
    assert library.scan(str(tmp_path / "nope")) == {"cameras": [], "days": []}
    assert library.scan(str(tmp_path)) == {"cameras": [], "days": []}


def test_scan_finds_clips(tmp_path):
    _make_backup(tmp_path)
    result = library.scan(str(tmp_path))
    assert result["cameras"] == ["Front Door"]
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert day["date"] == "2026-08-05"
    clip = day["clips"][0]
    assert clip["file"] == "2026-08-05/Front Door/FrontDoor_2026-08-05_14-00.mp4"
    assert clip["startEpoch"] == 1754400000
    assert clip["durationSec"] == 3600


def test_scan_skips_failed_and_deleted(tmp_path):
    _make_backup(tmp_path, run_id="fail01", status="failed")
    clip = _make_backup(tmp_path, run_id="gone02", camera="Lobby")
    clip.unlink()  # retention deleted it
    result = library.scan(str(tmp_path))
    assert result["days"] == []


def test_scan_dedupes_same_file_across_manifests(tmp_path):
    _make_backup(tmp_path, run_id="run001")
    _make_backup(tmp_path, run_id="run002")  # same clip file again
    result = library.scan(str(tmp_path))
    assert len(result["days"][0]["clips"]) == 1


def test_scan_ignores_junk(tmp_path):
    _make_backup(tmp_path)
    (tmp_path / "2026-08-05" / "manifest_bad.json").write_text("{not json")
    (tmp_path / "not-a-date").mkdir()
    result = library.scan(str(tmp_path))
    assert len(result["days"]) == 1


def test_resolve_media_ok(tmp_path):
    _make_backup(tmp_path)
    p = library.resolve_media(
        str(tmp_path), "2026-08-05/Front Door/FrontDoor_2026-08-05_14-00.mp4")
    assert p.is_file()


@pytest.mark.parametrize("rel", [
    "", "../etc/passwd", "/etc/passwd",
    "2026-08-05/../../outside.mp4", "2026-08-05/Front Door/missing.mp4",
])
def test_resolve_media_rejects(tmp_path, rel):
    _make_backup(tmp_path)
    (tmp_path.parent / "outside.mp4").write_bytes(b"x")
    with pytest.raises(FriendlyError):
        library.resolve_media(str(tmp_path), rel)


def test_resolve_media_no_destination(tmp_path):
    with pytest.raises(FriendlyError):
        library.resolve_media("", "anything.mp4")
