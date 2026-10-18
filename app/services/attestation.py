"""Verifikasi integritas perangkat (H.7.7).

Pada Fase 2 dipakai verifier mock: token dianggap sah bila diawali
``att_valid_``. Ganti ``verify_token`` dengan Play Integrity / App Attest
saat kredensial cloud tersedia. Flag ``security.attestation_required``
mengendalikan apakah verifikasi diwajibkan.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError
from app.models import Device
from app.services import settings as settings_service

VALID_PROVIDERS = {"PLAY_INTEGRITY", "APP_ATTEST"}


def verify_token(provider: str, token: str) -> bool:
    """Mock: hanya token berawalan ``att_valid_`` yang diterima."""
    return provider in VALID_PROVIDERS and token.startswith("att_valid_")


def verify_attestation(
    db: Session,
    request: Request,
    device: Device | None = None,
    *,
    required: bool | None = None,
) -> str | None:
    if required is None:
        required = settings_service.get_bool(db, "security.attestation_required", False)
    if not required:
        return None

    provider = request.headers.get("X-Attestation-Provider", "").strip().upper()
    token = request.headers.get("X-Attestation", "").strip()
    if not provider or not token or not verify_token(provider, token):
        raise AppError("DEVICE_ATTESTATION_FAILED")

    request.state.attestation_provider = provider
    if device is not None:
        device.attestation_provider = provider
        device.attested_at = utcnow()
    return provider
