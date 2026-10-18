"""Kontrak error dan envelope respons.

Semua respons sukses berbentuk::

    {"success": true, "code": "OK", "message": "...", "data": ..., "meta": {...}}

Semua respons gagal berbentuk::

    {"success": false, "code": "...", "message": "...", "errors": [...],
     "details": ..., "meta": {...}}
"""

from __future__ import annotations

import logging
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.clock import now_iso

logger = logging.getLogger("poinqu")

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


@dataclass(frozen=True)
class ErrorDef:
    status: int
    message: str


ERRORS: dict[str, ErrorDef] = {
    # --- umum ---
    "VALIDATION_ERROR": ErrorDef(422, "Data yang dikirim tidak valid."),
    "INTERNAL_ERROR": ErrorDef(500, "Terjadi kesalahan pada server."),
    "NOT_FOUND": ErrorDef(404, "Data tidak ditemukan."),
    "UNAUTHORIZED": ErrorDef(401, "Sesi tidak valid. Silakan login kembali."),
    "TOKEN_EXPIRED": ErrorDef(401, "Access token kedaluwarsa."),
    "FORBIDDEN": ErrorDef(403, "Tidak punya izin untuk aksi ini."),
    "RATE_LIMITED": ErrorDef(429, "Terlalu banyak permintaan. Coba lagi nanti."),
    "SERVICE_UNAVAILABLE": ErrorDef(503, "Layanan sedang pemeliharaan."),
    "UPGRADE_REQUIRED": ErrorDef(426, "Versi aplikasi terlalu lama. Perbarui aplikasi."),
    "INVALID_FORMAT": ErrorDef(422, "Format tidak valid."),
    "INVALID_VALUE": ErrorDef(422, "Nilai tidak valid."),
    "INVALID_PHONE": ErrorDef(422, "Nomor HP tidak valid."),
    "INVALID_EMAIL": ErrorDef(422, "Format email tidak valid."),
    "INVALID_DATE": ErrorDef(422, "Format tanggal tidak valid."),
    "INVALID_CURSOR": ErrorDef(422, "Cursor tidak valid."),
    "INVALID_CATEGORY": ErrorDef(422, "Kategori tidak valid."),
    "INVALID_TYPE": ErrorDef(422, "Tipe tidak valid."),
    "INVALID_LENGTH": ErrorDef(422, "Panjang tidak valid."),
    "REQUIRED": ErrorDef(422, "Wajib diisi."),
    "TOO_SHORT": ErrorDef(422, "Terlalu pendek."),
    "TOO_LONG": ErrorDef(422, "Terlalu panjang."),
    "OUT_OF_RANGE": ErrorDef(422, "Nilai di luar rentang."),
    # --- auth ---
    "OTP_INVALID": ErrorDef(422, "Kode OTP salah."),
    "OTP_EXPIRED": ErrorDef(410, "Kode OTP sudah kedaluwarsa. Minta kode baru."),
    "OTP_SESSION_NOT_FOUND": ErrorDef(404, "Sesi OTP tidak ditemukan. Minta kode baru."),
    "OTP_ATTEMPTS_EXCEEDED": ErrorDef(429, "Terlalu banyak percobaan. Minta kode baru."),
    "OTP_RATE_LIMITED": ErrorDef(429, "Terlalu banyak permintaan OTP. Coba lagi nanti."),
    "OTP_RESEND_TOO_SOON": ErrorDef(429, "Tunggu sebentar sebelum minta kode lagi."),
    "OTP_RESEND_LIMIT": ErrorDef(429, "Batas kirim ulang OTP tercapai."),
    "OTP_PROVIDER_UNAVAILABLE": ErrorDef(503, "Layanan pengiriman OTP sedang gangguan."),
    "OTP_TARGET_NOT_WHATSAPP": ErrorDef(422, "Nomor ini tidak terdaftar di WhatsApp."),
    "PHONE_ALREADY_REGISTERED": ErrorDef(409, "Nomor HP sudah terdaftar."),
    "PHONE_NOT_REGISTERED": ErrorDef(404, "Nomor HP belum terdaftar."),
    "PHONE_SAME_AS_CURRENT": ErrorDef(422, "Nomor baru sama dengan nomor lama."),
    "PIN_INVALID": ErrorDef(401, "PIN salah."),
    "PIN_LOCKED": ErrorDef(423, "PIN terkunci karena terlalu banyak percobaan."),
    "PIN_TOO_WEAK": ErrorDef(422, "PIN terlalu mudah ditebak."),
    "PIN_MISMATCH": ErrorDef(422, "PIN dan konfirmasi PIN tidak sama."),
    "PIN_SAME_AS_OLD": ErrorDef(422, "PIN baru tidak boleh sama dengan PIN lama."),
    "PIN_NOT_SET": ErrorDef(409, "PIN belum dibuat."),
    "PIN_TOKEN_INVALID": ErrorDef(401, "Verifikasi PIN diperlukan atau sudah kedaluwarsa."),
    "PIN_TOKEN_EXPIRED": ErrorDef(401, "Verifikasi PIN kedaluwarsa."),
    "PIN_TOKEN_MISMATCH": ErrorDef(403, "Verifikasi PIN tidak cocok dengan transaksi ini."),
    "VERIFICATION_TOKEN_INVALID": ErrorDef(401, "Sesi verifikasi tidak valid."),
    "VERIFICATION_TOKEN_EXPIRED": ErrorDef(401, "Sesi verifikasi sudah kedaluwarsa."),
    "VERIFICATION_PURPOSE_MISMATCH": ErrorDef(403, "Token verifikasi tidak untuk keperluan ini."),
    "ACCOUNT_LOCKED": ErrorDef(423, "Akun dikunci sementara."),
    "ACCOUNT_SUSPENDED": ErrorDef(403, "Akun dibekukan. Hubungi bantuan."),
    "ACCOUNT_RESTRICTED": ErrorDef(403, "Akun dibatasi. Hubungi bantuan."),
    "REFRESH_TOKEN_INVALID": ErrorDef(401, "Sesi tidak valid. Silakan login kembali."),
    "REFRESH_TOKEN_REVOKED": ErrorDef(401, "Sesi dihentikan. Silakan login kembali."),
    "DEVICE_MISMATCH": ErrorDef(403, "Perangkat tidak cocok dengan sesi."),
    "TERMS_NOT_ACCEPTED": ErrorDef(422, "Syarat dan ketentuan harus disetujui."),
    "RECOVERY_NOT_FOUND": ErrorDef(404, "Sesi pemulihan tidak ditemukan."),
    "RECOVERY_EXPIRED": ErrorDef(410, "Sesi pemulihan berakhir. Mulai lagi."),
    "RECOVERY_ATTEMPTS_EXCEEDED": ErrorDef(429, "Percobaan pemulihan habis. Hubungi bantuan."),
    "RECOVERY_STEP_INVALID": ErrorDef(409, "Langkah pemulihan belum bisa dilakukan."),
    "LIVENESS_SESSION_INVALID": ErrorDef(422, "Sesi verifikasi wajah tidak valid atau kedaluwarsa."),
    # --- biometrik ---
    "FACE_NOT_MATCH": ErrorDef(401, "Wajah tidak cocok."),
    "FACE_NOT_ENROLLED": ErrorDef(404, "Wajah belum didaftarkan."),
    "FACE_LOCKED": ErrorDef(423, "Scan wajah dinonaktifkan sementara."),
    "FACE_LIVENESS_FAILED": ErrorDef(422, "Verifikasi wajah gagal. Ikuti instruksi."),
    "FACE_QUALITY_LOW": ErrorDef(422, "Kualitas gambar kurang baik."),
    "FACE_KTP_MISMATCH": ErrorDef(422, "Wajah tidak cocok dengan foto KTP."),
    "BIOMETRIC_NOT_REGISTERED": ErrorDef(404, "Biometrik belum didaftarkan."),
    "BIOMETRIC_LOCKED": ErrorDef(423, "Biometrik dinonaktifkan sementara."),
    "BIOMETRIC_SIGNATURE_INVALID": ErrorDef(401, "Biometrik tidak dikenali."),
    "BIOMETRIC_ALREADY_REGISTERED": ErrorDef(409, "Biometrik sudah terdaftar."),
    "CHALLENGE_EXPIRED": ErrorDef(410, "Sesi biometrik berakhir."),
    "INVALID_BIOMETRIC_TYPE": ErrorDef(422, "Tipe biometrik tidak valid."),
    "NO_BIOMETRIC_REGISTERED": ErrorDef(404, "Daftarkan biometrik terlebih dahulu."),
    # --- dompet (dipakai fase berikutnya) ---
    "INSUFFICIENT_BALANCE": ErrorDef(422, "Saldo tidak cukup."),
    "BALANCE_LIMIT_EXCEEDED": ErrorDef(422, "Saldo melebihi batas maksimal akun."),
    "MONTHLY_INCOMING_LIMIT_EXCEEDED": ErrorDef(422, "Batas dana masuk bulan ini tercapai."),
    "TRANSFER_LIMIT_EXCEEDED": ErrorDef(422, "Nominal melebihi batas maksimal transfer."),
    "PREMIUM_REQUIRED": ErrorDef(403, "Fitur ini hanya untuk akun Premium."),
    "AMOUNT_TOO_LOW": ErrorDef(422, "Nominal terlalu kecil."),
    "AMOUNT_TOO_HIGH": ErrorDef(422, "Nominal terlalu besar."),
    "AMOUNT_OUT_OF_RANGE": ErrorDef(422, "Nominal di luar batas."),
    # --- KYC ---
    "KYC_ALREADY_VERIFIED": ErrorDef(409, "Akun sudah Premium."),
    "KYC_PENDING": ErrorDef(409, "Pengajuan sebelumnya masih diproses."),
    "KYC_NOT_FOUND": ErrorDef(404, "Data pengajuan tidak ditemukan."),
    "KYC_NOT_DRAFT": ErrorDef(422, "Pengajuan sudah dikirim sebelumnya."),
    "KYC_DRAFT_EXPIRED": ErrorDef(410, "Sesi pengisian data berakhir."),
    "NIK_ALREADY_USED": ErrorDef(409, "NIK sudah terdaftar pada akun lain."),
    "KTP_IMAGE_UNREADABLE": ErrorDef(422, "Foto KTP tidak terbaca."),
    "KTP_DATA_MISMATCH": ErrorDef(422, "NIK atau nama tidak sesuai dengan foto KTP."),
    "NAME_LOCKED": ErrorDef(409, "Nama tidak bisa diubah setelah KTP terverifikasi."),
    "EMAIL_ALREADY_USED": ErrorDef(409, "Email sudah dipakai akun lain."),
    "EMAIL_ALREADY_VERIFIED": ErrorDef(409, "Email sudah terverifikasi."),
    "EMAIL_NOT_SET": ErrorDef(409, "Email belum diatur."),
    "EMAIL_SAME_AS_CURRENT": ErrorDef(422, "Email baru sama dengan email lama."),
    "CONTACT_CHANGE_NOT_FOUND": ErrorDef(404, "Permintaan perubahan kontak tidak ditemukan."),
    "CONTACT_CHANGE_EXPIRED": ErrorDef(410, "Permintaan perubahan kontak sudah kedaluwarsa."),
    "CONTACT_CHANGE_ALREADY_USED": ErrorDef(409, "Permintaan perubahan kontak sudah dipakai."),
    # --- perangkat ---
    "DEVICE_NOT_FOUND": ErrorDef(404, "Perangkat tidak ditemukan."),
    "CANNOT_REMOVE_CURRENT_DEVICE": ErrorDef(409, "Perangkat yang sedang dipakai tidak bisa dikeluarkan."),
    "NO_OTHER_DEVICES": ErrorDef(404, "Tidak ada perangkat lain."),
    "AVATAR_NOT_FOUND": ErrorDef(404, "Foto profil belum ada."),
    "FILE_TOO_LARGE": ErrorDef(413, "Ukuran file terlalu besar."),
    "UNSUPPORTED_MEDIA_TYPE": ErrorDef(415, "Format file tidak didukung."),
    # --- admin ---
    "ADMIN_CREDENTIALS_INVALID": ErrorDef(422, "Email atau password admin salah."),
    "ADMIN_2FA_REQUIRED": ErrorDef(422, "Kode 2FA diperlukan."),
    "ADMIN_2FA_INVALID": ErrorDef(422, "Kode 2FA salah."),
    "ADMIN_LOCKED": ErrorDef(422, "Akun admin dikunci sementara."),
    "ADMIN_PASSWORD_WEAK": ErrorDef(422, "Password admin terlalu lemah."),
    "ADMIN_PASSWORD_CHANGE_REQUIRED": ErrorDef(422, "Ganti password terlebih dahulu."),
    "ADMIN_EMAIL_ALREADY_USED": ErrorDef(409, "Email admin sudah dipakai."),
    "ADMIN_NOT_FOUND": ErrorDef(404, "Admin tidak ditemukan."),
    "ROLE_NOT_FOUND": ErrorDef(404, "Peran tidak ditemukan."),
    "CANNOT_MODIFY_SELF": ErrorDef(422, "Tidak bisa mengubah akun admin sendiri."),
    "LAST_SUPERADMIN": ErrorDef(422, "Harus ada minimal satu superadmin aktif."),
    "DEVICE_ATTESTATION_FAILED": ErrorDef(403, "Perangkat gagal diverifikasi keamanannya."),
    "RECOVERY_REQUEST_NOT_FOUND": ErrorDef(404, "Pengajuan pemulihan tidak ditemukan."),
    "RECOVERY_REQUEST_ALREADY_DECIDED": ErrorDef(409, "Pengajuan sudah diputuskan."),
    "SETTING_NOT_FOUND": ErrorDef(404, "Pengaturan tidak ditemukan."),
    "SETTING_VERSION_CONFLICT": ErrorDef(422, "Pengaturan sudah diubah orang lain. Muat ulang."),
    "SETTING_VALUE_INVALID": ErrorDef(422, "Nilai pengaturan tidak valid."),
}


