"""Profil, PIN, biometrik, perangkat, dan aktivitas keamanan (bagian 4.17 - 4.32)."""

from __future__ import annotations

from contextlib import suppress
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import to_iso, utcnow
from app.core.deps import client_ip, device_header, get_current_device, get_current_user
from app.core.errors import AppError, ok
from app.core.security import mask_identifier, normalize_email, public_id
from app.db import get_db
from app.models import (
    BiometricType,
    ContactChangeRequest,
    Device,
    KycStatus,
    OtpPurpose,
    OtpSession,
    Platform,
    RefreshToken,
    SecurityEvent,
    SecuritySeverity,
    User,
)
from app.schemas import (
    BiometricRegisterIn,
    BiometricSettingsIn,
    ContactChangeConfirmIn,
    EmailChangeRequestIn,
    EmailVerificationVerifyIn,
    FaceRegisterIn,
    PhoneChangeRequestIn,
    PinChangeIn,
    PinVerifyIn,
    ProfileUpdateIn,
    PushTokenIn,
)
from app.services import avatar as avatar_service
from app.services import biometrics as bio_service
from app.services import email as email_service
from app.services import pin as pin_service
from app.services import whatsapp
from app.services.auth import (
    otp_public,
    request_otp,
    revoke_user_sessions,
    verify_otp_code,
)
from app.services.profile import (
    avatar_url,
    device_public,
    find_user_by_email,
    find_user_by_phone,
    record_security_event,
    security_activity_public,
    user_public,
)
from app.services.revocation import store as revocation_store

router = APIRouter(prefix="/me", tags=["me"])


# ------------------------------------------------------------------ profil


@router.get("", summary="Ambil profil")
def get_profile(user: User = Depends(get_current_user)):
    return ok(user_public(user))


