"""Email gateway SMTP dan pengiriman OTP email."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db import SessionLocal
from app.models import EmailMessage, OtpPurpose, OtpSession
from app.services import email as email_service
from app.services.auth import otp_public, request_otp
from app.services.wa import SendResult
from tests.conftest import DEVICE_A


class FailingEmailGateway(email_service.EmailGateway):
    name = "FAIL"

    def send_message(self, email: str, subject: str, text: str) -> SendResult:
        return SendResult(
            ok=False,
            status="PROVIDER_ERROR",
            failure_reason="smtp down",
            error_code="OTP_PROVIDER_UNAVAILABLE",
        )


class FakeSMTP:
    instances: list[FakeSMTP] = []
    fail_send = False

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.message = None
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message) -> None:
        if FakeSMTP.fail_send:
            raise OSError("smtp failure")
        self.message = message

    def quit(self) -> None:
        self.quit_called = True


def test_email_otp_is_delivered_and_logged() -> None:
    with SessionLocal() as db:
        session = request_otp(
            db,
            target="koko@example.com",
            target_type="EMAIL",
            purpose=OtpPurpose.LOGIN,
            device_id=DEVICE_A,
            ip="127.0.0.1",
        )
        db.commit()

        assert session.channel == "EMAIL"
        assert session.target_type == "EMAIL"
        assert session.phone is None

        gateway = email_service.get_gateway()
        assert isinstance(gateway, email_service.LoggingEmailGateway)
        assert gateway.messages
        email, subject, body = gateway.messages[-1]
        assert email == "koko@example.com"
        assert subject == "Kode verifikasi Poinqu"
        assert re.search(r"\b\d{6}\b", body)

        record = db.scalar(
            select(EmailMessage).where(EmailMessage.otp_session_id == session.id)
        )
        assert record is not None
        assert record.status == "SENT"
        assert record.email == "koko@example.com"

        public = otp_public(session)
        assert public["target_type"] == "EMAIL"
        assert public["masked_identifier"] == "ko***@example.com"


def test_email_provider_error_cancels_session() -> None:
    email_service.set_gateway(FailingEmailGateway())

    with SessionLocal() as db:
        with pytest.raises(AppError) as exc:
            request_otp(
                db,
                target="koko@example.com",
                target_type="EMAIL",
                purpose=OtpPurpose.LOGIN,
                device_id=DEVICE_A,
                ip="127.0.0.1",
            )
        assert exc.value.code == "OTP_PROVIDER_UNAVAILABLE"

        session = db.scalar(select(OtpSession).where(OtpSession.target == "koko@example.com"))
        assert session is not None
        assert session.cancelled_at is not None
        record = db.scalar(
            select(EmailMessage).where(EmailMessage.otp_session_id == session.id)
        )
        assert record is not None
        assert record.status == "PROVIDER_ERROR"


def test_smtp_gateway_sends_message() -> None:
    FakeSMTP.instances.clear()
    FakeSMTP.fail_send = False

    gateway = email_service.SmtpEmailGateway(
        host="smtp.example.test",
        port=587,
        from_addr="no-reply@poinqu.id",
        user="user",
        password="pass",
        use_tls=True,
        smtp_factory=FakeSMTP,
    )
    result = gateway.send_message("koko@example.com", "Subjek", "Isi pesan")

    assert result.ok is True
    assert result.status == "SENT"
    client = FakeSMTP.instances[-1]
    assert client.host == "smtp.example.test"
    assert client.port == 587
    assert client.started_tls is True
    assert client.logged_in == ("user", "pass")
    assert client.message["To"] == "koko@example.com"
    assert client.message["Subject"] == "Subjek"
    assert "Isi pesan" in client.message.get_content()
    assert client.quit_called is True


def test_smtp_gateway_maps_failure() -> None:
    FakeSMTP.instances.clear()
    FakeSMTP.fail_send = True

    gateway = email_service.SmtpEmailGateway(
        host="smtp.example.test",
        port=587,
        from_addr="no-reply@poinqu.id",
        smtp_factory=FakeSMTP,
    )
    result = gateway.send_message("koko@example.com", "Subjek", "Isi pesan")

    assert result.ok is False
    assert result.status == "PROVIDER_ERROR"
    assert result.error_code == "OTP_PROVIDER_UNAVAILABLE"
