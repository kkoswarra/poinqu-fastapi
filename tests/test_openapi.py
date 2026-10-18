"""Kontrak dokumentasi OpenAPI (H.7.9)."""

from __future__ import annotations

from tests.conftest import client


def _operation(schema: dict, path: str, method: str) -> dict:
    return schema["paths"][path][method]


def test_openapi_documents_envelope_errors_and_headers() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    schema = response.json()

    schemas = schema["components"]["schemas"]
    assert {"ApiResponse", "ErrorResponse", "MetaOut", "ErrorItem"} <= set(schemas)
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas

    otp = _operation(schema, "/v1/auth/otp/request", "post")
    assert otp["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiResponse"
    }
    assert otp["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    header_names = {item["name"] for item in otp.get("parameters", [])}
    assert {"X-Device-Id", "X-App-Version", "X-App-Template-Version"} <= header_names
    assert "X-Attestation" in header_names
    assert "Idempotency-Key" in header_names
    assert "security" not in otp

    admin = _operation(schema, "/v1/admin/admins", "get")
    assert admin["security"] == [{"HTTPBearer": []}]
    assert admin["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiResponse"
    }
    assert "X-Device-Id" not in {item["name"] for item in admin.get("parameters", [])}

    optional = _operation(schema, "/v1/admin/auth/2fa/setup", "post")
    assert optional["security"] == [{}, {"HTTPBearer": []}]

    biometric = _operation(schema, "/v1/me/biometrics/fingerprint", "post")
    pin_header = next(
        item for item in biometric["parameters"] if item["name"] == "X-Pin-Token"
    )
    assert pin_header["required"] is True

    webhook = _operation(schema, "/v1/webhooks/fonnte/{secret}/status", "post")
    assert "security" not in webhook
    assert "X-Device-Id" not in {item["name"] for item in webhook.get("parameters", [])}

    retry = otp["responses"]["429"]
    assert retry["headers"]["Retry-After"]["schema"]["type"] == "integer"
