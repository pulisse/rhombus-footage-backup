from unittest import mock

from rhombus_backup.core import env_setup
from rhombus_backup.core.config import AppConfig


def _wire(monkeypatch, tmp_path, env=None, stored_key=None, cameras=None):
    """Point env_setup at fake credentials, config saving, and API."""
    for var in ("RBB_API_KEY", "RBB_DESTINATION", "RBB_SCHEDULE",
                "RBB_CAMERAS", "RBB_RETENTION_DAYS", "RBB_USE_WAN"):
        monkeypatch.delenv(var, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)

    store = {"key": stored_key}
    monkeypatch.setattr(env_setup.config_mod, "get_api_key", lambda: store["key"])
    monkeypatch.setattr(env_setup.config_mod, "set_api_key",
                        lambda k: store.__setitem__("key", k))
    saved = []
    monkeypatch.setattr(env_setup.config_mod, "save",
                        lambda cfg, path=None: saved.append(cfg))

    client = mock.Mock()
    client.get_cameras.return_value = [{"uuid": u} for u in (cameras or [])]
    monkeypatch.setattr(env_setup, "RhombusClient", lambda key: client)
    return store, saved


def test_no_env_does_nothing(monkeypatch, tmp_path):
    _, saved = _wire(monkeypatch, tmp_path)
    cfg = AppConfig()
    assert env_setup.apply_env_setup(cfg) is False
    assert not cfg.setup_complete and saved == []


def test_completes_setup_with_all_cameras(monkeypatch, tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    _, saved = _wire(
        monkeypatch, tmp_path, cameras=["cam1", "cam2"],
        env={"RBB_API_KEY": "k123", "RBB_DESTINATION": str(dest),
             "RBB_SCHEDULE": "hourly", "RBB_RETENTION_DAYS": "14",
             "RBB_USE_WAN": "true"},
    )
    cfg = AppConfig()
    assert env_setup.apply_env_setup(cfg) is True
    assert cfg.setup_complete and saved
    assert cfg.camera_uuids == ["cam1", "cam2"]
    assert cfg.schedule == "hourly"
    assert cfg.retention_days == 14
    assert cfg.use_wan is True
    assert cfg.destination == str(dest)


def test_explicit_camera_uuids_skip_api(monkeypatch, tmp_path):
    dest = tmp_path / "b"
    dest.mkdir()
    _wire(monkeypatch, tmp_path,
          env={"RBB_API_KEY": "k", "RBB_DESTINATION": str(dest),
               "RBB_CAMERAS": " u1 , u2 "})
    cfg = AppConfig()
    assert env_setup.apply_env_setup(cfg) is True
    assert cfg.camera_uuids == ["u1", "u2"]


def test_existing_setup_untouched(monkeypatch, tmp_path):
    dest = tmp_path / "b"
    dest.mkdir()
    _, saved = _wire(monkeypatch, tmp_path, cameras=["c1"],
                     env={"RBB_API_KEY": "new", "RBB_DESTINATION": str(dest),
                          "RBB_SCHEDULE": "hourly"})
    cfg = AppConfig(setup_complete=True, schedule="manual", destination="/old")
    assert env_setup.apply_env_setup(cfg) is False
    assert cfg.schedule == "manual" and cfg.destination == "/old"
    assert saved == []


def test_missing_destination_dir_declines(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, cameras=["c1"],
          env={"RBB_API_KEY": "k", "RBB_DESTINATION": str(tmp_path / "nope")})
    cfg = AppConfig()
    assert env_setup.apply_env_setup(cfg) is False
    assert not cfg.setup_complete


def test_bad_schedule_declines(monkeypatch, tmp_path):
    dest = tmp_path / "b"
    dest.mkdir()
    _wire(monkeypatch, tmp_path, cameras=["c1"],
          env={"RBB_API_KEY": "k", "RBB_DESTINATION": str(dest),
               "RBB_SCHEDULE": "fortnightly"})
    cfg = AppConfig()
    assert env_setup.apply_env_setup(cfg) is False
    assert not cfg.setup_complete


def test_api_failure_fails_soft(monkeypatch, tmp_path):
    dest = tmp_path / "b"
    dest.mkdir()
    _wire(monkeypatch, tmp_path,
          env={"RBB_API_KEY": "k", "RBB_DESTINATION": str(dest)})
    boom = mock.Mock()
    boom.get_cameras.side_effect = RuntimeError("api down")
    monkeypatch.setattr(env_setup, "RhombusClient", lambda key: boom)
    cfg = AppConfig()
    assert env_setup.apply_env_setup(cfg) is False
    assert not cfg.setup_complete


def test_key_installed_even_without_full_setup(monkeypatch, tmp_path):
    store, _ = _wire(monkeypatch, tmp_path, env={"RBB_API_KEY": "just-key"})
    env_setup.apply_env_setup(AppConfig())
    assert store["key"] == "just-key"
