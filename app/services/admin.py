"""Admin: seed, login 2FA, sesi, dan audit log."""

from __future__ import annotations

import logging
import secrets
import uuid
from contextlib import suppress
from datetime import datetime, timedelta

import pyotp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import seconds_until, to_iso, utcnow
from app.core.errors import AppError, request_id_ctx
from app.core.security import (
    admin_access_token,
    admin_challenge_token,
    decode_admin_challenge,
    hash_secret,
    opaque_token,
    sha256,
    verify_secret,
)
from app.models import (
    Admin,
    AdminPasswordHistory,
    AdminSession,
    AuditLog,
    Device,
    Permission,
    RecoveryRequest,
    Role,
    RolePermission,
    User,
)
from app.services import settings as settings_service

logger = logging.getLogger("poinqu.admin")

PERMISSIONS = [
    "admin.read",
    "admin.write",
    "settings.read",
    "settings.write",
    "users.read",
    "user.read",
    "user.write",
    "catalog.read",
    "catalog.write",
    "txn.read",
    "txn.write",
    "kyc.review",
    "recovery.review",
    "audit.read",
]

ROLE_PERMISSIONS = {
    "SUPERADMIN": PERMISSIONS,
    "CS": ["users.read", "recovery.review"],
}


def ensure_seed(db: Session) -> None:
    """Seed izin, peran, admin awal, dan pengaturan default H.7.10."""
    settings_service.seed_defaults(db)

    permissions: dict[str, Permission] = {}
    for code in PERMISSIONS:
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code)
            db.add(permission)
            db.flush()
        permissions[code] = permission

    role_public = {"SUPERADMIN": "role_super", "CS": "role_cs"}
    roles: dict[str, Role] = {}
    for name, codes in ROLE_PERMISSIONS.items():
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, public_id=role_public[name])
            db.add(role)
            db.flush()
        elif not role.public_id:
            role.public_id = role_public[name]
        roles[name] = role
        for code in codes:
            permission = permissions[code]
            if db.get(RolePermission, (role.id, permission.id)) is None:
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()

    superadmin_role = roles["SUPERADMIN"]
    admin = db.scalar(select(Admin).limit(1))
    if admin is not None:
        # Data admin lama (sebelum H.7.10) diselaraskan sekali.
        if not admin.public_id:
            admin.public_id = f"adm_{admin.id.hex[:8].upper()}"
            admin.must_change_password = False
            admin.totp_enabled = bool(admin.totp_secret)
        db.commit()
        return

    secret = settings.ADMIN_TOTP_SECRET or pyotp.random_base32()
    admin = Admin(
        email=settings.ADMIN_EMAIL.lower(),
        name=settings.ADMIN_NAME,
        password_hash=hash_secret(settings.ADMIN_PASSWORD),
        totp_secret=secret,
        totp_enabled=True,
        must_change_password=False,
        public_id="adm_bootstrap",
        role_id=superadmin_role.id,
    )
    db.add(admin)
    db.flush()
    db.commit()

    uri = pyotp.TOTP(secret).provisioning_uri(name=admin.email, issuer_name=settings.APP_NAME)
    logger.warning("Admin awal dibuat: %s", admin.email)
    logger.warning("TOTP secret (simpan di authenticator): %s", secret)
    logger.warning("otpauth:// URI: %s", uri)


def admin_public(db: Session, admin: Admin) -> dict:
    role = db.get(Role, admin.role_id)
    rows = db.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == admin.role_id)
    ).all()
    return {
        "id": admin.public_id or f"adm_{admin.id.hex[:8].upper()}",
        "email": admin.email,
        "name": admin.name,
        "role": role.name if role else None,
        "permissions": sorted(rows),
    }


def admin_detail(db: Session, admin: Admin) -> dict:
    role = db.get(Role, admin.role_id)
    return {
        "id": admin.public_id or f"adm_{admin.id.hex[:8].upper()}",
        "email": admin.email,
        "name": admin.name,
        "role": role.name if role else None,
        "status": admin.status,
        "totp_enabled": admin.totp_enabled,
        "last_login_at": to_iso(admin.last_login_at),
        "created_at": to_iso(admin.created_at),
    }


def admin_next_step(admin: Admin) -> str:
    if admin.must_change_password:
        return "CHANGE_PASSWORD"
    if not admin.totp_enabled:
        return "SETUP_2FA"
    return "VERIFY_2FA"


def record_audit(
    db: Session,
    *,
    actor_type: str,
    action: str,
    actor_id: uuid.UUID | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before=before,
        after=after,
        ip=ip,
        request_id=request_id_ctx.get(),
    )
    db.add(log)
    db.flush()
    return log


