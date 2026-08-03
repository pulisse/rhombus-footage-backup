from pathlib import Path

from rhombus_backup.core import fs_browse


def test_lists_only_visible_directories(tmp_path):
    (tmp_path / "Backups").mkdir()
    (tmp_path / "Videos").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    r = fs_browse.list_folders(str(tmp_path))
    assert [f["name"] for f in r["folders"]] == ["Backups", "Videos"]
    assert r["current"] == str(tmp_path.resolve())
    assert r["error"] == ""
    assert r["writable"] is True
    assert isinstance(r["places"], list) and r["places"]


def test_missing_path_falls_back_to_home():
    r = fs_browse.list_folders("/definitely/not/a/real/path")
    assert r["current"] == str(Path.home().resolve())
    assert "doesn't exist" in r["error"]


def test_no_path_defaults_to_home():
    assert fs_browse.list_folders(None)["current"] == str(Path.home().resolve())


def test_parent_navigation(tmp_path):
    child = tmp_path / "sub"
    child.mkdir()
    r = fs_browse.list_folders(str(child))
    assert r["parent"] == str(tmp_path.resolve())


def test_create_folder(tmp_path):
    r = fs_browse.create_folder(str(tmp_path), "New Backups")
    assert r["ok"] and Path(r["path"]).is_dir()
    # idempotent
    assert fs_browse.create_folder(str(tmp_path), "New Backups")["ok"]


def test_create_folder_rejects_bad_names(tmp_path):
    assert not fs_browse.create_folder(str(tmp_path), "a/b")["ok"]
    assert not fs_browse.create_folder(str(tmp_path), "")["ok"]
    assert not fs_browse.create_folder(str(tmp_path), "..")["ok"]
