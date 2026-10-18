"""Endpoint autentikasi pengguna (bagian 4.1 - 4.12)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import to_iso, utcnow
from app.core.deps import client_ip, device_header, get_current_user
from app.core.errors import AppError, ok
from app.core.security import is_weak_pin, mask_phone
from app.db import get_db
from app.models import (
    BiometricType,
    Device,
    KycStatus,
    OtpPurpose,
    OtpSession,
    RefreshToken,
    SecuritySeverity,
    User,
    UserBiometric,
    UserLevel,
    UserStatus,
)
from app.schemas import (
    BiometricChallengeIn,
    BiometricLoginIn,
    LoginPinIn,
    LoginStartIn,
    LogoutIn,
    OtpRequestIn,
    OtpResendIn,
    OtpVerifyIn,
    PinResetIn,
    RegisterCompleteIn,
    RegisterIn,
    TokenRefreshIn,
)
from app.services import attestation, rate_limit
from app.services import biometrics as bio_service
from app.services import pin as pin_service
from app.services import settings as settings_service
from app.services.auth import (
    create_trusted_login_token,
    equalize_timing,
    issue_user_tokens,
    mark_verification_used,
    otp_public,
    request_otp,
    resend_otp,
    revoke_user_sessions,
    rotate_user_refresh,
    validate_verification,
    verify_otp,
)
from app.services.profile import (
    find_user_by_phone,
    mark_device_trusted,
    record_security_event,
    upsert_device,
    user_public,
)
from app.services.revocation import store as revocation_store

router = APIRouter(prefix="/auth", tags=["auth"])


def _ensure_device_match(request: Request, device_id_value: str) -> None:
    if device_header(request) != device_id_value:
        raise AppError("DEVICE_MISMATCH", status=422)


def _ensure_user_active(user: User) -> None:
    if user.status == UserStatus.SUSPENDED:
        raise AppError("ACCOUNT_SUSPENDED")
    if user.status == UserStatus.LOCKED:
        raise AppError("ACCOUNT_LOCKED", details={"retry_after": 3600})


def _login_methods(db: Session, user: User, request: Request) -> tuple[str, list[str]]:
    device = db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == device_header(request),
            Device.revoked_at.is_(None),
        )
    )
    methods = ["PIN"]
    if device is None:
        return "PIN", methods

    rows = db.scalars(
        select(UserBiometric).where(
            UserBiometric.user_id == user.id, UserBiometric.device_id == device.id
        )
    ).all()
    registered = {row.type for row in rows}
    if BiometricType.FINGERPRINT in registered:
        methods.append("FINGERPRINT")
    if BiometricType.FACE in registered:
        methods.append("FACE")

    preferred = "PIN"
    if user.biometric_login:
        if BiometricType.FINGERPRINT in registered:
            preferred = "FINGERPRINT"
        elif BiometricType.FACE in registered:
            preferred = "FACE"
    return preferred, methods


@router.post("/otp/request", summary="Minta OTP")
def otp_request(payload: OtpRequestIn, request: Request, db: Session = Depends(get_db)):
    purpose = OtpPurpose(payload.purpose)
    if purpose == OtpPurpose.CHANGE_PHONE:
        raise AppError("INVALID_VALUE", message="Gunakan alur pemulihan nomor.")

    attestation.verify_attestation(db, request)
    device_id = device_header(request)
    ip = client_ip(request)
    user = find_user_by_phone(db, payload.phone)

    if purpose in (OtpPurpose.LOGIN, OtpPurpose.FORGOT_PIN):
        if user is None:
            # Anti-enumerasi (H.7.2): sesi palsu, tanpa pesan WhatsApp.
            session = request_otp(
                db,
                phone=payload.phone,
                purpose=purpose,
                device_id=device_id,
                ip=ip,
                decoy=True,
            )
            db.commit()
            return ok(otp_public(session), "Kode OTP dikirim.")
        _ensure_user_active(user)
    elif purpose == OtpPurpose.REGISTER and user is not None:
        # Nomor sudah terdaftar: balas sukses + pemberitahuan, bukan OTP.
        session = request_otp(
            db,
            phone=payload.phone,
            purpose=purpose,
            device_id=device_id,
            ip=ip,
            decoy=True,
            notification=(
                "Nomor ini sudah punya akun Poinqu. Silakan masuk, "
                "atau pakai Lupa PIN bila perlu."
            ),
        )
        db.commit()
        return ok(otp_public(session), "Kode OTP dikirim.")

    session = request_otp(
        db,
        phone=payload.phone,
        purpose=purpose,
        user=user,
        device_id=device_id,
        ip=ip,
    )
    db.commit()
    return ok(otp_public(session), "Kode OTP dikirim.")


@router.post("/otp/verify", summary="Verifikasi OTP")
def otp_verify(payload: OtpVerifyIn, request: Request, db: Session = Depends(get_db)):
    verification, raw = verify_otp(db, payload.otp_session_id, payload.code)
    session = db.get(OtpSession, verification.otp_session_id)
    if session is None:  # pragma: no cover - dijaga FK
        raise AppError("OTP_SESSION_NOT_FOUND")

    next_step = {
        OtpPurpose.LOGIN: "PIN",
        OtpPurpose.REGISTER: "SET_PIN",
        OtpPurpose.FORGOT_PIN: "NEW_PIN",
        OtpPurpose.CHANGE_PHONE: "COMPLETE",
    }.get(session.purpose, "PIN")

    data = {
        "verification_token": raw,
        "purpose": session.purpose.value,
        "expires_in": settings.VERIFICATION_TOKEN_TTL,
        "next_step": next_step,
    }

    if session.purpose == OtpPurpose.LOGIN and session.user_id:
        user = db.get(User, session.user_id)
        if user is not None:
            preferred, methods = _login_methods(db, user, request)
            data["preferred_method"] = preferred
            data["available_methods"] = methods

    db.commit()
    return ok(data)


@router.post("/otp/resend", summary="Kirim ulang OTP")
def otp_resend(payload: OtpResendIn, request: Request, db: Session = Depends(get_db)):
    attestation.verify_attestation(db, request)
    session = resend_otp(db, payload.otp_session_id)
    data = {
        "otp_session_id": session.public_id,
        "expires_in": settings.OTP_TTL,
        "resend_available_in": settings.OTP_RESEND_COOLDOWN,
        "resend_remaining": max(0, settings.OTP_MAX_RESENDS - session.resend_count),
    }
    db.commit()
    return ok(data, "Kode OTP dikirim ulang.")


@router.post("/register", summary="Daftar akun (langkah 1)")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    attestation.verify_attestation(db, request)
    device_id = device_header(request)
    ip = client_ip(request)
    existing = find_user_by_phone(db, payload.phone)

    if existing is not None:
        # Anti-enumerasi (H.7.2): respons identik, kirim pemberitahuan.
        session = request_otp(
            db,
            phone=payload.phone,
            purpose=OtpPurpose.REGISTER,
            device_id=device_id,
            ip=ip,
            decoy=True,
            notification=(
                "Nomor ini sudah punya akun Poinqu. Silakan masuk, "
                "atau pakai Lupa PIN bila perlu."
            ),
        )
        db.commit()
        return ok(otp_public(session), "Kode OTP dikirim.")

    context = {
        "name": payload.name,
        "phone": payload.phone,
        "gender": payload.gender,
        "terms_accepted_at": to_iso(utcnow()),
    }
    session = request_otp(
        db,
        phone=payload.phone,
        purpose=OtpPurpose.REGISTER,
        context=context,
        device_id=device_id,
        ip=ip,
    )
    db.commit()
    return ok(otp_public(session), "Kode OTP dikirim.")


@router.post("/register/complete", summary="Selesaikan pendaftaran", status_code=201)
def register_complete(payload: RegisterCompleteIn, request: Request, db: Session = Depends(get_db)):
    _ensure_device_match(request, payload.device.device_id)
    attestation.verify_attestation(db, request)
    verification, session = validate_verification(db, payload.verification_token, OtpPurpose.REGISTER)
    context = session.context or {}
    phone = context.get("phone") or session.phone

    if payload.pin != payload.pin_confirmation:
        raise AppError("PIN_MISMATCH")
    if is_weak_pin(payload.pin, phone):
        raise AppError("PIN_TOO_WEAK")
    if find_user_by_phone(db, phone) is not None:
        raise AppError("PHONE_ALREADY_REGISTERED")

    from app.core.security import hash_secret

    terms_raw = context.get("terms_accepted_at")
    terms_at = utcnow()
    if terms_raw:
        try:
            from datetime import datetime

            terms_at = datetime.fromisoformat(terms_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

    user = User(
        phone=phone,
        name=context.get("name") or "Pengguna",
        gender=context.get("gender"),
        pin_hash=hash_secret(payload.pin),
        level=UserLevel.BASIC,
        kyc_status=KycStatus.NONE,
        status=UserStatus.ACTIVE,
        terms_accepted_at=terms_at,
    )
    db.add(user)
    db.flush()

    device, _ = upsert_device(db, user, payload.device, request)
    mark_device_trusted(db, device)
    tokens, _ = issue_user_tokens(db, user, device)
    mark_verification_used(db, verification)
    db.commit()

    body = ok({"user": user_public(user), "tokens": tokens}, "Pendaftaran berhasil.")
    return JSONResponse(status_code=201, content=jsonable_encoder(body))


@router.post("/login/start", summary="Mulai login (cek perangkat)")
def login_start(payload: LoginStartIn, request: Request, db: Session = Depends(get_db)):
    _ensure_device_match(request, payload.device_id)
    ip = client_ip(request)

    per_device = settings_service.get_int(db, "otp.rate.per_device_hour", 10)
    per_ip = settings_service.get_int(db, "otp.rate.per_ip_hour", 20)
    if rate_limit.exceeded(db, "login_device", payload.device_id, per_device, 3600) or (
        ip and rate_limit.exceeded(db, "login_ip", ip, per_ip, 3600)
    ):
        raise AppError(
            "RATE_LIMITED", details={"retry_after": 60}, retry_after=60
        )
    rate_limit.bump(db, "login_device", payload.device_id, 3600)
    if ip:
        rate_limit.bump(db, "login_ip", ip, 3600)

    user = find_user_by_phone(db, payload.phone)
    device = None
    if user is not None:
        device = db.scalar(
            select(Device).where(
                Device.user_id == user.id,
                Device.device_id == payload.device_id,
                Device.revoked_at.is_(None),
            )
        )

    attestation.verify_attestation(db, request, device)

    trusted = bool(device and device.trusted_at)
    if trusted:
        idle_days = settings_service.get_int(db, "security.trusted_device_idle_days", 90)
        if device.last_active_at < utcnow() - timedelta(days=idle_days):
            device.trusted_at = None
            db.flush()
            trusted = False

    base = {
        "masked_phone": mask_phone(payload.phone),
        "verification_token": None,
        "expires_in": None,
        "preferred_method": None,
        "available_methods": [],
    }

    if trusted and user is not None:
        _ensure_user_active(user)
        raw = create_trusted_login_token(db, user, payload.phone, payload.device_id)
        preferred, methods = _login_methods(db, user, request)
        db.commit()
        return ok(
            {
                **base,
                "method": "PIN",
                "verification_token": raw,
                "expires_in": settings.VERIFICATION_TOKEN_TTL,
                "preferred_method": preferred,
                "available_methods": methods,
            }
        )

    db.commit()
    equalize_timing()
    return ok({**base, "method": "OTP"})


@router.post("/login/pin", summary="Login dengan PIN")
def login_pin(payload: LoginPinIn, request: Request, db: Session = Depends(get_db)):
    _ensure_device_match(request, payload.device.device_id)
    attestation.verify_attestation(db, request)
    verification, session = validate_verification(db, payload.verification_token, OtpPurpose.LOGIN)
    if verification.device_id and verification.device_id != payload.device.device_id:
        raise AppError("DEVICE_MISMATCH", status=422)

    user = db.get(User, session.user_id) if session.user_id else find_user_by_phone(db, session.phone)
    if user is None:
        raise AppError("UNAUTHORIZED")
    _ensure_user_active(user)

    device, _ = upsert_device(db, user, payload.device, request)
    pin_service.verify_user_pin(db, user, payload.pin, device)
    mark_device_trusted(db, device)

    tokens, _ = issue_user_tokens(db, user, device)
    mark_verification_used(db, verification)
    db.commit()
    return ok({"user": user_public(user), "tokens": tokens}, "Berhasil masuk.")


@router.post("/biometric/challenge", summary="Challenge biometrik")
def biometric_challenge(payload: BiometricChallengeIn, request: Request, db: Session = Depends(get_db)):
    # Kompatibilitas app: device_id boleh tidak dikirim; pakai X-Device-Id.
    device_id_value = payload.device_id or device_header(request)
    if not device_id_value:
        raise AppError("DEVICE_MISMATCH", status=422)
    _ensure_device_match(request, device_id_value)
    attestation.verify_attestation(db, request)
    verification, session = validate_verification(db, payload.verification_token, OtpPurpose.LOGIN)
    if verification.device_id and verification.device_id != device_id_value:
        raise AppError("DEVICE_MISMATCH", status=422)
    user = db.get(User, session.user_id) if session.user_id else None
    if user is None:
        raise AppError("VERIFICATION_TOKEN_INVALID")

    device = db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == device_id_value,
            Device.revoked_at.is_(None),
        )
    )
    if device is None:
        raise AppError("DEVICE_MISMATCH", status=422)

    kind = BiometricType(payload.type)
    biometric = bio_service.get_biometric(db, user, device, kind)
    if biometric is None:
        raise AppError("BIOMETRIC_NOT_REGISTERED")
    bio_service.ensure_biometric_unlocked(biometric)

    challenge = bio_service.create_challenge(db, user, device, kind)
    db.commit()
    return ok(bio_service.challenge_public(challenge))


def _biometric_login(
    payload: BiometricLoginIn,
    request: Request,
    db: Session,
    expected: BiometricType,
):
    _ensure_device_match(request, payload.device.device_id)
    attestation.verify_attestation(db, request)
    verification, session = validate_verification(db, payload.verification_token, OtpPurpose.LOGIN)
    if verification.device_id and verification.device_id != payload.device.device_id:
        raise AppError("DEVICE_MISMATCH", status=422)
    user = db.get(User, session.user_id) if session.user_id else None
    if user is None:
        raise AppError("VERIFICATION_TOKEN_INVALID")
    _ensure_user_active(user)

    device = db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == payload.device.device_id,
            Device.revoked_at.is_(None),
        )
    )
    if device is None:
        raise AppError("BIOMETRIC_NOT_REGISTERED")

    challenge = bio_service.get_challenge(db, payload.challenge_id)
    if challenge.type != expected:
        raise AppError("CHALLENGE_EXPIRED")
    bio_service.verify_login(
        db,
        user=user,
        device=device,
        challenge=challenge,
        signature=payload.signature,
    )

    device, _ = upsert_device(db, user, payload.device, request)
    mark_device_trusted(db, device)
    tokens, _ = issue_user_tokens(db, user, device)
    mark_verification_used(db, verification)
    db.commit()
    return ok({"user": user_public(user), "tokens": tokens}, "Berhasil masuk.")


@router.post("/login/fingerprint", summary="Login dengan sidik jari")
def login_fingerprint(payload: BiometricLoginIn, request: Request, db: Session = Depends(get_db)):
    return _biometric_login(payload, request, db, BiometricType.FINGERPRINT)


@router.post("/login/face", summary="Login dengan wajah")
def login_face(payload: BiometricLoginIn, request: Request, db: Session = Depends(get_db)):
    return _biometric_login(payload, request, db, BiometricType.FACE)


@router.post("/token/refresh", summary="Perbarui token")
def token_refresh(payload: TokenRefreshIn, db: Session = Depends(get_db)):
    tokens = rotate_user_refresh(db, payload.refresh_token, payload.device_id)
    db.commit()
    return ok(tokens, "Token diperbarui.")


@router.post("/logout", summary="Keluar")
def logout(
    payload: LogoutIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.all_devices:
        revoke_user_sessions(db, user, all_devices=True)
    else:
        device = db.scalar(
            select(Device).where(
                Device.user_id == user.id,
                Device.device_id == device_header(request),
            )
        )
        if device is not None:
            now = utcnow()
            for token in db.scalars(
                select(RefreshToken).where(
                    RefreshToken.device_id == device.id,
                    RefreshToken.revoked_at.is_(None),
                )
            ).all():
                token.revoked_at = now
            # Keluar dari satu perangkat tidak mencabut kepercayaan perangkat.
            session_id = getattr(request.state, "token_payload", {}).get("sid")
            if session_id:
                revocation_store.revoke_session(str(session_id), settings.ACCESS_TOKEN_TTL)
    db.commit()
    return ok(None, "Berhasil keluar.")


@router.post("/pin/reset", summary="Reset PIN (lupa PIN)")
def pin_reset(payload: PinResetIn, db: Session = Depends(get_db)):
    verification, session = validate_verification(
        db, payload.verification_token, OtpPurpose.FORGOT_PIN
    )
    user = db.get(User, session.user_id) if session.user_id else find_user_by_phone(db, session.phone)
    if user is None:
        raise AppError("VERIFICATION_TOKEN_INVALID")
    _ensure_user_active(user)

    pin_service.check_new_pin(user, payload.new_pin, payload.pin_confirmation)
    pin_service.set_pin(db, user, payload.new_pin)
    revoke_user_sessions(db, user, all_devices=True)
    record_security_event(
        db,
        user,
        "PASSWORD_RESET",
        SecuritySeverity.HIGH,
        description="PIN direset melalui verifikasi OTP.",
    )
    mark_verification_used(db, verification)
    db.commit()
    return ok({"redirect": "LOGIN", "sessions_revoked": True}, "PIN berhasil direset.")
