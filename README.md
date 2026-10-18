# Poinqu API — Fase 2

Backend dompet digital **Poinqu** dengan FastAPI. Repo ini berisi fondasi
Fase 2 sesuai `docs/PLAN.md` v0.4 dan `docs/FASE-2-API.md` (termasuk **H.7**):
autentikasi OTP WhatsApp + PIN, perangkat tepercaya, biometrik, profil,
pemulihan nomor, admin 2FA/RBAC, pencabutan token, dan audit log.

> API contoh `items` sudah dihapus.

## Cakupan Fase 2

- OTP WhatsApp (Fonnte): 6 digit, 300 detik, maks 5 percobaan, cooldown
  30 detik, maks 3 kirim ulang.
- **Login perangkat tepercaya**: PIN/biometrik tanpa OTP; OTP hanya untuk
  perangkat baru, daftar, lupa PIN, dan ganti nomor.
- **Anti-enumerasi**: `otp/request` dan `register` tidak membocorkan apakah
  nomor terdaftar; sesi OTP palsu tetap dihitung ke batas laju.
- Pendaftaran 2 langkah + PIN; aturan PIN lemah (berulang, berurutan, atau
  6 digit terakhir nomor HP).
- **PIN terkunci per perangkat** (5x → 15 menit, berulang → 1 jam → 24 jam)
  dan **kunci akun** setelah 15 salah/jam.
- `verification_token` sekali pakai, terikat purpose/device, 600 detik.
- Access token JWT 900 detik + refresh token 30 hari dengan **rotasi**;
  pemakaian ulang refresh token mencabut seluruh keluarga token.
- **Pencabutan token langsung berlaku** (klaim `sid`, Redis/in-memory).
- Device binding `X-Device-Id` + **attestation** (flag, default nonaktif).
- Biometrik: challenge ECDSA P-256, verifikasi tanda tangan server-side.
- Pemulihan nomor: jalur KYC (lama) dan **pengajuan admin untuk akun tanpa KYC**
  (saldo ditahan + cooldown transaksi keluar 24 jam).
- Admin: password + TOTP 2FA, kelola admin/peran, pengaturan berversi,
  pencarian pengguna, antrean pemulihan, audit log.
- Envelope respons dan daftar kode error mengikuti dokumen kontrak.

## Struktur

```
app/
├── main.py                 # app, middleware, exception handler, lifespan
├── config.py               # setelan dari environment
├── db.py                   # engine + session + rekonsiliasi skema dev
├── models.py               # skema database
├── schemas.py              # validasi request (Pydantic v2)
├── core/
│   ├── errors.py           # kode error, envelope, handler validasi
│   ├── security.py         # Argon2id, JWT, token, ECDSA, PIN
│   ├── deps.py             # auth pengguna/admin, izin, revocation check
│   └── clock.py            # waktu UTC, ISO 8601, epoch
├── services/
│   ├── auth.py             # OTP, anti-enumerasi, verification, refresh
│   ├── pin.py              # PIN per perangkat + kunci bertingkat
│   ├── biometrics.py       # challenge + registrasi biometrik
│   ├── profile.py          # serialisasi, perangkat, security event
│   ├── admin.py            # seed, login/2FA, kelola admin, audit
│   ├── settings.py         # app_settings berversi + validasi
│   ├── rate_limit.py       # penghitung batas laju berbasis DB
│   ├── revocation.py       # rev: sid/user (Redis atau in-memory)
│   ├── attestation.py      # verifikasi integritas perangkat (mock)
│   ├── whatsapp.py         # kirim OTP + log metadata
│   ├── avatar.py           # validasi + resize foto profil
│   └── wa.py               # adapter Fonnte / gateway log
└── routers/
    ├── auth.py             # /v1/auth/*
    ├── recovery.py         # /v1/auth/phone-recovery/*
    ├── me.py               # /v1/me/*
    ├── admin.py            # /v1/admin/*
    └── webhooks.py         # /v1/webhooks/fonnte/*
```

## Menjalankan lokal (SQLite)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

$env:JWT_SECRET="secret-lokal-minimal-32-karakter"
uvicorn app.main:app --reload
```

- Docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health
- Default DB: `sqlite+pysqlite:///./poinqu.db`.
- Redis **opsional** di lokal: jika `REDIS_URL` kosong, pencabutan token
  memakai penyimpanan in-memory (hanya dev/test).

