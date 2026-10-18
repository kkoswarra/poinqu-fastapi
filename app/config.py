"""Konfigurasi aplikasi (environment variable)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Aplikasi
    APP_NAME: str = os.getenv("APP_NAME", "Poinqu API")
    APP_VERSION: str = os.getenv("APP_VERSION", "0.2.0")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = _env_bool("DEBUG", True)
    API_PREFIX: str = os.getenv("API_PREFIX", "/v1")
    MIN_APP_VERSION: str = os.getenv("MIN_APP_VERSION", "")
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8081,"
        "https://poinqu.id,https://www.poinqu.id",
    )

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./poinqu.db")
    AUTO_CREATE_TABLES: bool = _env_bool("AUTO_CREATE_TABLES", True)
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # Token
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_TTL: int = _env_int("ACCESS_TOKEN_TTL", 900)
    REFRESH_TOKEN_TTL: int = _env_int("REFRESH_TOKEN_TTL", 2_592_000)
    ADMIN_REFRESH_TOKEN_TTL: int = _env_int("ADMIN_REFRESH_TOKEN_TTL", 28_800)
    VERIFICATION_TOKEN_TTL: int = _env_int("VERIFICATION_TOKEN_TTL", 600)
    PIN_TOKEN_TTL: int = _env_int("PIN_TOKEN_TTL", 120)
    CHALLENGE_TTL: int = _env_int("CHALLENGE_TTL", 120)

    # OTP
    # Kosong = otomatis: FONNTE bila FONNTE_TOKEN diisi, selain itu LOG.
    OTP_PROVIDER: str = os.getenv("OTP_PROVIDER", "").strip().lower()
    OTP_TTL: int = _env_int("OTP_TTL", 300)
    OTP_MAX_ATTEMPTS: int = _env_int("OTP_MAX_ATTEMPTS", 5)
    OTP_RESEND_COOLDOWN: int = _env_int("OTP_RESEND_COOLDOWN", 30)
    OTP_MAX_RESENDS: int = _env_int("OTP_MAX_RESENDS", 3)
    OTP_HOURLY_LIMIT: int = _env_int("OTP_HOURLY_LIMIT", 5)
    OTP_MESSAGE_TEMPLATE: str = os.getenv(
        "OTP_MESSAGE_TEMPLATE",
        "{code} adalah kode verifikasi Poinqu kamu. Berlaku {minutes} menit.\n"
        "Jangan berikan kode ini ke siapa pun, termasuk yang mengaku dari Poinqu.",
    )
    # Hanya untuk development: mencetak kode OTP ke log. JANGAN aktifkan di produksi.
    OTP_DEV_ECHO: bool = _env_bool("OTP_DEV_ECHO", False)

    # Fonnte (WhatsApp gateway)
    FONNTE_TOKEN: str = os.getenv("FONNTE_TOKEN", "")
    FONNTE_BASE_URL: str = os.getenv("FONNTE_BASE_URL", "https://api.fonnte.com")
    FONNTE_TIMEOUT_SECONDS: int = _env_int("FONNTE_TIMEOUT_SECONDS", 8)
    FONNTE_WEBHOOK_SECRET: str = os.getenv("FONNTE_WEBHOOK_SECRET", "")
    FONNTE_ALLOWED_IPS: str = os.getenv("FONNTE_ALLOWED_IPS", "")

    # Email SMTP (OTP email & notifikasi)
    # Kosong = otomatis: SMTP bila SMTP_HOST diisi, selain itu gateway log.
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = _env_int("SMTP_PORT", 587)
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "no-reply@poinqu.id")
    SMTP_USE_TLS: bool = _env_bool("SMTP_USE_TLS", True)
    SMTP_USE_SSL: bool = _env_bool("SMTP_USE_SSL", False)
    SMTP_TIMEOUT_SECONDS: int = _env_int("SMTP_TIMEOUT_SECONDS", 10)
    EMAIL_OTP_SUBJECT: str = os.getenv("EMAIL_OTP_SUBJECT", "Kode verifikasi Poinqu")
    EMAIL_OTP_TEMPLATE: str = os.getenv(
        "EMAIL_OTP_TEMPLATE",
        "Kode verifikasi Poinqu kamu adalah {code}. Berlaku {minutes} menit.\n"
        "Jangan berikan kode ini ke siapa pun, termasuk yang mengaku dari Poinqu.",
    )

    # PIN
    PIN_MAX_FAILED: int = _env_int("PIN_MAX_FAILED", 5)
    PIN_LOCK_SECONDS: int = _env_int("PIN_LOCK_SECONDS", 900)
    BIOMETRIC_MAX_FAILED: int = _env_int("BIOMETRIC_MAX_FAILED", 5)
    BIOMETRIC_LOCK_SECONDS: int = _env_int("BIOMETRIC_LOCK_SECONDS", 900)

    # Avatar
    # Vercel hanya mengizinkan tulis di /tmp (ephemeral). Untuk produksi,
    # ganti ke object storage (Vercel Blob/S3).
    AVATAR_DIR: str = os.getenv(
        "AVATAR_DIR", "/tmp/avatars" if os.getenv("VERCEL") else "media/avatars"
    )
    AVATAR_MAX_BYTES: int = _env_int("AVATAR_MAX_BYTES", 5 * 1024 * 1024)
    MEDIA_BASE_URL: str = os.getenv("MEDIA_BASE_URL", "").rstrip("/")

    # Admin awal (dibuat saat startup bila belum ada)
    ADMIN_NAME: str = os.getenv("ADMIN_NAME", "Superadmin")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "owner@poinqu.id")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin-password-123")
    ADMIN_TOTP_SECRET: str = os.getenv("ADMIN_TOTP_SECRET", "")
    ADMIN_LOCK_SECONDS: int = _env_int("ADMIN_LOCK_SECONDS", 900)
    ADMIN_MAX_FAILED: int = _env_int("ADMIN_MAX_FAILED", 5)
    ADMIN_2FA_TTL: int = _env_int("ADMIN_2FA_TTL", 300)


settings = Settings()
