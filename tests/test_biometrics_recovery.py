"""Kontrak biometrik dan pemulihan nomor HP."""

from __future__ import annotations

import base64
from datetime import date

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.config import settings
from app.core.security import sha256
from app.db import SessionLocal
from app.models import KycProfile, KycStatus, User
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

NIK = "3171234567890001"
BIRTH_DATE = date(1995, 4, 17)


def _keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
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
    assert response.json()["data"]["face"]["registered"] is False

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


def test_face_enrollment_and_delete() -> None:
    data = register()
    access = data["tokens"]["access_token"]
    _, public_key = _keypair()

    response = client.post(
        "/v1/me/biometrics/face",
        json={
            "device_id": DEVICE_A,
            "public_key": public_key,
            "liveness_session_id": "lv_session_test",
        },
        headers=auth_headers(access, **{"X-Pin-Token": _pin_token(access)}),
    )
    assert response.status_code == 201, response.text

    response = client.delete("/v1/me/biometrics/FACE", headers=auth_headers(access))
    assert response.status_code == 200
    assert response.json()["data"] == {"type": "FACE", "use_for_login": False}

    response = client.delete("/v1/me/biometrics/FACE", headers=auth_headers(access))
    assert response.status_code == 404
    assert response.json()["code"] == "NO_BIOMETRIC_REGISTERED"


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


def _seed_kyc(phone: str = "081234567890", birth_date: date = BIRTH_DATE) -> User:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == phone))
        user.kyc_status = KycStatus.VERIFIED
        db.add(
            KycProfile(
                user_id=user.id,
                nik_hash=sha256(f"{settings.JWT_SECRET}:nik:{NIK}"),
                birth_date=birth_date,
            )
        )
        db.commit()
        db.refresh(user)
        return user


def test_phone_recovery_rejects_underage_kyc() -> None:
    register()
    minor_birth = date(date.today().year - 16, 1, 1)
    _seed_kyc(birth_date=minor_birth)

    response = client.post(
        "/v1/auth/phone-recovery",
        json={"nik": NIK, "birth_date": minor_birth.isoformat()},
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_DATE"


def test_phone_recovery_happy_path() -> None:
    register()
    _seed_kyc()

    response = client.post(
        "/v1/auth/phone-recovery",
        json={"nik": NIK, "birth_date": BIRTH_DATE.isoformat()},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    recovery_id = data["recovery_id"]
    assert data["liveness_session_id"].startswith("lv_")

    response = client.post(
        f"/v1/auth/phone-recovery/{recovery_id}/face",
        json={"liveness_session_id": data["liveness_session_id"]},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["face_verified"] is True

    response = client.post(
        f"/v1/auth/phone-recovery/{recovery_id}/phone",
        json={"new_phone": "081298765432"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["data"]["otp_session_id"]

    code = gateway.sent["081298765432"]
    response = otp_verify(session_id, code)
    assert response.status_code == 200, response.text
    token = response.json()["data"]["verification_token"]

    response = client.post(
        f"/v1/auth/phone-recovery/{recovery_id}/complete",
        json={"verification_token": token},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["new_phone"] == "081298765432"

    response = client.post(
        "/v1/auth/otp/request",
        json={"phone": "081234567890", "purpose": "LOGIN"},
        headers=headers(),
    )
    assert response.status_code == 200
    decoy = response.json()["data"]["otp_session_id"]
    response = otp_verify(decoy, "123456")
    assert response.status_code == 422
    assert response.json()["code"] == "OTP_INVALID"


def test_phone_recovery_rejects_wrong_nik_with_attempt_limit() -> None:
    register()
    _seed_kyc()

    for expected_left in (2, 1):
        response = client.post(
            "/v1/auth/phone-recovery",
            json={"nik": "3171234567890002", "birth_date": BIRTH_DATE.isoformat()},
            headers=headers(),
        )
        assert response.status_code == 404
        assert response.json()["code"] == "KYC_NOT_FOUND"
        assert response.json()["details"]["attempts_left"] == expected_left

    response = client.post(
        "/v1/auth/phone-recovery",
        json={"nik": "3171234567890002", "birth_date": BIRTH_DATE.isoformat()},
        headers=headers(),
    )
    assert response.status_code == 429
    assert response.json()["code"] == "RECOVERY_ATTEMPTS_EXCEEDED"


def test_recovery_requires_face_before_phone_step() -> None:
    register()
    _seed_kyc()
    response = client.post(
        "/v1/auth/phone-recovery",
        json={"nik": NIK, "birth_date": BIRTH_DATE.isoformat()},
        headers=headers(),
    )
    recovery_id = response.json()["data"]["recovery_id"]

    response = client.post(
        f"/v1/auth/phone-recovery/{recovery_id}/phone",
        json={"new_phone": "081298765432"},
        headers=headers(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "RECOVERY_STEP_INVALID"


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
