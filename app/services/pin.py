"""PIN: verifikasi per perangkat, kunci bertingkat, dan PIN token sekali pakai."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import seconds_until, to_iso, utcnow
from app.core.errors import AppError
from app.core.security import (
    hash_secret,
    is_weak_pin,
    opaque_token,
    sha256,
    verify_secret,
)
from app.models import AttemptCounter, Device, PinAttempt, PinToken, SecuritySeverity, User
from app.services import rate_limit
from app.services import settings as settings_service
from app.services.profile import record_security_event

_LOCK_DURATIONS = {1: "lock_minutes", 2: "hour", 3: "day"}


def check_new_pin(user: User, new_pin: str, confirmation: str, phone: str | None = None) -> None:
    if new_pin != confirmation:
        raise AppError("PIN_MISMATCH")
    if is_weak_pin(new_pin, phone or user.phone):
        raise AppError("PIN_TOO_WEAK")
    if user.pin_hash and verify_secret(user.pin_hash, new_pin):
        raise AppError("PIN_SAME_AS_OLD")


def _attempt_row(db: Session, user: User, device: Device) -> PinAttempt:
    row = db.get(PinAttempt, (user.id, device.id))
    if row is None:
        row = PinAttempt(user_id=user.id, device_id=device.id)
        db.add(row)
        db.flush()
    return row


def _lock_seconds(db: Session, level: int) -> int:
    base_minutes = settings_service.get_int(db, "security.pin.lock_minutes", 15)
    if level <= 1:
        return base_minutes * 60
    if level == 2:
        return 3600
    return 86_400


def verify_user_pin(db: Session, user: User, pin: str, device: Device) -> None:
    now = utcnow()
    if not user.pin_hash:
        raise AppError("PIN_NOT_SET")

    # Kunci tingkat akun (15 salah/jam dari perangkat mana pun).
    if user.pin_locked_until and user.pin_locked_until > now:
        retry_after = seconds_until(user.pin_locked_until)
        raise AppError(
            "ACCOUNT_LOCKED",
            details={"retry_after": retry_after},
            retry_after=retry_after,
        )

    attempt = _attempt_row(db, user, device)
    if attempt.locked_until and attempt.locked_until > now:
        retry_after = seconds_until(attempt.locked_until)
        raise AppError(
            "PIN_LOCKED",
            details={
                "retry_after": retry_after,
                "locked_until": to_iso(attempt.locked_until),
            },
            retry_after=retry_after,
        )

    if verify_secret(user.pin_hash, pin):
        attempt.failed_count = 0
        attempt.lockout_level = 0
        attempt.locked_until = None
        user.pin_failed_count = 0
        user.pin_locked_until = None
        rate_limit.reset(db, "pin_account", str(user.id))
        db.flush()
        return

    max_attempts = settings_service.get_int(db, "security.pin.max_attempts", 5)
    account_limit = settings_service.get_int(
        db, "security.pin.account_max_attempts_hour", 15
    )

    attempt.failed_count += 1
    attempt.last_failed_at = now
    rate_limit.bump(db, "pin_account", str(user.id), 3600)
    account_counter = db.get(AttemptCounter, ("pin_account", str(user.id)))
    account_failures = account_counter.count if account_counter else 1
    user.pin_failed_count = account_failures

    if account_failures >= account_limit:
        user.pin_locked_until = now + timedelta(seconds=3600)
        db.flush()
        record_security_event(
            db,
            user,
            "PIN_FAILED",
            SecuritySeverity.HIGH,
            device=device,
            description="Terlalu banyak PIN salah dalam satu jam; akun dikunci sementara.",
        )
        db.commit()
        raise AppError(
            "ACCOUNT_LOCKED",
            details={"retry_after": 3600},
            retry_after=3600,
        )

    if attempt.failed_count >= max_attempts:
        level = min(attempt.lockout_level + 1, 3)
        duration = _lock_seconds(db, level)
        attempt.lockout_level = level
        attempt.failed_count = 0
        attempt.locked_until = now + timedelta(seconds=duration)
        db.flush()
        record_security_event(
            db,
            user,
            "PIN_FAILED",
            SecuritySeverity.HIGH,
            device=device,
            description=f"PIN salah {max_attempts} kali; perangkat dikunci {duration // 60} menit.",
        )
        db.commit()
        raise AppError(
            "PIN_LOCKED",
            details={
                "retry_after": duration,
                "locked_until": to_iso(attempt.locked_until),
            },
            retry_after=duration,
        )

    attempts_left = max(0, max_attempts - attempt.failed_count)
    db.flush()
    record_security_event(
        db,
        user,
        "PIN_FAILED",
        SecuritySeverity.MEDIUM,
        device=device,
        description=f"PIN salah ({attempts_left} percobaan tersisa di perangkat ini).",
    )
    db.commit()
    raise AppError("PIN_INVALID", details={"attempts_left": attempts_left})


def set_pin(db: Session, user: User, new_pin: str) -> None:
    user.pin_hash = hash_secret(new_pin)
    user.pin_failed_count = 0
    user.pin_locked_until = None
    for row in db.scalars(select(PinAttempt).where(PinAttempt.user_id == user.id)).all():
        row.failed_count = 0
        row.lockout_level = 0
        row.locked_until = None
    db.flush()


def create_pin_token(db: Session, user: User, purpose: str, preview_id: str | None = None) -> str:
    raw = opaque_token("pt")
    token = PinToken(
        user_id=user.id,
        token_hash=sha256(raw),
        purpose=purpose,
        preview_id=preview_id,
        expires_at=utcnow() + timedelta(seconds=settings.PIN_TOKEN_TTL),
    )
    db.add(token)
    db.flush()
    return raw


def consume_pin_token(db: Session, user: User, raw: str, purpose: str) -> PinToken:
    if not raw:
        raise AppError("PIN_TOKEN_INVALID")
    token = db.scalar(
        select(PinToken).where(PinToken.user_id == user.id, PinToken.token_hash == sha256(raw))
    )
    if token is None or token.used_at is not None:
        raise AppError("PIN_TOKEN_INVALID")
    if token.expires_at <= utcnow():
        raise AppError("PIN_TOKEN_EXPIRED")
    if token.purpose != purpose:
        raise AppError("PIN_TOKEN_MISMATCH")
    token.used_at = utcnow()
    db.flush()
    return token
