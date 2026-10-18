"""Login/registrasi memakai email (Sprint 3)."""

from __future__ import annotations

import re

from sqlalchemy import select

from app.core.clock import utcnow
from app.db import SessionLocal
from app.models import User
from app.services import email as email_service
from tests.conftest import (
    DEVICE_A,
    DEVICE_B,
    client,
    device_info,
    headers,
    login_verification,
    otp_verify,
    register,
)


def _email_code() -> str:
    email_gateway = email_service.get_gateway()
    assert isinstance(email_gateway, email_service.LoggingEmailGateway)
    assert email_gateway.messages
    text = email_gateway.messages[-1][2]
    match = re.search(r"\b\d{6}\b", text)
    assert match is not None
    return match.group(0)


def _verify_email(email: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        user.email_verified_at = utcnow()
        db.commit()


def test_register_requires_email() -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "name": "Koko",
            "phone": "081234567890",
            "gender": "MALE",
            "accept_terms": True,
        },
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert any(item["field"] == "email" for item in response.json()["errors"])


def test_register_existing_email_is_anti_enumerated() -> None:
    data = register()
    email = data["user"]["email"]
    before = len(email_service.get_gateway().messages)

    response = client.post(
        "/v1/auth/register",
        json={
            "name": "Orang Lain",
            "phone": "081298765432",
            "email": email,
            "gender": "FEMALE",
            "accept_terms": True,
        },
        headers=headers(DEVICE_B),
    )
    assert response.status_code == 200
    assert response.json()["code"] == "OK"
    messages = email_service.get_gateway().messages
    assert len(messages) == before + 1
    assert messages[-1][0] == email
    assert "sudah terdaftar" in messages[-1][2]


def test_login_by_verified_email_uses_email_otp() -> None:
    data = register()
    email = data["user"]["email"]
    _verify_email(email)

    start = client.post(
        "/v1/auth/login/start",
        json={"identifier": email, "device_id": DEVICE_B},
        headers=headers(DEVICE_B),
    )
    assert start.status_code == 200, start.text
    assert start.json()["data"]["method"] == "OTP"
    assert start.json()["data"]["target_type"] == "EMAIL"
    assert start.json()["data"]["masked_phone"] is None

    otp = client.post(
        "/v1/auth/otp/request",
        json={"identifier": email, "purpose": "LOGIN"},
        headers=headers(DEVICE_B),
    )
    assert otp.status_code == 200, otp.text
    session_id = otp.json()["data"]["otp_session_id"]
    code = _email_code()

    verified = otp_verify(session_id, code, DEVICE_B)
    assert verified.status_code == 200, verified.text
    token = verified.json()["data"]["verification_token"]

    login = client.post(
        "/v1/auth/login/pin",
        json={
            "verification_token": token,
            "pin": "246810",
            "device": device_info(DEVICE_B, platform="IOS"),
        },
        headers=headers(DEVICE_B),
    )
    assert login.status_code == 200, login.text
    assert login.json()["data"]["tokens"]["access_token"]


def test_login_by_unverified_email_does_not_send_otp() -> None:
    data = register()
    email = data["user"]["email"]
    before = len(email_service.get_gateway().messages)

    response = client.post(
        "/v1/auth/otp/request",
        json={"identifier": email, "purpose": "LOGIN"},
        headers=headers(DEVICE_B),
    )
    assert response.status_code == 200
    assert len(email_service.get_gateway().messages) == before

    session_id = response.json()["data"]["otp_session_id"]
    invalid = otp_verify(session_id, "123456", DEVICE_B)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "OTP_INVALID"


def test_forgot_pin_by_verified_email() -> None:
    data = register()
    email = data["user"]["email"]
    _verify_email(email)

    otp = client.post(
        "/v1/auth/otp/request",
        json={"identifier": email, "purpose": "FORGOT_PIN"},
        headers=headers(DEVICE_B),
    )
    assert otp.status_code == 200, otp.text
    session_id = otp.json()["data"]["otp_session_id"]
    code = _email_code()

    verified = otp_verify(session_id, code, DEVICE_B)
    assert verified.status_code == 200, verified.text
    token = verified.json()["data"]["verification_token"]

    reset = client.post(
        "/v1/auth/pin/reset",
        json={
            "verification_token": token,
            "new_pin": "135790",
            "pin_confirmation": "135790",
        },
        headers=headers(DEVICE_B),
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["redirect"] == "LOGIN"

    # Login dengan PIN baru memakai nomor HP lewat OTP (sesi lama dicabut).
    token = login_verification("081234567890")
    pin = client.post(
        "/v1/auth/login/pin",
        json={
            "verification_token": token,
            "pin": "135790",
            "device": device_info(DEVICE_A),
        },
        headers=headers(DEVICE_A),
    )
    assert pin.status_code == 200, pin.text
    assert pin.json()["data"]["tokens"]["access_token"]
