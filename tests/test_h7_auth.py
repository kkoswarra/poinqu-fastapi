"""H.7.1/H.7.2/H.7.5/H.7.6/H.7.7: login tepercaya, anti-enumerasi, token, PIN, attestation."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.db import SessionLocal
from app.models import AppSetting, Device, PinAttempt, User
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


def test_trusted_device_login_without_otp_and_token_binding() -> None:
    data = register()
    access = data["tokens"]["access_token"]

    response = client.post(
        "/v1/auth/logout", json={"all_devices": False}, headers=auth_headers(access)
    )
    assert response.status_code == 200
    assert client.get("/v1/me", headers=auth_headers(access)).status_code == 401

    response = client.post(
        "/v1/auth/login/start",
        json={"phone": "081234567890", "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    start = response.json()["data"]
    assert start["method"] == "PIN"
    assert start["verification_token"]
    assert start["expires_in"] == 600
    assert "PIN" in start["available_methods"]

    # Token login/start terikat ke device; device lain ditolak.
    response = client.post(
        "/v1/auth/login/pin",
        json={
            "verification_token": start["verification_token"],
            "pin": "246810",
            "device": device_info(DEVICE_B),
        },
        headers=headers(DEVICE_B),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "DEVICE_MISMATCH"

    response = client.post(
        "/v1/auth/login/pin",
        json={
            "verification_token": start["verification_token"],
            "pin": "246810",
            "device": device_info(DEVICE_A),
        },
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["tokens"]["access_token"]


def test_login_start_shape_is_identical_for_unknown_phone_and_device() -> None:
    register()
    known_unknown_device = client.post(
        "/v1/auth/login/start",
        json={"phone": "081234567890", "device_id": DEVICE_B},
        headers=headers(DEVICE_B),
    )
    unknown_phone = client.post(
        "/v1/auth/login/start",
        json={"phone": "089999999999", "device_id": DEVICE_B},
        headers=headers(DEVICE_B),
    )
    for response in (known_unknown_device, unknown_phone):
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["method"] == "OTP"
        assert data["verification_token"] is None
        assert data["expires_in"] is None
        assert data["preferred_method"] is None
        assert data["available_methods"] == []


def test_trusted_device_expires_after_idle_days() -> None:
    register()
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_id == DEVICE_A))
        device.last_active_at = utcnow() - timedelta(days=91)
        db.commit()

    response = client.post(
        "/v1/auth/login/start",
        json={"phone": "081234567890", "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 200
    assert response.json()["data"]["method"] == "OTP"

    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_id == DEVICE_A))
        assert device.trusted_at is None


def test_otp_request_does_not_reveal_unregistered_phone() -> None:
    response = otp_request("089999999999", "LOGIN")
    assert response.status_code == 200
    assert response.json()["code"] == "OK"
    assert "089999999999" not in gateway.sent

    session_id = response.json()["data"]["otp_session_id"]
    response = otp_verify(session_id, "123456")
    assert response.status_code == 422
    assert response.json()["code"] == "OTP_INVALID"

    for _ in range(3):
        response = otp_verify(session_id, "123456")
        assert response.json()["code"] == "OTP_INVALID"
    response = otp_verify(session_id, "123456")
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_ATTEMPTS_EXCEEDED"


def test_register_existing_phone_is_anti_enumerated() -> None:
    register()
    before = len(gateway.messages)

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
    assert response.status_code == 200
    session_id = response.json()["data"]["otp_session_id"]
    assert len(gateway.messages) == before + 1
    assert "sudah punya akun" in gateway.messages[-1][1]

    response = otp_verify(session_id, "123456")
    assert response.status_code == 422
    assert response.json()["code"] == "OTP_INVALID"


def test_otp_rate_limits_per_device_and_phone() -> None:
    for index in range(10):
        response = otp_request(f"08999000{index:04d}", "LOGIN")
        assert response.status_code == 200, response.text

    response = otp_request("089990000999", "LOGIN")
    assert response.status_code == 429
    assert response.json()["code"] == "OTP_RATE_LIMITED"


def test_pin_lock_is_per_device() -> None:
    register()
    token_a = login_verification("081234567890", DEVICE_A)
    token_b = login_verification("081234567890", DEVICE_B)

    def attempt(device_id: str, token: str, pin: str):
        return client.post(
            "/v1/auth/login/pin",
            json={
                "verification_token": token,
                "pin": pin,
                "device": device_info(device_id),
            },
            headers=headers(device_id),
        )

    for expected_left in (4, 3, 2, 1):
        response = attempt(DEVICE_A, token_a, "000000")
        assert response.status_code == 401
        assert response.json()["details"]["attempts_left"] == expected_left

    response = attempt(DEVICE_A, token_a, "000000")
    assert response.status_code == 423
    assert response.json()["code"] == "PIN_LOCKED"

    # Perangkat B tidak ikut terkunci.
    response = attempt(DEVICE_B, token_b, "246810")
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "081234567890"))
        rows = {
            str(row.device_id): row
            for row in db.scalars(
                select(PinAttempt).where(PinAttempt.user_id == user.id)
            ).all()
        }
        assert any(row.lockout_level == 1 for row in rows.values())


def test_logout_all_and_pin_reset_revoke_access_tokens() -> None:
    data = register()
    access_a = data["tokens"]["access_token"]
    response = login("081234567890", "246810", device_id=DEVICE_B)
    access_b = response.json()["data"]["tokens"]["access_token"]

    response = client.post(
        "/v1/auth/logout", json={"all_devices": True}, headers=auth_headers(access_b, DEVICE_B)
    )
    assert response.status_code == 200
    assert client.get("/v1/me", headers=auth_headers(access_a)).status_code == 401
    assert (
        client.get("/v1/me", headers=auth_headers(access_b, DEVICE_B)).status_code == 401
    )

    login_response = login("081234567890")
    access = login_response.json()["data"]["tokens"]["access_token"]
    response = client.post(
        "/v1/auth/otp/request",
        json={"phone": "081234567890", "purpose": "FORGOT_PIN"},
        headers=headers(),
    )
    session_id = response.json()["data"]["otp_session_id"]
    token = otp_verify(session_id, gateway.sent["081234567890"]).json()["data"][
        "verification_token"
    ]
    response = client.post(
        "/v1/auth/pin/reset",
        json={
            "verification_token": token,
            "new_pin": "135790",
            "pin_confirmation": "135790",
        },
        headers=headers(),
    )
    assert response.status_code == 200
    assert client.get("/v1/me", headers=auth_headers(access)).status_code == 401


def test_refresh_reuse_revokes_access_tokens() -> None:
    tokens = register()["tokens"]
    access = tokens["access_token"]

    response = client.post(
        "/v1/auth/token/refresh",
        json={"refresh_token": tokens["refresh_token"], "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 200

    # Pemakaian ulang refresh token lama = indikasi pencurian.
    response = client.post(
        "/v1/auth/token/refresh",
        json={"refresh_token": tokens["refresh_token"], "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_REVOKED"
    assert client.get("/v1/me", headers=auth_headers(access)).status_code == 401


def test_attestation_flag_enforced() -> None:
    register()
    with SessionLocal() as db:
        setting = db.get(AppSetting, "security.attestation_required")
        setting.value = True
        db.commit()

    response = client.post(
        "/v1/auth/login/start",
        json={"phone": "081234567890", "device_id": DEVICE_A},
        headers=headers(),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DEVICE_ATTESTATION_FAILED"

    response = client.post(
        "/v1/auth/login/start",
        json={"phone": "081234567890", "device_id": DEVICE_A},
        headers=headers(
            **{
                "X-Attestation-Provider": "PLAY_INTEGRITY",
                "X-Attestation": "att_valid_demo",
            }
        ),
    )
    assert response.status_code == 200
    assert response.json()["data"]["method"] == "PIN"

    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_id == DEVICE_A))
        assert device.attestation_provider == "PLAY_INTEGRITY"
        assert device.attested_at is not None