def _check_admin_lock(admin: Admin) -> None:
    now = utcnow()
    if admin.locked_until and admin.locked_until > now:
        retry_after = seconds_until(admin.locked_until)
        raise AppError("ADMIN_LOCKED", details={"retry_after": retry_after}, retry_after=retry_after)


def admin_login(db: Session, email: str, password: str, ip: str) -> tuple[Admin, str, str]:
    admin = db.scalar(select(Admin).where(Admin.email == email.lower()))
    if admin is None:
        raise AppError("ADMIN_CREDENTIALS_INVALID")

    _check_admin_lock(admin)
    if admin.status != "ACTIVE":
        raise AppError("ACCOUNT_SUSPENDED")

    if not verify_secret(admin.password_hash, password):
        admin.failed_count += 1
        if admin.failed_count >= settings.ADMIN_MAX_FAILED:
            admin.failed_count = 0
            admin.locked_until = utcnow() + timedelta(seconds=settings.ADMIN_LOCK_SECONDS)
            db.flush()
            record_audit(
                db,
                actor_type="ADMIN",
                actor_id=admin.id,
                action="admin.login.locked",
                entity="admins",
                entity_id=admin.public_id or str(admin.id),
                ip=ip,
            )
            db.commit()
            raise AppError(
                "ADMIN_LOCKED",
                details={"retry_after": settings.ADMIN_LOCK_SECONDS},
                retry_after=settings.ADMIN_LOCK_SECONDS,
            )
        db.flush()
        db.commit()
        raise AppError("ADMIN_CREDENTIALS_INVALID")

    admin.failed_count = 0
    admin.locked_until = None
    db.flush()
    return admin, admin_challenge_token(str(admin.id)), admin_next_step(admin)


def issue_admin_tokens(
    db: Session,
    admin: Admin,
    *,
    ip: str,
    family_id: uuid.UUID | None = None,
) -> tuple[dict, AdminSession]:
    raw = opaque_token("ar")
    record = AdminSession(
        admin_id=admin.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=sha256(raw),
        expires_at=utcnow() + timedelta(seconds=settings.ADMIN_REFRESH_TOKEN_TTL),
        ip=ip,
    )
    db.add(record)
    db.flush()
    payload = {
        "access_token": admin_access_token(str(admin.id)),
        "refresh_token": raw,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_TTL,
        "refresh_expires_in": settings.ADMIN_REFRESH_TOKEN_TTL,
    }
    return payload, record


def verify_admin_2fa(db: Session, challenge_token: str, code: str, ip: str) -> tuple[dict, Admin]:
    payload = decode_admin_challenge(challenge_token)
    try:
        admin_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise AppError("ADMIN_2FA_REQUIRED") from exc

    admin = db.get(Admin, admin_id)
    if admin is None:
        raise AppError("ADMIN_2FA_REQUIRED")
    _check_admin_lock(admin)
    if admin.status != "ACTIVE":
        raise AppError("ACCOUNT_SUSPENDED")
    if admin.must_change_password:
        raise AppError("ADMIN_PASSWORD_CHANGE_REQUIRED")
    if not admin.totp_enabled:
        raise AppError("ADMIN_2FA_REQUIRED")

    secret = admin.totp_secret
    if not secret or not pyotp.TOTP(secret).verify(code, valid_window=1):
        admin.failed_count += 1
        if admin.failed_count >= settings.ADMIN_MAX_FAILED:
            admin.failed_count = 0
            admin.locked_until = utcnow() + timedelta(seconds=settings.ADMIN_LOCK_SECONDS)
            db.flush()
            record_audit(
                db,
                actor_type="ADMIN",
                actor_id=admin.id,
                action="admin.2fa.locked",
                entity="admins",
                entity_id=str(admin.id),
                ip=ip,
            )
            db.commit()
            raise AppError("ADMIN_LOCKED", details={"retry_after": settings.ADMIN_LOCK_SECONDS})
        db.flush()
        db.commit()
        raise AppError("ADMIN_2FA_INVALID")

    admin.failed_count = 0
    admin.locked_until = None
    admin.last_login_at = utcnow()
    tokens, _ = issue_admin_tokens(db, admin, ip=ip)
    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=admin.id,
        action="admin.login",
        entity="admins",
        entity_id=admin.public_id or str(admin.id),
        ip=ip,
    )
    db.flush()
    return tokens, admin


