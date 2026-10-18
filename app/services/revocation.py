"""Pencabutan token langsung berlaku (H.7.5).

Default memakai penyimpanan in-memory (lokal/test). Bila ``REDIS_URL`` diisi,
dipakai Redis dengan kunci ``rev:sid:<family_id>`` dan ``rev:user:<user_id>``.
"""

from __future__ import annotations

import logging
import time

from app.config import settings

logger = logging.getLogger("poinqu.revocation")


class RevocationUnavailable(RuntimeError):
    """Penyimpanan pencabutan tidak bisa dihubungi."""


class MemoryRevocationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, float] = {}
        self._users: dict[str, tuple[int, float]] = {}

    def _prune(self, now: float) -> None:
        self._sessions = {key: exp for key, exp in self._sessions.items() if exp > now}
        self._users = {key: item for key, item in self._users.items() if item[1] > now}

    def revoke_session(self, session_id: str, ttl: int) -> None:
        self._sessions[session_id] = time.time() + ttl

    def revoke_user(self, user_id: str, iat_before: int, ttl: int) -> None:
        self._users[user_id] = (iat_before, time.time() + ttl)

    def is_revoked(self, session_id: str | None, user_id: str, iat: int) -> bool:
        now = time.time()
        self._prune(now)
        if session_id and session_id in self._sessions:
            return True
        entry = self._users.get(user_id)
        return bool(entry and iat <= entry[0])

    def reset(self) -> None:
        self._sessions.clear()
        self._users.clear()


class RedisRevocationStore:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=1.5,
            socket_connect_timeout=1.5,
        )

    def revoke_session(self, session_id: str, ttl: int) -> None:
        try:
            self._client.setex(f"rev:sid:{session_id}", ttl, "1")
        except Exception as exc:  # noqa: BLE001
            logger.critical("Gagal menulis revokasi sesi ke Redis: %s", type(exc).__name__)

    def revoke_user(self, user_id: str, iat_before: int, ttl: int) -> None:
        try:
            self._client.setex(f"rev:user:{user_id}", ttl, str(iat_before))
        except Exception as exc:  # noqa: BLE001
            logger.critical("Gagal menulis revokasi user ke Redis: %s", type(exc).__name__)

    def is_revoked(self, session_id: str | None, user_id: str, iat: int) -> bool:
        keys = [f"rev:user:{user_id}"]
        if session_id:
            keys.insert(0, f"rev:sid:{session_id}")
        try:
            values = self._client.mget(keys)
        except Exception as exc:  # noqa: BLE001
            raise RevocationUnavailable(type(exc).__name__) from exc

        if session_id and values[0] is not None:
            return True
        user_value = values[-1]
        if user_value is None:
            return False
        try:
            return iat <= int(user_value)
        except (TypeError, ValueError):
            return True

    def reset(self) -> None:
        """Hanya dipakai test; tidak dipanggil di produksi."""
        try:
            for key in self._client.scan_iter("rev:*"):
                self._client.delete(key)
        except Exception:  # noqa: BLE001
            pass


def build_store() -> MemoryRevocationStore | RedisRevocationStore:
    if settings.REDIS_URL:
        logger.info("Revocation store: Redis")
        return RedisRevocationStore(settings.REDIS_URL)
    logger.warning("REDIS_URL kosong; memakai revocation store in-memory (khusus dev/test).")
    return MemoryRevocationStore()


store = build_store()
