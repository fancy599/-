from datetime import datetime, timezone

from app.utils.timeutil import as_utc, to_local_iso, utc_now


def test_utc_now_is_aware():
    dt = utc_now()
    assert dt.tzinfo is not None


def test_to_local_iso_from_naive_utc():
    dt = datetime(2026, 5, 28, 18, 7, 45)
    s = to_local_iso(dt)
    assert s == "2026-05-29 02:07:45"


def test_to_local_iso_from_aware_utc():
    dt = datetime(2026, 5, 28, 18, 7, 45, tzinfo=timezone.utc)
    s = to_local_iso(dt)
    assert s == "2026-05-29 02:07:45"


def test_as_utc_from_naive_and_aware():
    naive = datetime(2026, 5, 28, 18, 7, 45)
    aware = datetime(2026, 5, 28, 18, 7, 45, tzinfo=timezone.utc)

    assert as_utc(naive) == aware
    assert as_utc(aware) == aware