def rotate_admin_refresh(db: Session, raw: str, ip: str) -> dict:
    now = utcnow()
    record = db.scalar(select(AdminSession).where(AdminSession.token_hash == sha256(raw)))
    if record is None:
        raise AppError("REFRESH_TOKEN_INVALID")

    if record.revoked_at is not None:
        if record.replaced_by is not None:
            for sibling in db.scalars(
                select(AdminSession).where(AdminSession.family_id == record.family_id)
            ).all():
                if sibling.revoked_at is None:
                    sibling.revoked_at = now
            db.commit()
        raise AppError("REFRESH_TOKEN_REVOKED")

    if record.expires_at <= now:
        raise AppError("REFRESH_TOKEN_INVALID")

    admin = db.get(Admin, record.admin_id)
    if admin is None:
        raise AppError("REFRESH_TOKEN_INVALID")
    if admin.status != "ACTIVE":
        raise AppError("ACCOUNT_SUSPENDED")

    record.revoked_at = now
    tokens, new_record = issue_admin_tokens(db, admin, ip=ip, family_id=record.family_id)
    record.replaced_by = new_record.id
    db.flush()
    return tokens


def revoke_admin_sessions(db: Session, admin: Admin) -> None:
    now = utcnow()
    for record in db.scalars(
        select(AdminSession).where(AdminSession.admin_id == admin.id, AdminSession.revoked_at.is_(None))
    ).all():
        record.revoked_at = now
    db.flush()


# ------------------------------------------------------------ H.7.8 admin


def admin_from_challenge(db: Session, challenge_token: str) -> Admin:
    try:
        payload = decode_admin_challenge(challenge_token)
    except AppError as exc:
        raise AppError("ADMIN_2FA_REQUIRED") from exc
    try:
        admin_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise AppError("ADMIN_2FA_REQUIRED") from exc
    admin = db.get(Admin, admin_id)
    if admin is None:
        raise AppError("ADMIN_2FA_REQUIRED")
    return admin


def _password_reused(db: Session, admin: Admin, new_password: str) -> bool:
    history = db.scalars(
        select(AdminPasswordHistory.password_hash)
        .where(AdminPasswordHistory.admin_id == admin.id)
        .order_by(AdminPasswordHistory.created_at.desc())
        .limit(5)
    ).all()
    return any(
        verify_secret(hashed, new_password)
        for hashed in [admin.password_hash, *history]
        if hashed
    )


def change_admin_password(
    db: Session, admin: Admin, old_password: str, new_password: str, ip: str | None = None
) -> str:
    if not verify_secret(admin.password_hash, old_password):
        raise AppError("ADMIN_CREDENTIALS_INVALID")
    if (
        len(new_password) < 12
        or admin.email.lower() in new_password.lower()
        or _password_reused(db, admin, new_password)
    ):
        raise AppError("ADMIN_PASSWORD_WEAK")

    db.add(
        AdminPasswordHistory(
            admin_id=admin.id,
            password_hash=admin.password_hash,
        )
    )
    admin.password_hash = hash_secret(new_password)
    admin.must_change_password = False
    db.flush()
    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=admin.id,
        action="admin.password.change",
        entity="admins",
        entity_id=admin.public_id or str(admin.id),
        ip=ip,
    )
    return admin_next_step(admin)


def setup_admin_2fa(db: Session, admin: Admin, ip: str | None = None) -> dict:
    if admin.must_change_password:
        raise AppError("ADMIN_PASSWORD_CHANGE_REQUIRED")
    secret = pyotp.random_base32()
    admin.totp_pending_secret = secret
    db.flush()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=admin.email, issuer_name=settings.APP_NAME
    )
    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=admin.id,
        action="admin.2fa.setup",
        entity="admins",
        entity_id=admin.public_id or str(admin.id),
        ip=ip,
    )
    return {"otpauth_uri": uri, "secret": secret, "expires_in": 300}