`OTP_PROVIDER` kosong = otomatis: **Fonnte bila `FONNTE_TOKEN` diisi**,
selain itu gateway log. Pada gateway log kode **tidak** dicetak; set
`OTP_DEV_ECHO=true` hanya bila benar-benar perlu melihatnya di lokal.
Admin awal dibuat saat startup dan TOTP secret-nya dicetak di log.

## Menjalankan dengan Docker (PostgreSQL + Redis)

```powershell
Copy-Item .env.example .env
# wajib: ganti JWT_SECRET, ADMIN_PASSWORD, ADMIN_TOTP_SECRET

docker compose up --build -d
docker compose ps
docker compose logs -f api
```

- API: http://127.0.0.1:8000
- PostgreSQL 16 (`pgdata`), Redis 7 (pencabutan token), avatar (`media`).
- Healthcheck API memanggil `/health`; API menunggu DB dan Redis sehat.

Development (auto-reload):

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Bila port 8000 terpakai: `$env:PORT=8080; docker compose up -d`.

Skema: `AUTO_CREATE_TABLES=true` membuat tabel baru dan menambahkan kolom
H.7 yang belum ada pada database lama. Ini jembatan dev; **Alembic wajib**
sebelum produksi.

## Endpoint

Semua endpoint pengguna memerlukan `X-Device-Id`. `/v1/admin/*` dan
`/v1/webhooks/*` tidak memerlukannya.

### Auth (publik)

| Method | Path | Keterangan |
|---|---|---|
| POST | `/v1/auth/login/start` | Cek perangkat: `PIN` (tepercaya) atau `OTP` |
| POST | `/v1/auth/otp/request` | Minta OTP (`LOGIN`/`REGISTER`/`FORGOT_PIN`) |
| POST | `/v1/auth/otp/verify` | Verifikasi OTP → `verification_token` |
| POST | `/v1/auth/otp/resend` | Kirim ulang OTP |
| POST | `/v1/auth/register` | Daftar langkah 1 (anti-enumerasi) |
| POST | `/v1/auth/register/complete` | Daftar langkah 2 (201) |
| POST | `/v1/auth/login/pin` | Login PIN (token dari `login/start`/OTP) |
| POST | `/v1/auth/biometric/challenge` | Challenge biometrik |
| POST | `/v1/auth/login/fingerprint` | Login sidik jari |
| POST | `/v1/auth/login/face` | Login wajah |
| POST | `/v1/auth/token/refresh` | Rotasi token |
| POST | `/v1/auth/logout` | Keluar (Bearer); `all_devices` opsional |
| POST | `/v1/auth/pin/reset` | Lupa PIN |
| POST | `/v1/auth/phone-recovery` | Mulai pemulihan (akun KYC) |
| POST | `/v1/auth/phone-recovery/{id}/face` | Verifikasi wajah |
| POST | `/v1/auth/phone-recovery/{id}/phone` | OTP nomor baru |
| POST | `/v1/auth/phone-recovery/{id}/complete` | Selesai |
| POST | `/v1/auth/phone-recovery/support` | Ajukan pemulihan tanpa KYC |
| POST | `/v1/auth/phone-recovery/support/submit` | Kirim pengajuan (201) |

### Profil & keamanan (Bearer)

| Method | Path | Keterangan |
|---|---|---|
| GET / PATCH | `/v1/me` | Profil |
| POST / DELETE | `/v1/me/avatar` | Foto profil |
| POST | `/v1/me/pin/change` | Ganti PIN (sesi lain dicabut) |
| POST | `/v1/me/pin/verify` | PIN → `pin_token` (120 detik) |
| GET | `/v1/me/biometrics` | Status biometrik |
| POST | `/v1/me/biometrics/fingerprint` | Daftarkan sidik jari (201) |
| POST | `/v1/me/biometrics/face` | Daftarkan wajah (201) |
| DELETE | `/v1/me/biometrics/{type}` | Hapus biometrik |
| PATCH | `/v1/me/biometrics/settings` | Aktifkan login biometrik |
| GET | `/v1/me/devices` | Perangkat aktif |
| DELETE | `/v1/me/devices/{device_id}` | Keluarkan perangkat |
| DELETE | `/v1/me/devices` | Keluarkan semua perangkat lain |
| PUT | `/v1/me/devices/current/push-token` | Simpan push token |
| GET | `/v1/me/security/activities` | 50 aktivitas terakhir |

