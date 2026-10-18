"""Penghitung batas laju berbasis DB (tanpa Redis, aman untuk monolith)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import seconds_until, utcnow
from app.models import AttemptCounter


def _counter(db: Session, scope: str, key: str, window_seconds: int) -> AttemptCounter:
    now = utcnow()
    counter = db.get(AttemptCounter, (scope, key))
    if counter is None:
        counter = AttemptCounter(
            scope=scope,
            key=key,
            count=0,
            window_start=now,
        )
        db.add(counter)
        db.flush()
    elif counter.window_start + timedelta(seconds=window_seconds) <= now:
        counter.count = 0
        counter.window_start = now
        db.flush()
    return counter


def retry_after(db: Session, scope: str, key: str, window_seconds: int) -> int:
    counter = db.get(AttemptCounter, (scope, key))
    if counter is None:
        return window_seconds
    return max(1, seconds_until(counter.window_start + timedelta(seconds=window_seconds)))


def exceeded(db: Session, scope: str, key: str, limit: int, window_seconds: int) -> bool:
    counter = _counter(db, scope, key, window_seconds)
    return counter.count >= limit


def bump(db: Session, scope: str, key: str, window_seconds: int) -> None:
    counter = _counter(db, scope, key, window_seconds)
    counter.count += 1
    db.flush()


def reset(db: Session, scope: str, key: str) -> None:
    counter = db.get(AttemptCounter, (scope, key))
    if counter is not None:
        counter.count = 0
        counter.window_start = utcnow()
        db.flush()
