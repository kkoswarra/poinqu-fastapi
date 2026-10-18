"""Pengiriman OTP + log metadata WhatsApp (tanpa menyimpan isi pesan)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import utcnow
from app.core.errors import AppError
from app.models import AppSetting, OtpSession, WhatsAppMessage
from app.services import wa

PROVIDER_HEALTH_KEY = "otp.provider_healthy"
PROVIDER_UNAVAILABLE_RETRY = 30


def render_otp_message(code: str) -> str:
    minutes = max(1, settings.OTP_TTL // 60)
    return settings.OTP_MESSAGE_TEMPLATE.format(code=code, minutes=minutes)


def provider_healthy(db: Session) -> bool:
    setting = db.get(AppSetting, PROVIDER_HEALTH_KEY)
    if setting is None:
        return True
    value = setting.value
    if isinstance(value, dict):
        return bool(value.get("healthy", True))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return True


def ensure_provider_healthy(db: Session) -> None:
    if not provider_healthy(db):
        raise AppError(
            "OTP_PROVIDER_UNAVAILABLE",
            details={"retry_after": PROVIDER_UNAVAILABLE_RETRY},
            retry_after=PROVIDER_UNAVAILABLE_RETRY,
        )


def set_provider_healthy(
    db: Session,
    healthy: bool,
    *,
    device: str | None = None,
    reason: str | None = None,
) -> AppSetting:
    setting = db.get(AppSetting, PROVIDER_HEALTH_KEY)
    if setting is None:
        setting = AppSetting(
            key=PROVIDER_HEALTH_KEY,
            value=healthy,
            version=1,
            description="Status kesehatan gateway WhatsApp.",
        )
        db.add(setting)
    else:
        setting.value = healthy
        setting.version += 1
    db.flush()
    return setting


def send_text(db: Session, phone: str, text: str) -> WhatsAppMessage:
    """Kirim pesan non-OTP (mis. pemberitahuan nomor sudah terdaftar)."""
    gateway = wa.get_gateway()
    result = gateway.send_message(phone, text)

    record = WhatsAppMessage(
        otp_session_id=None,
        phone=phone,
        provider=gateway.name,
        provider_msg_id=result.provider_msg_id,
        provider_state_id=result.provider_state_id,
        request_id=result.request_id,
        status=result.status,
        provider_status=result.provider_status,
        failure_reason=result.failure_reason,
        sent_at=utcnow() if result.status == "SENT" else None,
    )
    db.add(record)
    db.flush()

    if not result.ok:
        raise AppError(
            result.error_code or "OTP_PROVIDER_UNAVAILABLE",
            details={"retry_after": PROVIDER_UNAVAILABLE_RETRY},
            retry_after=PROVIDER_UNAVAILABLE_RETRY,
        )
    return record


def send_otp(db: Session, session: OtpSession, code: str) -> WhatsAppMessage:
    """Kirim OTP lewat gateway aktif dan catat metadata pengiriman.

    Isi pesan/kode tidak pernah disimpan ke database maupun log. Kegagalan
    dipetakan ke ``OTP_TARGET_NOT_WHATSAPP`` (422) atau
    ``OTP_PROVIDER_UNAVAILABLE`` (503).
    """
    if session.channel == "EMAIL":
        # Pengiriman email diimplementasikan pada Sprint 2.
        raise AppError(
            "OTP_PROVIDER_UNAVAILABLE",
            details={"retry_after": PROVIDER_UNAVAILABLE_RETRY},
            retry_after=PROVIDER_UNAVAILABLE_RETRY,
        )

    target = session.target or session.phone or ""
    gateway = wa.get_gateway()
    result = gateway.send_otp(
        target,
        render_otp_message(code),
        code=code,
    )

    record = WhatsAppMessage(
        otp_session_id=session.id,
        phone=target,
        provider=gateway.name,
        provider_msg_id=result.provider_msg_id,
        provider_state_id=result.provider_state_id,
        request_id=result.request_id,
        status=result.status,
        provider_status=result.provider_status,
        failure_reason=result.failure_reason,
        sent_at=utcnow() if result.status == "SENT" else None,
    )
    db.add(record)
    db.flush()

    if not result.ok:
        raise AppError(
            result.error_code or "OTP_PROVIDER_UNAVAILABLE",
            details={"retry_after": PROVIDER_UNAVAILABLE_RETRY},
            retry_after=PROVIDER_UNAVAILABLE_RETRY,
        )
    return record
