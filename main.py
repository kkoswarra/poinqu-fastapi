"""Entrypoint Vercel: Vercel mendeteksi variabel ``app`` di file root ini."""

from app.main import app

__all__ = ["app"]
