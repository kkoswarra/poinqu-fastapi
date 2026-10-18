"""Database: engine, session, dan Base declarative."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return kwargs
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}


def normalize_database_url(url: str) -> str:
    """Neon/Vercel memberi ``postgresql://``; SQLAlchemy butuh driver psycopg3."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from app import models  # noqa: F401  (pastikan model terdaftar)

    Base.metadata.create_all(bind=engine)


def _add_column_if_missing(
    table: str, column: str, ddl_type: str, default: str | None = None
) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {item["name"] for item in inspector.get_columns(table)}
    if column in existing:
        return
    clause = f" DEFAULT {default}" if default is not None else ""
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}{clause}")
        )


def init_schema() -> None:
    """Buat tabel baru + lengkapi kolom yang ditambahkan setelah rilis awal.

    Ini jembatan kecil sebelum Alembic dipakai di produksi. Hanya menambah
    kolom; tidak menghapus atau mengubah data.
    """
    create_all()
    timestamp_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    boolean_type = "BOOLEAN"
    boolean_false = "false" if engine.dialect.name == "postgresql" else "0"
    boolean_true = "true" if engine.dialect.name == "postgresql" else "1"

    columns = [
        ("devices", "trusted_at", timestamp_type, None),
        ("devices", "attestation_provider", "VARCHAR(20)", None),
        ("devices", "attested_at", timestamp_type, None),
        ("users", "email_verified_at", timestamp_type, None),
        ("verification_tokens", "via", "VARCHAR(20)", "'OTP'"),
        ("verification_tokens", "device_id", "VARCHAR(64)", None),
        ("users", "recovery_hold", boolean_type, boolean_false),
        ("users", "transfer_blocked_until", timestamp_type, None),
        ("otp_sessions", "is_decoy", boolean_type, boolean_false),
        ("otp_sessions", "target", "VARCHAR(150)", None),
        ("otp_sessions", "target_type", "VARCHAR(10)", "'PHONE'"),
        ("admins", "public_id", "VARCHAR(32)", None),
        ("admins", "must_change_password", boolean_type, boolean_true),
        ("admins", "totp_enabled", boolean_type, boolean_false),
        ("admins", "totp_pending_secret", "VARCHAR(64)", None),
        ("admins", "last_login_at", timestamp_type, None),
        ("roles", "public_id", "VARCHAR(32)", None),
        ("app_settings", "description", "TEXT", None),
        ("otp_sessions", "cancelled_at", timestamp_type, None),
    ]
    for table, column, ddl_type, default in columns:
        _add_column_if_missing(table, column, ddl_type, default)

    # Backfill dan indeks yang tidak ditangani oleh create_all pada tabel lama.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE otp_sessions SET target = phone WHERE target IS NULL")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_otp_sessions_target "
                "ON otp_sessions (target)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower "
                "ON users (lower(email))"
            )
        )