class AppError(Exception):
    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        details: Any = None,
        errors: list[dict[str, Any]] | None = None,
        status: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        if code not in ERRORS:
            raise ValueError(f"Kode error tidak dikenal: {code}")
        self.code = code
        self.defn = ERRORS[code]
        self.message = message or self.defn.message
        self.details = details
        self.errors = errors
        self.status = status or self.defn.status
        self.retry_after = retry_after
        super().__init__(self.message)


def new_request_id() -> str:
    return "req_" + secrets.token_hex(5)


def meta() -> dict[str, str]:
    return {"request_id": request_id_ctx.get() or new_request_id(), "timestamp": now_iso()}


def ok(data: Any = None, message: str = "Berhasil.") -> dict[str, Any]:
    return {"success": True, "code": "OK", "message": message, "data": data, "meta": meta()}


def error_body(
    code: str,
    *,
    message: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    details: Any = None,
) -> dict[str, Any]:
    defn = ERRORS.get(code, ERRORS["INTERNAL_ERROR"])
    body: dict[str, Any] = {
        "success": False,
        "code": code if code in ERRORS else "INTERNAL_ERROR",
        "message": message or defn.message,
    }
    if errors:
        body["errors"] = errors
    body["details"] = details
    body["meta"] = meta()
    return body


