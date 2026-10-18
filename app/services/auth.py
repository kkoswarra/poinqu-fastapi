"""OTP, verification token, JWT sesi pengguna, dan rotasi refresh token."""

from __future__ import annotations

import random
import secrets
import time
import uuid
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import seconds_until, to_epoch, to_iso, utcnow
from app.core.errors import AppError
from app.core.security import (
    access_token,
    decode_user_access,  # noqa: F401  (re-export untuk router)
    hash_secret,
    opaque_token,
    public_id,
    sha256,
    verify_secret,
)
from app.models import (
    Device,
    OtpPurpose,
    OtpSession,
    RefreshToken,
    User,
    UserStatus,
    VerificationToken,
)
from app.services import rate_limit, whatsapp
from app.services import settings as settings_service
from app.services.revocation import store as revocation_store


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_public(session: OtpSession) -> dict:
    return {
        "otp_session_id": session.public_id,
        "purpose": session.purpose.value,
        "masked_phone": _mask(session.phone),
        "channel": session.channel,
        "expires_in": settings.OTP_TTL,
        "resend_available_in": settings.OTP_RESEND_COOLDOWN,
        "max_attempts": settings.OTP_MAX_ATTEMPTS,
    }


def _mask(phone: str) -> str:
    return f"{phone[:4]}****{phone[-4:]}" if len(phone) > 8 else phone


def equalize_timing() -> None:
    """Samakan waktu respons jalur "tidak mengirim" (H.7.2): 200-600 ms."""
    time.sleep(random.uniform(0.2, 0.6))


def _otp_limits(db: Session) -> tuple[int, int, int]:
    return (
        settings_service.get_int(db, "otp.rate.per_phone_hour", 5),
        settings_service.get_int(db, "otp.rate.per_device_hour", 10),
        settings_service.get_int(db, "otp.rate.per_ip_hour", 20),
    )


def enforce_otp_limits(db: Session, phone: str, device_id: str, ip: str) -> None:
    per_phone, per_device, per_ip = _otp_limits(db)
    now = utcnow()
    window_start = now - timedelta(hours=1)

    phone_count = db.scalar(
        select(func.count())
        .select_from(OtpSession)
        .where(
            OtpSession.phone == phone,
            OtpSession.created_at >= window_start,
            OtpSession.cancelled_at.is_(None),
        )
    )
    retries: list[int] = []
    if (phone_count or 0) >= per_phone:
        oldest = db.scalar(
            select(OtpSession.created_at)
            .where(
                OtpSession.phone == phone,
                OtpSession.created_at >= window_start,
                OtpSession.cancelled_at.is_(None),
            )
            .order_by(OtpSession.created_at.asc())
            .limit(1)
        )
        retries.append(
            seconds_until(oldest + timedelta(hours=1)) if oldest else 1800
        )

    if device_id and rate_limit.exceeded(db, "otp_device", device_id, per_device, 3600):
        retries.append(rate_limit.retry_after(db, "otp_device", device_id, 3600))
    if ip and rate_limit.exceeded(db, "otp_ip", ip, per_ip, 3600):
        retries.append(rate_limit.retry_after(db, "otp_ip", ip, 3600))

    if retries:
        retry_after = max(1, max(retries))
        raise AppError(
            "OTP_RATE_LIMITED",
            details={"retry_after": retry_after},
            retry_after=retry_after,
        )


def bump_otp_scope(db: Session, device_id: str, ip: str) -> None:
    if device_id:
        rate_limit.bump(db, "otp_device", device_id, 3600)
    if ip:
        rate_limit.bump(db, "otp_ip", ip, 3600)


def request_otp(
    db: Session,
    *,
    phone: str,
    purpose: OtpPurpose,
    context: dict | None = None,
    user: User | None = None,
    device_id: str = "",
    ip: str = "",
    decoy: bool = False,
    notification: str | None = None,
) -> OtpSession:
    whatsapp.ensure_provider_healthy(db)
    enforce_otp_limits(db, phone, device_id, ip)

    now = utcnow()
    code = _new_code()
    session = OtpSession(
        public_id=public_id("otp"),
        phone=phone,
        user_id=user.id if user else None,
        purpose=purpose,
        code_hash=hash_secret(code),
        context=context,
        expires_at=now + timedelta(seconds=settings.OTP_TTL),
        last_sent_at=now,
        is_decoy=decoy,
    )
    db.add(session)
    db.flush()

    if notification is not None:
        with suppress(AppError):
            # Pemberitahuan bersifat best-effort; jangan bocorkan status akun.
            whatsapp.send_text(db, phone, notification)
        bump_otp_scope(db, device_id, ip)
        if decoy:
            equalize_timing()
        return session

    if decoy:
        # Tidak ada pesan WhatsApp. Tetap dihitung ke batas dan waktunya disamakan.
        bump_otp_scope(db, device_id, ip)
        equalize_timing()
        return session

    try:
        whatsapp.send_otp(db, session, code)
    except AppError:
        # Pengiriman gagal: sesi dibatalkan dan tidak dihitung ke batas per jam.
        session.cancelled_at = utcnow()
        db.commit()
        raise
    bump_otp_scope(db, device_id, ip)
    return session


