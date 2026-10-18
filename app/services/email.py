"""Adapter email SMTP (OTP & notifikasi).

Kode OTP tidak pernah ditulis ke log. ``LoggingEmailGateway`` menyimpan pesan
di memori hanya untuk test/development.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage as MimeMessage

from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import utcnow
from app.core.errors import AppError
from app.models import EmailMessage, OtpSession
from app.services.wa import SendResult

logger = logging.getLogger("poinqu.email")

PROVIDER_UNAVAILABLE_RETRY = 30


def render_otp_email(code: str) -> str:
    minutes = max(1, settings.OTP_TTL // 60)
    return settings.EMAIL_OTP_TEMPLATE.format(code=code, minutes=minutes)


class EmailGateway:
    name = "LOG"

    def send_message(self, email: str, subject: str, text: str) -> SendResult:
        raise NotImplementedError


class LoggingEmailGateway(EmailGateway):
    """Gateway lokal/test; menyimpan pesan di memori, tidak mengirim email."""

    name = "LOG"

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def send_message(self, email: str, subject: str, text: str) -> SendResult:
        self.messages.append((email, subject, text))
        logger.info("[EMAIL:log] Pesan untuk %s diproses (mode log)", _mask(email))
        return SendResult(ok=True, status="SENT")


class SmtpEmailGateway(EmailGateway):
    name = "SMTP"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_addr: str,
        user: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: float = 10,
        smtp_factory=None,
    ) -> None:
        self._host = host
        self._port = port
        self._from_addr = from_addr
        self._user = user
        self._password = password
        self._use_tls = use_tls
        self._use_ssl = use_ssl
        self._timeout = timeout
        self._smtp_factory = smtp_factory or (
            smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        )

    def send_message(self, email: str, subject: str, text: str) -> SendResult:
        message = MimeMessage()
        message["From"] = self._from_addr
        message["To"] = email
        message["Subject"] = subject
        message.set_content(text)

        client = None
        try:
            client = self._smtp_factory(self._host, self._port, timeout=self._timeout)
            if self._use_tls and not self._use_ssl:
                client.starttls()
            if self._user:
                client.login(self._user, self._password)
            client.send_message(message)
            return SendResult(ok=True, status="SENT")
        except (smtplib.SMTPException, OSError, TimeoutError, ValueError) as exc:
            logger.error("SMTP gagal mengirim email: %s", type(exc).__name__)
            return SendResult(
                ok=False,
                status="PROVIDER_ERROR",
                failure_reason=type(exc).__name__,
                error_code="OTP_PROVIDER_UNAVAILABLE",
            )
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:  # noqa: BLE001
                    pass


def _mask(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "***"
    return f"{local[:2]}***@{domain}"


def resolve_provider(provider: str | None = None, host: str | None = None) -> str:
    selected = (settings.EMAIL_PROVIDER if provider is None else provider).strip().lower()
    if selected:
        return selected
    value = settings.SMTP_HOST if host is None else host
    return "smtp" if value.strip() else "log"


def build_gateway() -> EmailGateway:
    provider = resolve_provider()
    if provider == "smtp":
        if not settings.SMTP_HOST:
            logger.error(
                "EMAIL_PROVIDER=smtp tetapi SMTP_HOST kosong; email OTP akan gagal."
            )
        return SmtpEmailGateway(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            from_addr=settings.SMTP_FROM,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
            use_ssl=settings.SMTP_USE_SSL,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )
    if provider != "log":
        logger.warning("EMAIL_PROVIDER=%s tidak dikenal; memakai gateway log.", provider)
    return LoggingEmailGateway()


_gateway: EmailGateway = build_gateway()


def get_gateway() -> EmailGateway:
    return _gateway


def set_gateway(gateway: EmailGateway) -> None:
    """Dipakai test untuk menyuntikkan gateway palsu."""

    global _gateway
    _gateway = gateway


def send_otp(db: Session, session: OtpSession, code: str) -> EmailMessage:
    """Kirim OTP email dan catat metadata. Isi/kode tidak disimpan."""

    gateway = get_gateway()
    result = gateway.send_message(
        session.target,
        settings.EMAIL_OTP_SUBJECT,
        render_otp_email(code),
    )
    record = EmailMessage(
        otp_session_id=session.id,
        email=session.target,
        provider=gateway.name,
        provider_msg_id=result.provider_msg_id,
        status=result.status,
        failure_reason=result.failure_reason,
        sent_at=utcnow() if result.status == "SENT" else None,
    )
    db.add(record)
    db.flush()

    if not result.ok:
        raise AppError(
            result.error_code or "OTP_PROVIDER_UNAVAILABLE",
            details={"retry_after": PROVIDER_UNAVAILABLE_RETRY},
            retry_after=PROVIDER_UNAVAILABLE_RETRY,
        )
    return record


def send_notification(
    db: Session,
    email: str,
    subject: str,
    text: str,
) -> EmailMessage:
    gateway = get_gateway()
    result = gateway.send_message(email, subject, text)
    record = EmailMessage(
        otp_session_id=None,
        email=email,
        provider=gateway.name,
        provider_msg_id=result.provider_msg_id,
        status=result.status,
        failure_reason=result.failure_reason,
        sent_at=utcnow() if result.status == "SENT" else None,
    )
    db.add(record)
    db.flush()

    if not result.ok:
        raise AppError(
            result.error_code or "OTP_PROVIDER_UNAVAILABLE",
            details={"retry_after": PROVIDER_UNAVAILABLE_RETRY},
            retry_after=PROVIDER_UNAVAILABLE_RETRY,
        )
    return record
