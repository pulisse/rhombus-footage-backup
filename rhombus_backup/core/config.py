"""App configuration: JSON file for settings, OS credential store for the API key.

The API key is NEVER written to the config file or logs. It lives in the
Windows Credential Manager / macOS Keychain / Secret Service via `keyring`.
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from . import paths

KEYRING_SERVICE = "RhombusBackup"
KEYRING_USER = "api-key"

SCHEDULE_CHOICES = [
    ("hourly", "Every hour"),
    ("every4h", "Every 4 hours"),
    ("daily_midnight", "Daily at midnight"),
    ("weekdays_business", "Weekdays during business hours (8am-6pm, hourly)"),
    ("manual", "Manual only"),
]


@dataclass
class AppConfig:
    destination: str = ""
    camera_uuids: List[str] = field(default_factory=list)  # empty = none selected
    schedule: str = "manual"
    retention_days: int = 30
    use_wan: bool = False           # False = "this computer is on the same network"
    threads: int = 4                # respect API rate limits; advanced setting
    backup_window_hours: float = 1.0  # how much footage each scheduled run grabs
    os_schedule_enabled: bool = False
    setup_complete: bool = False
    # notifications
    notify_mode: str = "never"      # never | always | failures
    slack_webhook: str = ""
    teams_webhook: str = ""
    gchat_webhook: str = ""
    email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""             # SMTP password lives in the OS keyring

    def validate(self) -> List[str]:
        """Return a list of human-readable problems (empty list = valid)."""
        problems = []
        if self.setup_complete and not self.destination:
            problems.append("No backup destination folder is set.")
        if self.retention_days < 1:
            problems.append("Retention must be at least 1 day.")
        if not (1 <= self.threads <= 16):
            problems.append("Simultaneous downloads must be between 1 and 16.")
        if self.schedule not in {key for key, _ in SCHEDULE_CHOICES}:
            problems.append("Unknown schedule choice.")
        if not (0.25 <= self.backup_window_hours <= 24):
            problems.append("Backup window must be between 15 minutes and 24 hours.")
        if self.notify_mode not in ("never", "always", "failures"):
            problems.append("Unknown notification choice.")
        if not (1 <= self.smtp_port <= 65535):
            problems.append("The mail server port must be between 1 and 65535.")
        for label, url in (("Slack", self.slack_webhook), ("Teams", self.teams_webhook),
                           ("Google Chat", self.gchat_webhook)):
            if url and not url.startswith("https://"):
                problems.append("The {} webhook address must start with https://".format(label))
        return problems


def load(path: Optional[Path] = None) -> AppConfig:
    path = path or paths.config_file()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    known = {f for f in AppConfig.__dataclass_fields__}
    return AppConfig(**{k: v for k, v in data.items() if k in known})


def save(cfg: AppConfig, path: Optional[Path] = None) -> None:
    path = path or paths.config_file()
    data = asdict(cfg)
    # Belt and braces: never allow a key to sneak into the JSON file.
    data.pop("api_key", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_api_key() -> Optional[str]:
    import keyring
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def set_api_key(key: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)


def delete_api_key() -> None:
    import keyring
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


KEYRING_SMTP_USER = "smtp-password"


def get_smtp_password() -> Optional[str]:
    import keyring
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_SMTP_USER)
    except Exception:
        return None


def set_smtp_password(password: str) -> None:
    import keyring
    if password:
        keyring.set_password(KEYRING_SERVICE, KEYRING_SMTP_USER, password)
