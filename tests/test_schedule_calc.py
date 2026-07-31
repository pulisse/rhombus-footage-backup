from datetime import datetime

from rhombus_backup.core import schedule_calc as sc


def test_manual_never_fires():
    assert sc.next_run("manual", datetime(2026, 7, 31, 12, 30)) is None


def test_hourly():
    assert sc.next_run("hourly", datetime(2026, 7, 31, 12, 30)) == datetime(2026, 7, 31, 13, 0)
    assert sc.next_run("hourly", datetime(2026, 7, 31, 23, 10)) == datetime(2026, 8, 1, 0, 0)


def test_every4h():
    assert sc.next_run("every4h", datetime(2026, 7, 31, 9, 15)) == datetime(2026, 7, 31, 12, 0)
    assert sc.next_run("every4h", datetime(2026, 7, 31, 22, 0, 1)) == datetime(2026, 8, 1, 0, 0)


def test_daily_midnight():
    assert sc.next_run("daily_midnight", datetime(2026, 7, 31, 0, 0, 1)) == datetime(2026, 8, 1, 0, 0)


def test_weekdays_business_skips_weekend():
    # Friday 17:30 -> Friday 18:00 is still within business window
    assert sc.next_run("weekdays_business", datetime(2026, 7, 31, 17, 30)) == datetime(2026, 7, 31, 18, 0)
    # Friday 18:30 -> next Monday 08:00 (2026-07-31 is a Friday)
    assert sc.next_run("weekdays_business", datetime(2026, 7, 31, 18, 30)) == datetime(2026, 8, 3, 8, 0)
    # Saturday -> Monday 08:00
    assert sc.next_run("weekdays_business", datetime(2026, 8, 1, 12, 0)) == datetime(2026, 8, 3, 8, 0)


def test_window_matches_cadence():
    now = datetime(2026, 7, 31, 12, 0)
    assert sc.window_for("hourly", now, 1.0) == 1.0
    assert sc.window_for("every4h", now, 1.0) == 4.0
    assert sc.window_for("daily_midnight", now, 1.0) == 24.0
    assert sc.window_for("manual", now, 2.5) == 2.5
