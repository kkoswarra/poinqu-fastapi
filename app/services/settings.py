"""Pengaturan aplikasi berversi di ``app_settings`` (H.7.8/H.7.10)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AppSetting


def _int_range(minimum: int, maximum: int) -> Callable[[Any], bool]:
    def check(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum

    return check


def _bool(value: Any) -> bool:
    return isinstance(value, bool)


SETTING_SPECS: dict[str, tuple[Any, str, Callable[[Any], bool], str]] = {
    "security.trusted_device_idle_days": (
        90,
        "Hari maksimal perangkat tepercaya tanpa aktivitas sebelum kepercayaan dicabut.",
        _int_range(1, 3650),
        "integer >= 1",
    ),
    "security.pin.max_attempts": (
        5,
        "Jumlah PIN salah per perangkat sebelum dikunci.",
        _int_range(1, 50),
        "integer >= 1",
    ),
    "security.pin.lock_minutes": (
        15,
        "Durasi kunci PIN pertama (menit); kunci berulang naik bertingkat.",
        _int_range(1, 1440),
        "integer >= 1",
    ),
    "security.pin.account_max_attempts_hour": (
        15,
        "Jumlah PIN salah per akun dalam satu jam sebelum akun dikunci.",
        _int_range(1, 100),
        "integer >= 1",
    ),
    "security.attestation_required": (
        False,
        "Wajibkan verifikasi Play Integrity/App Attest pada endpoint auth publik.",
        _bool,
        "boolean",
    ),
    "otp.rate.per_phone_hour": (
        5,
        "Batas permintaan OTP per nomor per jam.",
        _int_range(1, 1000),
        "integer >= 1",
    ),
    "otp.rate.per_device_hour": (
        10,
        "Batas permintaan OTP per perangkat per jam.",
        _int_range(1, 1000),
        "integer >= 1",
    ),
    "otp.rate.per_ip_hour": (
        20,
        "Batas permintaan OTP per IP per jam.",
        _int_range(1, 10000),
        "integer >= 1",
    ),
    "otp.provider_healthy": (
        True,
        "Status kesehatan gateway WhatsApp; diubah oleh webhook device Fonnte.",
        _bool,
        "boolean",
    ),
    "recovery.cooldown_hours": (
        24,
        "Lama transaksi keluar ditahan setelah pemulihan nomor disetujui (jam).",
        _int_range(0, 168),
        "integer >= 0",
    ),
    "limits.balance_cap.BASIC": (
        2_000_000,
        "Saldo maksimal akun Basic (rupiah).",
        _int_range(0, 1_000_000_000_000),
        "integer >= 0",
    ),
    "limits.balance_cap.PREMIUM": (
        20_000_000,
        "Saldo maksimal akun Premium (rupiah).",
        _int_range(0, 1_000_000_000_000),
        "integer >= 0",
    ),
    "limits.incoming_monthly.BASIC": (
        20_000_000,
        "Batas dana masuk bulanan akun Basic (rupiah).",
        _int_range(0, 1_000_000_000_000),
        "integer >= 0",
    ),
    "limits.incoming_monthly.PREMIUM": (
        40_000_000,
        "Batas dana masuk bulanan akun Premium (rupiah).",
        _int_range(0, 1_000_000_000_000),
        "integer >= 0",
    ),
}


def seed_defaults(db: Session) -> None:
    for key, (value, description, _, _) in SETTING_SPECS.items():
        setting = db.get(AppSetting, key)
        if setting is None:
            db.add(AppSetting(key=key, value=value, description=description))
        elif not setting.description:
            setting.description = description
    db.flush()


def get_value(db: Session, key: str, default: Any = None) -> Any:
    setting = db.get(AppSetting, key)
    if setting is None:
        default_spec = SETTING_SPECS.get(key)
        return default_spec[0] if default_spec else default
    return setting.value


def get_int(db: Session, key: str, default: int) -> int:
    value = get_value(db, key, default)
    return int(value)


def get_bool(db: Session, key: str, default: bool = False) -> bool:
    value = get_value(db, key, default)
    if isinstance(value, dict):
        value = value.get("healthy", value.get("value", default))
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def validate_value(key: str, value: Any) -> None:
    spec = SETTING_SPECS.get(key)
    if spec is None:
        if not isinstance(value, (bool, int, str, dict, list)):
            raise AppError("SETTING_VALUE_INVALID", details={"expected": "json value"})
        return
    expected = spec[3]
    if not spec[2](value):
        raise AppError("SETTING_VALUE_INVALID", details={"expected": expected})


def list_settings(db: Session, prefix: str | None = None) -> list[AppSetting]:
    statement = select(AppSetting)
    if prefix:
        statement = statement.where(AppSetting.key.startswith(prefix))
    return list(db.scalars(statement.order_by(AppSetting.key.asc())).all())


def known_keys() -> set[str]:
    return set(SETTING_SPECS)
