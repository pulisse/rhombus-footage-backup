from datetime import date

from rhombus_backup.core import retention


TODAY = date(2026, 7, 31)


def make_day(root, name, with_manifest=True):
    d = root / name
    d.mkdir(parents=True)
    (d / "SomeCam").mkdir()
    (d / "SomeCam" / "clip.mp4").write_bytes(b"video")
    if with_manifest:
        (d / "manifest_abc123.json").write_text("{}")
    return d


def test_deletes_only_expired_dated_folders(tmp_path):
    old = make_day(tmp_path, "2026-06-01")          # 60 days old -> expired
    recent = make_day(tmp_path, "2026-07-25")       # 6 days old -> kept
    removed = retention.cleanup(str(tmp_path), 30, today=TODAY)
    assert removed == [old]
    assert not old.exists()
    assert recent.exists()


def test_boundary_day_is_kept(tmp_path):
    # exactly retention_days old == cutoff -> kept (delete strictly older)
    boundary = make_day(tmp_path, "2026-07-01")
    assert retention.cleanup(str(tmp_path), 30, today=TODAY) == []
    assert boundary.exists()


def test_never_touches_foreign_folders(tmp_path):
    no_manifest = make_day(tmp_path, "2026-01-01", with_manifest=False)
    not_a_date = tmp_path / "Invoices"
    not_a_date.mkdir()
    weird = tmp_path / "2026-13-99"
    weird.mkdir()
    (tmp_path / "loose_file.txt").write_text("hi")
    assert retention.cleanup(str(tmp_path), 30, today=TODAY) == []
    assert no_manifest.exists() and not_a_date.exists() and weird.exists()


def test_missing_destination_is_noop():
    assert retention.cleanup("/does/not/exist", 30, today=TODAY) == []
