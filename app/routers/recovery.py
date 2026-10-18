"""Pemulihan nomor HP (bagian 4.13 - 4.16)."""

from __future__ import annotations

import secrets
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import seconds_until, utcnow
from app.core.deps import client_ip, device_header
from app.core.errors import AppError, ok
from app.core.security import sha256
from app.db import get_db
from app.models import (
    AttemptCounter,
    KycProfile,
    KycStatus,
    OtpPurpose,
    PhoneRecovery,
    RecoveryRequest,
    SecuritySeverity,
    User,
)
from app.schemas import (
    PhoneRecoveryCompleteIn,
    PhoneRecoveryFaceIn,
    PhoneRecoveryPhoneIn,
    PhoneRecoveryStartIn,
    RecoverySupportStartIn,
    RecoverySupportSubmitIn,
)
from app.services import biometrics as bio_service
from app.services import rate_limit
from app.services.auth import (
    mark_verification_used,
    otp_public,
    otp_target,
    request_otp,
    revoke_user_sessions,
    validate_verification,
)
from app.services.profile import find_user_by_phone, record_security_event

router = APIRouter(prefix="/auth/phone-recovery", tags=["phone-recovery"])


def _nik_hash(nik: str) -> str:
    return sha256(f"{settings.JWT_SECRET}:nik:{nik}")


def _attempt_key(request: Request) -> str:
    return f"{device_header(request)}|{client_ip(request)}"


def _counter(db: Session, key: str) -> AttemptCounter:
    now = utcnow()
    counter = db.get(AttemptCounter, ("phone_recovery", key))
    if counter is None:
        counter = AttemptCounter(scope="phone_recovery", key=key, count=0, window_start=now)
        db.add(counter)
        db.flush()
    elif counter.window_start + timedelta(seconds=settings.RECOVERY_ATTEMPT_WINDOW) <= now:
        counter.count = 0
        counter.window_start = now
        db.flush()
    return counter


def _attempts_left(counter: AttemptCounter) -> int:
    return max(0, settings.RECOVERY_MAX_ATTEMPTS - counter.count)


