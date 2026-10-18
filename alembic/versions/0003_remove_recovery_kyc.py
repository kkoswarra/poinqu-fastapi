"""hapus fitur recovery dan KYC

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19

KYC dan recovery dihapus dari produk (D-13, D-22). Kolom legacy
`users.kyc_status`/`level` dibiarkan agar data lama tetap terbaca; API tidak
lagi memakainya.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()

    for table_name in ("phone_recoveries", "kyc_profiles", "recovery_requests"):
        if table_name in tables:
            op.drop_table(table_name)

    if "users" in tables:
        columns = _columns("users")
        with op.batch_alter_table("users") as batch:
            if "recovery_hold" in columns:
                batch.drop_column("recovery_hold")
            if "transfer_blocked_until" in columns:
                batch.drop_column("transfer_blocked_until")


def downgrade() -> None:
    # Data recovery/KYC tidak dibuat ulang. Downgrade hanya mengembalikan
    # kolom penanda agar schema lama bisa dibuka kembali.
    bind = op.get_bind()
    tables = _table_names()
    if "users" not in tables:
        return
    columns = _columns("users")
    with op.batch_alter_table("users") as batch:
        if "recovery_hold" not in columns:
            batch.add_column(
                sa.Column("recovery_hold", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "transfer_blocked_until" not in columns:
            batch.add_column(sa.Column("transfer_blocked_until", sa.DateTime(), nullable=True))
