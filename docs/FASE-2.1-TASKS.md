# TASKS — Fase 2.1 (Pondasi: Auth Email/HP & Pivot PPOB)

Status: **checklist implementasi** · 18 Oktober 2026

Kerjakan ini **sebelum** Fase 3. Semua keputusan mengacu ke `DECISIONS.md`.
Dokumen kontrak: `FASE-2-API.md` + `FASE-2.1-PIVOT.md`.

---

## 0. Sprint 0 — Safety net & Alembic

**Status:** selesai (CI hijau, 18 Oktober 2026).

- [x] Tambah Alembic + baseline schema Fase 2 (`alembic/versions/0001_baseline.py`).
- [x] Tambah workflow CI `.github/workflows/tests.yml`.
- [x] Tambah panduan dev tanpa Docker/admin (`docs/DEV-SETUP.md`).
- [x] Jalankan `pytest` baseline sampai hijau (GitHub Actions).
- [x] Verifikasi `alembic upgrade head` dari DB kosong (GitHub Actions).
- [ ] Backup/export data recovery & KYC yang masih ada (jika ada).
- [ ] Buat branch `feat/fase-2.1-auth` untuk implementasi (opsional; saat ini main).

---

## 1. Database & migrasi

**Status:** selesai untuk schema (CI hijau, 19 Oktober 2026). Validation/API email menyusul Sprint 3.

- [x] `users.email` wajib untuk user baru; data lama boleh `NULL` (validasi API menyusul Sprint 3).
- [x] Tambah `users.email_verified_at`.
- [x] Unique index `lower(email)` untuk email tidak null.
- [x] `otp_sessions`: tambah `target`, `target_type` (`PHONE`/`EMAIL`),
      `channel` (`WHATSAPP`/`EMAIL`); `phone` boleh null.
- [x] Backfill `target = phone`, `target_type = PHONE` untuk data lama.
- [x] Tabel `email_messages` (metadata pengiriman, tanpa isi/kode).
- [x] Tabel `contact_change_requests` (PHONE/EMAIL, status, OTP, expiry).
- [x] Refactor `OtpSession`/service OTP ke `target`/`target_type` (phone lama tetap didukung).
- [ ] Hapus router/tabel recovery setelah backup:
      `phone_recoveries`, `recovery_requests`, `recovery_hold`,
      `transfer_blocked_until` (bila tidak dipakai).
- [ ] Hapus KYC: `kyc_profiles`, `kyc_status`, `level=PREMIUM` dari alur
      aktif; tabel `kyc_submissions` tidak dibuat.
- [ ] `user_biometrics.type` hanya menerima `FINGERPRINT` untuk data baru;
      data lama `FACE` dibiarkan historis.
- [ ] Migrasi wajib lewat Alembic, bukan `AUTO_CREATE_TABLES`.

---

## 2. Email gateway SMTP

**Status:** selesai (gateway + test; kredensial SMTP staging menyusul).

