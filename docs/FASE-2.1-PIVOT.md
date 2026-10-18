# FASE 2.1 — Pivot Produk & Rework Auth

Status: **draft keputusan** · 18 Oktober 2026

> **Status:** change spec untuk **Fase 2.1**. Area yang tercakup di sini
> mengalahkan `FASE-2-API.md`. Log keputusan tunggal ada di `DECISIONS.md`;
> indeks dokumen ada di `README.md`.

Dokumen ini merangkum perubahan Fase 2 setelah pivot dari **dompet digital**
menjadi **penjualan pulsa & PPOB**. Tujuannya supaya backend, app, dan admin
memakai kontrak yang sama sebelum Fase 3 dilanjutkan.

---

## 1. Keputusan produk

- Produk utama: **penjualan pulsa dan PPOB**, bukan dompet digital.
- **Wallet + top-up dipertahankan** sebagai saldo prabayar untuk pembelian
  PPOB.
- **Batas nominal top-up diatur admin di database**; default tanpa batas
  maksimum.
- **KYC dan Premium dihapus**; tidak ada face liveness, KTP, atau admin KYC.
- **Domain final `poinqu`** (deep link `poinqu://`, web `https://poinqu.id`).
- **Email wajib saat register**; OTP register tetap via WhatsApp.
- **Verifikasi email memakai OTP** dan dikirim lewat **SMTP**.
- **Ganti nomor HP**: PIN + OTP ke nomor baru via WhatsApp + notifikasi email.
- **Ganti email**: PIN + OTP ke email baru via SMTP + notifikasi kontak lama.
- **Recovery backend dihapus total**, bukan hanya disembunyikan dari app.
- Regulasi e-money tidak lagi menjadi fokus utama; tetap perlu review untuk
  penyimpanan saldo/top-up bila fitur itu dipertahankan.
- **Biometric wajah dihapus**; sidik jari tetap.
- **Scan QR dan transfer** hanya pajangan/coming soon; belum berfungsi.
- **Pemulihan akun (Lost Phone) dihapus dari app** karena login bisa memakai
  nomor HP atau email.
- Fase 2 tetap menjadi fondasi auth, perangkat, PIN, profil, admin, dan
  keamanan.

---

## 2. Alur auth target

### 2.1 Register

1. User mengisi **nama, nomor HP, email, gender, setuju syarat**.
2. OTP register dikirim ke **WhatsApp** (bukan email).
3. User verifikasi OTP.
4. User membuat PIN baru.
5. Konfirmasi PIN.
6. Akun dibuat; user langsung login.
7. Email berstatus **belum terverifikasi** (opsional diverifikasi nanti).

Catatan: email ditambahkan sebagai identitas login/cadangan, bukan kanal OTP
register.

### 2.2 Login

Dua metode:

**A. Nomor HP**

1. `login/start` dengan nomor HP.
2. OTP dikirim ke WhatsApp.
3. Verifikasi OTP.
4. PIN.
5. Home.

**B. Email**

1. `login/start` dengan email.
2. Jika email **sudah terverifikasi**, OTP dikirim ke email.
3. Jika email belum terverifikasi/tidak dikenal, respons tetap generik
   (anti-enumerasi) tetapi tidak ada OTP yang bisa dipakai.
4. Verifikasi OTP.
5. PIN.
6. Home.

Perangkat tepercaya tetap boleh langsung PIN/fingerprint tanpa OTP, dengan
syarat perangkat dan token valid. Ini tidak berubah dari Fase 2.

### 2.3 Lupa PIN

Dua metode:

- Nomor HP → OTP WhatsApp.
- Email terverifikasi → OTP email.
- OTP benar → PIN baru → konfirmasi PIN → login ulang.

Email yang belum terverifikasi tidak bisa dipakai untuk lupa PIN.

### 2.4 Verifikasi email (opsional)

- Jika `email_verified_at` kosong, Home menampilkan banner/badge.
- User dapat meminta OTP verifikasi ke email.
- Setelah OTP benar, `email_verified_at` diisi.
- Email terverifikasi bisa dipakai untuk:
  - login,
  - lupa PIN,
  - pergantian nomor HP di halaman akun.
- Verifikasi email tidak wajib untuk memakai app.

### 2.5 Ganti nomor HP

- Dilakukan dari halaman akun (sudah login).
- Wajib PIN/step-up sesuai kebijakan.
- OTP dikirim ke **nomor baru** via WhatsApp.
- Email terverifikasi menerima notifikasi perubahan.
- Nomor lama (jika masih aktif) juga menerima notifikasi.
- Setelah sukses, sesi perangkat lain dicabut; perangkat saat ini tetap.