### Admin

| Method | Path | Keterangan |
|---|---|---|
| POST | `/v1/admin/auth/login` | Password → challenge + `next_step` |
| POST | `/v1/admin/auth/password/change` | Ganti password (challenge/Bearer) |
| POST | `/v1/admin/auth/2fa/setup` | Buat rahasia TOTP baru |
| POST | `/v1/admin/auth/2fa/enable` | Konfirmasi TOTP → token sesi |
| POST | `/v1/admin/auth/2fa/verify` | TOTP login normal |
| POST | `/v1/admin/auth/token/refresh` | Rotasi token admin |
| POST | `/v1/admin/auth/logout` | Keluar |
| GET | `/v1/admin/me` | Profil + permission |
| GET | `/v1/admin/admins` | Daftar admin |
| POST | `/v1/admin/admins` | Buat admin + password sementara (201) |
| PATCH | `/v1/admin/admins/{id}` | Ubah peran/status |
| GET | `/v1/admin/roles` | Peran + izin |
| GET | `/v1/admin/settings` | Pengaturan (`prefix`) |
| PUT | `/v1/admin/settings/{key}` | Ubah dengan `version` + `reason` |
| GET | `/v1/admin/users` | Cari pengguna (masked) |
| GET | `/v1/admin/recovery-requests` | Antrean pemulihan |
| POST | `/v1/admin/recovery-requests/{id}/decision` | Setujui/tolak |
| GET | `/v1/admin/audit-logs` | Filter + cursor pagination |

### Webhook Fonnte

| Method | Path | Keterangan |
|---|---|---|
| POST | `/v1/webhooks/fonnte/{secret}/status` | Update status pesan |
| POST | `/v1/webhooks/fonnte/{secret}/device` | Device connect/disconnect |

## Login perangkat tepercaya

`POST /auth/login/start` selalu membalas 200 dengan bentuk sama:

- Perangkat dikenal & tepercaya → `method="PIN"`, `verification_token`
  (purpose `LOGIN`, terikat `device_id`), `preferred_method`, dan daftar
  `available_methods` (PIN/FINGERPRINT/FACE).
- Perangkat baru / nomor tidak dikenal → `method="OTP"`, token `null`,
  daftar metode kosong. Waktu respons disamakan 200–600 ms.

Token dari `login/start` ditolak (`DEVICE_MISMATCH`) bila dipakai dengan
`device_id` berbeda. Kepercayaan dicabut saat logout semua perangkat, reset
PIN, pemulihan nomor, perangkat dikeluarkan, refresh token dipakai ulang,
atau perangkat idle melewati `security.trusted_device_idle_days` (90 hari).
Logout satu perangkat **tidak** mencabut kepercayaan perangkat itu.

## Anti-enumerasi & batas laju

- `otp/request` `LOGIN`/`FORGOT_PIN` untuk nomor tak terdaftar tetap 200,
  tetapi tidak mengirim WhatsApp; `otp/verify` selalu `OTP_INVALID`.
- `register` untuk nomor terdaftar tetap 200 dan mengirim **pemberitahuan**
  (bukan OTP).
- Batas OTP (di `app_settings`): 5/jam per nomor, 10/jam per perangkat,
  20/jam per IP. Sesi palsu ikut dihitung; `OTP_RATE_LIMITED` tidak
  menyebut cakupan mana yang terlampaui.

## Pemulihan nomor tanpa KYC

1. `POST /auth/phone-recovery/support` → OTP ke nomor baru (purpose
   `CHANGE_PHONE`), respons selalu sukses meski nomor lama tidak ada.
2. `POST .../support/submit` → tiket `rcv_...`; jika nomor lama cocok,
   `users.recovery_hold=true`.
3. Admin melihat antrean (`GET /admin/recovery-requests`, izin
   `recovery.review`) dan memutuskan lewat `.../decision`.