- [x] Konfigurasi `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
      `SMTP_FROM`, `SMTP_USE_TLS`, `SMTP_TIMEOUT_SECONDS`.
- [x] Adapter `EmailGateway.send_otp(email, code)`.
- [x] Adapter `EmailGateway.send_notification(email, subject, text)`.
- [x] Simpan metadata ke `email_messages`; jangan simpan isi/kode.
- [x] Timeout + mapping error ke `OTP_PROVIDER_UNAVAILABLE`.
- [x] Rate limit email/device/IP (menggunakan counter target).
- [x] Template OTP dan notifikasi.
- [ ] Uji kirim email nyata di staging (SMTP kredensial).

---

## 3. Auth publik

**Status:** login/register/lupa PIN HP/email selesai (CI hijau, 19 Oktober 2026).
Penghapusan face/recovery/KYC menyusul Sprint 5.

- [x] `POST /auth/register`: tambah `email` wajib, cek unik, OTP ke WA.
- [x] `POST /auth/login/start`: `identifier` HP/email; respons generik.
- [x] `POST /auth/otp/request`: target HP/email; email hanya jika verified.
- [x] `POST /auth/otp/resend`: ikut target/channel sesi; decoy tetap kena
      cooldown/limit.
- [ ] `POST /auth/otp/verify`: `next_step` untuk `VERIFY_EMAIL`,
      `CHANGE_PHONE`, `CHANGE_EMAIL` (Sprint 4).
- [x] `POST /auth/pin/reset`: via OTP HP/email verified.
- [ ] Hapus `POST /auth/login/face`.
- [ ] Hapus seluruh route `/auth/phone-recovery*`.
- [ ] Hapus `/me/kyc*` dan admin KYC.
- [ ] Hapus `/me/biometrics/face`; challenge hanya FINGERPRINT.

---

## 4. Akun & kontak

**Status:** selesai (CI hijau, 19 Oktober 2026).

- [x] `GET /me`: tambah `email_verified`, `email_verified_at`.
- [x] `POST /me/email/verification/request` (OTP ke email).
- [x] `POST /me/email/verification/verify`.
- [x] `POST /me/phone/change/request`: PIN token `CHANGE_PHONE` + OTP ke
      nomor baru via WA.
- [x] `POST /me/phone/change/confirm`.
- [x] `POST /me/email/change/request`: PIN token `CHANGE_EMAIL` + OTP ke
      email baru via SMTP.
- [x] `POST /me/email/change/confirm`.
- [x] Notifikasi ke kontak lama/email terverifikasi.
- [x] `PATCH /me` tidak boleh mengubah email langsung.
- [ ] Hapus `NAME_LOCKED` (KYC dihapus); nama boleh diubah (Sprint 5).

---

## 5. App React Native

- [ ] Register: field email wajib.
- [ ] Login: pilihan metode HP/email; kirim `identifier`.
- [ ] Lupa PIN: pilihan HP/email.
- [ ] Home: banner verifikasi email.
- [ ] Akun: ganti nomor HP dan email.
- [ ] Hapus layar `LostPhone` dan pemanggilan recovery.
- [ ] Hapus UI face: login/enrollment; sisakan fingerprint.
- [ ] Scan dan transfer: coming soon/disabled.
- [ ] Perbaiki `refreshClient` agar mengirim `X-Device-Id`.
- [ ] Perbaiki format public key biometrik (PEM vs base64 DER).
- [ ] `UNAUTHORIZED` → logout.
- [ ] Samakan deep link `poinqu://` + `https://poinqu.id`.
- [ ] Satukan peta error `src/api/errors.ts` + `src/lib/errors.ts`.

---

## 6. Test wajib

- [ ] Register email wajib; email duplikat ditolak.
- [ ] OTP register ke WA, bukan email.
- [ ] Login HP → OTP WA; login email terverifikasi → OTP SMTP.
- [ ] Login email belum terverifikasi → respons generik, tidak kirim OTP.
- [ ] Lupa PIN HP/email; email belum verified ditolak generik.
- [ ] Verifikasi email OTP; status berubah.
- [ ] Ganti nomor HP: PIN + OTP nomor baru; notifikasi.
- [ ] Ganti email: PIN + OTP email baru; notifikasi.
- [ ] Recovery endpoint 404/tidak ada.
- [ ] Face endpoint 404/tidak ada.
- [ ] Fingerprint masih berfungsi.
- [ ] Anti-enumerasi email/HP.
- [ ] Rate limit OTP email/HP/device/IP.
- [ ] Refresh token dengan `X-Device-Id` berhasil.
- [ ] Scan/transfer tidak bisa dipanggil dari UI.

---

## 7. Definition of Done Fase 2.1

- [ ] App bisa register/login/lupa PIN lewat HP atau email.
- [ ] Email wajib saat register; verifikasi email opsional dan bisa dipakai
      untuk login/lupa PIN/ganti nomor.
- [ ] Ganti nomor dan email berjalan dengan OTP ke kontak baru.
- [ ] Tidak ada face biometric, recovery, KYC, atau admin KYC.
- [ ] Scan/transfer tampil coming soon.
- [ ] Wallet/top-up belum diimplementasikan (Fase 3).
- [ ] Semua test backend/app lulus.
- [ ] Dokumen `FASE-2-API.md` dan `FASE-2.1-PIVOT.md` sudah disinkronkan.

---

## 8. Setelah Fase 2.1

Baru mulai Fase 3:

- Wallet/ledger + top-up Duitku (VA/QRIS).
- Read bootstrap: transaksi, katalog Home, notifikasi.
- Katalog/inquiry/transaksi PPOB.
- Tanpa KYC; semua pembelian dari saldo wallet.
- Batas saldo wallet Rp5.000.000 (admin-configurable).
- Batas top-up admin DB; default tanpa maksimum.