### 2.6 Ganti email

- Dilakukan dari halaman akun (sudah login).
- Wajib PIN/step-up.
- OTP dikirim ke **email baru**.
- Setelah OTP benar, email diganti dan langsung terverifikasi.
- Email lama menerima notifikasi.
- Email baru harus unik dan belum dipakai akun lain.
- Setelah sukses, email baru bisa dipakai login/lupa PIN.

### 2.7 Hapus pemulihan akun

- App menghapus layar `LostPhone` dan seluruh pemanggilan
  `/auth/phone-recovery*`.
- Backend: endpoint recovery dapat **dihapus** atau ditandai deprecated.
  Rekomendasi: hapus dari router app; simpan kode/admin recovery hanya bila
  masih dibutuhkan operasional.

---

## 3. Perubahan kontrak API

### 3.1 Register

`POST /auth/register`

```json
{
  "name": "Koko",
  "phone": "081234567890",
  "email": "koko@example.com",
  "gender": "MALE",
  "accept_terms": true
}
```

Validasi:

- `email`: wajib, format valid, unik (case-insensitive).
- OTP tetap dikirim ke WhatsApp.
- Respons sama seperti Fase 2 (`OtpRequestData`), ditambah `target_type` dan
  `masked_identifier` bila app memerlukannya.

### 3.2 Login start

`POST /auth/login/start`

```json
{
  "identifier": "koko@example.com",
  "device_id": "dev_and_91ab3c"
}
```

Aturan:

- `identifier` boleh nomor HP atau email; backend mendeteksi dari format.
- Respons selalu 200 dengan bentuk sama untuk nomor/email dikenal maupun
  tidak dikenal.
- `method` tetap `PIN` atau `OTP`.
- `target_type`: `PHONE` atau `EMAIL`.
- `masked_identifier`: nomor/email yang disamarkan.
- `verification_token` hanya terisi untuk perangkat tepercaya.
- Email yang belum terverifikasi diperlakukan seperti target tidak valid:
  tidak mengirim OTP, tetapi respons tetap generik.

### 3.3 Minta OTP

`POST /auth/otp/request`

```json
{
  "identifier": "081234567890",
  "purpose": "LOGIN"
}
```

- `identifier` nomor HP → kanal `WHATSAPP`.
- `identifier` email → kanal `EMAIL` (hanya jika email terverifikasi).
- `purpose`: `LOGIN`, `REGISTER`, `FORGOT_PIN`, `VERIFY_EMAIL`,
  `CHANGE_EMAIL`, `CHANGE_PHONE`.
- `CHANGE_PHONE` hanya lewat endpoint perubahan nomor, bukan endpoint publik.
- Respons menambahkan `target_type`, `masked_identifier`, dan `channel`.

### 3.4 Verifikasi OTP

`POST /auth/otp/verify`

Body tetap:

```json
{ "otp_session_id": "otp_Qm81xZ3a", "code": "482913" }
```

`next_step`:

- `LOGIN` → `PIN`
- `REGISTER` → `SET_PIN`
- `FORGOT_PIN` → `NEW_PIN`
- `VERIFY_EMAIL` → `EMAIL_VERIFIED`
- `CHANGE_PHONE` → `COMPLETE`
- `CHANGE_EMAIL` → `COMPLETE`

### 3.5 Kirim ulang OTP

`POST /auth/otp/resend` tetap memakai `otp_session_id`. Kanal mengikuti sesi.

### 3.6 Verifikasi email

`POST /me/email/verification/request` · Auth: Bearer

- Mengirim OTP ke email user saat ini.
- Jika email sudah terverifikasi → `EMAIL_ALREADY_VERIFIED` [usulan].
- Rate limit per email/device.

`POST /me/email/verification/verify` · Auth: Bearer

```json
{ "otp_session_id": "otp_...", "code": "482913" }
```

- Set `email_verified_at`.
- Buat security event/notifikasi.

### 3.7 Ganti nomor HP

`POST /me/phone/change/request` · Auth: Bearer

```json
{ "new_phone": "081298765432", "pin_token": "pt_..." }
```

- Wajib PIN token purpose `CHANGE_PHONE` (atau field `pin_token`).
- Cek nomor baru belum dipakai.
- Kirim OTP ke **nomor baru** via WhatsApp; jangan kirim OTP ke nomor lama.

`POST /me/phone/change/confirm` · Auth: Bearer

