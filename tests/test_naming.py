from datetime import datetime
from pathlib import Path

from rhombus_backup.core import naming


T = datetime(2026, 7, 31, 14, 0)


def test_clip_filename_is_human_readable():
    assert naming.clip_filename("Front Door", T) == "FrontDoor_2026-07-31_14-00.mp4"


def test_no_uuid_in_filename():
    name = naming.clip_filename("Lobby Cam", T)
    assert "uuid" not in name.lower()
    assert name == "LobbyCam_2026-07-31_14-00.mp4"


def test_sanitize_strips_illegal_characters():
    assert naming.sanitize_name('Door <A>: "West"/Side\\?*') == "Door A WestSide"
    assert naming.sanitize_name("   ") == "Camera"
    assert naming.sanitize_name("CON") == "Camera"          # Windows reserved
    assert naming.sanitize_name("x" * 200) == "x" * 80      # length cap


def test_clip_path_layout(tmp_path):
    p = naming.clip_path(str(tmp_path), "Front Door", T)
    assert p == tmp_path / "2026-07-31" / "Front Door" / "FrontDoor_2026-07-31_14-00.mp4"


def test_dedupe_path(tmp_path):
    p = tmp_path / "clip.mp4"
    assert naming.dedupe_path(p) == p
    p.write_bytes(b"x")
    assert naming.dedupe_path(p) == tmp_path / "clip_2.mp4"
    (tmp_path / "clip_2.mp4").write_bytes(b"x")
    assert naming.dedupe_path(p) == tmp_path / "clip_3.mp4"
