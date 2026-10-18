"""Verifikasi email dan perubahan nomor/email dari halaman akun."""

from __future__ import annotations

import re

from app.services import email as email_service
from tests.conftest import (
    DEVICE_A,
    auth_headers,
    client,
    gateway,
    otp_verify,
    register,
)


def _pin_token(access: str, purpose: str) -> str:
    response = client.post(
        "/v1/me/pin/verify",
        json={"pin": "246810", "purpose": purpose},
        headers=auth_headers(access),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["pin_token"]


def _email_code() -> str:
    gateway_email = email_service.get_gateway()
    assert isinstance(gateway_email, email_service.LoggingEmailGateway)
    assert gateway_email.messages
    text = gateway_email.messages[-1][2]
    match = re.search(r"\b\d{6}\b", text)
    assert match is not None
    return match.group(0)


def _me(access: str) -> dict:
    response = client.get("/v1/me", headers=auth_headers(access))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_email_verification_flow() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    assert _me(access)["email_verified"] is False

    requested = client.post(
        "/v1/me/email/verification/request", headers=auth_headers(access)
    )
    assert requested.status_code == 200, requested.text
    session_id = requested.json()["data"]["otp_session_id"]
    code = _email_code()

    verified = client.post(
        "/v1/me/email/verification/verify",
        json={"otp_session_id": session_id, "code": code},
        headers=auth_headers(access),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["email_verified"] is True
    assert _me(access)["email_verified"] is True


def test_change_phone_flow() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    pin_token = _pin_token(access, "CHANGE_PHONE")

    requested = client.post(
        "/v1/me/phone/change/request",
        json={"new_phone": "081298765432"},
        headers=auth_headers(access, **{"X-Pin-Token": pin_token}),
    )
    assert requested.status_code == 200, requested.text
    payload = requested.json()["data"]
    code = gateway.sent["081298765432"]

    confirmed = client.post(
        "/v1/me/phone/change/confirm",
        json={
            "change_id": payload["change_id"],
            "otp_session_id": payload["otp_session_id"],
            "code": code,
        },
        headers=auth_headers(access),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["new_phone"] == "081298765432"
    assert _me(access)["phone"] == "081298765432"

    # Perangkat saat ini tetap bisa dipakai; nomor lama mendapat notifikasi.
    assert any(phone == "081234567890" for phone, _ in gateway.messages)


def test_change_email_flow() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    old_email = data["user"]["email"]
    new_email = "koko.baru@example.com"
    pin_token = _pin_token(access, "CHANGE_EMAIL")

    requested = client.post(
        "/v1/me/email/change/request",
        json={"new_email": new_email},
        headers=auth_headers(access, **{"X-Pin-Token": pin_token}),
    )
    assert requested.status_code == 200, requested.text
    payload = requested.json()["data"]
    code = _email_code()

    confirmed = client.post(
        "/v1/me/email/change/confirm",
        json={
            "change_id": payload["change_id"],
            "otp_session_id": payload["otp_session_id"],
            "code": code,
        },
        headers=auth_headers(access),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["new_email"] == new_email
    user = _me(access)
    assert user["email"] == new_email
    assert user["email_verified"] is True

    # Email lama mendapat notifikasi.
    email_gateway = email_service.get_gateway()
    assert isinstance(email_gateway, email_service.LoggingEmailGateway)
    assert any(
        recipient == old_email and "telah diubah" in text
        for recipient, _, text in email_gateway.messages
    )


def test_change_phone_requires_pin_token() -> None:
    data = register()
    response = client.post(
        "/v1/me/phone/change/request",
        json={"new_phone": "081298765432"},
        headers=auth_headers(data["tokens"]["access_token"]),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "PIN_TOKEN_INVALID"


def test_change_email_rejects_duplicate_and_same() -> None:
    first = register()
    second = register(phone="081298765432", device_id=DEVICE_A)
    access = first["tokens"]["access_token"]

    pin_token = _pin_token(access, "CHANGE_EMAIL")
    duplicate = client.post(
        "/v1/me/email/change/request",
        json={"new_email": second["user"]["email"]},
        headers=auth_headers(access, **{"X-Pin-Token": pin_token}),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMAIL_ALREADY_USED"

    pin_token = _pin_token(access, "CHANGE_EMAIL")
    same = client.post(
        "/v1/me/email/change/request",
        json={"new_email": first["user"]["email"]},
        headers=auth_headers(access, **{"X-Pin-Token": pin_token}),
    )
    assert same.status_code == 422
    assert same.json()["code"] == "EMAIL_SAME_AS_CURRENT"
