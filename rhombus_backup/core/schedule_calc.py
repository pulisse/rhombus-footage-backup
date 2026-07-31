"""Compute the next run time for each plain-English schedule choice.

Pure logic (no threads) so it is unit-testable; local time throughout.
"""
from datetime import datetime, timedelta
from typing import Optional

BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 18  # last run of the day fires at 18:00


def next_run(schedule: str, after: datetime) -> Optional[datetime]:
    """Next fire time strictly after `after`; None for manual."""
    if schedule == "manual":
        return None

    if schedule == "hourly":
        base = after.replace(minute=0, second=0, microsecond=0)
        return base + timedelta(hours=1)

    if schedule == "every4h":
        base = after.replace(minute=0, second=0, microsecond=0)
        next_block = ((base.hour // 4) + 1) * 4
        if next_block >= 24:
            return base.replace(hour=0) + timedelta(days=1)
        return base.replace(hour=next_block)

    if schedule == "daily_midnight":
        return after.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    if schedule == "weekdays_business":
        candidate = after.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        for _ in range(24 * 8):  # bounded search, at most a week ahead
            if candidate.weekday() < 5 and BUSINESS_START_HOUR <= candidate.hour <= BUSINESS_END_HOUR:
                return candidate
            candidate += timedelta(hours=1)
        return None

    return None


def window_for(schedule: str, fire_time: datetime, default_hours: float) -> float:
    """Hours of footage a scheduled run should fetch (covers the gap since last run)."""
    if schedule == "hourly":
        return 1.0
    if schedule == "every4h":
        return 4.0
    if schedule == "daily_midnight":
        return 24.0
    if schedule == "weekdays_business":
        return 1.0
    return default_hours