def _age_on(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _get_recovery(db: Session, recovery_public_id: str) -> PhoneRecovery:
    recovery = db.scalar(select(PhoneRecovery).where(PhoneRecovery.public_id == recovery_public_id))
    if recovery is None:
        raise AppError("RECOVERY_NOT_FOUND")
    if recovery.completed_at is not None or recovery.expires_at <= utcnow():
        raise AppError("RECOVERY_EXPIRED")
    return recovery


@router.post("", summary="Mulai pemulihan nomor")
def start_recovery(payload: PhoneRecoveryStartIn, request: Request, db: Session = Depends(get_db)):
    counter = _counter(db, _attempt_key(request))
    if counter.count >= settings.RECOVERY_MAX_ATTEMPTS:
        retry_after = seconds_until(
            counter.window_start + timedelta(seconds=settings.RECOVERY_ATTEMPT_WINDOW)
        ) or 60
        raise AppError(
            "RECOVERY_ATTEMPTS_EXCEEDED",
            details={"retry_after": retry_after},
            retry_after=retry_after,
        )

    if payload.birth_date >= date.today():
        raise AppError("INVALID_DATE", message="Tanggal lahir tidak valid.")
    if _age_on(payload.birth_date, date.today()) < 17:
        raise AppError("INVALID_DATE", message="Usia minimal 17 tahun.")

    profile = db.scalar(select(KycProfile).where(KycProfile.nik_hash == _nik_hash(payload.nik)))
    user = db.get(User, profile.user_id) if profile else None
    if profile is None or user is None or profile.birth_date != payload.birth_date:
        counter.count += 1
        db.commit()
        left = _attempts_left(counter)
        if left <= 0:
            retry_after = seconds_until(
                counter.window_start + timedelta(seconds=settings.RECOVERY_ATTEMPT_WINDOW)
            ) or 60
            raise AppError(
                "RECOVERY_ATTEMPTS_EXCEEDED",
                details={"retry_after": retry_after},
                retry_after=retry_after,
            )
        raise AppError("KYC_NOT_FOUND", details={"attempts_left": left})

    counter.count = 0
    recovery = PhoneRecovery(
        public_id=f"rec_{secrets.token_hex(5)}",
        user_id=user.id,
        attempts_left=_attempts_left(counter),
        expires_at=utcnow() + timedelta(seconds=settings.RECOVERY_TTL),
    )
    liveness_session_id = f"lv_{secrets.token_hex(8)}"
    recovery.liveness_session_id = liveness_session_id
    db.add(recovery)
    db.commit()

    return ok(
        {
            "recovery_id": recovery.public_id,
            "liveness_session_id": liveness_session_id,
            "expires_in": settings.RECOVERY_TTL,
            "attempts_left": recovery.attempts_left,
        }
    )


@router.post("/{recovery_id}/face", summary="Verifikasi wajah pemulihan")
def verify_recovery_face(
    recovery_id: str,
    payload: PhoneRecoveryFaceIn,
    db: Session = Depends(get_db),
):
    recovery = _get_recovery(db, recovery_id)
    if payload.liveness_session_id != recovery.liveness_session_id:
        raise AppError("LIVENESS_SESSION_INVALID")
    bio_service.check_liveness(payload.liveness_session_id)

    recovery.face_verified = True
    db.commit()
    return ok(
        {
            "recovery_id": recovery.public_id,
            "face_verified": True,
            "expires_in": seconds_until(recovery.expires_at),
        }
    )


@router.post("/{recovery_id}/phone", summary="Kirim OTP ke nomor baru")
def recovery_new_phone(
    recovery_id: str,
    payload: PhoneRecoveryPhoneIn,
    db: Session = Depends(get_db),
):
    recovery = _get_recovery(db, recovery_id)
    if not recovery.face_verified:
        raise AppError("RECOVERY_STEP_INVALID")

    user = db.get(User, recovery.user_id)
    if user is None:
        raise AppError("RECOVERY_NOT_FOUND")
    if payload.new_phone == user.phone:
        raise AppError("PHONE_SAME_AS_CURRENT")
    if find_user_by_phone(db, payload.new_phone) is not None:
        raise AppError("PHONE_ALREADY_REGISTERED")

    recovery.new_phone = payload.new_phone
    session = request_otp(
        db,
        phone=payload.new_phone,
        purpose=OtpPurpose.CHANGE_PHONE,
        user=user,
        context={"recovery_id": recovery.public_id, "new_phone": payload.new_phone},
    )
    db.commit()
    return ok(otp_public(session), "Kode OTP dikirim.")


@router.post("/{recovery_id}/complete", summary="Selesaikan pemulihan nomor")
def recovery_complete(
    recovery_id: str,
    payload: PhoneRecoveryCompleteIn,
    db: Session = Depends(get_db),
):
    verification, session = validate_verification(
        db, payload.verification_token, OtpPurpose.CHANGE_PHONE
    )
    context = session.context or {}
    if context.get("recovery_id") != recovery_id:
        raise AppError("RECOVERY_NOT_FOUND")

    recovery = _get_recovery(db, recovery_id)
    if not recovery.face_verified:
        raise AppError("RECOVERY_STEP_INVALID")

    user = db.get(User, recovery.user_id)
    if user is None:
        raise AppError("RECOVERY_NOT_FOUND")

    new_phone = context.get("new_phone") or recovery.new_phone
    if not new_phone:
        raise AppError("RECOVERY_STEP_INVALID")
    other = find_user_by_phone(db, new_phone)
    if other is not None and other.id != user.id:
        raise AppError("PHONE_ALREADY_REGISTERED")

    old_phone = user.phone
    user.phone = new_phone
    user.kyc_status = KycStatus.VERIFIED
    recovery.completed_at = utcnow()
    revoke_user_sessions(db, user, all_devices=True)
    record_security_event(
        db,
        user,
        "PHONE_CHANGED",
        SecuritySeverity.HIGH,
        description=f"Nomor HP diubah dari {old_phone} ke {new_phone}.",
    )
    mark_verification_used(db, verification)
    db.commit()

    return ok(
        {
            "new_phone": new_phone,
            "redirect": "LOGIN",
            "sessions_revoked": True,
        },
        "Nomor berhasil diganti.",
    )

# ------------------------------------------------- H.7.3 pemulihan tanpa KYC


@router.post("/support", summary="Ajukan pemulihan tanpa KYC (langkah 1)")
def support_start(
    payload: RecoverySupportStartIn,
    request: Request,
    db: Session = Depends(get_db),
):
    old_user = find_user_by_phone(db, payload.old_phone)
    if payload.old_phone == payload.new_phone:
        raise AppError("PHONE_SAME_AS_CURRENT")
    context = {
        "flow": "SUPPORT",
        "old_phone": payload.old_phone,
        "new_phone": payload.new_phone,
        "name": payload.name,
        "user_id": str(old_user.id) if old_user else None,
    }
    session = request_otp(
        db,
        phone=payload.new_phone,
        purpose=OtpPurpose.CHANGE_PHONE,
        user=old_user,
        context=context,
        device_id=device_header(request),
        ip=client_ip(request),
    )
    db.commit()
    return ok(otp_public(session), "Kode OTP dikirim.")


@router.post("/support/submit", summary="Ajukan pemulihan tanpa KYC (langkah 2)")
def support_submit(
    payload: RecoverySupportSubmitIn,
    request: Request,
    db: Session = Depends(get_db),
):
    verification, session = validate_verification(
        db, payload.verification_token, OtpPurpose.CHANGE_PHONE
    )
    context = session.context or {}
    if context.get("flow") != "SUPPORT":
        raise AppError("VERIFICATION_TOKEN_INVALID")

    device_id = device_header(request)
    ip = client_ip(request)
    if device_id and rate_limit.exceeded(
        db, "recovery_device", device_id, 1, 3600
    ):
        raise AppError("RATE_LIMITED", details={"retry_after": 3600}, retry_after=3600)
    if ip and rate_limit.exceeded(db, "recovery_ip", ip, 1, 3600):
        raise AppError("RATE_LIMITED", details={"retry_after": 3600}, retry_after=3600)
    if device_id:
        rate_limit.bump(db, "recovery_device", device_id, 3600)
    if ip:
        rate_limit.bump(db, "recovery_ip", ip, 3600)

    user = None
    raw_user_id = context.get("user_id")
    if raw_user_id:
        try:
            user = db.get(User, uuid.UUID(str(raw_user_id)))
        except ValueError:
            user = None

    old_phone = context.get("old_phone") or otp_target(session)
    new_phone = context.get("new_phone") or otp_target(session)
    if user is not None:
        user.recovery_hold = True

    request_row = RecoveryRequest(
        public_id=f"rcv_{secrets.token_hex(5)}",
        user_id=user.id if user else None,
        old_phone=old_phone,
        new_phone=new_phone,
        name=context.get("name") or "Pengguna",
        last_transaction_hint=payload.last_transaction_hint,
        balance_hint=payload.balance_hint,
        note=payload.note,
        status="PENDING_REVIEW",
    )
    db.add(request_row)
    db.flush()
    mark_verification_used(db, verification)
    db.commit()

    body = ok(
        {
            "ticket_id": request_row.public_id,
            "status": "PENDING_REVIEW",
            "estimated_hours": 24,
            "balance_on_hold": True,
        },
        "Pengajuan diterima.",
    )
    return JSONResponse(status_code=201, content=jsonable_encoder(body))