def get_otp_session(db: Session, session_public_id: str) -> OtpSession:
    session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_public_id))
    if session is None or session.verified_at is not None or session.cancelled_at is not None:
        raise AppError("OTP_SESSION_NOT_FOUND")
    return session


def resend_otp(db: Session, session_public_id: str) -> OtpSession:
    whatsapp.ensure_provider_healthy(db)

    session = get_otp_session(db, session_public_id)
    now = utcnow()

    retry_after = seconds_until(session.last_sent_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN))
    if retry_after > 0:
        raise AppError("OTP_RESEND_TOO_SOON", details={"retry_after": retry_after}, retry_after=retry_after)

    if session.resend_count >= settings.OTP_MAX_RESENDS:
        raise AppError("OTP_RESEND_LIMIT")

    code = _new_code()
    if session.is_decoy:
        # Anti-enumerasi (H.7.2): sesi palsu harus melewati aturan cooldown,
        # batas kirim ulang, dan bentuk respons yang sama tanpa mengirim WhatsApp.
        equalize_timing()
    else:
        try:
            # Kirim dulu; state sesi baru diubah bila provider menerima.
            whatsapp.send_otp(db, session, code)
        except AppError:
            db.commit()
            raise

    session.code_hash = hash_secret(code)
    session.resend_count += 1
    session.attempts = 0
    session.expires_at = now + timedelta(seconds=settings.OTP_TTL)
    session.last_sent_at = now
    db.flush()
    return session


def issue_verification(
    db: Session,
    session: OtpSession,
    *,
    via: str = "OTP",
    device_id: str | None = None,
) -> tuple[VerificationToken, str]:
    raw = opaque_token("vt")
    now = utcnow()
    verification = VerificationToken(
        token_hash=sha256(raw),
        otp_session_id=session.id,
        purpose=session.purpose,
        via=via,
        device_id=device_id,
        expires_at=now + timedelta(seconds=settings.VERIFICATION_TOKEN_TTL),
    )
    db.add(verification)
    db.flush()
    return verification, raw


def create_trusted_login_token(
    db: Session, user: User, phone: str, device_id: str
) -> str:
    """Token LOGIN tanpa OTP untuk perangkat tepercaya (H.7.1)."""
    now = utcnow()
    session = OtpSession(
        public_id=public_id("otp"),
        phone=phone,
        user_id=user.id,
        purpose=OtpPurpose.LOGIN,
        code_hash=hash_secret(_new_code()),
        context={"via": "TRUSTED_DEVICE"},
        expires_at=now + timedelta(seconds=settings.VERIFICATION_TOKEN_TTL),
        cancelled_at=now,  # tidak dihitung ke batas OTP
    )
    db.add(session)
    db.flush()
    _, raw = issue_verification(
        db, session, via="TRUSTED_DEVICE", device_id=device_id
    )
    return raw


def verify_otp(db: Session, session_public_id: str, code: str) -> tuple[VerificationToken, str]:
    session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_public_id))
    if session is None or session.verified_at is not None or session.cancelled_at is not None:
        raise AppError("OTP_SESSION_NOT_FOUND")

    now = utcnow()
    if session.expires_at <= now:
        raise AppError("OTP_EXPIRED")

    if session.is_decoy:
        session.attempts += 1
        attempts_left = max(0, settings.OTP_MAX_ATTEMPTS - session.attempts)
        db.commit()
        if attempts_left == 0:
            raise AppError(
                "OTP_ATTEMPTS_EXCEEDED",
                details={"retry_after": 900},
                retry_after=900,
            )
        raise AppError("OTP_INVALID", details={"attempts_left": attempts_left})

    if session.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise AppError(
            "OTP_ATTEMPTS_EXCEEDED",
            details={"retry_after": 900},
            retry_after=900,
        )

    if not verify_secret(session.code_hash, code):
        session.attempts += 1
        attempts_left = max(0, settings.OTP_MAX_ATTEMPTS - session.attempts)
        db.commit()
        if attempts_left == 0:
            raise AppError(
                "OTP_ATTEMPTS_EXCEEDED",
                details={"retry_after": 900},
                retry_after=900,
            )
        raise AppError("OTP_INVALID", details={"attempts_left": attempts_left})

    session.verified_at = now
    verification, raw = issue_verification(db, session)
    db.flush()
    return verification, raw


