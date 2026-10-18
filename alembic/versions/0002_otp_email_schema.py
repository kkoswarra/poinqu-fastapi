"""otp target/channel email + email verification metadata

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18

Migration ini dibuat idempotent karena baseline 0001 memakai metadata model
saat ini. Pada database kosong, 0001 sudah membuat kolom/tabel baru; pada
database existing, 0002 menambahkannya.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app import models  # noqa: F401
from app.db import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> dict[str, dict]:
    return {item["name"]: item for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()

    if "users" in tables:
        user_columns = _columns("users")
        if "email_verified_at" not in user_columns:
            with op.batch_alter_table("users") as batch:
                batch.add_column(sa.Column("email_verified_at", sa.DateTime(), nullable=True))
        # Expression index tidak selalu terbaca konsisten oleh inspector.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower "
            "ON users (lower(email))"
        )

    if "otp_sessions" in tables:
        otp_columns = _columns("otp_sessions")
        with op.batch_alter_table("otp_sessions") as batch:
            if "target" not in otp_columns:
                batch.add_column(sa.Column("target", sa.String(150), nullable=True))
            if "target_type" not in otp_columns:
                batch.add_column(
                    sa.Column(
                        "target_type",
                        sa.String(10),
                        nullable=False,
                        server_default="PHONE",
                    )
                )
            if not otp_columns.get("phone", {}).get("nullable", True):
                batch.alter_column(
                    "phone",
                    existing_type=sa.String(16),
                    nullable=True,
                )

        op.execute("UPDATE otp_sessions SET target = phone WHERE target IS NULL")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_otp_sessions_target "
            "ON otp_sessions (target)"
        )

        # Setelah backfill, target wajib terisi untuk data ke depan.
        otp_columns = _columns("otp_sessions")
        if otp_columns.get("target", {}).get("nullable", True):
            with op.batch_alter_table("otp_sessions") as batch:
                batch.alter_column(
                    "target",
                    existing_type=sa.String(150),
                    nullable=False,
                )

    for table_name in ("email_messages", "contact_change_requests"):
        if table_name not in tables:
            Base.metadata.tables[table_name].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()

    for table_name in ("contact_change_requests", "email_messages"):
        if table_name in tables:
            Base.metadata.tables[table_name].drop(bind=bind)

    if "otp_sessions" in tables:
        op.execute("DROP INDEX IF EXISTS ix_otp_sessions_target")
        otp_columns = _columns("otp_sessions")
        with op.batch_alter_table("otp_sessions") as batch:
            for column in ("target_type", "target"):
                if column in otp_columns:
                    batch.drop_column(column)

    if "users" in tables:
        op.execute("DROP INDEX IF EXISTS uq_users_email_lower")
        user_columns = _columns("users")
        if "email_verified_at" in user_columns:
            with op.batch_alter_table("users") as batch:
                batch.drop_column("email_verified_at")