4. `APPROVE` mengganti nomor, mencabut semua sesi + kepercayaan perangkat,
   melepas hold, mengisi `transfer_blocked_until` (+`recovery.cooldown_hours`,
   default 24 jam), dan mengirim notifikasi ke nomor baru.

`recovery_hold`/`transfer_blocked_until` sudah tersimpan; penolakan transaksi
keluar (`ACCOUNT_RESTRICTED`) menunggu endpoint uang Fase 3.

## Pencabutan token (Redis)

Klaim access token: `sub`, `sid` (= `refresh_tokens.family_id`), `did`,
`iat`, `exp`, `jti`. Saat sesi dicabut:

| Kunci | Isi | TTL |
|---|---|---|
| `rev:sid:<family_id>` | `1` | umur access token |
| `rev:user:<user_id>` | epoch `iat_before` | umur access token |

Setiap request terautentikasi memeriksa kedua kunci. Token yang dicabut
membalas `401 UNAUTHORIZED` (bukan `TOKEN_EXPIRED`). Bila Redis tidak bisa
dihubungi: endpoint baca **fail-open** dengan peringatan, endpoint uang
(prefix `/v1/transfers`, `/v1/topup`, `/v1/ppob`, `/v1/payment-requests`)
**fail-closed**. Isi `REDIS_URL` di produksi; Docker Compose sudah menyiapkan
Redis 7.

## PIN per perangkat & attestation

- PIN salah 5x pada satu perangkat → `PIN_LOCKED` 15 menit; kunci berulang
  naik 1 jam lalu 24 jam. Perangkat lain tidak ikut terkunci.
- 15 PIN salah dalam 1 jam (lintas perangkat) → `ACCOUNT_LOCKED`; pulihkan
  lewat Lupa PIN/OTP.
- Attestation: kirim `X-Attestation-Provider` (`PLAY_INTEGRITY`/`APP_ATTEST`)
  dan `X-Attestation`. Aktifkan `security.attestation_required` di produksi.
  Verifier saat ini **mock**: token `att_valid_*` dianggap sah.

## Pengaturan awal (`app_settings`)

| Kunci | Default |
|---|---|
| `security.trusted_device_idle_days` | 90 |
| `security.pin.max_attempts` | 5 |
| `security.pin.lock_minutes` | 15 |
| `security.pin.account_max_attempts_hour` | 15 |
| `security.attestation_required` | false |
| `otp.rate.per_phone_hour` / `per_device_hour` / `per_ip_hour` | 5 / 10 / 20 |
| `otp.provider_healthy` | true |
| `recovery.cooldown_hours` | 24 |
| `limits.balance_cap.BASIC` / `PREMIUM` | 2 jt / 20 jt |

Ubah lewat `PUT /admin/settings/{key}` dengan `version` (optimistic
concurrency) dan `reason`; perubahan dicatat di audit log `before`/`after`.

## Integrasi WhatsApp (Fonnte)

```dotenv
OTP_PROVIDER=fonnte
FONNTE_TOKEN=xxxxxxxxxxxxxxxx
FONNTE_BASE_URL=https://api.fonnte.com
FONNTE_TIMEOUT_SECONDS=8
FONNTE_WEBHOOK_SECRET=<32+ karakter acak>
FONNTE_ALLOWED_IPS=            # opsional, pisahkan koma
```

- Setiap pengiriman mencatat metadata di `whatsapp_messages`
  (`provider_msg_id`, `requestid`, status, failure reason). **Isi pesan dan
  kode OTP tidak disimpan/dilog.**
- `reason: target invalid` → `OTP_TARGET_NOT_WHATSAPP` (422); token/kuota/
  timeout/5xx → `OTP_PROVIDER_UNAVAILABLE` (503, `retry_after=30`).
- Pengiriman gagal membatalkan sesi dan tidak dihitung ke batas laju;
  `resend_count` tidak bertambah.
- Webhook status idempoten dan tidak menurunkan status dari `SENT`.
- Device `disconnect` → `otp.provider_healthy=false` + audit `SYSTEM`;
  OTP langsung 503 sampai `connect`.
- Daftarkan URL di dashboard Fonnte:
  `https://<host>/v1/webhooks/fonnte/<secret>/status` dan `.../device`.

## Deploy ke Vercel

Production: **https://poinqu-backend.vercel.app**

