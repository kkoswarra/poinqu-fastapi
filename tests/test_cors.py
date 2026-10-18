"""CORS untuk web app (Expo web) saat pengembangan."""

from __future__ import annotations

from tests.conftest import client


def _preflight(origin: str):
    return client.options(
        "/v1/auth/otp/request",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-device-id",
        },
    )


def test_cors_expo_web_port_8082():
    origin = "http://localhost:8082"
    response = _preflight(origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_lan_origin_allowed_di_non_produksi():
    origin = "http://192.168.1.3:8081"
    response = _preflight(origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
