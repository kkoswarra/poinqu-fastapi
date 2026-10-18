"""Profil, PIN, biometrik, perangkat, dan aktivitas keamanan (bagian 4.17 - 4.32)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import to_iso, utcnow
from app.core.deps import device_header, get_current_device, get_current_user
from app.core.errors import AppError, ok
from app.db import get_db
from app.models import (
    BiometricType,
    Device,
    KycStatus,
    Platform,
    RefreshToken,
    SecurityEvent,
    User,
)
from app.schemas import (
    BiometricRegisterIn,
    BiometricSettingsIn,
    FaceRegisterIn,
    PinChangeIn,
    PinVerifyIn,
    ProfileUpdateIn,
    PushTokenIn,
)
from app.services import avatar as avatar_service
from app.services import biometrics as bio_service
from app.services import pin as pin_service
from app.services.auth import revoke_user_sessions
from app.services.profile import (
    avatar_url,
    device_public,
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
    if payload.name is not None and payload.name != user.name:
        if user.kyc_status == KycStatus.VERIFIED:
            raise AppError("NAME_LOCKED")
        user.name = payload.name

    if payload.email is not None and payload.email != user.email:
        existing = db.scalar(select(User).where(User.email == str(payload.email)))
        if existing is not None and existing.id != user.id:
            raise AppError("EMAIL_ALREADY_USED")
        user.email = str(payload.email)

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
