"""Endpoint admin panel (bagian 4.33 - 4.38)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import to_iso
from app.core.deps import (
    BearerCreds,
    client_ip,
    get_current_admin,
    permission_required,
)
from app.core.errors import AppError, ok
from app.core.security import admin_challenge_token
from app.db import get_db
from app.models import Admin, AppSetting, AuditLog, RecoveryRequest, User
from app.schemas import (
    Admin2FAEnableIn,
    Admin2FASetupIn,
    AdminCreateIn,
    AdminLoginIn,
    AdminPasswordChangeIn,
    AdminRefreshIn,
    AdminTwoFactorIn,
    AdminUpdateIn,
    RecoveryDecisionIn,
    SettingUpdateIn,
)
from app.services import admin as admin_service
from app.services import settings as settings_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _resolve_admin(
    db: Session,
    credentials: BearerCreds,
    challenge_token: str | None,
) -> Admin:
    if challenge_token:
        admin = admin_service.admin_from_challenge(db, challenge_token)
        if admin.status != "ACTIVE":
            raise AppError("ACCOUNT_SUSPENDED")
        return admin
    return get_current_admin(credentials, db)


@router.post("/auth/login", summary="Login admin (langkah 1)")
def admin_login(payload: AdminLoginIn, request: Request, db: Session = Depends(get_db)):
    _, challenge, next_step = admin_service.admin_login(
        db, str(payload.email), payload.password, client_ip(request)
    )
    db.commit()
    return ok(
        {
            "challenge_token": challenge,
            "expires_in": settings.ADMIN_2FA_TTL,
            "twofa_required": next_step == "VERIFY_2FA",
            "next_step": next_step,
        },
        "Lanjut ke verifikasi 2FA."
        if next_step == "VERIFY_2FA"
        else "Lanjutkan penyiapan akun admin.",
    )


@router.post("/auth/2fa/verify", summary="Login admin (langkah 2: 2FA)")
def admin_two_factor(
    payload: AdminTwoFactorIn,
    request: Request,
    db: Session = Depends(get_db),
):
    tokens, admin = admin_service.verify_admin_2fa(
        db, payload.challenge_token, payload.code, client_ip(request)
    )
    db.commit()
    return ok(
        {"admin": admin_service.admin_public(db, admin), "tokens": tokens},
        "Berhasil masuk.",
    )


@router.post("/auth/token/refresh", summary="Perbarui token admin")
def admin_token_refresh(
    payload: AdminRefreshIn,
    request: Request,
    db: Session = Depends(get_db),
):
    tokens = admin_service.rotate_admin_refresh(
        db, payload.refresh_token, client_ip(request)
    )
    db.commit()
    return ok(tokens, "Token diperbarui.")


@router.post("/auth/logout", summary="Keluar admin")
def admin_logout(
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    admin_service.revoke_admin_sessions(db, admin)
    admin_service.record_audit(
        db,
        actor_type="ADMIN",
        actor_id=admin.id,
        action="admin.logout",
        entity="admins",
        entity_id=str(admin.id),
        ip=client_ip(request),
    )
    db.commit()
    return ok(None, "Berhasil keluar.")


@router.get("/me", summary="Profil admin")
def admin_me(
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    return ok(admin_service.admin_public(db, admin))


def _parse_date(value: str, *, end: bool = False) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise AppError("INVALID_DATE") from exc
    if end:
        parsed = parsed + timedelta(days=1)
    return parsed


@router.get("/audit-logs", summary="Audit log")
def audit_logs(
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("audit.read")),
    actor_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    stmt = select(AuditLog)

    if actor_type:
        if actor_type not in {"USER", "ADMIN", "SYSTEM"}:
            raise AppError("INVALID_TYPE")
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= _parse_date(date_from))
    if date_to:
        stmt = stmt.where(AuditLog.created_at < _parse_date(date_to, end=True))

    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError as exc:
            raise AppError("INVALID_CURSOR") from exc
        stmt = stmt.where(AuditLog.id < cursor_id)

    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return ok(
        {
            "items": [admin_service.audit_log_public(log) for log in items],
            "pagination": {
                "next_cursor": next_cursor,
                "has_more": has_more,
                "limit": limit,
            },
        }
    )

# ------------------------------------------------------------ H.7.8 admin


@router.post("/auth/password/change", summary="Ganti password admin")
def admin_password_change(
    payload: AdminPasswordChangeIn,
    request: Request,
    credentials: BearerCreds,
    db: Session = Depends(get_db),
):
    admin = _resolve_admin(db, credentials, payload.challenge_token)
    next_step = admin_service.change_admin_password(
        db,
        admin,
        payload.old_password,
        payload.new_password,
        client_ip(request),
    )
    db.commit()
    return ok(
        {
            "next_step": next_step,
            "challenge_token": admin_challenge_token(str(admin.id)),
            "expires_in": settings.ADMIN_2FA_TTL,
        },
        "Password diganti.",
    )


@router.post("/auth/2fa/setup", summary="Mulai pasang 2FA admin")
def admin_2fa_setup(
    payload: Admin2FASetupIn,
    request: Request,
    credentials: BearerCreds,
    db: Session = Depends(get_db),
):
    admin = _resolve_admin(db, credentials, payload.challenge_token)
    data = admin_service.setup_admin_2fa(db, admin, client_ip(request))
    db.commit()
    return ok(data, "Rahasia 2FA dibuat.")


@router.post("/auth/2fa/enable", summary="Aktifkan 2FA admin")
def admin_2fa_enable(
    payload: Admin2FAEnableIn,
    request: Request,
    credentials: BearerCreds,
    db: Session = Depends(get_db),
):
    admin = _resolve_admin(db, credentials, payload.challenge_token)
    tokens, admin = admin_service.enable_admin_2fa(
        db, admin, payload.code, client_ip(request)
    )
    db.commit()
    return ok(
        {"admin": admin_service.admin_public(db, admin), "tokens": tokens},
        "2FA aktif.",
    )


@router.get("/admins", summary="Daftar admin")
def list_admins(
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("admin.read")),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    return ok(admin_service.list_admins(db, cursor, limit))


@router.post("/admins", summary="Buat admin", status_code=201)
def create_admin(
    payload: AdminCreateIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("admin.write")),
):
    created, temporary_password = admin_service.create_admin(
        db,
        admin,
        str(payload.email),
        payload.name,
        payload.role_id,
        client_ip(request),
    )
    db.commit()
    body = ok(
        {
            "admin": admin_service.admin_detail(db, created),
            "temporary_password": temporary_password,
        },
        "Admin dibuat.",
    )
    return JSONResponse(status_code=201, content=jsonable_encoder(body))


@router.patch("/admins/{admin_id}", summary="Ubah admin")
def update_admin(
    admin_id: str,
    payload: AdminUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("admin.write")),
):
    updated = admin_service.update_admin(
        db,
        admin,
        admin_id,
        payload.role_id,
        payload.status,
        client_ip(request),
    )
    db.commit()
    return ok(admin_service.admin_detail(db, updated), "Admin diperbarui.")


@router.get("/roles", summary="Daftar peran dan izin")
def list_roles(
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("admin.read")),
):
    return ok({"items": admin_service.roles_public(db)})


@router.get("/settings", summary="Daftar pengaturan")
def list_settings(
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("settings.read")),
    prefix: str | None = Query(default=None),
):
    items = [
        admin_service.setting_public(db, setting)
        for setting in settings_service.list_settings(db, prefix)
    ]
    return ok({"items": items})


@router.put("/settings/{key}", summary="Ubah pengaturan")
def update_setting(
    key: str,
    payload: SettingUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("settings.write")),
):
    setting = db.get(AppSetting, key)
    if setting is None:
        raise AppError("SETTING_NOT_FOUND")
    if payload.version != setting.version:
        raise AppError(
            "SETTING_VERSION_CONFLICT",
            details={"current_version": setting.version},
        )

    settings_service.validate_value(key, payload.value)
    before = {"value": setting.value, "version": setting.version}
    setting.value = payload.value
    setting.version += 1
    setting.updated_by = admin.id
    admin_service.record_audit(
        db,
        actor_type="ADMIN",
        actor_id=admin.id,
        action="settings.update",
        entity="app_settings",
        entity_id=key,
        before=before,
        after={
            "value": setting.value,
            "version": setting.version,
            "reason": payload.reason,
        },
        ip=client_ip(request),
    )
    db.commit()
    return ok(admin_service.setting_public(db, setting), "Pengaturan diperbarui.")


@router.get("/users", summary="Cari pengguna")
def search_users(
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("users.read")),
    q: str | None = Query(default=None, min_length=4),
    status: Literal["ACTIVE", "LOCKED", "SUSPENDED"] | None = Query(default=None),
    level: Literal["BASIC", "PREMIUM"] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    return ok(
        admin_service.search_users(
            db, q=q, status=status, level=level, cursor=cursor, limit=limit
        )
    )


@router.get("/recovery-requests", summary="Daftar pengajuan pemulihan")
def list_recovery_requests(
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("recovery.review")),
    status: Literal["PENDING_REVIEW", "APPROVED", "REJECTED"] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    statement = select(RecoveryRequest)
    if status:
        statement = statement.where(RecoveryRequest.status == status)
    cursor_at = admin_service._parse_cursor(cursor)
    if cursor_at is not None:
        statement = statement.where(RecoveryRequest.created_at < cursor_at)
    rows = db.scalars(
        statement.order_by(RecoveryRequest.created_at.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return ok(
        {
            "items": [
                {
                    "id": row.public_id,
                    "status": row.status,
                    "name": row.name,
                    "old_phone": f"{row.old_phone[:4]}****{row.old_phone[-4:]}",
                    "new_phone": f"{row.new_phone[:4]}****{row.new_phone[-4:]}",
                    "account_found": row.user_id is not None,
                    "last_transaction_hint": row.last_transaction_hint,
                    "balance_hint": row.balance_hint,
                    "note": row.note,
                    "created_at": to_iso(row.created_at),
                    "decided_at": to_iso(row.decided_at),
                }
                for row in items
            ],
            "pagination": {
                "next_cursor": to_iso(items[-1].created_at)
                if has_more and items
                else None,
                "has_more": has_more,
                "limit": limit,
            },
        }
    )


@router.post(
    "/recovery-requests/{request_id}/decision",
    summary="Putuskan pengajuan pemulihan",
)
def decide_recovery_request(
    request_id: str,
    payload: RecoveryDecisionIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(permission_required("recovery.review")),
):
    row = admin_service.decide_recovery_request(
        db,
        admin,
        request_id,
        payload.decision,
        payload.reason,
        client_ip(request),
    )
    db.commit()
    user = db.get(User, row.user_id) if row.user_id else None
    return ok(
        {
            "id": row.public_id,
            "status": row.status,
            "decided_at": to_iso(row.decided_at),
            "transfer_blocked_until": to_iso(user.transfer_blocked_until)
            if user
            else None,
        },
        "Keputusan disimpan.",
    )
