"""Model database (lihat docs/FASE-2-API.md bagian 3)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PyEnum
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db import Base


class UserLevel(StrEnum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    SUSPENDED = "SUSPENDED"


class KycStatus(StrEnum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OtpPurpose(StrEnum):
    LOGIN = "LOGIN"
    REGISTER = "REGISTER"
    FORGOT_PIN = "FORGOT_PIN"
    CHANGE_PHONE = "CHANGE_PHONE"
    CHANGE_EMAIL = "CHANGE_EMAIL"
    VERIFY_EMAIL = "VERIFY_EMAIL"
    STEPUP = "STEPUP"


class OtpTargetType(StrEnum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"


class Platform(StrEnum):
    IOS = "IOS"
    ANDROID = "ANDROID"
    WEB = "WEB"


class BiometricType(StrEnum):
    FINGERPRINT = "FINGERPRINT"
    FACE = "FACE"


class SecuritySeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


def _enum(enum_cls: type[PyEnum], length: int = 20) -> Enum:
    return Enum(enum_cls, native_enum=False, length=length, validate_strings=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    gender: Mapped[str | None] = mapped_column(String(6))
    avatar_key: Mapped[str | None] = mapped_column(Text)
    level: Mapped[UserLevel] = mapped_column(_enum(UserLevel), default=UserLevel.BASIC)
    kyc_status: Mapped[KycStatus] = mapped_column(_enum(KycStatus), default=KycStatus.NONE)
    status: Mapped[UserStatus] = mapped_column(_enum(UserStatus), default=UserStatus.ACTIVE)
    pin_hash: Mapped[str | None] = mapped_column(Text)
    pin_failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    biometric_login: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recovery_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transfer_blocked_until: Mapped[datetime | None] = mapped_column(DateTime)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)


Index("uq_users_email_lower", func.lower(User.email), unique=True)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_devices_user_device"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[Platform] = mapped_column(_enum(Platform, 10), nullable=False)
    os_version: Mapped[str | None] = mapped_column(String(32))
    app_version: Mapped[str | None] = mapped_column(String(32))
    push_token: Mapped[str | None] = mapped_column(Text)
    last_ip: Mapped[str | None] = mapped_column(String(64))
    last_location: Mapped[str | None] = mapped_column(String(100))
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    trusted_at: Mapped[datetime | None] = mapped_column(DateTime)
    attestation_provider: Mapped[str | None] = mapped_column(String(20))
    attested_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class OtpSession(Base):
    __tablename__ = "otp_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    target: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(10), default="PHONE", nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[OtpPurpose] = mapped_column(_enum(OtpPurpose, 16), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), default="WHATSAPP", nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resend_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_decoy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class WhatsAppMessage(Base):
    """Log metadata pengiriman OTP (isi pesan tidak disimpan)."""

    __tablename__ = "whatsapp_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    otp_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("otp_sessions.id"))
    phone: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(10), default="FONNTE", nullable=False)
    provider_msg_id: Mapped[str | None] = mapped_column(String(40), index=True)
    provider_state_id: Mapped[str | None] = mapped_column(String(64), index=True)
    request_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    provider_status: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class EmailMessage(Base):
    """Log metadata pengiriman OTP/notifikasi email (isi pesan tidak disimpan)."""

    __tablename__ = "email_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    otp_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("otp_sessions.id"))
    email: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), default="SMTP", nullable=False)
    provider_msg_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ContactChangeRequest(Base):
    """Permintaan ganti nomor HP/email dengan verifikasi OTP."""

    __tablename__ = "contact_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # PHONE | EMAIL
    new_value: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", nullable=False)
    otp_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("otp_sessions.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class VerificationToken(Base):
    __tablename__ = "verification_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    otp_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("otp_sessions.id"), nullable=False)
    purpose: Mapped[OtpPurpose] = mapped_column(_enum(OtpPurpose, 16), nullable=False)
    via: Mapped[str] = mapped_column(String(20), default="OTP", nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class UserBiometric(Base):
    __tablename__ = "user_biometrics"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", "type", name="uq_biometric_user_device_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    type: Mapped[BiometricType] = mapped_column(_enum(BiometricType, 12), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class BiometricChallenge(Base):
    __tablename__ = "biometric_challenges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    type: Mapped[BiometricType] = mapped_column(_enum(BiometricType, 12), nullable=False)
    challenge: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class PinToken(Base):
    __tablename__ = "pin_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    preview_id: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class PhoneRecovery(Base):
    __tablename__ = "phone_recoveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    attempts_left: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    liveness_session_id: Mapped[str | None] = mapped_column(String(64))
    face_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    new_phone: Mapped[str | None] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[SecuritySeverity] = mapped_column(
        _enum(SecuritySeverity, 8), default=SecuritySeverity.LOW
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id"))
    description: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class KycProfile(Base):
    """Data KYC minimal yang dibutuhkan pemulihan nomor (fase KYC mengisi ini)."""

    __tablename__ = "kyc_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    nik_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class AttemptCounter(Base):
    """Penghitung percobaan generik per (scope, key)."""

    __tablename__ = "attempt_counters"

    scope: Mapped[str] = mapped_column(String(30), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class PinAttempt(Base):
    """Kunci PIN per perangkat (H.7.6)."""

    __tablename__ = "pin_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lockout_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RecoveryRequest(Base):
    """Pengajuan pemulihan nomor untuk akun tanpa KYC (H.7.3)."""

    __tablename__ = "recovery_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    old_phone: Mapped[str] = mapped_column(String(16), nullable=False)
    new_phone: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_transaction_hint: Mapped[str | None] = mapped_column(String(200))
    balance_hint: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(14), default="PENDING_REVIEW", nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admins.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


# ---------------------------------------------------------------- admin


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id"), primary_key=True)


class Admin(TimestampMixin, Base):
    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    public_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_pending_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admins.id"), nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AdminPasswordHistory(Base):
    __tablename__ = "admin_password_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admins.id"), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(6), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | bool | int | str] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admins.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
