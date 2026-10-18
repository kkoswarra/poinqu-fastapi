"""Dependency FastAPI: sesi DB, autentikasi pengguna/admin, izin."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError
from app.core.security import decode_admin_access, decode_user_access
from app.db import get_db
from app.models import Admin, Device, Permission, RolePermission, User, UserStatus
from app.services.revocation import RevocationUnavailable
from app.services.revocation import store as revocation_store

logger = logging.getLogger("poinqu.auth")

bearer_scheme = HTTPBearer(auto_error=False)

MONEY_PATH_PREFIXES = ("/v1/transfers", "/v1/topup", "/v1/ppob", "/v1/payment-requests")

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
BearerCreds = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def device_header(request: Request) -> str:
    return request.headers.get("X-Device-Id", "")


def _require_credentials(credentials: HTTPAuthorizationCredentials | None):
    if credentials is None or not credentials.credentials:
        raise AppError("UNAUTHORIZED")
    return credentials.credentials


def get_current_user(request: Request, credentials: BearerCreds, db: DbSession) -> User:
    payload = decode_user_access(_require_credentials(credentials))
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
        token_device_id = uuid.UUID(str(payload.get("did") or payload.get("dev")))
    except (ValueError, TypeError) as exc:
        raise AppError("UNAUTHORIZED") from exc

    request.state.token_payload = payload
    try:
        if revocation_store.is_revoked(
            payload.get("sid"), str(user_id), int(payload.get("iat", 0))
        ):
            raise AppError("UNAUTHORIZED")
    except RevocationUnavailable:
        logger.warning("Revocation store tidak tersedia; memeriksa izin fail-open.")
        if request.url.path.startswith(MONEY_PATH_PREFIXES):
            raise AppError("SERVICE_UNAVAILABLE") from None

    user = db.get(User, user_id)
    if user is None:
        raise AppError("UNAUTHORIZED")
    if user.status == UserStatus.SUSPENDED:
        raise AppError("ACCOUNT_SUSPENDED")
    if user.status == UserStatus.LOCKED:
        raise AppError("ACCOUNT_LOCKED")

    device = db.get(Device, token_device_id)
    header = device_header(request)
    if device is None or device.user_id != user.id or device.revoked_at is not None:
        raise AppError("UNAUTHORIZED")
    if header and device.device_id != header:
        raise AppError("DEVICE_MISMATCH")

    device.last_active_at = utcnow()
    db.flush()
    return user


def get_current_device(
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> Device:
    header = device_header(request)
    if not header:
        raise AppError("DEVICE_MISMATCH")
    device = db.scalar(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == header,
            Device.revoked_at.is_(None),
        )
    )
    if device is None:
        raise AppError("DEVICE_MISMATCH")
    return device


def get_current_admin(credentials: BearerCreds, db: DbSession) -> Admin:
    payload = decode_admin_access(_require_credentials(credentials))
    try:
        admin_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise AppError("UNAUTHORIZED") from exc

    admin = db.get(Admin, admin_id)
    if admin is None:
        raise AppError("UNAUTHORIZED")
    if admin.status != "ACTIVE":
        raise AppError("ACCOUNT_SUSPENDED")
    return admin


def admin_permission_codes(db: Session, admin: Admin) -> list[str]:
    rows = db.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == admin.role_id)
    ).all()
    return sorted(rows)


def permission_required(code: str):
    def dependency(
        admin: Annotated[Admin, Depends(get_current_admin)],
        db: DbSession,
    ) -> Admin:
        if code not in admin_permission_codes(db, admin):
            raise AppError("FORBIDDEN", status=422)
        return admin

    return dependency
