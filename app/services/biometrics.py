"""Biometrik: challenge, verifikasi tanda tangan, dan pendaftaran kunci."""

from __future__ import annotations

import base64
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import seconds_until, to_iso, utcnow
from app.core.errors import AppError
from app.core.security import public_id, validate_ec_public_key, verify_ecdsa
from app.models import BiometricChallenge, BiometricType, Device, SecuritySeverity, User, UserBiometric
from app.services.profile import record_security_event


def get_biometric(
    db: Session, user: User, device: Device, kind: BiometricType
) -> UserBiometric | None:
    return db.scalar(
        select(UserBiometric).where(
            UserBiometric.user_id == user.id,
            UserBiometric.device_id == device.id,
            UserBiometric.type == kind,
        )
    )


def ensure_biometric_unlocked(biometric: UserBiometric) -> None:
    if biometric.locked_until and biometric.locked_until > utcnow():
        retry_after = seconds_until(biometric.locked_until)
        raise AppError("BIOMETRIC_LOCKED", details={"retry_after": retry_after}, retry_after=retry_after)


def create_challenge(db: Session, user: User, device: Device, kind: BiometricType) -> BiometricChallenge:
    challenge = BiometricChallenge(
        public_id=public_id("chl"),
        user_id=user.id,
        device_id=device.id,
        type=kind,
        challenge=base64.b64encode(secrets.token_bytes(32)).decode(),
        expires_at=utcnow() + timedelta(seconds=settings.CHALLENGE_TTL),
    )
    db.add(challenge)
    db.flush()
    return challenge


def challenge_public(challenge: BiometricChallenge) -> dict:
    return {
        "challenge_id": challenge.public_id,
        "challenge": challenge.challenge,
        "expires_in": settings.CHALLENGE_TTL,
    }


def get_challenge(db: Session, challenge_public_id: str) -> BiometricChallenge:
    challenge = db.scalar(
        select(BiometricChallenge).where(BiometricChallenge.public_id == challenge_public_id)
    )
    if challenge is None or challenge.used_at is not None or challenge.expires_at <= utcnow():
        raise AppError("CHALLENGE_EXPIRED")
    return challenge


def verify_login(
    db: Session,
    *,
    user: User,
    device: Device,
    challenge: BiometricChallenge,
    signature: str,
) -> None:
    if challenge.user_id != user.id or challenge.device_id != device.id:
        raise AppError("CHALLENGE_EXPIRED")

    biometric = get_biometric(db, user, device, challenge.type)
    if biometric is None:
        raise AppError("BIOMETRIC_NOT_REGISTERED")
    ensure_biometric_unlocked(biometric)

    if not verify_ecdsa(biometric.public_key, challenge.challenge, signature):
        biometric.failed_count += 1
        if biometric.failed_count >= settings.BIOMETRIC_MAX_FAILED:
            biometric.failed_count = 0
            biometric.locked_until = utcnow() + timedelta(seconds=settings.BIOMETRIC_LOCK_SECONDS)
            db.flush()
            record_security_event(
                db,
                user,
                "FACE_FAILED" if challenge.type == BiometricType.FACE else "PIN_FAILED",
                SecuritySeverity.HIGH,
                device=device,
                description="Biometrik gagal berulang; dinonaktifkan sementara.",
            )
            db.commit()
            raise AppError(
                "BIOMETRIC_LOCKED",
                details={"retry_after": settings.BIOMETRIC_LOCK_SECONDS},
                retry_after=settings.BIOMETRIC_LOCK_SECONDS,
            )
        db.flush()
        if challenge.type == BiometricType.FACE:
            record_security_event(
                db,
                user,
                "FACE_FAILED",
                SecuritySeverity.MEDIUM,
                device=device,
                description="Verifikasi wajah gagal.",
            )
        db.commit()
        raise AppError("BIOMETRIC_SIGNATURE_INVALID")

    biometric.failed_count = 0
    biometric.locked_until = None
    challenge.used_at = utcnow()
    db.flush()


def check_liveness(liveness_session_id: str) -> None:
    """Mock penyedia liveness untuk Fase 2.

    ``lv_`` diterima; ``lv_fail`` mensimulasikan liveness gagal.
    """
    if liveness_session_id == "lv_fail":
        raise AppError("FACE_LIVENESS_FAILED")
    if not liveness_session_id.startswith("lv_"):
        raise AppError("LIVENESS_SESSION_INVALID")


def register_biometric(
    db: Session,
    *,
    user: User,
    device: Device,
    kind: BiometricType,
    public_key: str,
    liveness_session_id: str | None = None,
) -> UserBiometric:
    existing = get_biometric(db, user, device, kind)
    if existing is not None:
        raise AppError("BIOMETRIC_ALREADY_REGISTERED")

    validate_ec_public_key(public_key)
    if kind == BiometricType.FACE:
        if not liveness_session_id:
            raise AppError("LIVENESS_SESSION_INVALID")
        check_liveness(liveness_session_id)

    biometric = UserBiometric(
        user_id=user.id,
        device_id=device.id,
        type=kind,
        public_key=public_key,
        registered_at=utcnow(),
    )
    db.add(biometric)
    db.flush()
    return biometric


def biometrics_status(db: Session, user: User, device: Device) -> dict:
    result = {
        "fingerprint": {"registered": False, "registered_at": None},
        "face": {"registered": False, "registered_at": None},
        "use_for_login": user.biometric_login,
    }
    rows = db.scalars(
        select(UserBiometric).where(
            UserBiometric.user_id == user.id,
            UserBiometric.device_id == device.id,
        )
    ).all()
    for row in rows:
        key = "fingerprint" if row.type == BiometricType.FINGERPRINT else "face"
        result[key] = {"registered": True, "registered_at": to_iso(row.registered_at)}
    return result


def count_biometrics(db: Session, user: User) -> int:
    return len(db.scalars(select(UserBiometric).where(UserBiometric.user_id == user.id)).all())