def enable_admin_2fa(
    db: Session, admin: Admin, code: str, ip: str
) -> tuple[dict, Admin]:
    if admin.must_change_password:
        raise AppError("ADMIN_PASSWORD_CHANGE_REQUIRED")
    secret = admin.totp_pending_secret
    if not secret:
        raise AppError("ADMIN_2FA_REQUIRED")

    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        admin.failed_count += 1
        if admin.failed_count >= settings.ADMIN_MAX_FAILED:
            admin.failed_count = 0
            admin.locked_until = utcnow() + timedelta(seconds=settings.ADMIN_LOCK_SECONDS)
            db.flush()
            raise AppError(
                "ADMIN_LOCKED",
                details={"retry_after": settings.ADMIN_LOCK_SECONDS},
                retry_after=settings.ADMIN_LOCK_SECONDS,
            )
        db.flush()
        raise AppError("ADMIN_2FA_INVALID")

    admin.totp_secret = secret
    admin.totp_pending_secret = None
    admin.totp_enabled = True
    admin.failed_count = 0
    admin.locked_until = None
    admin.last_login_at = utcnow()
    tokens, _ = issue_admin_tokens(db, admin, ip=ip)
    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=admin.id,
        action="admin.2fa.enable",
        entity="admins",
        entity_id=admin.public_id or str(admin.id),
        ip=ip,
    )
    db.flush()
    return tokens, admin


def _parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise AppError("INVALID_CURSOR") from exc


def list_admins(db: Session, cursor: str | None, limit: int) -> dict:
    statement = select(Admin)
    cursor_at = _parse_cursor(cursor)
    if cursor_at is not None:
        statement = statement.where(Admin.created_at < cursor_at)
    rows = db.scalars(statement.order_by(Admin.created_at.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [admin_detail(db, row) for row in items],
        "pagination": {
            "next_cursor": to_iso(items[-1].created_at) if has_more and items else None,
            "has_more": has_more,
            "limit": limit,
        },
    }


def create_admin(
    db: Session, actor: Admin, email: str, name: str, role_id: str, ip: str | None = None
) -> tuple[Admin, str]:
    if db.scalar(select(Admin).where(Admin.email == email.lower())) is not None:
        raise AppError("ADMIN_EMAIL_ALREADY_USED")
    role = db.scalar(select(Role).where(Role.public_id == role_id))
    if role is None:
        raise AppError("ROLE_NOT_FOUND")

    temporary_password = secrets.token_urlsafe(12)
    admin = Admin(
        public_id=f"adm_{secrets.token_hex(5)}",
        email=email.lower(),
        name=name,
        password_hash=hash_secret(temporary_password),
        role_id=role.id,
        status="ACTIVE",
        must_change_password=True,
        totp_enabled=False,
    )
    db.add(admin)
    db.flush()
    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=actor.id,
        action="admin.create",
        entity="admins",
        entity_id=admin.public_id,
        after={"email": admin.email, "name": admin.name, "role": role.name},
        ip=ip,
    )
    return admin, temporary_password


def _active_superadmins(db: Session, excluding: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Admin)
            .join(Role, Role.id == Admin.role_id)
            .where(
                Role.name == "SUPERADMIN",
                Admin.status == "ACTIVE",
                Admin.id != excluding,
            )
        )
        or 0
    )


def update_admin(
    db: Session,
    actor: Admin,
    public_id: str,
    role_id: str | None,
    status: str | None,
    ip: str | None = None,
) -> Admin:
    admin = db.scalar(select(Admin).where(Admin.public_id == public_id))
    if admin is None:
        raise AppError("ADMIN_NOT_FOUND")
    if admin.id == actor.id:
        raise AppError("CANNOT_MODIFY_SELF")

    before = admin_detail(db, admin)
    role = None
    if role_id is not None:
        role = db.scalar(select(Role).where(Role.public_id == role_id))
        if role is None:
            raise AppError("ROLE_NOT_FOUND")

    target_is_super = db.get(Role, admin.role_id)
    target_is_super = bool(target_is_super and target_is_super.name == "SUPERADMIN")
    loses_super = target_is_super and (
        (role is not None and role.name != "SUPERADMIN") or status == "DISABLED"
    )
    if loses_super and admin.status == "ACTIVE" and _active_superadmins(db, admin.id) == 0:
        raise AppError("LAST_SUPERADMIN")

    if role is not None:
        admin.role_id = role.id
    if status is not None:
        admin.status = status
        if status == "DISABLED":
            revoke_admin_sessions(db, admin)
    db.flush()

    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=actor.id,
        action="admin.update",
        entity="admins",
        entity_id=admin.public_id,
        before=before,
        after=admin_detail(db, admin),
        ip=ip,
    )
    return admin


def roles_public(db: Session) -> list[dict]:
    items = []
    for role in db.scalars(select(Role).order_by(Role.name.asc())).all():
        codes = db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).all()
        items.append(
            {
                "id": role.public_id or str(role.id),
                "name": role.name,
                "permissions": sorted(codes),
            }
        )
    return items


