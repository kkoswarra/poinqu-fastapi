"""Kustomisasi OpenAPI agar sesuai kontrak respons di ``docs/FASE-2-API.md``.

FastAPI hanya mendokumentasikan ``{}`` untuk endpoint yang mengembalikan
``dict`` dan ``HTTPValidationError`` untuk 422. Modul ini menambahkan:

- envelope sukses :class:`ApiResponse` dan gagal :class:`ErrorResponse`;
- respons error umum (401/403/404/409/410/413/415/422/423/429/500/503);
- parameter header yang dipakai middleware (``X-Device-Id``, ``X-Pin-Token``,
  ``X-Attestation``, dan versi app);
- security scheme Bearer, termasuk endpoint admin yang boleh memakai
  ``challenge_token`` tanpa Bearer.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.schemas import ApiResponse, ErrorItem, ErrorResponse, MetaOut

JSON = "application/json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

# Endpoint admin yang menerima challenge_token ATAU Bearer.
ADMIN_OPTIONAL_AUTH = {
    "/v1/admin/auth/password/change",
    "/v1/admin/auth/2fa/setup",
    "/v1/admin/auth/2fa/enable",
}

# Endpoint admin publik (belum punya sesi).
ADMIN_PUBLIC_AUTH = {
    "/v1/admin/auth/login",
    "/v1/admin/auth/2fa/verify",
    "/v1/admin/auth/token/refresh",
}

# Endpoint auth yang memakai verifikasi attestation.
ATTESTATION_PATHS = {
    "/v1/auth/login/start",
    "/v1/auth/login/pin",
    "/v1/auth/login/fingerprint",
    "/v1/auth/login/face",
    "/v1/auth/biometric/challenge",
    "/v1/auth/register",
    "/v1/auth/register/complete",
    "/v1/auth/otp/request",
    "/v1/auth/otp/resend",
}

# Endpoint yang mewajibkan X-Pin-Token.
PIN_TOKEN_PATHS = {
    "/v1/me/biometrics/fingerprint",
    "/v1/me/biometrics/face",
}

PROTECTED_AUTH_PATHS = {"/v1/auth/logout"}

HEADER_META: dict[str, tuple[str, str]] = {
    "X-Device-Id": (
        "ID perangkat dari app (format dev_<platform>_<hex>). Wajib untuk "
        "semua endpoint /v1 kecuali admin dan webhook.",
        "dev_and_91ab3c",
    ),
    "X-App-Version": (
        "Versi app; backend dapat menolak versi lama dengan UPGRADE_REQUIRED.",
        "1.0.0",
    ),
    "X-App-Template-Version": (
        "Versi template SDUI yang dipakai app.",
        "1",
    ),
    "X-Attestation-Provider": (
        "Penyedia attestation perangkat: PLAY_INTEGRITY atau APP_ATTEST.",
        "PLAY_INTEGRITY",
    ),
    "X-Attestation": (
        "Token Play Integrity atau assertion App Attest. Dipakai bila "
        "security.attestation_required aktif.",
        "att_valid_xxx",
    ),
    "X-Pin-Token": (
        "Token sekali pakai hasil POST /me/pin/verify dengan purpose "
        "ENROLL_BIOMETRIC.",
        "pt_77ac10d9e3",
    ),
    "Idempotency-Key": (
        "Wajib untuk POST yang mengubah uang (mulai Fase 3); belum dipakai "
        "di Fase 2.",
        "idem_01J9Z3K7QX",
    ),
}

ERROR_DESCRIPTIONS = {
    "401": "Tidak terautentikasi, token tidak valid/kedaluwarsa, atau sesi dicabut.",
    "403": "Tidak punya izin, perangkat tidak cocok, akun dibatasi, atau attestation gagal.",
    "404": "Data yang diminta tidak ditemukan.",
    "409": "Konflik state atau data sudah terdaftar.",
    "410": "Data atau sesi sudah kedaluwarsa.",
    "413": "Ukuran file terlalu besar.",
    "415": "Format file tidak didukung.",
    "422": "Validasi gagal atau permintaan tidak dapat diproses.",
    "423": "Akun, PIN, atau biometrik terkunci sementara.",
    "429": "Terlalu banyak permintaan; lihat header Retry-After.",
    "500": "Terjadi kesalahan pada server.",
    "503": "Layanan atau penyedia sedang tidak tersedia.",
}


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _add_model(components: dict[str, Any], name: str, model: type) -> None:
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = schema.pop("$defs", {})
    for definition_name, definition in definitions.items():
        components.setdefault(definition_name, definition)
    components[name] = schema


def _header(name: str, required: bool) -> dict[str, Any]:
    description, example = HEADER_META[name]
    return {
        "name": name,
        "in": "header",
        "required": required,
        "description": description,
        "schema": {"type": "string"},
        "example": example,
    }


def _add_parameters(operation: dict[str, Any], parameters: list[dict[str, Any]]) -> None:
    existing = operation.get("parameters")
    if not isinstance(existing, list):
        existing = []
        operation["parameters"] = existing
    keys = {(item.get("name"), item.get("in")) for item in existing if isinstance(item, dict)}
    for parameter in parameters:
        key = (parameter.get("name"), parameter.get("in"))
        if key not in keys:
            existing.append(parameter)
            keys.add(key)


def _success_response(operation: dict[str, Any]) -> None:
    responses = operation.setdefault("responses", {})
    for status in ("200", "201"):
        if status in responses:
            responses[status]["content"] = {JSON: {"schema": _ref("ApiResponse")}}
            responses[status].setdefault("description", "Respons sukses.")


def _error_statuses(path: str) -> set[str]:
    if path.startswith("/v1/webhooks"):
        return {"401", "422"}
    if path.startswith("/v1/admin"):
        return {"401", "403", "404", "409", "422", "429", "500"}
    if path.startswith("/v1/me"):
        statuses = {"401", "403", "404", "409", "422", "423", "429", "500"}
        if path.endswith("/avatar"):
            statuses |= {"413", "415"}
        return statuses
    if path.startswith("/v1/auth"):
        return {"401", "403", "404", "409", "410", "422", "423", "429", "500", "503"}
    return {"422", "500"}


def _error_response(status: str) -> dict[str, Any]:
    response: dict[str, Any] = {
        "description": ERROR_DESCRIPTIONS.get(status, "Respons gagal."),
        "content": {JSON: {"schema": _ref("ErrorResponse")}},
    }
    if status == "429":
        response["headers"] = {
            "Retry-After": {
                "description": "Waktu tunggu dalam detik sebelum mencoba lagi.",
                "schema": {"type": "integer", "minimum": 1},
            }
        }
    return response


def _apply_errors(operation: dict[str, Any], path: str) -> None:
    responses = operation.setdefault("responses", {})
    for status in _error_statuses(path):
        responses[status] = _error_response(status)


def _apply_headers(operation: dict[str, Any], path: str, method: str) -> None:
    if path.startswith("/v1/admin") or path.startswith("/v1/webhooks"):
        return

    parameters = [
        _header("X-Device-Id", True),
        _header("X-App-Version", False),
        _header("X-App-Template-Version", False),
    ]
    if path in ATTESTATION_PATHS:
        parameters.extend(
            [
                _header("X-Attestation-Provider", False),
                _header("X-Attestation", False),
            ]
        )
    if path in PIN_TOKEN_PATHS:
        parameters.append(_header("X-Pin-Token", True))
    if method == "post":
        parameters.append(_header("Idempotency-Key", False))

    _add_parameters(operation, parameters)


def _apply_security(operation: dict[str, Any], path: str) -> None:
    if path in ADMIN_OPTIONAL_AUTH:
        operation["security"] = [{}, {"HTTPBearer": []}]
        return
    if (
        path in ADMIN_PUBLIC_AUTH
        or path.startswith("/v1/webhooks")
        or (path.startswith("/v1/auth") and path not in PROTECTED_AUTH_PATHS)
    ):
        operation.pop("security", None)
        return
    operation["security"] = [{"HTTPBearer": []}]


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Buat skema OpenAPI lengkap (envelope, error, header, security)."""
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    _add_model(components, "MetaOut", MetaOut)
    _add_model(components, "ErrorItem", ErrorItem)
    _add_model(components, "ApiResponse", ApiResponse)
    _add_model(components, "ErrorResponse", ErrorResponse)

    schemes = schema["components"].setdefault("securitySchemes", {})
    bearer = schemes.setdefault("HTTPBearer", {"type": "http", "scheme": "bearer"})
    bearer.setdefault("bearerFormat", "JWT")

    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            if path.startswith("/v1"):
                _success_response(operation)
                _apply_errors(operation, path)
                _apply_headers(operation, path, method.lower())
                _apply_security(operation, path)

    # Skema bawaan FastAPI sudah diganti ErrorResponse di semua endpoint /v1.
    for legacy in ("HTTPValidationError", "ValidationError"):
        components.pop(legacy, None)

    return schema
