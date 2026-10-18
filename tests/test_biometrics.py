"""Kontrak biometrik sidik jari dan PIN reset."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tests.conftest import (
    DEVICE_A,
    DEVICE_B,
    auth_headers,
    client,
    device_info,
    gateway,
    headers,
    login_verification,
    otp_verify,
    register,
)


def _keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()
    return key, public


def _sign(key, challenge: str) -> str:
    signature = key.sign(challenge.encode(), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode()


def _pin_token(access: str) -> str:
    response = client.post(
        "/v1/me/pin/verify",
        json={"pin": "246810", "purpose": "ENROLL_BIOMETRIC"},
        headers=auth_headers(access),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["pin_token"]


def _challenge(token: str, device_id: str | None = None) -> dict:
    payload = {"verification_token": token, "type": "FINGERPRINT"}
    if device_id is not None:
        payload["device_id"] = device_id
    response = client.post(
        "/v1/auth/biometric/challenge",
        json=payload,
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_biometric_challenge_uses_header_when_device_id_omitted() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    _, public_key = _keypair()

    response = client.post(
        "/v1/me/biometrics/fingerprint",
        json={"device_id": DEVICE_A, "public_key": public_key},
        headers=auth_headers(access, **{"X-Pin-Token": _pin_token(access)}),
    )
    assert response.status_code == 201, response.text

    token = login_verification("081234567890")

    response = client.post(
        "/v1/auth/biometric/challenge",
        json={"verification_token": token, "device_id": DEVICE_B, "type": "FINGERPRINT"},
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "DEVICE_MISMATCH"

    response = client.post(
        "/v1/auth/biometric/challenge",
        json={"verification_token": token, "type": "FINGERPRINT"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["challenge_id"].startswith("chl_")


def test_biometric_enrollment_and_login() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    key, public_key = _keypair()

    response = client.post(
        "/v1/me/biometrics/fingerprint",
        json={"device_id": DEVICE_A, "public_key": public_key},
        headers=auth_headers(access, **{"X-Pin-Token": _pin_token(access)}),
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["type"] == "FINGERPRINT"

    response = client.get("/v1/me/biometrics", headers=auth_headers(access))
    assert response.status_code == 200
    assert response.json()["data"]["fingerprint"]["registered"] is True
    assert "face" not in response.json()["data"]

    token = login_verification("081234567890")
    challenge = _challenge(token)
    signature = _sign(key, challenge["challenge"])

    response = client.post(
        "/v1/auth/login/fingerprint",
        json={
            "verification_token": token,
            "challenge_id": challenge["challenge_id"],
            "signature": signature,
            "device": device_info(),
        },
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["tokens"]["access_token"]


def test_biometric_wrong_signature_then_success_and_reuse() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    key, public_key = _keypair()
    response = client.post(
        "/v1/me/biometrics/fingerprint",
        json={"device_id": DEVICE_A, "public_key": public_key},
        headers=auth_headers(access, **{"X-Pin-Token": _pin_token(access)}),
    )
    assert response.status_code == 201, response.text

    token = login_verification("081234567890")
    challenge = _challenge(token)
    payload = {
        "verification_token": token,
        "challenge_id": challenge["challenge_id"],
        "signature": base64.b64encode(b"palsu").decode(),
        "device": device_info(),
    }
    response = client.post("/v1/auth/login/fingerprint", json=payload, headers=headers())
    assert response.status_code == 401
    assert response.json()["code"] == "BIOMETRIC_SIGNATURE_INVALID"

    payload["signature"] = _sign(key, challenge["challenge"])
    response = client.post("/v1/auth/login/fingerprint", json=payload, headers=headers())
    assert response.status_code == 200, response.text

    token2 = login_verification("081234567890")
    payload["verification_token"] = token2
    response = client.post("/v1/auth/login/fingerprint", json=payload, headers=headers())
    assert response.status_code == 410
    assert response.json()["code"] == "CHALLENGE_EXPIRED"


def test_biometric_requires_pin_token_and_rejects_duplicate() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    _, public_key = _keypair()

    response = client.post(
        "/v1/me/biometrics/fingerprint",
        json={"device_id": DEVICE_A, "public_key": public_key},
        headers=auth_headers(access),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "PIN_TOKEN_INVALID"

    response = client.post(
        "/v1/me/biometrics/fingerprint",
        json={"device_id": DEVICE_A, "public_key": public_key},
        headers=auth_headers(access, **{"X-Pin-Token": _pin_token(access)}),
    )
    assert response.status_code == 201

    response = client.post(
        "/v1/me/biometrics/fingerprint",
        json={"device_id": DEVICE_A, "public_key": public_key},
        headers=auth_headers(access, **{"X-Pin-Token": _pin_token(access)}),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "BIOMETRIC_ALREADY_REGISTERED"


def test_biometric_settings_require_enrollment() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    response = client.patch(
        "/v1/me/biometrics/settings",
        json={"use_for_login": True},
        headers=auth_headers(access),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NO_BIOMETRIC_REGISTERED"


def test_pin_reset_via_otp() -> None:
    register()
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
    assert response.status_code == 200, response.text
    assert response.json()["data"]["sessions_revoked"] is True

    response = client.post(
        "/v1/auth/otp/request",
        json={"phone": "081234567890", "purpose": "LOGIN"},
        headers=headers(),
    )
    session_id = response.json()["data"]["otp_session_id"]
    token = otp_verify(session_id, gateway.sent["081234567890"]).json()["data"][
        "verification_token"
    ]
    response = client.post(
        "/v1/auth/login/pin",
        json={"verification_token": token, "pin": "135790", "device": device_info()},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
