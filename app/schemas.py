"""Schema request dan model dokumentasi respons.

Respons aktual dibentuk eksplisit oleh serializer di lapisan service/router;
model ``ApiResponse``/``ErrorResponse`` dipakai untuk dokumentasi OpenAPI.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints, model_validator


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("62"):
        digits = "0" + digits[2:]
    if not digits.startswith("08") or not (9 <= len(digits) <= 13):
        raise ValueError("INVALID_PHONE")
    return digits


Phone = Annotated[str, AfterValidator(_normalize_phone)]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)]
Pin6 = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]
OtpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]
Gender = Literal["MALE", "FEMALE"]
Platform = Literal["IOS", "ANDROID", "WEB"]
BiometricKind = Literal["FINGERPRINT", "FACE"]
OtpPurposeIn = Literal["LOGIN", "REGISTER", "FORGOT_PIN", "CHANGE_PHONE"]


class DeviceInfo(BaseModel):
    device_id: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    platform: Platform
    os_version: Annotated[str | None, Field(default=None, max_length=32)] = None
    app_version: Annotated[str | None, Field(default=None, max_length=32)] = None
    push_token: str | None = None


# ------------------------------------------------------------------ auth


class OtpRequestIn(BaseModel):
    phone: Phone | None = None
    identifier: Annotated[str | None, Field(default=None, min_length=1, max_length=150)] = None
    purpose: OtpPurposeIn = "LOGIN"
    channel: Literal["WHATSAPP", "EMAIL"] | None = None

    @model_validator(mode="after")
    def check_identifier(self) -> OtpRequestIn:
        if not self.phone and not self.identifier:
            raise ValueError("REQUIRED")
        return self


class OtpVerifyIn(BaseModel):
    otp_session_id: Annotated[str, Field(min_length=1, max_length=64)]
    code: OtpCode


class OtpResendIn(BaseModel):
    otp_session_id: Annotated[str, Field(min_length=1, max_length=64)]


class LoginPinIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]
    pin: Pin6
    device: DeviceInfo


class LoginStartIn(BaseModel):
    phone: Phone | None = None
    identifier: Annotated[str | None, Field(default=None, min_length=1, max_length=150)] = None
    device_id: Annotated[str, Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def check_identifier(self) -> LoginStartIn:
        if not self.phone and not self.identifier:
            raise ValueError("REQUIRED")
        return self


class RegisterIn(BaseModel):
    name: PersonName
    phone: Phone
    email: EmailStr
    gender: Gender
    accept_terms: bool = False

    @model_validator(mode="after")
    def check_terms(self) -> RegisterIn:
        if not self.accept_terms:
            raise ValueError("TERMS_NOT_ACCEPTED")
        return self


class RegisterCompleteIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]
    pin: Pin6
    pin_confirmation: Pin6
    device: DeviceInfo


class BiometricChallengeIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]
    device_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    type: BiometricKind = "FINGERPRINT"


class BiometricLoginIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]
    challenge_id: Annotated[str, Field(min_length=1, max_length=64)]
    signature: Annotated[str, Field(min_length=1)]
    device: DeviceInfo


class TokenRefreshIn(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1)]
    device_id: Annotated[str, Field(min_length=1, max_length=64)]


class LogoutIn(BaseModel):
    all_devices: bool = False


class PinResetIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]
    new_pin: Pin6
    pin_confirmation: Pin6


# -------------------------------------------------------- phone recovery


class PhoneRecoveryStartIn(BaseModel):
    nik: Annotated[str, StringConstraints(pattern=r"^\d{16}$")]
    birth_date: date


class PhoneRecoveryFaceIn(BaseModel):
    liveness_session_id: Annotated[str, Field(min_length=1, max_length=64)]


class PhoneRecoveryPhoneIn(BaseModel):
    new_phone: Phone


class PhoneRecoveryCompleteIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]


class RecoverySupportStartIn(BaseModel):
    old_phone: Phone
    new_phone: Phone
    name: PersonName


class RecoverySupportSubmitIn(BaseModel):
    verification_token: Annotated[str, Field(min_length=1)]
    last_transaction_hint: Annotated[str | None, Field(default=None, max_length=200)] = None
    balance_hint: Annotated[int | None, Field(default=None, ge=0)] = None
    note: Annotated[str | None, Field(default=None, max_length=500)] = None


class RecoveryDecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


# --------------------------------------------------------------- profile


class ProfileUpdateIn(BaseModel):
    name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)] = None
    email: EmailStr | None = None
    gender: Gender | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> ProfileUpdateIn:
        if self.name is None and self.email is None and self.gender is None:
            raise ValueError("REQUIRED")
        return self


# ------------------------------------------------------------------- pin


class PinChangeIn(BaseModel):
    old_pin: Pin6
    new_pin: Pin6
    pin_confirmation: Pin6


class PinVerifyIn(BaseModel):
    pin: Pin6
    purpose: Literal[
        "TRANSACTION",
        "POINT_REDEEM",
        "ENROLL_BIOMETRIC",
        "CHANGE_PHONE",
        "CHANGE_EMAIL",
    ]
    preview_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    reward_id: Annotated[str | None, Field(default=None, max_length=64)] = None

    @model_validator(mode="after")
    def check_purpose_fields(self) -> PinVerifyIn:
        if self.purpose == "TRANSACTION" and not self.preview_id:
            raise ValueError("REQUIRED")
        if self.purpose == "POINT_REDEEM" and not self.reward_id:
            raise ValueError("REQUIRED")
        return self


class EmailVerificationVerifyIn(BaseModel):
    otp_session_id: Annotated[str, Field(min_length=1, max_length=64)]
    code: OtpCode


class PhoneChangeRequestIn(BaseModel):
    new_phone: Phone


class EmailChangeRequestIn(BaseModel):
    new_email: EmailStr


class ContactChangeConfirmIn(BaseModel):
    change_id: Annotated[str, Field(min_length=1, max_length=64)]
    otp_session_id: Annotated[str, Field(min_length=1, max_length=64)]
    code: OtpCode


# -------------------------------------------------------------- biometric


class BiometricRegisterIn(BaseModel):
    device_id: Annotated[str, Field(min_length=1, max_length=64)]
    public_key: Annotated[str, Field(min_length=1)]


class FaceRegisterIn(BiometricRegisterIn):
    liveness_session_id: Annotated[str, Field(min_length=1, max_length=64)]


class BiometricSettingsIn(BaseModel):
    use_for_login: bool


# ---------------------------------------------------------------- devices


class PushTokenIn(BaseModel):
    push_token: Annotated[str, Field(min_length=1)]
    platform: Literal["IOS", "ANDROID"]


# ------------------------------------------------------------------ admin


class AdminLoginIn(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1)]


class AdminTwoFactorIn(BaseModel):
    challenge_token: Annotated[str, Field(min_length=1)]
    code: OtpCode


class AdminRefreshIn(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1)]


class AdminPasswordChangeIn(BaseModel):
    challenge_token: Annotated[str | None, Field(default=None)] = None
    old_password: Annotated[str, Field(min_length=1)]
    new_password: Annotated[str, Field(min_length=1)]


class Admin2FASetupIn(BaseModel):
    challenge_token: Annotated[str | None, Field(default=None)] = None


class Admin2FAEnableIn(BaseModel):
    challenge_token: Annotated[str | None, Field(default=None)] = None
    code: OtpCode


class AdminCreateIn(BaseModel):
    email: EmailStr
    name: PersonName
    role_id: Annotated[str, Field(min_length=1, max_length=40)]


class AdminUpdateIn(BaseModel):
    role_id: Annotated[str | None, Field(default=None, max_length=40)] = None
    status: Literal["ACTIVE", "DISABLED"] | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> AdminUpdateIn:
        if self.role_id is None and self.status is None:
            raise ValueError("REQUIRED")
        return self


class SettingUpdateIn(BaseModel):
    value: Any
    version: int
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


# ------------------------------------------------- respons (dokumentasi OpenAPI)


class MetaOut(BaseModel):
    request_id: str = Field(description="ID request untuk korelasi log.")
    timestamp: str = Field(description="Waktu respons ISO 8601 UTC.")


class ApiResponse(BaseModel):
    """Envelope respons sukses (bagian 1.1 dokumen API)."""

    success: bool = Field(default=True, description="Selalu true untuk respons sukses.")
    code: str = Field(default="OK", description="Kode sukses; saat ini selalu OK.")
    message: str = Field(default="Berhasil.", description="Pesan yang aman ditampilkan ke pengguna.")
    data: Any = Field(default=None, description="Payload endpoint; null bila tidak ada.")
    meta: MetaOut


class ErrorItem(BaseModel):
    field: str = Field(description="Nama field yang gagal divalidasi.")
    code: str = Field(description="Kode error field, mis. REQUIRED atau INVALID_PHONE.")
    message: str = Field(description="Pesan error untuk field tersebut.")


class ErrorResponse(BaseModel):
    """Envelope respons gagal (bagian 1.2 dokumen API)."""

    success: bool = Field(default=False, description="Selalu false untuk respons gagal.")
    code: str = Field(
        description=(
            "Kode error, mis. VALIDATION_ERROR, PIN_INVALID, OTP_RATE_LIMITED, "
            "PIN_LOCKED, atau REFRESH_TOKEN_REVOKED."
        )
    )
    message: str = Field(description="Pesan error berbahasa Indonesia.")
    errors: list[ErrorItem] | None = Field(
        default=None, description="Rincian validasi; hanya ada pada error validasi."
    )
    details: Any = Field(default=None, description="Detail tambahan yang berbeda per kode.")
    meta: MetaOut
