"""Fixture test: database SQLite in-memory, seed admin, gateway OTP log."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-jangan-dipakai-di-produksi"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "false"
os.environ["ADMIN_EMAIL"] = "admin@poinqu.id"
os.environ["ADMIN_PASSWORD"] = "admin-password-123"
os.environ["ADMIN_TOTP_SECRET"] = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
os.environ["FONNTE_WEBHOOK_SECRET"] = "test-webhook-secret-32-characters-min"
os.environ["MEDIA_BASE_URL"] = ""
os.environ["AVATAR_DIR"] = str(Path(tempfile.gettempdir()) / "poinqu-test-media" / "avatars")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import email as email_service  # noqa: E402
from app.services.admin import ensure_seed  # noqa: E402
from app.services.revocation import store as revocation_store  # noqa: E402
from app.services.wa import gateway  # noqa: E402

client = TestClient(app)

DEVICE_A = "dev_and_test01"
DEVICE_B = "dev_ios_test02"

ADMIN_EMAIL = "admin@poinqu.id"
ADMIN_PASSWORD = "admin-password-123"
ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_seed(db)
    gateway.sent.clear()
    previous_email_gateway = email_service.get_gateway()
    email_service.set_gateway(email_service.LoggingEmailGateway())
    revocation_store.reset()
    yield
    gateway.sent.clear()
    email_service.set_gateway(previous_email_gateway)
    revocation_store.reset()


def headers(device_id: str = DEVICE_A, **extra: str) -> dict[str, str]:
    return {"X-Device-Id": device_id, "X-App-Version": "1.0.0", **extra}


def auth_headers(token: str, device_id: str = DEVICE_A, **extra: str) -> dict[str, str]:
    return headers(device_id, Authorization=f"Bearer {token}", **extra)


def device_info(device_id: str = DEVICE_A, platform: str = "ANDROID") -> dict:
    return {
        "device_id": device_id,
        "name": "Pixel 8" if platform == "ANDROID" else "iPhone 14",
        "platform": platform,
        "os_version": "15",
        "app_version": "1.0.0",
        "push_token": None,
    }


def otp_request(phone: str, purpose: str = "REGISTER", device_id: str = DEVICE_A):
    return client.post(
        "/v1/auth/otp/request",
        json={"phone": phone, "purpose": purpose},
        headers=headers(device_id),
    )


def otp_verify(session_id: str, code: str, device_id: str = DEVICE_A):
    return client.post(
        "/v1/auth/otp/verify",
        json={"otp_session_id": session_id, "code": code},
        headers=headers(device_id),
    )


def register(
    phone: str = "081234567890",
    pin: str = "246810",
    device_id: str = DEVICE_A,
    name: str = "Koko",
) -> dict:
    response = client.post(
        "/v1/auth/register",
        json={"name": name, "phone": phone, "gender": "MALE", "accept_terms": True},
        headers=headers(device_id),
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["data"]["otp_session_id"]

    response = otp_verify(session_id, gateway.sent[phone], device_id)
    assert response.status_code == 200, response.text
    token = response.json()["data"]["verification_token"]

    response = client.post(
        "/v1/auth/register/complete",
        json={
            "verification_token": token,
            "pin": pin,
            "pin_confirmation": pin,
            "device": device_info(device_id),
        },
        headers=headers(device_id),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def login_verification(phone: str, device_id: str = DEVICE_A) -> str:
    response = otp_request(phone, "LOGIN", device_id)
    assert response.status_code == 200, response.text
    session_id = response.json()["data"]["otp_session_id"]
    response = otp_verify(session_id, gateway.sent[phone], device_id)
    assert response.status_code == 200, response.text
    return response.json()["data"]["verification_token"]


def login(phone: str, pin: str = "246810", device_id: str = DEVICE_A):
    token = login_verification(phone, device_id)
    return client.post(
        "/v1/auth/login/pin",
        json={"verification_token": token, "pin": pin, "device": device_info(device_id)},
        headers=headers(device_id),
    )


def admin_login() -> dict:
    import pyotp

    response = client.post(
        "/v1/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    challenge = response.json()["data"]["challenge_token"]

    response = client.post(
        "/v1/admin/auth/2fa/verify",
        json={"challenge_token": challenge, "code": pyotp.TOTP(ADMIN_TOTP_SECRET).now()},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]