def error_response(
    code: str,
    *,
    message: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    details: Any = None,
    status: int | None = None,
    retry_after: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = error_body(code, message=message, errors=errors, details=details)
    defn = ERRORS.get(code, ERRORS["INTERNAL_ERROR"])
    response_headers = dict(headers or {})
    if retry_after is not None:
        response_headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=status or defn.status,
        content=jsonable_encoder(body),
        headers=response_headers,
    )


_VALIDATION_TYPE_CODES = {
    "missing": "REQUIRED",
    "string_too_short": "TOO_SHORT",
    "string_too_long": "TOO_LONG",
    "string_pattern_mismatch": "INVALID_FORMAT",
    "greater_than": "OUT_OF_RANGE",
    "greater_than_equal": "OUT_OF_RANGE",
    "less_than": "OUT_OF_RANGE",
    "less_than_equal": "OUT_OF_RANGE",
    "int_parsing": "INVALID_FORMAT",
    "float_parsing": "INVALID_FORMAT",
    "bool_parsing": "INVALID_FORMAT",
    "date_from_datetime_parsing": "INVALID_DATE",
    "date_parsing": "INVALID_DATE",
    "datetime_parsing": "INVALID_DATE",
    "string_type": "INVALID_FORMAT",
    "literal_error": "INVALID_VALUE",
    "enum": "INVALID_VALUE",
    "value_error": "INVALID_VALUE",
}

