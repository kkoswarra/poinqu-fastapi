"""H.7.8: password/2FA admin, kelola admin, peran, pengaturan, cari pengguna."""

from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db import SessionLocal
from app.models import Admin, AdminPasswordHistory, AuditLog, Permission, Role, RolePermission
from app.services import admin as admin_service
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    admin_login,
    client,
    register,
)


def _bootstrap_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_login()['tokens']['access_token']}"}


def test_admin_password_and_2fa_setup_flow() -> None:
    bootstrap = _bootstrap_headers()

    response = client.get("/v1/admin/roles", headers=bootstrap)
    assert response.status_code == 200
    roles = {item["name"]: item["id"] for item in response.json()["data"]["items"]}
    assert roles["SUPERADMIN"] == "role_super"
    assert "role_cs" in roles.values()

    response = client.post(
        "/v1/admin/admins",
        json={"email": "cs@poinqu.id", "name": "Tim CS", "role_id": "role_cs"},
        headers=bootstrap,
    )
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    temporary_password = created["temporary_password"]
    admin_id = created["admin"]["id"]
    assert created["admin"]["totp_enabled"] is False
    assert len(temporary_password) >= 12

    response = client.get("/v1/admin/admins", headers=bootstrap)
    assert response.status_code == 200
    listed = response.json()["data"]["items"]
    assert {item["email"] for item in listed} == {ADMIN_EMAIL, "cs@poinqu.id"}
    assert all("totp_enabled" in item and "last_login_at" in item for item in listed)

    response = client.post(
        "/v1/admin/auth/login",
        json={"email": "cs@poinqu.id", "password": temporary_password},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["next_step"] == "CHANGE_PASSWORD"
    challenge = response.json()["data"]["challenge_token"]

    response = client.post(
        "/v1/admin/auth/2fa/verify",
        json={"challenge_token": challenge, "code": "000000"},
    )
    assert response.json()["code"] == "ADMIN_PASSWORD_CHANGE_REQUIRED"

    response = client.post(
        "/v1/admin/auth/password/change",
        json={
            "challenge_token": challenge,
            "old_password": temporary_password,
            "new_password": "PasswordBaruCS-2026",
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()["data"]
    assert changed["next_step"] == "SETUP_2FA"
    challenge = changed["challenge_token"]

    response = client.post(
        "/v1/admin/auth/2fa/setup", json={"challenge_token": challenge}
    )
    assert response.status_code == 200, response.text
    secret = response.json()["data"]["secret"]
    assert response.json()["data"]["otpauth_uri"].startswith("otpauth://totp/")

    response = client.post(
        "/v1/admin/auth/2fa/enable",
        json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200, response.text
    cs_tokens = response.json()["data"]["tokens"]

    with SessionLocal() as db:
        cs_admin = db.scalar(select(Admin).where(Admin.email == "cs@poinqu.id"))
        assert cs_admin.totp_enabled is True

    # Login berikutnya memakai 2FA normal.
    response = client.post(
        "/v1/admin/auth/login",
        json={"email": "cs@poinqu.id", "password": "PasswordBaruCS-2026"},
    )
    assert response.json()["data"]["next_step"] == "VERIFY_2FA"
    challenge = response.json()["data"]["challenge_token"]
    response = client.post(
        "/v1/admin/auth/2fa/verify",
        json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200, response.text

    # CS tidak punya izin admin.read.
    response = client.get(
        "/v1/admin/roles",
        headers={"Authorization": f"Bearer {cs_tokens['access_token']}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "FORBIDDEN"

    # Superadmin menonaktifkan CS; sesi CS langsung ditolak.
    response = client.patch(
        f"/v1/admin/admins/{admin_id}",
        json={"status": "DISABLED"},
        headers=bootstrap,
    )
    assert response.status_code == 200, response.text

    response = client.get(
        "/v1/admin/me",
        headers={"Authorization": f"Bearer {cs_tokens['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_SUSPENDED"


def test_admin_settings_versioning_and_audit() -> None:
    bootstrap = _bootstrap_headers()

    response = client.get(
        "/v1/admin/settings", params={"prefix": "security."}, headers=bootstrap
    )
    assert response.status_code == 200, response.text
    items = {item["key"]: item for item in response.json()["data"]["items"]}
    assert "security.pin.max_attempts" in items
    setting = items["security.pin.max_attempts"]

    response = client.put(
        "/v1/admin/settings/security.pin.max_attempts",
        json={"value": 6, "version": setting["version"] - 1, "reason": "Uji konflik versi lama"},
        headers=bootstrap,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SETTING_VERSION_CONFLICT"
    assert response.json()["details"]["current_version"] == setting["version"]

    response = client.put(
        "/v1/admin/settings/security.pin.max_attempts",
        json={
            "value": 6,
            "version": setting["version"],
            "reason": "Penyesuaian kebijakan keamanan",
        },
        headers=bootstrap,
    )
    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert updated["value"] == 6
    assert updated["version"] == setting["version"] + 1

    with SessionLocal() as db:
        log = db.scalar(
            select(AuditLog).where(AuditLog.action == "settings.update")
        )
        assert log is not None
        assert log.before["value"] == setting["value"]
        assert log.after["value"] == 6
        assert log.after["reason"] == "Penyesuaian kebijakan keamanan"


def test_admin_user_search_and_self_modification_guard() -> None:
    register()
    bootstrap = _bootstrap_headers()

    response = client.get(
        "/v1/admin/users", params={"q": "Kok"}, headers=bootstrap
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "INVALID_LENGTH"

    response = client.get(
        "/v1/admin/users", params={"q": "Koko"}, headers=bootstrap
    )
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert items and items[0]["phone_masked"].startswith("0812****")
    assert items[0]["recovery_hold"] is False

    response = client.get("/v1/admin/me", headers=bootstrap)
    my_id = response.json()["data"]["id"]
    response = client.patch(
        f"/v1/admin/admins/{my_id}", json={"status": "DISABLED"}, headers=bootstrap
    )
    assert response.status_code == 422
    assert response.json()["code"] == "CANNOT_MODIFY_SELF"


def test_last_superadmin_guard() -> None:
    with SessionLocal() as db:
        cs_role = db.scalar(select(Role).where(Role.name == "CS"))
        admin_write = db.scalar(select(Permission).where(Permission.code == "admin.write"))
        if db.get(RolePermission, (cs_role.id, admin_write.id)) is None:
            db.add(RolePermission(role_id=cs_role.id, permission_id=admin_write.id))
        actor = Admin(
            public_id="adm_cs_actor",
            email="actor@poinqu.id",
            name="Actor",
            password_hash="x",
            role_id=cs_role.id,
            must_change_password=False,
            totp_enabled=True,
        )
        db.add(actor)
        bootstrap = db.scalar(select(Admin).where(Admin.email == ADMIN_EMAIL))
        db.commit()

        with pytest.raises(AppError) as exc:
            admin_service.update_admin(
                db, actor, bootstrap.public_id, None, "DISABLED"
            )
        assert exc.value.code == "LAST_SUPERADMIN"


def test_admin_password_history_is_recorded() -> None:
    bootstrap = _bootstrap_headers()
    response = client.post(
        "/v1/admin/auth/password/change",
        json={
            "old_password": ADMIN_PASSWORD,
            "new_password": "PasswordBootstrapBaru-2026",
        },
        headers=bootstrap,
    )
    assert response.status_code == 200, response.text
    challenge = response.json()["data"]["challenge_token"]
    response = client.post("/v1/admin/auth/2fa/setup", json={"challenge_token": challenge})
    secret = response.json()["data"]["secret"]
    response = client.post(
        "/v1/admin/auth/2fa/enable",
        json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.email == ADMIN_EMAIL))
        history = db.scalars(
            select(AdminPasswordHistory).where(
                AdminPasswordHistory.admin_id == admin.id
            )
        ).all()
        assert len(history) == 1
