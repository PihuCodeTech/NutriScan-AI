"""Timezone helpers. Dates in the API are local to `profile.timezone` (default Asia/Kolkata)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Kolkata"


def get_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def utcnow() -> datetime:
    return datetime.now(UTC)


def now_local(tz: ZoneInfo) -> datetime:
    return utcnow().astimezone(tz)


def ensure_utc(dt: datetime) -> datetime:
    """Naive datetimes are treated as UTC (the API documents UTC timestamps)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def local_date_of(dt: datetime, tz: ZoneInfo) -> date:
    return ensure_utc(dt).astimezone(tz).date()


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day, in UTC."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def default_meal_type(local: datetime) -> str:
    """05–10 breakfast, 11–15 lunch, 19–22 dinner, otherwise snack."""
    h = local.hour
    if 5 <= h <= 10:
        return "breakfast"
    if 11 <= h <= 15:
        return "lunch"
    if 19 <= h <= 22:
        return "dinner"
    return "snack"
