"""Primitif keamanan: hash, token, JWT, PIN, ECDSA."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import ExpiredSignatureError, InvalidAudienceError, InvalidTokenError

from app.config import settings
from app.core.clock import utcnow
from app.core.errors import AppError

_hasher = PasswordHasher()


def hash_secret(value: str) -> str:
    return _hasher.hash(value)


def verify_secret(hashed: str, value: str) -> bool:
    try:
        return _hasher.verify(hashed, value)
    except (VerifyMismatchError, VerificationError, InvalidHashError, Argon2Error):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def opaque_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def encode_jwt(payload: dict) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode(token: str, audience: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=audience,
        )
    except ExpiredSignatureError as exc:
        raise AppError("TOKEN_EXPIRED") from exc
    except InvalidAudienceError as exc:
        raise AppError("FORBIDDEN" if audience == "admin" else "UNAUTHORIZED") from exc
    except InvalidTokenError as exc:
        raise AppError("UNAUTHORIZED") from exc


def decode_user_access(token: str) -> dict:
    payload = _decode(token, "app")
    if payload.get("typ") != "access":
        raise AppError("UNAUTHORIZED")
    return payload


def decode_admin_access(token: str) -> dict:
    payload = _decode(token, "admin")
    if payload.get("typ") != "admin_access":
        raise AppError("FORBIDDEN")
    return payload


def decode_admin_challenge(token: str) -> dict:
    payload = _decode(token, "admin")
    if payload.get("typ") != "admin_2fa":
        raise AppError("ADMIN_2FA_REQUIRED")
    return payload


def access_token(user_id: str, device_id: str, session_id: str) -> str:
    now = utcnow()
    return encode_jwt(
        {
            "sub": user_id,
            "aud": "app",
            "typ": "access",
            "did": device_id,
            "sid": session_id,
            "jti": secrets.token_hex(8),
            "iat": now,
            "exp": now + timedelta(seconds=settings.ACCESS_TOKEN_TTL),
        }
    )


def admin_access_token(admin_id: str) -> str:
    now = utcnow()
    return encode_jwt(
        {
            "sub": admin_id,
            "aud": "admin",
            "typ": "admin_access",
            "iat": now,
            "exp": now + timedelta(seconds=settings.ACCESS_TOKEN_TTL),
        }
    )


def admin_challenge_token(admin_id: str) -> str:
    now = utcnow()
    return encode_jwt(
        {
            "sub": admin_id,
            "aud": "admin",
            "typ": "admin_2fa",
            "iat": now,
            "exp": now + timedelta(seconds=settings.ADMIN_2FA_TTL),
        }
    )


def mask_phone(phone: str) -> str:
    if len(phone) <= 8:
        return phone[:2] + "*" * max(0, len(phone) - 4) + phone[-2:]
    return f"{phone[:4]}****{phone[-4:]}"


def is_weak_pin(pin: str, phone: str | None = None) -> bool:
    if len(set(pin)) == 1:
        return True
    if pin in "01234567890123456789" or pin in "98765432109876543210":
        return True
    return bool(phone and len(phone) >= 6 and pin == phone[-6:])


def validate_ec_public_key(encoded: str) -> ec.EllipticCurvePublicKey:
    """Terima public key ECDSA P-256 base64 (DER SubjectPublicKeyInfo)."""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise AppError("INVALID_VALUE", message="Kunci publik tidak valid.") from exc

    key = None
    try:
        key = serialization.load_der_public_key(raw)
    except Exception:  # noqa: BLE001
        try:
            key = serialization.load_pem_public_key(raw)
        except Exception as exc:  # noqa: BLE001
            raise AppError("INVALID_VALUE", message="Kunci publik tidak valid.") from exc

    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise AppError("INVALID_VALUE", message="Kunci publik harus ECDSA P-256.")
    return key


def verify_ecdsa(public_key_b64: str, message: str, signature_b64: str) -> bool:
    try:
        key = validate_ec_public_key(public_key_b64)
        signature = base64.b64decode(signature_b64, validate=True)
        key.verify(signature, message.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
    except AppError:
        raise
    except Exception:  # noqa: BLE001
        return False


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("62"):
        digits = "0" + digits[2:]
    if not digits.startswith("08") or not (9 <= len(digits) <= 13):
        raise AppError("INVALID_PHONE")
    return digits
