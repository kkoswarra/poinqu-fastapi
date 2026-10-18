"""Serialisasi dan operasi profil/perangkat/kejadian keamanan."""

from __future__ import annotations

from datetime import datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import to_iso, utcnow
from app.core.deps import client_ip, device_header
from app.models import Device, Platform, SecurityEvent, SecuritySeverity, User


def user_public(user: User) -> dict:
    return {
        "id": f"usr_{user.id.hex[:10].upper()}",
        "name": user.name,
        "phone": user.phone,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
        "email_verified_at": to_iso(user.email_verified_at),
        "gender": user.gender,
        "avatar_url": avatar_url(user),
        "level": "BASIC",
        "points": 0,
        "member_since": user.created_at.date().isoformat(),
    }


def avatar_url(user: User) -> str | None:
    if not user.avatar_key:
        return None
    base = settings.MEDIA_BASE_URL
    version = int((user.updated_at or user.created_at).timestamp())
    return f"{base}/media/{user.avatar_key}?v={version}"


def device_public(device: Device, current_device_id: str | None) -> dict:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "platform": device.platform.value,
        "location": device.last_location,
        "last_active_at": to_iso(device.last_active_at),
        "is_current": device.device_id == current_device_id,
    }


def upsert_device(
    db: Session,
    user: User,
    info,
    request: Request,
) -> tuple[Device, bool]:
    device = db.scalar(
        select(Device).where(Device.user_id == user.id, Device.device_id == info.device_id)
    )
    created = device is None
    now = utcnow()
    if device is None:
        device = Device(
            user_id=user.id,
            device_id=info.device_id,
            name=info.name,
            platform=Platform(info.platform),
            os_version=info.os_version,
            app_version=info.app_version,
            push_token=info.push_token,
            last_ip=client_ip(request),
            last_active_at=now,
        )
        db.add(device)
        db.flush()
        record_security_event(
            db,
            user,
            "NEW_DEVICE",
            SecuritySeverity.MEDIUM,
            device=device,
            description=f"{device.name} masuk ke akunmu.",
        )
    else:
        device.name = info.name
        device.platform = Platform(info.platform)
        device.os_version = info.os_version
        device.app_version = info.app_version
        if info.push_token:
            device.push_token = info.push_token
        device.last_ip = client_ip(request)
        device.last_active_at = now
        device.revoked_at = None
    attestation_provider = getattr(request.state, "attestation_provider", None)
    if attestation_provider:
        device.attestation_provider = attestation_provider
        device.attested_at = now
    db.flush()
    return device, created


def mark_device_trusted(db: Session, device: Device) -> None:
    device.trusted_at = utcnow()
    db.flush()


def clear_device_trust(db: Session, user: User, device: Device | None = None) -> None:
    if device is not None:
        device.trusted_at = None
    else:
        for item in db.scalars(select(Device).where(Device.user_id == user.id)).all():
            item.trusted_at = None
    db.flush()


def record_security_event(
    db: Session,
    user: User,
    event_type: str,
    severity: SecuritySeverity = SecuritySeverity.LOW,
    *,
    device: Device | None = None,
    description: str | None = None,
) -> SecurityEvent:
    event = SecurityEvent(
        user_id=user.id,
        type=event_type,
        severity=severity,
        device_id=device.id if device else None,
        description=description,
    )
    db.add(event)
    db.flush()
    return event


_SECURITY_TITLES = {
    "NEW_DEVICE": "Login dari perangkat baru",
    "PIN_FAILED": "Percobaan PIN salah",
    "PIN_CHANGED": "PIN diubah",
    "PASSWORD_RESET": "PIN direset",
    "PHONE_CHANGED": "Nomor HP diubah",
    "EMAIL_VERIFIED": "Email diverifikasi",
    "EMAIL_CHANGED": "Email diubah",
}


def security_activity_public(db: Session, event: SecurityEvent) -> dict:
    device = db.get(Device, event.device_id) if event.device_id else None
    return {
        "id": f"sec_{event.id.hex[:6]}",
        "type": event.type,
        "title": _SECURITY_TITLES.get(event.type, "Aktivitas keamanan"),
        "description": event.description,
        "device": device.name if device else None,
        "location": device.last_location if device else None,
        "at": to_iso(event.created_at),
        "severity": event.severity.value,
    }


def find_user_by_phone(db: Session, phone: str) -> User | None:
    return db.scalar(select(User).where(User.phone == phone))


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


def current_device_for(db: Session, user: User, request: Request) -> Device | None:
    header = device_header(request)
    if not header:
        return None
    return db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == header,
            Device.revoked_at.is_(None),
        )
    )


def iso_now() -> datetime:
    return utcnow()
