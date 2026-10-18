"""Adapter WhatsApp gateway (Fonnte) — lihat docs/FASE-2-API.md bagian H.

Kode OTP tidak pernah ditulis ke log. ``LoggingWaGateway`` hanya menyimpan kode
di memori (untuk test) dan tidak mencetaknya; aktifkan ``OTP_DEV_ECHO=true``
hanya bila benar-benar butuh melihat kode di lingkungan lokal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger("poinqu.wa")

TARGET_INVALID_REASON = "target invalid"
_PROVIDER_ALERT_REASONS = {"token invalid", "insufficient quota"}


@dataclass
class SendResult:
    ok: bool
    status: str = "QUEUED"
    provider_msg_id: str | None = None
    provider_state_id: str | None = None
    request_id: int | None = None
    provider_status: str | None = None
    failure_reason: str | None = None
    error_code: str | None = None


class WhatsAppGateway:
    name = "LOG"

    def send_otp(self, phone: str, text: str, *, code: str | None = None) -> SendResult:
        raise NotImplementedError

    def send_message(self, phone: str, text: str) -> SendResult:
        raise NotImplementedError


class LoggingWaGateway(WhatsAppGateway):
    """Gateway lokal untuk development/test (tanpa memanggil jaringan)."""

    name = "LOG"

    def __init__(self) -> None:
        self.sent: dict[str, str] = {}
        self.messages: list[tuple[str, str]] = []

    def send_otp(self, phone: str, text: str, *, code: str | None = None) -> SendResult:
        if code:
            self.sent[phone] = code
        logger.info("[WA:log] OTP untuk %s diproses (mode log)", _mask(phone))
        if settings.OTP_DEV_ECHO and settings.ENVIRONMENT != "production" and code:
            logger.warning("[WA:dev] Kode OTP %s untuk %s (JANGAN di produksi)", code, phone)
        return SendResult(ok=True, status="QUEUED")

    def send_message(self, phone: str, text: str) -> SendResult:
        self.messages.append((phone, text))
        logger.info("[WA:log] Pesan untuk %s diproses (mode log)", _mask(phone))
        return SendResult(ok=True, status="QUEUED")


class FonnteGateway(WhatsAppGateway):
    name = "FONNTE"

    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Authorization": token},
        )

    def send_otp(self, phone: str, text: str, *, code: str | None = None) -> SendResult:
        return self._post(phone, text)

    def send_message(self, phone: str, text: str) -> SendResult:
        return self._post(phone, text)

    def _post(self, phone: str, text: str) -> SendResult:
        payload = {
            "target": phone,
            "message": text,
            "countryCode": "62",
            "connectOnly": "true",
            "typing": "false",
            "preview": "false",
        }
        try:
            response = self._client.post("/send", data=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException:
            logger.error("Fonnte timeout setelah %.0f detik", self._client.timeout.read or 0)
            return SendResult(
                ok=False,
                status="PROVIDER_ERROR",
                failure_reason="timeout",
                error_code="OTP_PROVIDER_UNAVAILABLE",
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.error("Fonnte tidak dapat dihubungi: %s", type(exc).__name__)
            return SendResult(
                ok=False,
                status="PROVIDER_ERROR",
                failure_reason=type(exc).__name__,
                error_code="OTP_PROVIDER_UNAVAILABLE",
            )

        if not isinstance(body, dict):
            return SendResult(
                ok=False,
                status="PROVIDER_ERROR",
                failure_reason="invalid response",
                error_code="OTP_PROVIDER_UNAVAILABLE",
            )

        if body.get("status") is not True:
            reason = str(body.get("reason") or body.get("detail") or "unknown")
            if reason.strip().lower() == TARGET_INVALID_REASON:
                return SendResult(
                    ok=False,
                    status="INVALID",
                    provider_status=reason,
                    failure_reason=reason,
                    error_code="OTP_TARGET_NOT_WHATSAPP",
                )
            if reason.strip().lower() in _PROVIDER_ALERT_REASONS:
                logger.critical("Fonnte menolak pengiriman: %s", reason)
            return SendResult(
                ok=False,
                status="PROVIDER_ERROR",
                provider_status=reason,
                failure_reason=reason,
                error_code="OTP_PROVIDER_UNAVAILABLE",
            )

        ids = body.get("id") or []
        provider_msg_id = str(ids[0]) if isinstance(ids, list) and ids else None
        request_id = body.get("requestid")
        try:
            request_id = int(request_id) if request_id is not None else None
        except (TypeError, ValueError):
            request_id = None

        detail = str(body.get("detail") or "")
        status = "PENDING" if "pending" in detail.lower() else "QUEUED"
        return SendResult(
            ok=True,
            status=status,
            provider_msg_id=provider_msg_id,
            request_id=request_id,
            provider_status=detail or None,
        )


def _mask(phone: str) -> str:
    return f"{phone[:4]}****{phone[-4:]}" if len(phone) > 8 else phone


def resolve_provider(provider: str | None = None, token: str | None = None) -> str:
    """Pilih provider: explicit env menang; kosong = Fonnte bila token ada."""
    selected = (settings.OTP_PROVIDER if provider is None else provider).strip().lower()
    if selected:
        return selected
    value = settings.FONNTE_TOKEN if token is None else token
    return "fonnte" if value.strip() else "log"


def build_gateway() -> WhatsAppGateway:
    provider = resolve_provider()
    if provider == "fonnte":
        if not settings.FONNTE_TOKEN:
            logger.error(
                "OTP_PROVIDER=fonnte tetapi FONNTE_TOKEN belum diisi; OTP akan gagal (503)."
            )
        return FonnteGateway(
            token=settings.FONNTE_TOKEN,
            base_url=settings.FONNTE_BASE_URL,
            timeout=settings.FONNTE_TIMEOUT_SECONDS,
        )
    if provider != "log":
        logger.warning("OTP_PROVIDER=%s tidak dikenal; memakai gateway log.", provider)
    return LoggingWaGateway()


_gateway: WhatsAppGateway = build_gateway()

# Alias untuk pengujian lokal (instance gateway saat modul dimuat).
gateway = _gateway


def get_gateway() -> WhatsAppGateway:
    return _gateway


def set_gateway(gateway: WhatsAppGateway) -> None:
    """Dipakai test untuk menyuntikkan gateway palsu."""
    global _gateway
    _gateway = gateway
