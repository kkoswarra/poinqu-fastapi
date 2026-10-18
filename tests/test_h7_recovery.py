"""H.7.3: pemulihan nomor tanpa KYC (pengajuan + keputusan admin)."""

from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Device, RecoveryRequest, User
from tests.conftest import (
    DEVICE_A,
    admin_login,
    auth_headers,
    client,
    gateway,
    headers,
    otp_verify,
    register,
)

NEW_PHONE = "081298765432"


def _start_and_submit(old_phone: str, new_phone: str = NEW_PHONE):
    response = client.post(
        "/v1/auth/phone-recovery/support",
        json={"old_phone": old_phone, "new_phone": new_phone, "name": "Koko Wijaya"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["data"]["otp_session_id"]

    response = otp_verify(session_id, gateway.sent[new_phone])
    assert response.status_code == 200, response.text
    token = response.json()["data"]["verification_token"]

    response = client.post(
        "/v1/auth/phone-recovery/support/submit",
        json={
            "verification_token": token,
            "last_transaction_hint": "Pulsa Telkomsel 10.000, 12 Oktober",
            "balance_hint": 450000,
            "note": "HP hilang di angkot",
        },
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_recovery_support_flow_approved_by_admin() -> None:
    data = register()
    old_access = data["tokens"]["access_token"]

    response = client.post(
        "/v1/auth/phone-recovery/support",
        json={"old_phone": "081234567890", "new_phone": NEW_PHONE, "name": "Koko Wijaya"},
        headers=headers(),
    )
    assert response.status_code == 200
    first = response.json()["data"]
    session_id = first["otp_session_id"]

    response = otp_verify(session_id, gateway.sent[NEW_PHONE])
    token = response.json()["data"]["verification_token"]
    response = client.post(
        "/v1/auth/phone-recovery/support/submit",
        json={
            "verification_token": token,
            "last_transaction_hint": "Pulsa Telkomsel 10.000, 12 Oktober",
            "balance_hint": 450000,
            "note": "HP hilang di angkot",
        },
        headers=headers(),
    )
    assert response.status_code == 201
    ticket = response.json()["data"]
    assert ticket["status"] == "PENDING_REVIEW"
    assert ticket["balance_on_hold"] is True
    assert ticket["ticket_id"].startswith("rcv_")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "081234567890"))
        assert user.recovery_hold is True
        request_row = db.scalar(
            select(RecoveryRequest).where(
                RecoveryRequest.public_id == ticket["ticket_id"]
            )
        )
        assert request_row is not None
        assert request_row.user_id == user.id

    admin = admin_login()
    admin_headers = {"Authorization": f"Bearer {admin['tokens']['access_token']}"}

    response = client.get("/v1/admin/recovery-requests", headers=admin_headers)
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == ticket["ticket_id"]
    assert items[0]["account_found"] is True
    assert "****" in items[0]["old_phone"]

    response = client.post(
        f"/v1/admin/recovery-requests/{ticket['ticket_id']}/decision",
        json={"decision": "APPROVE", "reason": "Selfie dan riwayat transaksi cocok"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    decision = response.json()["data"]
    assert decision["status"] == "APPROVED"
    assert decision["transfer_blocked_until"]

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == NEW_PHONE))
        assert user is not None
        assert user.recovery_hold is False
        assert user.transfer_blocked_until is not None
        device = db.scalar(select(Device).where(Device.device_id == DEVICE_A))
        assert device.trusted_at is None

    # Sesi lama langsung tidak berlaku.
    assert client.get("/v1/me", headers=auth_headers(old_access)).status_code == 401

    # Notifikasi dikirim ke nomor baru.
    assert any(phone == NEW_PHONE for phone, _ in gateway.messages)

    response = client.post(
        f"/v1/admin/recovery-requests/{ticket['ticket_id']}/decision",
        json={"decision": "APPROVE", "reason": "Selfie dan riwayat transaksi cocok"},
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "RECOVERY_REQUEST_ALREADY_DECIDED"


def test_recovery_support_is_anti_enumerated_and_handles_unknown_account() -> None:
    ticket = _start_and_submit("089999999999", "081298765433")
    assert ticket["status"] == "PENDING_REVIEW"
    assert ticket["balance_on_hold"] is True

    with SessionLocal() as db:
        request_row = db.scalar(
            select(RecoveryRequest).where(
                RecoveryRequest.public_id == ticket["ticket_id"]
            )
        )
        assert request_row.user_id is None

    admin = admin_login()
    admin_headers = {"Authorization": f"Bearer {admin['tokens']['access_token']}"}
    response = client.get("/v1/admin/recovery-requests", headers=admin_headers)
    item = response.json()["data"]["items"][0]
    assert item["account_found"] is False

    response = client.post(
        f"/v1/admin/recovery-requests/{ticket['ticket_id']}/decision",
        json={"decision": "APPROVE", "reason": "Dokumen tidak diperlukan untuk nomor ini"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["transfer_blocked_until"] is None


def test_recovery_support_rejects_same_phone() -> None:
    response = client.post(
        "/v1/auth/phone-recovery/support",
        json={
            "old_phone": "081234567890",
            "new_phone": "081234567890",
            "name": "Koko Wijaya",
        },
        headers=headers(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "PHONE_SAME_AS_CURRENT"
