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


# -- credential file fallback (Docker/NAS: no OS credential store) -------------

class _NoKeyring:
    """Stands in for the keyring module when no backend exists."""
    def get_password(self, *a):
        raise RuntimeError("no backend")
    def set_password(self, *a):
        raise RuntimeError("no backend")
    def delete_password(self, *a):
        raise RuntimeError("no backend")


def _use_file_fallback(monkeypatch, tmp_path):
    import sys
    monkeypatch.setitem(sys.modules, "keyring", _NoKeyring())
    monkeypatch.setattr(config_mod.paths, "config_dir", lambda: tmp_path)


def test_api_key_file_fallback_roundtrip(monkeypatch, tmp_path):
    _use_file_fallback(monkeypatch, tmp_path)
    assert config_mod.get_api_key() is None
    config_mod.set_api_key("rhombus-key-123")
    assert config_mod.get_api_key() == "rhombus-key-123"
    cred = tmp_path / "credentials.json"
    assert cred.is_file()
    assert (cred.stat().st_mode & 0o777) == 0o600  # owner-only
    config_mod.delete_api_key()
    assert config_mod.get_api_key() is None


def test_smtp_password_file_fallback(monkeypatch, tmp_path):
    _use_file_fallback(monkeypatch, tmp_path)
    config_mod.set_api_key("the-api-key")
    config_mod.set_smtp_password("hunter2")
    # both credentials coexist in the fallback file
    assert config_mod.get_api_key() == "the-api-key"
    assert config_mod.get_smtp_password() == "hunter2"


def test_working_keyring_still_wins(monkeypatch, tmp_path):
    import sys

    class _GoodKeyring:
        store = {}
        def get_password(self, svc, user):
            return self.store.get(user)
        def set_password(self, svc, user, val):
            self.store[user] = val
        def delete_password(self, svc, user):
            self.store.pop(user, None)

    monkeypatch.setitem(sys.modules, "keyring", _GoodKeyring())
    monkeypatch.setattr(config_mod.paths, "config_dir", lambda: tmp_path)
    config_mod.set_api_key("in-keychain")
    assert config_mod.get_api_key() == "in-keychain"
    assert not (tmp_path / "credentials.json").exists()  # file never touched
