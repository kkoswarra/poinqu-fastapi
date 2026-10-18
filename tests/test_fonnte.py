"""Integrasi Fonnte: adapter, log pengiriman, webhook, dan higiene log."""

from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from app.core.clock import utcnow
from app.db import SessionLocal
from app.models import AppSetting, AuditLog, OtpSession, WhatsAppMessage
from app.services import wa
from tests.conftest import client, gateway, headers, otp_request

WEBHOOK_SECRET = "test-webhook-secret-32-characters-min"


class FakeFonnte:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responder = lambda _: httpx.Response(
            200,
            json={
                "detail": "success! message in queue",
                "id": ["80367170"],
                "process": "pending",
                "requestid": 2937124,
                "status": True,
                "target": ["6281234567890"],
            },
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)

    @property
    def last_request(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def fonnte():
    previous = wa.get_gateway()
    fake = FakeFonnte()
    wa.set_gateway(
        wa.FonnteGateway(
            token="test-token",
            base_url="https://api.fonnte.test",
            timeout=2,
            transport=httpx.MockTransport(fake.handle),
        )
    )
    yield fake
    wa.set_gateway(previous)


def _latest_message() -> WhatsAppMessage:
    with SessionLocal() as db:
        return db.scalars(
            select(WhatsAppMessage).order_by(WhatsAppMessage.created_at.desc())
        ).first()


def _webhook(path: str, payload: dict):
    return client.post(f"/v1/webhooks/fonnte/{path}", json=payload)


def test_fonnte_success_stores_metadata_and_uses_expected_payload(fonnte: FakeFonnte) -> None:
    response = otp_request("081234567890")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["otp_session_id"].startswith("otp_")

    message = _latest_message()
    assert message.provider == "FONNTE"
    assert message.provider_msg_id == "80367170"
    assert message.request_id == 2937124
    assert message.status == "QUEUED"
    assert message.failure_reason is None

    body = parse_qs(fonnte.last_request.content.decode())
    assert body["target"] == ["081234567890"]
    assert body["countryCode"] == ["62"]
    assert body["connectOnly"] == ["true"]
    assert body["preview"] == ["false"]
    assert fonnte.last_request.headers["Authorization"] == "test-token"
    assert "Jangan berikan kode ini" in body["message"][0]
    # Tidak ada field Fonnte yang bocor ke respons API.
    assert set(response.json()["data"]) == {
        "otp_session_id",
        "purpose",
        "masked_phone",
        "channel",
        "expires_in",
        "resend_available_in",
        "max_attempts",
    }


def test_fonnte_target_invalid_is_not_counted_to_hourly_limit(fonnte: FakeFonnte) -> None:
    fonnte.responder = lambda _: httpx.Response(
        200, json={"status": False, "reason": "target invalid"}
    )

    for _ in range(6):
        response = otp_request("081234567890")
        assert response.status_code == 422
        assert response.json()["code"] == "OTP_TARGET_NOT_WHATSAPP"

    message = _latest_message()
    assert message.status == "INVALID"
    assert message.failure_reason == "target invalid"


def test_fonnte_provider_error_and_resend_does_not_bump_counter(fonnte: FakeFonnte) -> None:
    response = otp_request("081234567890")
    assert response.status_code == 200
    session_id = response.json()["data"]["otp_session_id"]

    with SessionLocal() as db:
        session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
        session.last_sent_at = utcnow() - timedelta(seconds=60)
        db.commit()

    fonnte.responder = lambda _: httpx.Response(
        200, json={"status": False, "reason": "insufficient quota"}
    )
    response = client.post(
        "/v1/auth/otp/resend", json={"otp_session_id": session_id}, headers=headers()
    )
    assert response.status_code == 503
    assert response.json()["code"] == "OTP_PROVIDER_UNAVAILABLE"
    assert response.json()["details"]["retry_after"] == 30

    with SessionLocal() as db:
        session = db.scalar(select(OtpSession).where(OtpSession.public_id == session_id))
        assert session.resend_count == 0
        message = db.scalars(
            select(WhatsAppMessage).order_by(WhatsAppMessage.created_at.desc())
        ).first()
        assert message.status == "PROVIDER_ERROR"
        assert message.failure_reason == "insufficient quota"


def test_fonnte_timeout_maps_to_provider_unavailable(fonnte: FakeFonnte) -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    fonnte.responder = timeout
    response = otp_request("081234567890")
    assert response.status_code == 503
    assert response.json()["code"] == "OTP_PROVIDER_UNAVAILABLE"
    assert _latest_message().status == "PROVIDER_ERROR"


def test_webhook_requires_secret() -> None:
    response = _webhook("salah/status", {"id": "80367170", "status": "sent"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_webhook_status_updates_and_never_downgrades(fonnte: FakeFonnte) -> None:
    assert otp_request("081234567890").status_code == 200

    response = _webhook(
        f"{WEBHOOK_SECRET}/status",
        {"id": "80367170", "stateid": "3EB0A1B2C3D4", "status": "processing"},
    )
    assert response.status_code == 200
    assert response.json()["data"] is None

    response = _webhook(
        f"{WEBHOOK_SECRET}/status",
        {"id": "80367170", "stateid": "3EB0A1B2C3D4", "status": "sent"},
    )
    assert response.status_code == 200

    response = _webhook(
        f"{WEBHOOK_SECRET}/status",
        {"id": "80367170", "stateid": "3EB0A1B2C3D4", "status": "pending"},
    )
    assert response.status_code == 200

    message = _latest_message()
    assert message.status == "SENT"
    assert message.provider_status == "pending"
    assert message.sent_at is not None

    # Pesan tidak dikenal tetap dijawab 200.
    response = _webhook(
        f"{WEBHOOK_SECRET}/status", {"id": "tidak-dikenal", "status": "sent"}
    )
    assert response.status_code == 200

    response = _webhook(f"{WEBHOOK_SECRET}/status", {"status": "sent"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_webhook_device_disconnect_blocks_otp_until_connect(fonnte: FakeFonnte) -> None:
    assert otp_request("081234567890").status_code == 200
    call_count = len(fonnte.requests)

    response = _webhook(
        f"{WEBHOOK_SECRET}/device",
        {
            "device": "6281234567890",
            "status": "disconnect",
            "reason": "logged out from phone",
        },
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        setting = db.get(AppSetting, "otp.provider_healthy")
        assert setting.value is False
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "whatsapp.device.disconnect")
        )
        assert audit is not None
        assert audit.actor_type == "SYSTEM"
        assert audit.after["reason"] == "logged out from phone"

    response = otp_request("081234567890")
    assert response.status_code == 503
    assert response.json()["code"] == "OTP_PROVIDER_UNAVAILABLE"
    assert len(fonnte.requests) == call_count  # tidak memanggil provider

    response = _webhook(
        f"{WEBHOOK_SECRET}/device", {"device": "6281234567890", "status": "connect"}
    )
    assert response.status_code == 200
    assert otp_request("081234567890").status_code == 200


def test_otp_code_is_not_written_to_logs(caplog: pytest.LogCaptureFixture) -> None:
    assert isinstance(wa.get_gateway(), wa.LoggingWaGateway)
    caplog.set_level(logging.DEBUG)

    response = otp_request("081234567890")
    assert response.status_code == 200
    code = gateway.sent["081234567890"]

    assert code not in caplog.text
    assert code not in response.text


def test_provider_auto_detection() -> None:
    assert wa.resolve_provider("", "") == "log"
    assert wa.resolve_provider("", "token-dari-fonnte") == "fonnte"
    assert wa.resolve_provider("log", "token-dari-fonnte") == "log"
    assert wa.resolve_provider("FONNTE", "") == "fonnte"
