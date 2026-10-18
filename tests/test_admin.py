"""Kontrak admin: login 2FA, sesi, audit log, isolasi token."""

from __future__ import annotations

import pyotp
from sqlalchemy import select

from app.core.clock import utcnow
from app.db import SessionLocal
from app.models import Admin
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ADMIN_TOTP_SECRET,
    admin_login,
    auth_headers,
    client,
    register,
)


def test_admin_login_2fa_and_audit_log() -> None:
    data = admin_login()
    assert data["admin"]["email"] == ADMIN_EMAIL
    assert data["admin"]["role"] == "SUPERADMIN"
    assert "audit.read" in data["admin"]["permissions"]

    access = data["tokens"]["access_token"]
    admin_headers = {"Authorization": f"Bearer {access}"}

    response = client.get("/v1/admin/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["data"]["email"] == ADMIN_EMAIL

    response = client.get("/v1/admin/audit-logs", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["items"][0]["action"] == "admin.login"
    assert body["items"][0]["actor_type"] == "ADMIN"
    assert "pagination" in body

    response = client.get(
        "/v1/admin/audit-logs", params={"limit": 1}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["data"]["pagination"]["limit"] == 1

    response = client.get(
        "/v1/admin/audit-logs", params={"date_from": "bukan-tanggal"}, headers=admin_headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_DATE"

    response = client.get(
        "/v1/admin/audit-logs", params={"cursor": "abc"}, headers=admin_headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_CURSOR"


def test_admin_refresh_rotation() -> None:
    data = admin_login()
    refresh = data["tokens"]["refresh_token"]

    response = client.post(
        "/v1/admin/auth/token/refresh", json={"refresh_token": refresh}
    )
    assert response.status_code == 200, response.text
    rotated = response.json()["data"]

    response = client.post(
        "/v1/admin/auth/token/refresh", json={"refresh_token": refresh}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_REVOKED"

    response = client.post(
        "/v1/admin/auth/token/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_REVOKED"


def test_admin_lock_after_failed_logins() -> None:
    for _ in range(4):
        response = client.post(
            "/v1/admin/auth/login",
            json={"email": ADMIN_EMAIL, "password": "password-salah"},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "ADMIN_CREDENTIALS_INVALID"

    response = client.post(
        "/v1/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": "password-salah"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ADMIN_LOCKED"

    response = client.post(
        "/v1/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ADMIN_LOCKED"

    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.email == ADMIN_EMAIL))
        admin.locked_until = utcnow()
        db.commit()

    response = client.post(
        "/v1/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["data"]["twofa_required"] is True


def test_admin_2fa_setup_accepts_challenge_without_bearer() -> None:
    response = client.post(
        "/v1/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    challenge = response.json()["data"]["challenge_token"]

    response = client.post(
        "/v1/admin/auth/2fa/setup",
        json={"challenge_token": challenge},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["secret"]


def test_admin_2fa_requires_valid_challenge() -> None:
    response = client.post(
        "/v1/admin/auth/2fa/verify",
        json={"challenge_token": "token-tidak-valid", "code": "000000"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ADMIN_2FA_REQUIRED"


def test_admin_wrong_2fa_code() -> None:
    response = client.post(
        "/v1/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    challenge = response.json()["data"]["challenge_token"]
    response = client.post(
        "/v1/admin/auth/2fa/verify",
        json={"challenge_token": challenge, "code": "000000"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ADMIN_2FA_INVALID"

    response = client.post(
        "/v1/admin/auth/2fa/verify",
        json={"challenge_token": challenge, "code": pyotp.TOTP(ADMIN_TOTP_SECRET).now()},
    )
    assert response.status_code == 200, response.text


def test_tokens_are_not_interchangeable() -> None:
    user_data = register()
    user_access = user_data["tokens"]["access_token"]

    response = client.get(
        "/v1/admin/me", headers={"Authorization": f"Bearer {user_access}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

    admin_access = admin_login()["tokens"]["access_token"]
    response = client.get("/v1/me", headers=auth_headers(admin_access))
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
