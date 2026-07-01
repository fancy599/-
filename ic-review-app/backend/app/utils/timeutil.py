from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=8))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return as_utc(dt).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
