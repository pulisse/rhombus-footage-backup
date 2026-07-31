import json

from rhombus_backup.core import config as config_mod
from rhombus_backup.core.config import AppConfig


def test_defaults_are_safe():
    cfg = AppConfig()
    assert cfg.threads == 4          # default concurrency respects rate limits
    assert cfg.use_wan is False      # LAN is the default
    assert cfg.retention_days == 30
    assert cfg.schedule == "manual"
    assert cfg.setup_complete is False


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig(
        destination="/backups", camera_uuids=["a", "b"], schedule="hourly",
        retention_days=7, use_wan=True, threads=2, setup_complete=True,
    )
    config_mod.save(cfg, path)
    loaded = config_mod.load(path)
    assert loaded == cfg


def test_api_key_never_in_file(tmp_path):
    path = tmp_path / "config.json"
    config_mod.save(AppConfig(destination="/x"), path)
    raw = path.read_text()
    assert "apiKey" not in raw and "api_key" not in raw


def test_load_missing_and_corrupt(tmp_path):
    assert config_mod.load(tmp_path / "nope.json") == AppConfig()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert config_mod.load(bad) == AppConfig()


def test_load_ignores_unknown_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"destination": "/d", "someFutureField": 1}))
    assert config_mod.load(path).destination == "/d"


def test_validate_catches_problems():
    cfg = AppConfig(setup_complete=True, destination="", retention_days=0,
                    threads=99, schedule="fortnightly")
    problems = cfg.validate()
    assert len(problems) == 4
    assert AppConfig(destination="/d", setup_complete=True).validate() == []