_FIELD_CODES = {
    "phone": "INVALID_PHONE",
    "new_phone": "INVALID_PHONE",
    "old_phone": "INVALID_PHONE",
    "email": "INVALID_EMAIL",
    "birth_date": "INVALID_DATE",
    "cursor": "INVALID_CURSOR",
    "date_from": "INVALID_DATE",
    "date_to": "INVALID_DATE",
    "q": "INVALID_LENGTH",
}

_KNOWN_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\b")


def _validation_code(exc: dict[str, Any], field: str) -> str:
    message = str(exc.get("msg", ""))
    for candidate in _KNOWN_CODE_RE.findall(message):
        if candidate in ERRORS:
            return candidate
    code = _VALIDATION_TYPE_CODES.get(str(exc.get("type")))
    if field in _FIELD_CODES and (code is None or code in _GENERIC_VALIDATION_CODES):
        return _FIELD_CODES[field]
    return code or "INVALID_FORMAT"


def _validation_field(loc: tuple[Any, ...]) -> str:
    parts = [str(item) for item in loc if item not in ("body", "query", "path", "header")]
    return ".".join(parts) or "body"


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return error_response(
        exc.code,
        message=exc.message,
        errors=exc.errors,
        details=exc.details,
        status=exc.status,
        retry_after=exc.retry_after,
    )


