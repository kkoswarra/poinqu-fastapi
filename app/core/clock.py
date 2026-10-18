"""Helper waktu.

Semua waktu disimpan sebagai UTC naive di database agar konsisten antara
PostgreSQL dan SQLite; konversi ke ISO 8601 berakhiran ``Z`` dilakukan saat
serialisasi.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


def now_iso() -> str:
    return to_iso(utcnow())  # type: ignore[return-value]


def seconds_until(value: datetime) -> int:
    delta = value - utcnow()
    return max(0, int(delta.total_seconds()))


def to_epoch(value: datetime) -> int:
    """Epoch detik untuk datetime naive yang diperlakukan sebagai UTC."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return int((value - datetime(1970, 1, 1)).total_seconds())