```json
{ "change_id": "chg_...", "otp_session_id": "otp_...", "code": "482913" }
```

- Set nomor baru, cabut sesi perangkat lain.
- Kirim notifikasi ke email terverifikasi dan nomor lama bila memungkinkan.

### 3.8 Ganti email

`POST /me/email/change/request` · Auth: Bearer

```json
{ "new_email": "koko.baru@example.com", "pin_token": "pt_..." }
```

- Wajib PIN token purpose `CHANGE_EMAIL` (atau field `pin_token`).
- Cek email baru belum dipakai.
- Kirim OTP ke **email baru** via SMTP; jangan kirim OTP ke email lama.

`POST /me/email/change/confirm` · Auth: Bearer

```json
{ "change_id": "chg_...", "otp_session_id": "otp_...", "code": "482913" }
```

- Set email baru + `email_verified_at`.
- Kirim notifikasi ke email lama.
- Sesi perangkat lain tidak perlu dicabut.

### 3.9 Profil

`GET /me` dan respons login menambahkan:

```json
{
  "email": "koko@example.com",
  "email_verified": false,
  "email_verified_at": null
}
```

`PATCH /me` tidak lagi mengubah email langsung; email hanya lewat alur
verifikasi di 3.8. Karena KYC dihapus, tidak ada `NAME_LOCKED`; nama boleh
diubah kapan saja lewat profil.

### 3.10 Biometrik

- Hapus `POST /auth/login/face`.
- Hapus `POST /me/biometrics/face`.
- `POST /auth/biometric/challenge` hanya `type = FINGERPRINT`.
- `GET /me/biometrics` hanya mengembalikan `fingerprint` dan `use_for_login`.
- Error `FACE_*` dan `LIVENESS_SESSION_INVALID` dihapus karena face/KYC
  dihapus.
- `INVALID_BIOMETRIC_TYPE` tetap dipakai untuk tipe selain `FINGERPRINT`.
- Tabel `user_biometrics` tetap menyimpan data lama `FACE`, tetapi API tidak
  menerima pendaftaran baru.

### 3.11 Scan & transfer

- App: tombol scan dan menu transfer menjadi `COMING_SOON`/disabled.
- Backend: tidak ada endpoint transfer baru di Fase 2.1.
- Route/screen boleh tetap ada untuk masa depan, tetapi tidak dipanggil.

---

## 4. Perubahan skema database

```sql
-- Identitas email
ALTER TABLE users
  ADD COLUMN email_verified_at timestamptz;

-- Email dipakai untuk login: normalisasi lowercase + unique.
CREATE UNIQUE INDEX users_email_lower_unique
  ON users (lower(email))
  WHERE email IS NOT NULL;

-- OTP generik: phone atau email.
ALTER TABLE otp_sessions
  ADD COLUMN target varchar(150),
  ADD COLUMN target_type varchar(10) NOT NULL DEFAULT 'PHONE'
    CHECK (target_type IN ('PHONE','EMAIL')),
  ADD COLUMN channel varchar(10) NOT NULL DEFAULT 'WHATSAPP'
    CHECK (channel IN ('WHATSAPP','EMAIL'));

-- Backfill data lama
UPDATE otp_sessions SET target = phone WHERE target IS NULL;

ALTER TABLE otp_sessions ALTER COLUMN phone DROP NOT NULL;
CREATE INDEX ON otp_sessions (target, created_at);

-- Log pengiriman email (metadata saja, tanpa isi/kode).
CREATE TABLE email_messages (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  otp_session_id  uuid REFERENCES otp_sessions(id),
  email           varchar(150) NOT NULL,
  provider        varchar(20) NOT NULL, -- RESEND/SMTP/SENDGRID
  provider_msg_id varchar(100),
  status          varchar(20) NOT NULL DEFAULT 'QUEUED',
  failure_reason  text,
  sent_at         timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- Perubahan nomor/email.
CREATE TABLE contact_change_requests (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id      varchar(32) NOT NULL UNIQUE,
  user_id        uuid NOT NULL REFERENCES users(id),
  type           varchar(10) NOT NULL CHECK (type IN ('PHONE','EMAIL')),
  new_value      varchar(150) NOT NULL,
  status         varchar(12) NOT NULL DEFAULT 'PENDING'
                 CHECK (status IN ('PENDING','VERIFIED','CANCELLED','EXPIRED')),
  otp_session_id uuid REFERENCES otp_sessions(id),
  expires_at     timestamptz NOT NULL,
  completed_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON contact_change_requests (user_id, created_at DESC);
```

Catatan migrasi:

- `phone` lama tetap dipertahankan; kode baru memakai `target`/`target_type`.
- Email lama `NULL` diperbolehkan untuk data existing; pendaftaran baru wajib
  email.
- `email_verified_at` hanya diisi setelah OTP email berhasil.
- `FACE` di `user_biometrics` tidak dihapus agar data lama tetap valid.

---

## 5. Email Gateway

Perlu adapter baru:

```python
class EmailGateway(Protocol):
    def send_otp(self, email: str, code: str) -> SendResult: ...
    def send_notification(self, email: str, subject: str, text: str) -> SendResult: ...
```

Konfigurasi:

| Variabel | Keterangan |
| --- | --- |
| `EMAIL_PROVIDER` | `RESEND`, `SENDGRID`, atau `SMTP` |
| `EMAIL_FROM` | Alamat pengirim |
| `EMAIL_API_KEY` | API key provider |
| `EMAIL_SMTP_*` | Bila memakai SMTP |
| `EMAIL_TIMEOUT_SECONDS` | Timeout pengiriman |

Aturan:

- Isi email OTP tidak disimpan di database/log.
- Kode OTP hanya ada di email dan hash di `otp_sessions`.
- Kegagalan kirim email tidak boleh membocorkan keberadaan akun.
- Rate limit per email + per device + per IP.
- Template OTP email: subjek + teks tanpa tautan/login otomatis.

---

## 6. Anti-enumerasi

- `login/start` dengan email/nomor tidak dikenal atau email belum terverifikasi
  harus mengembalikan bentuk respons yang sama.
- `otp/request` untuk email belum terverifikasi membuat sesi OTP palsu
  (decoy) tanpa mengirim email.
- `otp/resend` untuk decoy tetap mengikuti cooldown/limit.
- Register dengan email/phone yang sudah terdaftar tidak mengembalikan kode
  khusus; kirim notifikasi bila memungkinkan.
- Jangan pernah mengirim OTP ke email yang belum terverifikasi.

---

## 7. Dampak ke Fase 3

Keputusan final (D-09, D-10, D-13, D-14, D-16):

- **Wallet + top-up dipertahankan** sebagai saldo prabayar untuk pembelian
  PPOB.
- **KYC dihapus**. Tidak ada Premium, `kyc_submissions`, `/me/kyc`, admin
  KYC, KTP/selfie storage, atau face liveness KYC.
- Fase 3 berisi:
  1. wallet/ledger + saldo,
  2. top-up Duitku VA/QRIS,
  3. read bootstrap (transaksi, katalog Home, notifikasi),
  4. katalog/inquiry/transaksi PPOB.
- Batas nominal top-up diatur admin di database; default tanpa batas
  maksimum.
- Transfer/scan tetap ditunda (D-03).
- Level wallet disederhanakan menjadi BASIC; tidak ada PREMIUM/KYC.
- Limit saldo (bila ada) admin-configurable, bukan dari level KYC.

Dokumen Fase 3 lama sudah dihapus dan akan disusun ulang mengikuti keputusan
ini.

---

## 8. Yang tetap dari Fase 2

- PIN 6 digit, Argon2id, PIN token.
- Perangkat tepercaya dan `login/start`.
- Fingerprint (bukan face).
- Refresh token rotation + revocation.
- Admin 2FA/RBAC/audit.
- Fonnte untuk OTP WhatsApp.
- Settings berversi.
- Security events.

---

## 9. Keputusan

Semua keputusan Fase 2.1 sudah **CONFIRMED** di `DECISIONS.md`:

- D-18 email wajib saat register.
- D-19 email OTP via SMTP.
- D-20 ganti nomor HP: PIN + OTP ke nomor baru.
- D-21 ganti email: PIN + OTP ke email baru.
- D-22 recovery backend dihapus.

Yang masih terbuka hanya untuk Fase 3/ops: D-24 (Duitku sandbox), D-31
(SMTP from/limit), D-32 (minimum top-up).

---

## 10. Urutan kerja yang disarankan

1. Update `FASE-2-API.md` menjadi **Fase 2.1** (auth email/phone, tanpa face,
   tanpa recovery).
2. Update skema + migrasi Alembic.
3. Implementasi email gateway SMTP + OTP generic.
4. Implementasi endpoint email verification + change phone/email.
5. Hapus endpoint/tabel recovery.
6. Update app: register email, login method switch, forgot PIN method,
   home banner, account change, hapus LostPhone/face, scan/transfer disabled.
7. Baru lanjut Fase 3: wallet + top-up + PPOB, tanpa KYC.