def setting_public(db: Session, setting) -> dict:
    updated_by = None
    if setting.updated_by:
        admin = db.get(Admin, setting.updated_by)
        updated_by = admin.public_id if admin else None
    return {
        "key": setting.key,
        "value": setting.value,
        "version": setting.version,
        "description": setting.description,
        "updated_by": updated_by,
        "updated_at": to_iso(setting.updated_at),
    }


def search_users(
    db: Session,
    *,
    q: str | None,
    status: str | None,
    level: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    statement = select(User)
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            (User.name.ilike(pattern)) | (User.phone.like(pattern))
        )
    if status:
        statement = statement.where(User.status == status)
    if level:
        statement = statement.where(User.level == level)
    cursor_at = _parse_cursor(cursor)
    if cursor_at is not None:
        statement = statement.where(User.created_at < cursor_at)

    rows = db.scalars(statement.order_by(User.created_at.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    items = []
    for user in rows[:limit]:
        last_active = db.scalar(
            select(func.max(Device.last_active_at)).where(Device.user_id == user.id)
        )
        items.append(
            {
                "id": f"usr_{user.id.hex[:10].upper()}",
                "name": user.name,
                "phone_masked": f"{user.phone[:4]}****{user.phone[-4:]}",
                "level": user.level.value,
                "kyc_status": user.kyc_status.value,
                "status": user.status.value,
                "recovery_hold": user.recovery_hold,
                "created_at": to_iso(user.created_at),
                "last_active_at": to_iso(last_active),
            }
        )
    return {
        "items": items,
        "pagination": {
            "next_cursor": to_iso(rows[limit - 1].created_at) if has_more else None,
            "has_more": has_more,
            "limit": limit,
        },
    }


def decide_recovery_request(
    db: Session,
    actor: Admin,
    public_id: str,
    decision: str,
    reason: str,
    ip: str | None = None,
) -> RecoveryRequest:
    from app.services import whatsapp
    from app.services.auth import revoke_user_sessions
    from app.services.profile import record_security_event

    request = db.scalar(
        select(RecoveryRequest).where(RecoveryRequest.public_id == public_id)
    )
    if request is None:
        raise AppError("RECOVERY_REQUEST_NOT_FOUND")
    if request.status != "PENDING_REVIEW":
        raise AppError("RECOVERY_REQUEST_ALREADY_DECIDED")

    before = {
        "status": request.status,
        "old_phone": request.old_phone,
        "new_phone": request.new_phone,
    }
    user = db.get(User, request.user_id) if request.user_id else None

    if decision == "APPROVE" and user is not None:
        conflict = db.scalar(
            select(User).where(User.phone == request.new_phone, User.id != user.id)
        )
        if conflict is not None:
            raise AppError("PHONE_ALREADY_REGISTERED")

        user.phone = request.new_phone
        user.recovery_hold = False
        cooldown_hours = settings_service.get_int(db, "recovery.cooldown_hours", 24)
        user.transfer_blocked_until = utcnow() + timedelta(hours=cooldown_hours)
        revoke_user_sessions(db, user, all_devices=True)
        record_security_event(
            db,
            user,
            "PHONE_CHANGED",
            description="Nomor HP dipulihkan melalui persetujuan admin.",
        )
    elif user is not None:
        user.recovery_hold = False

    request.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    request.decided_by = actor.id
    request.decision_reason = reason
    request.decided_at = utcnow()
    db.flush()

    message = (
        "Pengajuan pemulihan nomor kamu disetujui. Silakan masuk dengan nomor baru."
        if decision == "APPROVE"
        else "Pengajuan pemulihan nomor kamu ditolak. Hubungi bantuan bila perlu."
    )
    with suppress(AppError):
        whatsapp.send_text(db, request.new_phone, message)
    record_audit(
        db,
        actor_type="ADMIN",
        actor_id=actor.id,
        action="recovery.decision",
        entity="recovery_requests",
        entity_id=request.public_id,
        before=before,
        after={
            "status": request.status,
            "reason": reason,
            "new_phone": request.new_phone,
        },
        ip=ip,
    )
    return request


def _audit_actor_id(log: AuditLog) -> str | None:
    if log.actor_id is None:
        return None
    if log.actor_type == "ADMIN":
        return f"adm_{log.actor_id.hex[:8].upper()}"
    return str(log.actor_id)


def audit_log_public(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "actor_type": log.actor_type,
        "actor_id": _audit_actor_id(log),
        "action": log.action,
        "entity": log.entity,
        "entity_id": log.entity_id,
        "before": log.before,
        "after": log.after,
        "ip": log.ip,
        "request_id": log.request_id,
        "created_at": to_iso(log.created_at),
    }
