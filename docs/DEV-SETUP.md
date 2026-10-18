# DEV SETUP — Tanpa Docker / Tanpa Administrator

Dokumen ini untuk menjalankan backend dan test di Windows tanpa Docker,
tanpa PostgreSQL lokal, dan tanpa akses administrator.

## 1. Python user-level (uv)

Pasang `uv` di profil user (tidak butuh admin):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Buka terminal baru, lalu:

```powershell
uv python install 3.12
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements-dev.txt
```

Jika PowerShell menolak aktivasi venv, panggil Python langsung:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Alternatif: install Python 3.12 dari python.org dengan opsi **Install for me
only** (tanpa admin), lalu buat venv seperti biasa.

## 2. Database

Test memakai **SQLite in-memory** (lihat `tests/conftest.py`). Tidak perlu
PostgreSQL atau Docker.

Untuk menjalankan app lokal:

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///./poinqu.db"
$env:JWT_SECRET="secret-lokal-minimal-32-karakter"
uvicorn app.main:app --reload
```

Untuk migrasi:

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///./poinqu.db"
alembic upgrade head
```

Jika database sudah punya tabel dari versi sebelumnya, tandai baseline
(tanpa menjalankan ulang create table):

```powershell
alembic stamp 0001
```

## 3. Redis

Tidak wajib di lokal. Jika `REDIS_URL` kosong, revocation store memakai
in-memory (khusus dev/test). Di production, isi Upstash/Redis lewat Vercel.

## 4. PostgreSQL integration

Jika butuh PostgreSQL tanpa Docker:

- Buat branch/database gratis di **Neon** (sudah dipakai production), atau
- Jalankan integration test lewat **GitHub Actions** (runner menyediakan
  Docker/Postgres).

Jangan memakai data production untuk test.

## 5. Email SMTP

- Unit test memakai fake `EmailGateway`, bukan SMTP asli.
- Untuk staging, gunakan penyedia SMTP (Mailtrap/Brevo/SES) dengan kredensial
  di environment Vercel.
- Jangan pernah menaruh kode OTP di log.

## 6. CI

`.github/workflows/tests.yml` menjalankan:

1. install dependencies,
2. syntax check,
3. `pytest`,
4. `alembic upgrade head` di SQLite.

Push ke GitHub akan menjalankan test tanpa perlu Docker lokal.

## 7. Perintah harian

```powershell
# test
.\.venv\Scripts\python.exe -m pytest -q

# syntax
.\.venv\Scripts\python.exe -m compileall -q app tests alembic

# migrasi
$env:DATABASE_URL="sqlite+pysqlite:///./poinqu.db"
alembic upgrade head

# app
$env:DATABASE_URL="sqlite+pysqlite:///./poinqu.db"
uvicorn app.main:app --reload
```
