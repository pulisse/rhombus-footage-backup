from unittest import mock

from rhombus_backup.core import space


def test_estimate_matches_rule_of_thumb():
    # 1 camera, 24h  ->  ~1.5 GB
    est = space.estimate_bytes(1, 86400)
    assert abs(est - 1.5 * space.GB) < 1024
    # 10 cameras, 1h -> ~0.625 GB
    assert space.estimate_bytes(10, 3600) == int(10 * 3600 * space.BYTES_PER_CAMERA_SECOND)


def test_human_sizes():
    assert space.human(None) == "unknown"
    assert space.human(500) == "500 B"
    assert space.human(1536) == "1.5 KB"
    assert space.human(2.5 * space.GB) == "2.5 GB"


def test_preflight_blocks_when_low(tmp_path):
    with mock.patch.object(space, "free_bytes", return_value=1 * space.GB):
        pre = space.preflight(str(tmp_path), camera_count=10, duration_sec=86400)
    assert pre["ok"] is False
    assert "Not enough space" in pre["message"]


def test_preflight_ok(tmp_path):
    with mock.patch.object(space, "free_bytes", return_value=500 * space.GB):
        pre = space.preflight(str(tmp_path), camera_count=2, duration_sec=3600)
    assert pre["ok"] is True and pre["message"] == ""


def test_preflight_unreachable_folder():
    with mock.patch.object(space, "free_bytes", return_value=None):
        pre = space.preflight("/gone", 1, 3600)
    assert pre["ok"] is False and "drive connected" in pre["message"]
