"""Kontrak profil, avatar, perangkat, dan aktivitas keamanan."""

from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import KycStatus, User
from tests.conftest import (
    DEVICE_A,
    DEVICE_B,
    auth_headers,
    client,
    login,
    register,
)


def test_device_list_and_revoke_rules() -> None:
    register()
    response = login("081234567890", "246810", device_id=DEVICE_B)
    assert response.status_code == 200, response.text
    access_b = response.json()["data"]["tokens"]["access_token"]

    response = client.get("/v1/me/devices", headers=auth_headers(access_b, DEVICE_B))
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 2
    assert sum(1 for item in items if item["is_current"]) == 1
    assert items[0]["platform"] in {"ANDROID", "IOS"}

    response = client.delete(
        f"/v1/me/devices/{DEVICE_B}", headers=auth_headers(access_b, DEVICE_B)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CANNOT_REMOVE_CURRENT_DEVICE"

    response = client.delete(
        f"/v1/me/devices/{DEVICE_A}", headers=auth_headers(access_b, DEVICE_B)
    )
    assert response.status_code == 200

    response = client.delete("/v1/me/devices", headers=auth_headers(access_b, DEVICE_B))
    assert response.status_code == 404
    assert response.json()["code"] == "NO_OTHER_DEVICES"


def test_access_with_wrong_device_header_is_rejected() -> None:
    data = register()
    response = client.get(
        "/v1/me", headers=auth_headers(data["tokens"]["access_token"], DEVICE_B)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DEVICE_MISMATCH"


def test_profile_update_email_conflict_and_name_lock() -> None:
    first = register()
    access = first["tokens"]["access_token"]

    response = client.patch(
        "/v1/me",
        json={"name": "Koko Wijaya", "email": "koko@poinqu.id"},
        headers=auth_headers(access),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == "Koko Wijaya"
    assert response.json()["data"]["email"] == "koko@poinqu.id"

    second = register(phone="081298765432", device_id=DEVICE_B)
    response = client.patch(
        "/v1/me",
        json={"email": "koko@poinqu.id"},
        headers=auth_headers(second["tokens"]["access_token"], DEVICE_B),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_USED"

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "081234567890"))
        user.kyc_status = KycStatus.VERIFIED
        db.commit()

    response = client.patch(
        "/v1/me",
        json={"name": "Nama Lain"},
        headers=auth_headers(access),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "NAME_LOCKED"


def test_patch_profile_requires_at_least_one_field() -> None:
    data = register()
    response = client.patch(
        "/v1/me", json={}, headers=auth_headers(data["tokens"]["access_token"])
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["errors"][0]["code"] == "REQUIRED"


def test_avatar_upload_and_delete() -> None:
    data = register()
    auth = auth_headers(data["tokens"]["access_token"])

    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), (10, 120, 200)).save(buffer, format="PNG")

    response = client.post(
        "/v1/me/avatar",
        files={"photo": ("avatar.png", buffer.getvalue(), "image/png")},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    url = response.json()["data"]["avatar_url"]
    assert url.startswith("/media/avatars/") and "?v=" in url

    response = client.delete("/v1/me/avatar", headers=auth)
    assert response.status_code == 200
    assert response.json()["data"]["avatar_url"] is None

    response = client.delete("/v1/me/avatar", headers=auth)
    assert response.status_code == 404
    assert response.json()["code"] == "AVATAR_NOT_FOUND"

    response = client.post(
        "/v1/me/avatar",
        files={"photo": ("catatan.txt", b"bukan gambar", "text/plain")},
        headers=auth,
    )
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_push_token_registration() -> None:
    data = register()
    auth = auth_headers(data["tokens"]["access_token"])
    response = client.put(
        "/v1/me/devices/current/push-token",
        json={"push_token": "ExponentPushToken[abc]", "platform": "ANDROID"},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["data"] is None