- Vercel mendeteksi FastAPI lewat `main.py` di root (`from app.main import app`);
  region `sin1`, `maxDuration` 60 detik (`vercel.json`).
- Database: **Neon Postgres** dan **Upstash Redis** lewat Vercel Marketplace;
  `DATABASE_URL` dan `REDIS_URL` di-inject otomatis.
- Environment manual yang perlu ada: `JWT_SECRET`, `ENVIRONMENT=production`,
  `DEBUG=false`, `ADMIN_*`, `OTP_PROVIDER=fonnte`, `FONNTE_TOKEN`,
  `FONNTE_WEBHOOK_SECRET`, `CORS_ORIGINS`, `MEDIA_BASE_URL`.
- Skema database dibuat sekali; produksi memakai `AUTO_CREATE_TABLES=false`.
- Webhook Fonnte:
  `https://poinqu-backend.vercel.app/v1/webhooks/fonnte/<FONNTE_WEBHOOK_SECRET>/status`
  dan `.../device`.
- Kredensial admin yang digenerate saat deploy ada di `.env.vercel.production`
  (lokal, sudah di-ignore) dan di Vercel Environment Variables tipe Config.
- Avatar di Vercel memakai `/tmp/avatars` dan **ephemeral**; pindahkan ke
  Vercel Blob/S3 untuk produksi.
- Preview deployment memakai Deployment Protection; alias production publik.
  Cold start ±15 detik, request hangat ±0,3 detik (Fluid Compute).
- Deploy ini dibuat dari CLI lokal. Project Vercel terhubung ke repo GitHub
  `poinqu-backend` (masih template); untuk auto-deploy berikutnya, hubungkan
  repo `poinqu-fastapi` ke project atau push kode ke repo yang terhubung.

## Format respons

Sukses:

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {},
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Gagal:

```json
{
  "success": false,
  "code": "PIN_INVALID",
  "message": "PIN salah.",
  "details": { "attempts_left": 3 },
  "meta": { "request_id": "req_41bd77a0c1", "timestamp": "2026-10-18T05:31:00Z" }
}
```

Error validasi menambahkan `errors: [{ field, code, message }]`. Pada 429
tersedia header `Retry-After` dan `details.retry_after`.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

**58 test** mencakup: OTP (salah/kedaluwarsa/limit/resend), anti-enumerasi,
login perangkat tepercaya + kedaluwarsa idle, PIN per perangkat & kunci
bertingkat, rotasi/reuse refresh token, pencabutan access token, verification
token sekali pakai, device binding, biometrik, attestation, pemulihan nomor
(KYC & pengajuan admin), avatar, admin password/2FA/kelola admin/peran/
settings/pengguna/audit, serta Fonnte (payload, error, timeout, webhook,
higiene log). Tes Fonnte memakai `httpx.MockTransport` (tanpa kuota).

## Catatan implementasi (perlu diketahui sebelum produksi)

- **JWT HS256** (satu secret); dokumen contoh memakai EdDSA.
- **Attestation masih mock** (`att_valid_*`); sambungkan Play Integrity /
  App Attest sebelum produksi.
- **Alert Fonnte** baru berupa log `critical`; integrasikan ke kanal ops.
- **recovery_hold/transfer_blocked_until** belum menolak transaksi karena
  endpoint uang baru ada di fase berikutnya.
- **Liveness & eKYC mock** (`lv_...`); `KycProfile` menyimpan hash NIK +
  tanggal lahir untuk pemulihan KYC.
- **Avatar lokal** di `media/avatars`; ganti object storage.
- **Rate limit** OTP/PIN/recovery memakai tabel DB; Redis hanya untuk
  pencabutan token. Rate limit umum per-IP perlu ditambah di gateway/WAF.
- **Status HTTP admin**: mengikuti kode error; beberapa status sedikit
  berbeda dari tabel dokumen (mis. kredensial admin 401, lock 423), app
  bergantung pada `code`.
- `AUTO_CREATE_TABLES` + rekonsiliasi kolom hanya untuk dev; gunakan Alembic.
- Waktu disimpan UTC (naive) dan diserialisasi ISO 8601 `Z`.
- Nominal uang fase berikutnya wajib integer rupiah, bukan float.
