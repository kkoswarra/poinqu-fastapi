"""Penyimpanan avatar lokal (ganti ke object storage pada fase produksi)."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.core.errors import AppError

AVATAR_SIZE = 512


def _avatar_path(user_id) -> Path:
    return Path(settings.AVATAR_DIR) / f"{user_id}.jpg"


def save_avatar(user_id, data: bytes) -> str:
    if len(data) > settings.AVATAR_MAX_BYTES:
        raise AppError("FILE_TOO_LARGE")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise AppError("UNSUPPORTED_MEDIA_TYPE") from exc

    if image.format not in {"JPEG", "PNG"}:
        raise AppError("UNSUPPORTED_MEDIA_TYPE")

    image = image.convert("RGB")
    image.thumbnail((AVATAR_SIZE, AVATAR_SIZE))
    directory = Path(settings.AVATAR_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    image.save(_avatar_path(user_id), format="JPEG", quality=85, optimize=True)
    return f"avatars/{user_id}.jpg"


def delete_avatar_file(key: str) -> None:
    path = Path(settings.AVATAR_DIR).parent / key
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
