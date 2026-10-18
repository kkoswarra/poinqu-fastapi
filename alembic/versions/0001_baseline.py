"""baseline schema Fase 2 (models saat ini)

Revision ID: 0001
Revises:
Create Date: 2026-10-18

Catatan:
- Ini baseline awal. Untuk database production yang sudah punya tabel,
  gunakan ``alembic stamp 0001`` agar Alembic tidak mencoba membuat ulang.
- Migration ini memakai metadata model saat ini. Setelah environment Python
  tersedia, snapshot statis dapat digenerate ulang dengan autogenerate bila
  diperlukan.
"""

from __future__ import annotations

from alembic import op

from app import models  # noqa: F401  (pastikan model terdaftar)
from app.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
