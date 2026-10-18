"""Kontrak auth: OTP, verification token, PIN, sesi, refresh."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.db import SessionLocal
from app.models import OtpSession, PinAttempt, User
from tests.conftest import (
    DEVICE_A,
    DEVICE_B,
    auth_headers,
    client,
    device_info,
    gateway,
    headers,
    login,
    login_verification,
    otp_request,
    otp_verify,
    register,
)


def test_register_and_profile_envelope() -> None:
    data = register()
    assert data["user"]["phone"] == "081234567890"
    assert data["user"]["level"] == "BASIC"
    assert data["user"]["email_verified"] is False
    assert data["tokens"]["token_type"] == "Bearer"
    assert data["tokens"]["expires_in"] == 900

    response = client.get("/v1/me", headers=auth_headers(data["tokens"]["access_token"]))
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["code"] == "OK"
    assert body["meta"]["request_id"].startswith("req_")
    assert body["meta"]["timestamp"].endswith("Z")


def test_register_terms_missing_is_rejected() -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "name": "Koko",
            "phone": "081234567890",
            "email": "koko@example.com",
            "gender": "MALE",
        },
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "TERMS_NOT_ACCEPTED"


def test_register_requires_terms_and_valid_phone() -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "name": "Koko",
            "phone": "081234567890",
            "email": "koko@example.com",
            "gender": "MALE",
            "accept_terms": False,
        },
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "TERMS_NOT_ACCEPTED"

    response = client.post(
        "/v1/auth/register",
        json={
            "name": "Koko",
            "phone": "12345",
            "email": "koko@example.com",
            "gender": "MALE",
            "accept_terms": True,
        },
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "INVALID_PHONE"


def test_device_header_required() -> None:
    response = client.post("/v1/auth/otp/request", json={"phone": "081234567890"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "X-Device-Id"


def test_otp_wrong_code_and_attempt_limit() -> None:
    response = otp_request("081234567890")
    session_id = response.json()["data"]["otp_session_id"]

    for expected_left in (4, 3, 2, 1):
        response = otp_verify(session_id, "000000")
        assert response.status_code == 422
        assert response.json()["code"] == "OTP_INVALID"
        assert response.json()["details"]["attempts_left"] == expected_left

    response = otp_verify(session_id, "000000")
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_ATTEMPTS_EXCEEDED"

    response = otp_verify(session_id, gateway.sent["081234567890"])
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_ATTEMPTS_EXCEEDED"


def test_otp_expired() -> None:
    session_id = otp_request("081234567890").json()["data"]["otp_session_id"]
    with SessionLocal() as db:
        session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    response = otp_verify(session_id, "123456")
    assert response.status_code == 410
    assert response.json()["code"] == "OTP_EXPIRED"


def test_otp_session_has_generic_target() -> None:
    response = otp_request("081234567890")
    session_id = response.json()["data"]["otp_session_id"]

    with SessionLocal() as db:
        session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
        assert session is not None
        assert session.target == "081234567890"
        assert session.target_type == "PHONE"
        assert session.channel == "WHATSAPP"
        assert session.phone == "081234567890"


def test_otp_hourly_rate_limit() -> None:
    for _ in range(5):
        assert otp_request("081234567890").status_code == 200

    response = otp_request("081234567890")
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_RATE_LIMITED"
    assert response.json()["details"]["retry_after"] > 0


def test_otp_resend_cooldown_and_limit() -> None:
    session_id = otp_request("081234567890").json()["data"]["otp_session_id"]

    response = client.post(
        "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
    )
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_RESEND_TOO_SOON"

    for expected_remaining in (2, 1, 0):
        with SessionLocal() as db:
            session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
            session.last_sent_at = utcnow() - timedelta(seconds=60)
            db.commit()
        response = client.post(
            "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["resend_remaining"] == expected_remaining

    with SessionLocal() as db:
        session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
        session.last_sent_at = utcnow() - timedelta(seconds=60)
        db.commit()
    response = client.post(
        "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
    )
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_RESEND_LIMIT"


def test_otp_resend_decoy_matches_real_session() -> None:
    response = otp_request("089999999999", "LOGIN")
    assert response.status_code == 200
    session_id = response.json()["data"]["otp_session_id"]
    assert "089999999999" not in gateway.sent

    # Cooldown harus sama dengan sesi nomor terdaftar.
    response = client.post(
        "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
    )
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_RESEND_TOO_SOON"

    for expected_remaining in (2, 1, 0):
        with SessionLocal() as db:
            session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
            session.last_sent_at = utcnow() - timedelta(seconds=60)
            db.commit()
        response = client.post(
            "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["resend_remaining"] == expected_remaining

    with SessionLocal() as db:
        session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
        session.last_sent_at = utcnow() - timedelta(seconds=60)
        db.commit()
    response = client.post(
        "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
    )
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_RESEND_LIMIT"

    # Sesi palsu tidak pernah mengirim WhatsApp.
    assert "089999999999" not in gateway.sent


def test_verification_token_single_use_and_purpose() -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "name": "Koko",
            "phone": "081234567890",
            "email": "koko@example.com",
            "gender": "MALE",
            "accept_terms": True,
        },
        headers=headers(),
    )
    session_id = response.json()["data"]["otp_session_id"]
    token = otp_verify(session_id, gateway.sent["081234567890"]).json()["data"][
        "verification_token"
    ]

    response = client.post(
        "/v1/auth/login/pin",
        json={"verification_token": token, "pin": "246810", "device": device_info()},
        headers=headers(),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "VERIFICATION_PURPOSE_MISMATCH"

    payload = {
        "verification_token": token,
        "pin": "246810",
        "pin_confirmation": "246810",
        "device": device_info(),
    }
    assert client.post("/v1/auth/register/complete", json=payload, headers=headers()).status_code == 201
    response = client.post("/v1/auth/register/complete", json=payload, headers=headers())
    assert response.status_code == 401
    assert response.json()["code"] == "VERIFICATION_TOKEN_INVALID"


def test_pin_lock_after_five_failures_and_reset_on_success() -> None:
    register(pin="246810")
    token = login_verification("081234567890")

    def attempt(pin: str):
        return client.post(
            "/v1/auth/login/pin",
            json={"verification_token": token, "pin": pin, "device": device_info()},
            headers=headers(),
        )

    for expected_left in (4, 3, 2, 1):
        response = attempt("000000")
        assert response.status_code == 401
        assert response.json()["code"] == "PIN_INVALID"
        assert response.json()["details"]["attempts_left"] == expected_left

    response = attempt("000000")
    assert response.status_code == 423
    assert response.json()["code"] == "PIN_LOCKED"
    assert response.json()["details"]["retry_after"] > 0

    response = attempt("246810")
    assert response.status_code == 423
    assert response.json()["code"] == "PIN_LOCKED"

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "081234567890"))
        user.pin_locked_until = utcnow() - timedelta(seconds=1)
        attempt_row = db.scalar(select(PinAttempt).where(PinAttempt.user_id == user.id))
        if attempt_row is not None:
            attempt_row.locked_until = utcnow() - timedelta(seconds=1)
        db.commit()

    response = attempt("246810")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["user"]["phone"] == "081234567890"

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "081234567890"))
        assert user.pin_failed_count == 0


def test_refresh_rotation_and_reuse_revokes_family() -> None:
    tokens = register()["tokens"]
    refresh = tokens["refresh_token"]

    response = client.post(
        "/v1/auth/token/refresh",
        json={"refresh_token": refresh, "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    rotated = response.json()["data"]
    assert rotated["refresh_token"] != refresh

    response = client.post(
        "/v1/auth/token/refresh",
        json={"refresh_token": refresh, "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_REVOKED"

    response = client.post(
        "/v1/auth/token/refresh",
        json={"refresh_token": rotated["refresh_token"], "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_REVOKED"


def test_refresh_device_mismatch() -> None:
    tokens = register()["tokens"]
    response = client.post(
        "/v1/auth/token/refresh",
        json={"refresh_token": tokens["refresh_token"], "device_id": DEVICE_B},
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "DEVICE_MISMATCH"


def test_login_from_new_device_records_security_event() -> None:
    register()
    response = login("081234567890", "246810", device_id=DEVICE_B)
    assert response.status_code == 200, response.text
    access = response.json()["data"]["tokens"]["access_token"]

    response = client.get(
        "/v1/me/security/activities", headers=auth_headers(access, DEVICE_B)
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert any(item["type"] == "NEW_DEVICE" for item in items)
    assert response.json()["data"]["unread_count"] >= 1
