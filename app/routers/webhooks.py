"""Webhook Fonnte (docs/FASE-2-API.md bagian H.4).

Pengamanan: rahasia di path (dibandingkan waktu-konstan) + opsional IP
allowlist. Webhook hanya memperbarui log pengiriman dan status kesehatan
provider; tidak pernah membuat/verifikasi OTP atau menyentuh saldo.
"""

from __future__ import annotations

import hmac
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import utcnow
from app.core.deps import client_ip
from app.core.errors import AppError, ok
from app.db import get_db
from app.models import WhatsAppMessage
from app.services import whatsapp
from app.services.admin import record_audit

logger = logging.getLogger("poinqu.webhooks")

router = APIRouter(prefix="/webhooks/fonnte", tags=["webhooks"])

_STATUS_MAP = {
    "sent": "SENT",
    "processing": "QUEUED",
    "pending": "PENDING",
    "waiting": "QUEUED",
    "invalid": "INVALID",
    "failed": "FAILED",
    "expired": "EXPIRED",
    "url unreachable": "FAILED",
}
_RANK = {
    "QUEUED": 0,
    "PENDING": 1,
    "SENT": 2,
    "FAILED": 3,
    "INVALID": 3,
    "EXPIRED": 3,
    "PROVIDER_ERROR": 3,
}
_TERMINAL = {"FAILED", "INVALID", "EXPIRED", "PROVIDER_ERROR"}


class FonnteStatusIn(BaseModel):
    id: str | None = None
    stateid: str | None = None
    status: str | None = None
    state: str | None = None
    device: str | None = None

    @model_validator(mode="after")
    def require_identifier(self) -> FonnteStatusIn:
        if not self.id and not self.stateid:
            raise ValueError("REQUIRED")
        return self


class FonnteDeviceIn(BaseModel):
    device: str | None = None
    status: Literal["connect", "disconnect"]
    reason: str | None = None
    timestamp: str | None = None


def _authorize(request: Request, secret: str) -> None:
    configured = settings.FONNTE_WEBHOOK_SECRET
    if not configured or not hmac.compare_digest(secret, configured):
        raise AppError("UNAUTHORIZED")

    allowed = [ip.strip() for ip in settings.FONNTE_ALLOWED_IPS.split(",") if ip.strip()]
    if allowed and client_ip(request) not in allowed:
        raise AppError("UNAUTHORIZED")


def _advance(message: WhatsAppMessage, raw_status: str | None) -> None:
    message.provider_status = raw_status
    mapped = _STATUS_MAP.get((raw_status or "").strip().lower())
    if mapped is None:
        return
    if message.status == "SENT":
        return
    if message.status in _TERMINAL and mapped != message.status:
        return
    if _RANK.get(mapped, 0) >= _RANK.get(message.status, 0):
        message.status = mapped
        if mapped == "SENT" and message.sent_at is None:
            message.sent_at = utcnow()


@router.post("/{secret}/status", summary="Webhook status pesan Fonnte")
def fonnte_message_status(
    secret: str,
    payload: FonnteStatusIn,
    request: Request,
    db: Session = Depends(get_db),
):
    _authorize(request, secret)

    message = None
    if payload.id:
        message = db.scalar(
            select(WhatsAppMessage).where(WhatsAppMessage.provider_msg_id == payload.id)
        )
    if message is None and payload.stateid:
        message = db.scalar(
            select(WhatsAppMessage).where(
                WhatsAppMessage.provider_state_id == payload.stateid
            )
        )

    if message is not None:
        _advance(message, payload.status or payload.state)
        db.commit()

    return ok(None, "Diterima.")


@router.post("/{secret}/device", summary="Webhook status device Fonnte")
def fonnte_device_status(
    secret: str,
    payload: FonnteDeviceIn,
    request: Request,
    db: Session = Depends(get_db),
):
    _authorize(request, secret)

    healthy = payload.status == "connect"
    whatsapp.set_provider_healthy(
        db,
        healthy,
        device=payload.device,
        reason=payload.reason,
    )
    record_audit(
        db,
        actor_type="SYSTEM",
        action=f"whatsapp.device.{payload.status}",
        entity="app_settings",
        entity_id=whatsapp.PROVIDER_HEALTH_KEY,
        after={
            "healthy": healthy,
            "device": payload.device,
            "reason": payload.reason,
        },
        ip=client_ip(request),
    )
    if not healthy:
        logger.critical(
            "Device Fonnte terputus (%s): %s", payload.device or "?", payload.reason or "-"
        )
    db.commit()

    return ok(None, "Diterima.")