def _find_verification(db: Session, raw: str) -> VerificationToken:
    verification = db.scalar(select(VerificationToken).where(VerificationToken.token_hash == sha256(raw)))
    if verification is None or verification.used_at is not None:
        raise AppError("VERIFICATION_TOKEN_INVALID")
    if verification.expires_at <= utcnow():
        raise AppError("VERIFICATION_TOKEN_EXPIRED")
    return verification


def validate_verification(db: Session, raw: str, purpose: OtpPurpose) -> tuple[VerificationToken, OtpSession]:
    verification = _find_verification(db, raw)
    if verification.purpose != purpose:
        raise AppError("VERIFICATION_PURPOSE_MISMATCH")
    session = db.get(OtpSession, verification.otp_session_id)
    if session is None:
        raise AppError("VERIFICATION_TOKEN_INVALID")
    return verification, session


def consume_verification(db: Session, raw: str, purpose: OtpPurpose) -> OtpSession:
    verification, session = validate_verification(db, raw, purpose)
    verification.used_at = utcnow()
    db.flush()
    return session


def mark_verification_used(db: Session, verification: VerificationToken) -> None:
    verification.used_at = utcnow()
    db.flush()


def issue_user_tokens(
    db: Session,
    user: User,
    device: Device,
    *,
    family_id: uuid.UUID | None = None,
) -> tuple[dict, RefreshToken]:
    raw = opaque_token("rt")
    now = utcnow()
    family = family_id or uuid.uuid4()
    record = RefreshToken(
        user_id=user.id,
        device_id=device.id,
        family_id=family,
        token_hash=sha256(raw),
        expires_at=now + timedelta(seconds=settings.REFRESH_TOKEN_TTL),
    )
    db.add(record)
    db.flush()
    payload = {
        "access_token": access_token(str(user.id), str(device.id), str(family)),
        "refresh_token": raw,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_TTL,
        "refresh_expires_in": settings.REFRESH_TOKEN_TTL,
    }
    return payload, record


def rotate_user_refresh(db: Session, raw: str, device_id_value: str) -> dict:
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(raw)))
    now = utcnow()
    if record is None:
        raise AppError("REFRESH_TOKEN_INVALID")

    if record.revoked_at is not None:
        if record.replaced_by is not None:
            for sibling in db.scalars(
                select(RefreshToken).where(RefreshToken.family_id == record.family_id)
            ).all():
                if sibling.revoked_at is None:
                    sibling.revoked_at = now
            for device in db.scalars(
                select(Device).where(Device.user_id == record.user_id)
            ).all():
                device.trusted_at = None
            revocation_store.revoke_user(
                str(record.user_id), to_epoch(now), settings.ACCESS_TOKEN_TTL
            )
            db.commit()
        raise AppError("REFRESH_TOKEN_REVOKED")

    if record.expires_at <= now:
        raise AppError("REFRESH_TOKEN_INVALID")

    device = db.get(Device, record.device_id)
    if device is None or device.revoked_at is not None:
        raise AppError("REFRESH_TOKEN_REVOKED")
    if device.device_id != device_id_value:
        raise AppError("DEVICE_MISMATCH", status=422)

    user = db.get(User, record.user_id)
    if user is None:
        raise AppError("REFRESH_TOKEN_INVALID")
    if user.status == UserStatus.SUSPENDED:
        raise AppError("ACCOUNT_SUSPENDED")
    if user.status == UserStatus.LOCKED:
        raise AppError("ACCOUNT_LOCKED")

    record.revoked_at = now
    tokens, new_record = issue_user_tokens(db, user, device, family_id=record.family_id)
    record.replaced_by = new_record.id
    db.flush()
    return tokens


def revoke_user_sessions(
    db: Session,
    user: User,
    *,
    except_device_uuid: uuid.UUID | None = None,
    all_devices: bool = False,
) -> None:
    now = utcnow()
    families: set[uuid.UUID] = set()
    for record in db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    ).all():
        if except_device_uuid is not None and record.device_id == except_device_uuid:
            continue
        record.revoked_at = now
        families.add(record.family_id)

    stmt = select(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))
    for device in db.scalars(stmt).all():
        if except_device_uuid is not None and not all_devices and device.id == except_device_uuid:
            continue
        device.revoked_at = now
        device.trusted_at = None

    for family in families:
        revocation_store.revoke_session(str(family), settings.ACCESS_TOKEN_TTL)
    if except_device_uuid is None or all_devices:
        revocation_store.revoke_user(
            str(user.id), to_epoch(now), settings.ACCESS_TOKEN_TTL
        )
    db.flush()


def token_payload_from_access(payload: dict) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        return uuid.UUID(str(payload["sub"])), uuid.UUID(str(payload["dev"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise AppError("UNAUTHORIZED") from exc


__all__ = [
    "consume_verification",
    "issue_user_tokens",
    "otp_public",
    "request_otp",
    "resend_otp",
    "revoke_user_sessions",
    "rotate_user_refresh",
    "to_iso",
    "validate_verification",
    "verify_otp",
]