@router.patch("", summary="Ubah profil")
def update_profile(
    payload: ProfileUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.email is not None:
        raise AppError(
            "INVALID_VALUE",
            message="Perubahan email harus lewat verifikasi email.",
        )

    if payload.name is not None and payload.name != user.name:
        if user.kyc_status == KycStatus.VERIFIED:
            raise AppError("NAME_LOCKED")
        user.name = payload.name

    if payload.gender is not None:
        user.gender = payload.gender

    db.commit()
    return ok(user_public(user), "Profil diperbarui.")


@router.post("/avatar", summary="Unggah foto profil")
def upload_avatar(
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = photo.file.read(settings.AVATAR_MAX_BYTES + 1)
    if len(data) > settings.AVATAR_MAX_BYTES:
        raise AppError("FILE_TOO_LARGE")
    old_key = user.avatar_key
    user.avatar_key = avatar_service.save_avatar(user.id, data)
    if old_key:
        avatar_service.delete_avatar_file(old_key)
    db.commit()
    return ok({"avatar_url": avatar_url(user)}, "Foto profil diperbarui.")


@router.delete("/avatar", summary="Hapus foto profil")
def delete_avatar(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.avatar_key:
        raise AppError("AVATAR_NOT_FOUND")
    avatar_service.delete_avatar_file(user.avatar_key)
    user.avatar_key = None
    db.commit()
    return ok({"avatar_url": None}, "Foto profil dihapus.")


# --------------------------------------------------------------------- PIN


@router.post("/pin/change", summary="Ganti PIN")
def change_pin(
    payload: PinChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    device: Device = Depends(get_current_device),
):
    pin_service.verify_user_pin(db, user, payload.old_pin, device)
    pin_service.check_new_pin(user, payload.new_pin, payload.pin_confirmation)
    pin_service.set_pin(db, user, payload.new_pin)
    revoke_user_sessions(db, user, except_device_uuid=device.id)
    record_security_event(
        db,
        user,
        "PIN_CHANGED",
        device=device,
        description="PIN berhasil diganti.",
    )
    db.commit()
    return ok({"other_sessions_revoked": True}, "PIN berhasil diganti.")


@router.post("/pin/verify", summary="Verifikasi PIN")
def verify_pin(
    payload: PinVerifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    device: Device = Depends(get_current_device),
):
    pin_service.verify_user_pin(db, user, payload.pin, device)
    token = pin_service.create_pin_token(
        db, user, payload.purpose, preview_id=payload.preview_id
    )
    db.commit()
    return ok(
        {"pin_token": token, "expires_in": settings.PIN_TOKEN_TTL},
        "PIN benar.",
    )


# ----------------------------------------------------------- email & kontak


def _consume_pin(request: Request, db: Session, user: User, purpose: str) -> None:
    pin_service.consume_pin_token(
        db, user, request.headers.get("X-Pin-Token", ""), purpose
    )


def _pending_change(
    db: Session, user: User, change_id: str, expected_type: str
) -> ContactChangeRequest:
    change = db.scalar(
        select(ContactChangeRequest).where(
            ContactChangeRequest.public_id == change_id,
            ContactChangeRequest.user_id == user.id,
            ContactChangeRequest.type == expected_type,
        )
    )
    if change is None:
        raise AppError("CONTACT_CHANGE_NOT_FOUND")
    if change.status != "PENDING":
        raise AppError("CONTACT_CHANGE_ALREADY_USED")
    if change.expires_at <= utcnow():
        change.status = "EXPIRED"
        db.commit()
        raise AppError("CONTACT_CHANGE_EXPIRED")
    return change


def _change_session(
    db: Session,
    change: ContactChangeRequest,
    user: User,
    otp_session_id: str,
    purpose: OtpPurpose,
) -> OtpSession:
    session = db.scalar(
        select(OtpSession).where(OtpSession.public_id == otp_session_id)
    )
    if (
        session is None
        or change.otp_session_id != session.id
        or session.user_id != user.id
        or session.purpose != purpose
        or session.target != change.new_value
    ):
        raise AppError("OTP_SESSION_NOT_FOUND")
    return session


@router.post("/email/verification/request", summary="Minta OTP verifikasi email")
def request_email_verification(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.email:
        raise AppError("EMAIL_NOT_SET")
    if user.email_verified_at is not None:
        raise AppError("EMAIL_ALREADY_VERIFIED")

    session = request_otp(
        db,
        target=user.email,
        target_type="EMAIL",
        purpose=OtpPurpose.VERIFY_EMAIL,
        user=user,
        context={"flow": "VERIFY_EMAIL"},
        device_id=device_header(request),
        ip=client_ip(request),
    )
    db.commit()
    return ok(otp_public(session), "Kode verifikasi email dikirim.")


@router.post("/email/verification/verify", summary="Verifikasi email dengan OTP")
def verify_email(
    payload: EmailVerificationVerifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.email:
        raise AppError("EMAIL_NOT_SET")
    if user.email_verified_at is not None:
        raise AppError("EMAIL_ALREADY_VERIFIED")

    session = verify_otp_code(db, payload.otp_session_id, payload.code)
    if (
        session.purpose != OtpPurpose.VERIFY_EMAIL
        or session.user_id != user.id
        or session.target.lower() != user.email.lower()
    ):
        raise AppError("OTP_SESSION_NOT_FOUND")

    user.email_verified_at = utcnow()
    record_security_event(
        db,
        user,
        "EMAIL_VERIFIED",
        SecuritySeverity.LOW,
        description="Email berhasil diverifikasi.",
    )
    db.commit()
    return ok(
        {
            "email": user.email,
            "email_verified": True,
            "email_verified_at": to_iso(user.email_verified_at),
        },
        "Email terverifikasi.",
    )


@router.post("/phone/change/request", summary="Minta OTP ganti nomor HP")
def request_phone_change(
    payload: PhoneChangeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _consume_pin(request, db, user, "CHANGE_PHONE")

    if payload.new_phone == user.phone:
        raise AppError("PHONE_SAME_AS_CURRENT")
    if find_user_by_phone(db, payload.new_phone) is not None:
        raise AppError("PHONE_ALREADY_REGISTERED")

    change = ContactChangeRequest(
        public_id=public_id("chg"),
        user_id=user.id,
        type="PHONE",
        new_value=payload.new_phone,
        status="PENDING",
        expires_at=utcnow() + timedelta(seconds=settings.OTP_TTL),
    )
    db.add(change)
    db.flush()

    try:
        session = request_otp(
            db,
            target=payload.new_phone,
            target_type="PHONE",
            purpose=OtpPurpose.CHANGE_PHONE,
            user=user,
            context={"change_id": change.public_id, "flow": "CHANGE_PHONE"},
            device_id=device_header(request),
            ip=client_ip(request),
        )
    except AppError:
        change.status = "CANCELLED"
        db.commit()
        raise

    change.otp_session_id = session.id
    db.commit()
    return ok(
        {
            "change_id": change.public_id,
            "otp_session_id": session.public_id,
            "type": "PHONE",
            "masked_identifier": mask_identifier(payload.new_phone, "PHONE"),
            "channel": session.channel,
            "expires_in": settings.OTP_TTL,
            "resend_available_in": settings.OTP_RESEND_COOLDOWN,
        },
        "Kode OTP dikirim.",
    )


@router.post("/phone/change/confirm", summary="Konfirmasi ganti nomor HP")
def confirm_phone_change(
    payload: ContactChangeConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    device: Device = Depends(get_current_device),
):
    change = _pending_change(db, user, payload.change_id, "PHONE")
    _change_session(
        db, change, user, payload.otp_session_id, OtpPurpose.CHANGE_PHONE
    )
    if find_user_by_phone(db, change.new_value) is not None:
        raise AppError("PHONE_ALREADY_REGISTERED")
    verify_otp_code(db, payload.otp_session_id, payload.code)

    old_phone = user.phone
    old_email = user.email if user.email_verified_at is not None else None
    user.phone = change.new_value
    change.status = "VERIFIED"
    change.completed_at = utcnow()
    revoke_user_sessions(db, user, except_device_uuid=device.id)
    record_security_event(
        db,
        user,
        "PHONE_CHANGED",
        SecuritySeverity.HIGH,
        device=device,
        description="Nomor HP diubah dari halaman akun.",
    )
    with suppress(AppError):
        whatsapp.send_text(
            db,
            old_phone,
            "Nomor HP akun Poinqu kamu telah diubah. "
            "Jika bukan kamu, hubungi bantuan.",
        )
    if old_email:
        with suppress(AppError):
            email_service.send_notification(
                db,
                old_email,
                "Poinqu",
                "Nomor HP akun Poinqu kamu telah diubah.",
            )
    db.commit()
    return ok(
        {"new_phone": change.new_value, "changed_at": to_iso(change.completed_at)},
        "Nomor HP berhasil diganti.",
    )


@router.post("/email/change/request", summary="Minta OTP ganti email")
def request_email_change(
    payload: EmailChangeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _consume_pin(request, db, user, "CHANGE_EMAIL")
    new_email = normalize_email(str(payload.new_email))

    if user.email and user.email.lower() == new_email:
        raise AppError("EMAIL_SAME_AS_CURRENT")
    if find_user_by_email(db, new_email) is not None:
        raise AppError("EMAIL_ALREADY_USED")

    change = ContactChangeRequest(
        public_id=public_id("chg"),
        user_id=user.id,
        type="EMAIL",
        new_value=new_email,
        status="PENDING",
        expires_at=utcnow() + timedelta(seconds=settings.OTP_TTL),
    )
    db.add(change)
    db.flush()

    try:
        session = request_otp(
            db,
            target=new_email,
            target_type="EMAIL",
            purpose=OtpPurpose.CHANGE_EMAIL,
            user=user,
            context={"change_id": change.public_id, "flow": "CHANGE_EMAIL"},
            device_id=device_header(request),
            ip=client_ip(request),
        )
    except AppError:
        change.status = "CANCELLED"
        db.commit()
        raise

    change.otp_session_id = session.id
    db.commit()
    return ok(
        {
            "change_id": change.public_id,
            "otp_session_id": session.public_id,
            "type": "EMAIL",
            "masked_identifier": mask_identifier(new_email, "EMAIL"),
            "channel": session.channel,
            "expires_in": settings.OTP_TTL,
            "resend_available_in": settings.OTP_RESEND_COOLDOWN,
        },
        "Kode OTP dikirim.",
    )


@router.post("/email/change/confirm", summary="Konfirmasi ganti email")
def confirm_email_change(
    payload: ContactChangeConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = _pending_change(db, user, payload.change_id, "EMAIL")
    _change_session(
        db, change, user, payload.otp_session_id, OtpPurpose.CHANGE_EMAIL
    )
    if find_user_by_email(db, change.new_value) is not None:
        raise AppError("EMAIL_ALREADY_USED")
    verify_otp_code(db, payload.otp_session_id, payload.code)

    old_email = user.email
    old_phone = user.phone
    user.email = change.new_value
    user.email_verified_at = utcnow()
    change.status = "VERIFIED"
    change.completed_at = utcnow()
    record_security_event(
        db,
        user,
        "EMAIL_CHANGED",
        SecuritySeverity.MEDIUM,
        description="Email diubah dari halaman akun.",
    )
    if old_email:
        with suppress(AppError):
            email_service.send_notification(
                db,
                old_email,
                "Poinqu",
                "Email akun Poinqu kamu telah diubah.",
            )
    with suppress(AppError):
        whatsapp.send_text(
            db,
            old_phone,
            "Email akun Poinqu kamu telah diubah. "
            "Jika bukan kamu, hubungi bantuan.",
        )
    db.commit()
    return ok(
        {
            "new_email": change.new_value,
            "email_verified": True,
            "changed_at": to_iso(change.completed_at),
        },
        "Email berhasil diganti.",
    )


# --------------------------------------------------------------- biometrik


def _require_pin_token(request: Request, db: Session, user: User) -> None:
    raw = request.headers.get("X-Pin-Token", "")
    pin_service.consume_pin_token(db, user, raw, "ENROLL_BIOMETRIC")


def _device_for_payload(
    db: Session, user: User, request: Request, payload_device_id: str
) -> Device:
    if device_header(request) != payload_device_id:
        raise AppError("DEVICE_MISMATCH", status=422)
    device = db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == payload_device_id,
            Device.revoked_at.is_(None),
        )
    )
    if device is None:
        raise AppError("DEVICE_MISMATCH", status=422)
    return device


@router.get("/biometrics", summary="Status biometrik")
def biometrics_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    device: Device = Depends(get_current_device),
):
    return ok(bio_service.biometrics_status(db, user, device))


@router.post("/biometrics/fingerprint", summary="Daftarkan sidik jari", status_code=201)
def register_fingerprint(
    payload: BiometricRegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_pin_token(request, db, user)
    device = _device_for_payload(db, user, request, payload.device_id)
    biometric = bio_service.register_biometric(
        db,
        user=user,
        device=device,
        kind=BiometricType.FINGERPRINT,
        public_key=payload.public_key,
    )
    db.commit()
    body = ok(
        {"type": "FINGERPRINT", "registered_at": to_iso(biometric.registered_at)},
        "Sidik jari terdaftar.",
    )
    return JSONResponse(status_code=201, content=jsonable_encoder(body))


@router.post("/biometrics/face", summary="Daftarkan wajah", status_code=201)
def register_face(
    payload: FaceRegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_pin_token(request, db, user)
    device = _device_for_payload(db, user, request, payload.device_id)
    biometric = bio_service.register_biometric(
        db,
        user=user,
        device=device,
        kind=BiometricType.FACE,
        public_key=payload.public_key,
        liveness_session_id=payload.liveness_session_id,
    )
    db.commit()
    body = ok(
        {"type": "FACE", "registered_at": to_iso(biometric.registered_at)},
        "Wajah terdaftar.",
    )
    return JSONResponse(status_code=201, content=jsonable_encoder(body))


@router.delete("/biometrics/{kind}", summary="Hapus biometrik")
def delete_biometric(
    kind: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    device: Device = Depends(get_current_device),
):
    if kind not in {"FINGERPRINT", "FACE"}:
        raise AppError("INVALID_BIOMETRIC_TYPE")
    biometric = bio_service.get_biometric(db, user, device, BiometricType(kind))
    if biometric is None:
        raise AppError("NO_BIOMETRIC_REGISTERED")

    db.delete(biometric)
    db.flush()
    remaining = bio_service.count_biometrics(db, user)
    if remaining == 0:
        user.biometric_login = False
    db.commit()
    return ok(
        {"type": kind, "use_for_login": user.biometric_login},
        "Biometrik dihapus.",
    )


@router.patch("/biometrics/settings", summary="Pengaturan login biometrik")
def biometric_settings(
    payload: BiometricSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.use_for_login and bio_service.count_biometrics(db, user) == 0:
        raise AppError("NO_BIOMETRIC_REGISTERED")
    user.biometric_login = payload.use_for_login
    db.commit()
    return ok({"use_for_login": user.biometric_login}, "Pengaturan disimpan.")


# ---------------------------------------------------------------- perangkat


@router.get("/devices", summary="Daftar perangkat")
def list_devices(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    now = utcnow()
    active_ids = select(RefreshToken.device_id).where(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > now,
    )
    devices = db.scalars(
        select(Device)
        .where(
            Device.user_id == user.id,
            Device.revoked_at.is_(None),
            Device.id.in_(active_ids),
        )
        .order_by(Device.last_active_at.desc())
    ).all()
    current = device_header(request)
    return ok({"items": [device_public(device, current) for device in devices]})


@router.delete("/devices/{device_id_value}", summary="Keluarkan satu perangkat")
def remove_device(
    device_id_value: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device = db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == device_id_value,
            Device.revoked_at.is_(None),
        )
    )
    if device is None:
        raise AppError("DEVICE_NOT_FOUND")
    if device.device_id == device_header(request):
        raise AppError("CANNOT_REMOVE_CURRENT_DEVICE")

    now = utcnow()
    device.revoked_at = now
    device.trusted_at = None
    for token in db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.device_id == device.id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all():
        token.revoked_at = now
        revocation_store.revoke_session(str(token.family_id), settings.ACCESS_TOKEN_TTL)
    db.commit()
    return ok({"device_id": device.device_id}, "Perangkat dikeluarkan.")


@router.delete("/devices", summary="Keluarkan semua perangkat lain")
def remove_other_devices(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    current = device_header(request)
    others = db.scalars(
        select(Device).where(
            Device.user_id == user.id,
            Device.revoked_at.is_(None),
            Device.device_id != current,
        )
    ).all()
    if not others:
        raise AppError("NO_OTHER_DEVICES")

    now = utcnow()
    for device in others:
        device.revoked_at = now
        device.trusted_at = None
    for token in db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.device_id.in_([device.id for device in others]),
        )
    ).all():
        token.revoked_at = now
        revocation_store.revoke_session(str(token.family_id), settings.ACCESS_TOKEN_TTL)
    db.commit()
    return ok({"removed_count": len(others)}, "Perangkat lain dikeluarkan.")


@router.put("/devices/current/push-token", summary="Daftarkan push token")
def register_push_token(
    payload: PushTokenIn,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
):
    device.push_token = payload.push_token
    device.platform = Platform(payload.platform)
    db.commit()
    return ok(None, "Push token disimpan.")


# ------------------------------------------------------- aktivitas keamanan


@router.get("/security/activities", summary="Aktivitas keamanan")
def security_activities(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    events = db.scalars(
        select(SecurityEvent)
        .where(SecurityEvent.user_id == user.id)
        .order_by(SecurityEvent.created_at.desc())
        .limit(50)
    ).all()
    unread = db.scalar(
        select(func.count())
        .select_from(SecurityEvent)
        .where(SecurityEvent.user_id == user.id, SecurityEvent.read_at.is_(None))
    )
    return ok(
        {
            "items": [security_activity_public(db, event) for event in events],
            "unread_count": int(unread or 0),
        }
    )