_GENERIC_VALIDATION_CODES = {
    "REQUIRED",
    "TOO_SHORT",
    "TOO_LONG",
    "OUT_OF_RANGE",
    "INVALID_FORMAT",
    "INVALID_VALUE",
    "INVALID_PHONE",
    "INVALID_EMAIL",
    "INVALID_DATE",
    "INVALID_CURSOR",
    "INVALID_LENGTH",
    "INVALID_TYPE",
    "INVALID_CATEGORY",
}


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    raw_errors = exc.errors()
    errors: list[dict[str, Any]] = []
    for item in raw_errors:
        field = _validation_field(tuple(item.get("loc", ())))
        code = _validation_code(item, field)
        errors.append(
            {
                "field": field,
                "code": code,
                "message": ERRORS[code].message,
            }
        )

    # Error tingkat model (mis. TERMS_NOT_ACCEPTED) dipromosikan menjadi kode utama
    # agar sesuai kontrak endpoint; error per-field tetap VALIDATION_ERROR.
    if len(raw_errors) == 1 and tuple(raw_errors[0].get("loc", ())) == ("body",):
        code = errors[0]["code"]
        if code not in _GENERIC_VALIDATION_CODES:
            return error_response(code, errors=errors)

    return error_response("VALIDATION_ERROR", errors=errors)


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response("NOT_FOUND", status=404)
    if exc.status_code == 401:
        return error_response("UNAUTHORIZED", status=401)
    if exc.status_code == 403:
        return error_response("FORBIDDEN", status=403)
    if exc.status_code == 429:
        return error_response("RATE_LIMITED", status=429)
    if exc.status_code >= 500:
        return error_response("INTERNAL_ERROR", status=500)
    return error_response(
        "INVALID_VALUE",
        message=str(exc.detail),
        status=exc.status_code,
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return error_response("INTERNAL_ERROR", status=500)
