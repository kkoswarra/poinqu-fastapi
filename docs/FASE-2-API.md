# PLAN API — Fase 2: Fondasi (Auth, PIN, Perangkat, Biometrik, Profil, Admin Auth)

Versi dokumen 0.3 · 18 Oktober 2026 · pelengkap `PLAN.md` v0.4

> **Status:** kontrak **baseline Fase 2** yang sudah berjalan.
>
> Perubahan setelah pivot ke pulsa/PPOB — auth email/nomor HP, hapus biometric
> wajah, hapus recovery di app, perubahan nomor/email, serta **KYC dihapus** —
> diatur di **`FASE-2.1-PIVOT.md`**. Wallet + top-up tetap dipakai.
> Jika ada pertentangan, **FASE-2.1 menang** untuk area yang tercakup.
>
> Indeks dokumen: `docs/README.md`. Log keputusan: `docs/DECISIONS.md`.

Dokumen ini adalah kontrak API Fase 2. Path, nama field, dan bentuk respons **diambil dari kode app React Native** (`src/api/endpoints/*`, `src/api/types/*`, `src/lib/errors.ts`) supaya app cukup mematikan `USE_MOCK` tanpa perubahan lain. Hal yang tidak ada di app (skema database, endpoint admin, kode error tambahan, angka konfigurasi) ditandai **[usulan]**.

Isi: (1) konvensi, (2) daftar lengkap kode error, (3) skema database, (4) endpoint beserta respons sukses dan gagal (bagian H: integrasi WhatsApp gateway Fonnte, H.7: perubahan hasil review yang menggantikan bagian yang bertentangan).

---

## 1. Konvensi

- Base URL: `/v1`. Format JSON UTF-8. Waktu ISO 8601 UTC. Uang berupa integer rupiah.
- Header request (app mengirim otomatis lewat `src/api/client.ts`):

| Header | Keterangan |
| --- | --- |
| `Authorization: Bearer <access_token>` | Wajib untuk semua endpoint kecuali yang bertanda "Publik" |
| `X-Device-Id` | ID perangkat (`dev_<platform>_<hex>`); wajib untuk semua endpoint |
| `X-App-Version`, `X-App-Template-Version` | Versi app dan template SDUI; backend boleh menolak versi lama dengan `UPGRADE_REQUIRED` (426) |
| `X-Pin-Token` | Hanya untuk pendaftaran biometrik (hasil `/me/pin/verify`) |
| `Idempotency-Key` | Wajib untuk POST yang mengubah uang (mulai Fase 3); tidak dipakai di Fase 2 |

- Token: access token berlaku 900 detik; refresh token 30 hari dan dirotasi setiap dipakai. Pemakaian ulang refresh token lama mencabut seluruh keluarga token (`REFRESH_TOKEN_REVOKED`). **[usulan: angka bisa diubah di `app_settings`]**
- Aturan umum **[usulan, bisa diubah di `app_settings`]**: PIN 6 digit, 5 kali salah → kunci 15 menit. OTP 6 digit, berlaku 300 detik, maksimal 5 percobaan, kirim ulang minimal 30 detik dan maksimal 3 kali, maksimal 5 permintaan OTP per nomor per jam.
- Pagination memakai cursor: `{ "pagination": { "next_cursor": "20", "has_more": true, "limit": 20 } }`.

### 1.1 Bentuk respons sukses

HTTP 200 (atau 201 untuk pembuatan). Field `data` berisi payload endpoint; bernilai `null` bila tidak ada.

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {},
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

### 1.2 Bentuk respons gagal

HTTP 4xx/5xx. `code` selalu salah satu dari daftar di bagian 2. `message` berbahasa Indonesia dan boleh ditampilkan langsung (app memakai `ERROR_MESSAGES` sebagai cadangan bila `message` kosong). `errors` hanya ada pada kesalahan validasi. `details` opsional, isinya berbeda per kode (lihat tiap endpoint). Pada 429 backend juga mengirim header `Retry-After` (detik); app membaca header itu atau `details.retry_after`.

```json
{
  "success": false,
  "code": "VALIDATION_ERROR",
  "message": "Data yang dikirim tidak valid.",
  "errors": [
    { "field": "phone", "code": "INVALID_PHONE", "message": "Nomor HP tidak valid." }
  ],
  "details": null,
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Contoh dengan `details` (PIN salah):

```json
{
  "success": false,
  "code": "PIN_INVALID",
  "message": "PIN salah.",
  "details": { "attempts_left": 3 },
  "meta": { "request_id": "req_41bd77a0c1", "timestamp": "2026-10-18T05:31:00Z" }
}
```

### 1.3 Error umum (berlaku di semua endpoint, tidak diulang di tiap endpoint)

| HTTP | Kode | Kapan |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | Header Authorization tidak ada atau token tidak valid |
| 401 | `TOKEN_EXPIRED` | Access token kedaluwarsa; app otomatis memanggil refresh lalu mengulang request satu kali |
| 403 | `ACCOUNT_SUSPENDED` / `ACCOUNT_RESTRICTED` | Akun dibekukan atau dibatasi |
| 403 | `DEVICE_MISMATCH` **[usulan]** | `X-Device-Id` tidak cocok dengan perangkat pada token |
| 422 | `VALIDATION_ERROR` | Body atau query tidak lolos validasi; rincian di `errors[]` |
| 426 | `UPGRADE_REQUIRED` | Versi app di bawah minimum |
| 429 | `RATE_LIMITED` | Terlalu banyak request; ada `Retry-After` |
| 500 | `INTERNAL_ERROR` | Kesalahan server |
| 503 | `SERVICE_UNAVAILABLE` **[usulan]** | Pemeliharaan |

Error jaringan (`NETWORK_ERROR`, `TIMEOUT`) dibuat oleh app sendiri bila tidak ada respons dari server; backend tidak mengirimnya.

---

## 2. Daftar lengkap kode error

Sumber: `src/lib/errors.ts` di app (sudah termasuk kode baru dari penyesuaian aturan v0.4: `BALANCE_LIMIT_EXCEEDED`, `MONTHLY_INCOMING_LIMIT_EXCEEDED`, `TRANSFER_LIMIT_EXCEEDED`, `PREMIUM_REQUIRED`; kode harian dihapus). Kolom HTTP adalah status yang **diusulkan** untuk backend; app hanya bergantung pada `code`, bukan pada status, kecuali 401 (`TOKEN_EXPIRED`, `REFRESH_TOKEN_*`) dan 429.


### 2.1 Auth

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Data yang dikirim tidak valid. |
| `OTP_INVALID` | 422 | Kode OTP salah. |
| `OTP_EXPIRED` | 410 | Kode OTP sudah kedaluwarsa. Minta kode baru. |
| `OTP_SESSION_NOT_FOUND` | 404 | Sesi OTP tidak ditemukan. Minta kode baru. |
| `OTP_ATTEMPTS_EXCEEDED` | 429 | Terlalu banyak percobaan. Minta kode baru. |
| `OTP_RATE_LIMITED` | 429 | Terlalu banyak permintaan OTP. Coba lagi nanti. |
| `OTP_RESEND_TOO_SOON` | 429 | Tunggu sebentar sebelum minta kode lagi. |
| `OTP_RESEND_LIMIT` | 429 | Batas kirim ulang OTP tercapai. |
| `OTP_PROVIDER_UNAVAILABLE` | 503 | Layanan pengiriman OTP sedang gangguan. |
| `PHONE_ALREADY_REGISTERED` | 409 | Nomor HP sudah terdaftar. |
| `PHONE_NOT_REGISTERED` | 404 | Nomor HP belum terdaftar. |
| `PIN_INVALID` | 401 | PIN salah. |
| `PIN_LOCKED` | 423 | PIN terkunci karena terlalu banyak percobaan. |
| `PIN_TOO_WEAK` | 422 | PIN terlalu mudah ditebak. |
| `PIN_MISMATCH` | 422 | PIN dan konfirmasi PIN tidak sama. |
| `PIN_SAME_AS_OLD` | 422 | PIN baru tidak boleh sama dengan PIN lama. |
| `PIN_TOKEN_INVALID` | 401 | Verifikasi PIN diperlukan atau sudah kedaluwarsa. |
| `PIN_TOKEN_EXPIRED` | 401 | Verifikasi PIN kedaluwarsa. |
| `PIN_TOKEN_MISMATCH` | 403 | Verifikasi PIN tidak cocok dengan transaksi ini. |
| `VERIFICATION_TOKEN_INVALID` | 401 | Sesi verifikasi tidak valid. |
| `VERIFICATION_TOKEN_EXPIRED` | 401 | Sesi verifikasi sudah kedaluwarsa. |
| `ACCOUNT_LOCKED` | 423 | Akun dikunci sementara. |
| `ACCOUNT_SUSPENDED` | 403 | Akun dibekukan. Hubungi bantuan. |
| `ACCOUNT_RESTRICTED` | 403 | Akun dibatasi. Hubungi bantuan. |
| `REFRESH_TOKEN_INVALID` | 401 | Sesi tidak valid. Silakan login kembali. |
| `REFRESH_TOKEN_REVOKED` | 401 | Sesi dihentikan. Silakan login kembali. |
| `UNAUTHORIZED` | 401 | Sesi tidak valid. Silakan login kembali. |
| `TOKEN_EXPIRED` | 401 | Access token kedaluwarsa. |

### 2.2 Biometric

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `FACE_NOT_MATCH` | 401 | Wajah tidak cocok. |
| `FACE_NOT_ENROLLED` | 404 | Wajah belum didaftarkan. |
| `FACE_LOCKED` | 423 | Scan wajah dinonaktifkan sementara. |
| `FACE_LIVENESS_FAILED` | 422 | Verifikasi wajah gagal. Ikuti instruksi. |
| `FACE_QUALITY_LOW` | 422 | Kualitas gambar kurang baik. |
| `FACE_KTP_MISMATCH` | 422 | Wajah tidak cocok dengan foto KTP. |
| `BIOMETRIC_NOT_REGISTERED` | 404 | Biometrik belum didaftarkan. |
| `BIOMETRIC_LOCKED` | 423 | Biometrik dinonaktifkan sementara. |
| `BIOMETRIC_SIGNATURE_INVALID` | 401 | Biometrik tidak dikenali. |
| `BIOMETRIC_ALREADY_REGISTERED` | 409 | Biometrik sudah terdaftar. |
| `CHALLENGE_EXPIRED` | 410 | Sesi biometrik berakhir. |
| `INVALID_BIOMETRIC_TYPE` | 422 | Tipe biometrik tidak valid. |
| `NO_BIOMETRIC_REGISTERED` | 404 | Daftarkan biometrik terlebih dahulu. |

### 2.3 Wallet

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `INSUFFICIENT_BALANCE` | 422 | Saldo tidak cukup. |
| `BALANCE_LIMIT_EXCEEDED` | 422 | Saldo melebihi batas maksimal akun. |
| `MONTHLY_INCOMING_LIMIT_EXCEEDED` | 422 | Batas dana masuk bulan ini tercapai. |
| `TRANSFER_LIMIT_EXCEEDED` | 422 | Nominal melebihi batas maksimal transfer. |
| `PREMIUM_REQUIRED` | 403 | Fitur ini hanya untuk akun Premium. |
| `AMOUNT_TOO_LOW` | 422 | Nominal terlalu kecil. |
| `AMOUNT_TOO_HIGH` | 422 | Nominal terlalu besar. |
| `AMOUNT_OUT_OF_RANGE` | 422 | Nominal di luar batas. |
| `TOPUP_NOT_FOUND` | 404 | Data isi saldo tidak ditemukan. |
| `TOPUP_PENDING_LIMIT` | 422 | Kamu punya terlalu banyak kode pembayaran aktif. |
| `TOPUP_ALREADY_PAID` | 409 | Pembayaran sudah diterima. |
| `TOPUP_NOT_CANCELLABLE` | 422 | Kode pembayaran tidak bisa dibatalkan. |
| `TOPUP_EXPIRED` | 410 | Kode pembayaran sudah kedaluwarsa. |
| `CHANNEL_NOT_AVAILABLE` | 503 | Metode ini sedang tidak tersedia. |
| `PAYMENT_PROVIDER_ERROR` | 502 | Gagal membuat kode pembayaran. |
| `CARD_DECLINED` | 422 | Kartu ditolak oleh bank. |
| `CARD_TOKEN_INVALID` | 422 | Data kartu tidak valid. |
| `METHOD_NOT_CARD` | 422 | Kode pembayaran ini bukan metode kartu debit. |

### 2.4 Inquiry

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `CUSTOMER_NOT_FOUND` | 404 | ID pelanggan tidak ditemukan. |
| `RECIPIENT_NOT_FOUND` | 404 | Rekening atau akun penerima tidak ditemukan. |
| `RECIPIENT_NOT_REGISTERED` | 422 | Nomor HP penerima tidak terdaftar di Poinqu. |
| `EWALLET_ACCOUNT_NOT_FOUND` | 404 | Akun e-wallet tidak ditemukan. |
| `NO_BILL_DUE` | 422 | Tidak ada tagihan untuk periode ini. |
| `BILL_ALREADY_PAID` | 409 | Tagihan sudah dibayar. |
| `SELF_TRANSFER_NOT_ALLOWED` | 422 | Tidak bisa transfer ke akun sendiri. |
| `BANK_UNSUPPORTED` | 422 | Bank tujuan belum didukung. |
| `BANK_UNAVAILABLE` | 503 | Bank tujuan sedang gangguan. |
| `PROVIDER_TIMEOUT` | 504 | Penyedia layanan tidak merespons. |
| `SERVICE_COMING_SOON` | 503 | Layanan ini belum tersedia. |

### 2.5 Transaction

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `PREVIEW_NOT_FOUND` | 404 | Data konfirmasi tidak ditemukan. |
| `PREVIEW_EXPIRED` | 410 | Konfirmasi sudah kedaluwarsa. |
| `PRICE_CHANGED` | 422 | Harga berubah. Periksa kembali rincian. |
| `PRODUCT_UNAVAILABLE` | 422 | Produk sedang tidak tersedia. |
| `DUPLICATE_TRANSACTION` | 409 | Transaksi serupa baru saja dibuat. |
| `INQUIRY_NOT_FOUND` | 404 | Data inquiry tidak ditemukan. |
| `INQUIRY_EXPIRED` | 410 | Data tagihan sudah kedaluwarsa. |
| `TRANSACTION_NOT_FOUND` | 404 | Transaksi tidak ditemukan. |
| `RECEIPT_NOT_AVAILABLE` | 422 | Struk belum tersedia. |
| `STEPUP_REQUIRED` | 403 | Transaksi ini memerlukan verifikasi tambahan. |
| `STEPUP_NOT_REQUIRED` | 422 | Transaksi ini tidak memerlukan verifikasi tambahan. |
| `STEPUP_TOKEN_INVALID` | 422 | Verifikasi tambahan tidak valid atau kedaluwarsa. |

### 2.6 Idempotency

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `IDEMPOTENCY_KEY_REQUIRED` | 422 | Header Idempotency-Key wajib diisi. |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Idempotency-Key sudah dipakai untuk transaksi berbeda. |

### 2.7 Promo

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `PROMO_NOT_FOUND` | 404 | Kode promo tidak ditemukan. |
| `PROMO_EXPIRED` | 410 | Promo sudah berakhir. |
| `PROMO_QUOTA_EXHAUSTED` | 422 | Kuota promo sudah habis. |
| `PROMO_USAGE_LIMIT` | 422 | Batas pemakaian promo tercapai. |
| `PROMO_NOT_APPLICABLE` | 422 | Promo tidak berlaku untuk layanan ini. |
| `PROMO_MIN_AMOUNT_NOT_MET` | 422 | Minimal transaksi untuk promo ini belum terpenuhi. |
| `PROMO_INVALID` | 422 | Promo tidak dapat dipakai untuk transaksi ini. |

### 2.8 Points

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `INSUFFICIENT_POINTS` | 422 | Poin tidak cukup. |
| `REWARD_NOT_FOUND` | 404 | Hadiah tidak ditemukan. |
| `REWARD_UNAVAILABLE` | 422 | Hadiah sedang tidak tersedia. |
| `REDEEM_LIMIT_EXCEEDED` | 422 | Batas penukaran poin hari ini tercapai. |

### 2.9 Saved & Reminders

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `SAVED_ALREADY_EXISTS` | 409 | Nomor ini sudah tersimpan. |
| `SAVED_NOT_FOUND` | 404 | Data tersimpan tidak ditemukan. |
| `SAVED_LIMIT_REACHED` | 422 | Maksimal data tersimpan tercapai. |
| `REMINDER_DUPLICATE` | 422 | Pengingat untuk nomor ini sudah ada. |
| `REMINDER_NOT_FOUND` | 404 | Pengingat tidak ditemukan. |
| `REMINDER_LIMIT_REACHED` | 422 | Maksimal pengingat tercapai. |

### 2.10 KYC

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `KYC_ALREADY_VERIFIED` | 409 | Akun sudah Premium. |
| `KYC_PENDING` | 409 | Pengajuan sebelumnya masih diproses. |
| `KYC_NOT_FOUND` | 404 | Data pengajuan tidak ditemukan. |
| `KYC_NOT_DRAFT` | 422 | Pengajuan sudah dikirim sebelumnya. |
| `KYC_DRAFT_EXPIRED` | 410 | Sesi pengisian data berakhir. |
| `NIK_ALREADY_USED` | 409 | NIK sudah terdaftar pada akun lain. |
| `KTP_IMAGE_UNREADABLE` | 422 | Foto KTP tidak terbaca. |
| `KTP_DATA_MISMATCH` | 422 | NIK atau nama tidak sesuai dengan foto KTP. |
| `NAME_LOCKED` | 409 | Nama tidak bisa diubah setelah KTP terverifikasi. |
| `EMAIL_ALREADY_USED` | 409 | Email sudah dipakai akun lain. |

### 2.11 Payment Requests

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `PAYMENT_REQUEST_NOT_FOUND` | 404 | QR minta tidak ditemukan. |
| `PAYMENT_REQUEST_LIMIT_REACHED` | 422 | Terlalu banyak QR aktif. |
| `PAYMENT_REQUEST_ALREADY_PAID` | 409 | Pembayaran sudah diterima. |
| `PAYMENT_REQUEST_NOT_CANCELLABLE` | 422 | QR sudah kedaluwarsa atau dibatalkan. |

### 2.12 Devices

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `DEVICE_NOT_FOUND` | 404 | Perangkat tidak ditemukan. |
| `CANNOT_REMOVE_CURRENT_DEVICE` | 409 | Perangkat yang sedang dipakai tidak bisa dikeluarkan. |
| `NO_OTHER_DEVICES` | 404 | Tidak ada perangkat lain. |
| `AVATAR_NOT_FOUND` | 404 | Foto profil belum ada. |
| `FILE_TOO_LARGE` | 413 | Ukuran file terlalu besar. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Format file tidak didukung. |

### 2.13 Support

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `TICKET_ALREADY_OPEN` | 409 | Sudah ada tiket terbuka untuk transaksi ini. |
| `TICKET_RATE_LIMITED` | 422 | Terlalu banyak tiket. Coba lagi nanti. |

### 2.14 Generic

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `RATE_LIMITED` | 429 | Terlalu banyak permintaan. Coba lagi nanti. |
| `INTERNAL_ERROR` | 500 | Terjadi kesalahan pada server. |
| `NOT_FOUND` | 404 | Data tidak ditemukan. |
| `INVALID_CURSOR` | 422 | Cursor tidak valid. |
| `INVALID_FORMAT` | 422 | Format tidak valid. |
| `INVALID_PHONE` | 422 | Nomor HP tidak valid. |
| `INVALID_CATEGORY` | 422 | Kategori tidak valid. |
| `INVALID_TYPE` | 422 | Tipe tidak valid. |
| `INVALID_VALUE` | 422 | Nilai tidak valid. |
| `INVALID_DATE` | 422 | Format tanggal tidak valid. |
| `INVALID_EMAIL` | 422 | Format email tidak valid. |
| `INVALID_LENGTH` | 422 | Panjang tidak valid. |
| `REQUIRED` | 422 | Wajib diisi. |
| `TOO_SHORT` | 422 | Terlalu pendek. |
| `TOO_LONG` | 422 | Terlalu panjang. |
| `OUT_OF_RANGE` | 422 | Nilai di luar rentang. |
| `NETWORK_ERROR` | — | Tidak dapat terhubung ke server. Periksa koneksimu. |
| `TIMEOUT` | — | Permintaan memakan waktu terlalu lama. |
| `UNKNOWN` | 500 | Terjadi kesalahan. Coba lagi nanti. |

### 2.15 Kode tambahan yang diusulkan untuk Fase 2 (belum ada di app)

Tambahkan ke `ERROR_MESSAGES` di app saat backend dipasang.

| Kode | HTTP | Pesan |
| --- | --- | --- |
| `UPGRADE_REQUIRED` | 426 | Versi aplikasi terlalu lama. Perbarui aplikasi. (dipakai app, belum ada di daftar pesan) |
| `FORBIDDEN` | 403 | Tidak punya izin untuk aksi ini. |
| `DEVICE_MISMATCH` | 403 | Perangkat tidak cocok dengan sesi. |
| `TERMS_NOT_ACCEPTED` | 422 | Syarat dan ketentuan harus disetujui. |
| `PIN_NOT_SET` | 409 | PIN belum dibuat. |
| `VERIFICATION_PURPOSE_MISMATCH` | 403 | Token verifikasi tidak untuk keperluan ini. |
| `RECOVERY_NOT_FOUND` | 404 | Sesi pemulihan tidak ditemukan. |
| `RECOVERY_EXPIRED` | 410 | Sesi pemulihan berakhir. Mulai lagi. |
| `RECOVERY_ATTEMPTS_EXCEEDED` | 429 | Percobaan pemulihan habis. Hubungi bantuan. |
| `RECOVERY_STEP_INVALID` | 409 | Langkah pemulihan belum bisa dilakukan. |
| `PHONE_SAME_AS_CURRENT` | 422 | Nomor baru sama dengan nomor lama. |
| `LIVENESS_SESSION_INVALID` | 422 | Sesi verifikasi wajah tidak valid atau kedaluwarsa. |
| `ADMIN_CREDENTIALS_INVALID` | 401 | Email atau password admin salah. |
| `ADMIN_2FA_REQUIRED` | 401 | Kode 2FA diperlukan. |
| `ADMIN_2FA_INVALID` | 401 | Kode 2FA salah. |
| `ADMIN_LOCKED` | 423 | Akun admin dikunci sementara. |
| `SERVICE_UNAVAILABLE` | 503 | Layanan sedang pemeliharaan. |
| `OTP_TARGET_NOT_WHATSAPP` | 422 | Nomor ini tidak terdaftar di WhatsApp. |
| `DEVICE_ATTESTATION_FAILED` | 403 | Perangkat gagal diverifikasi keamanannya. |
| `ADMIN_PASSWORD_WEAK` | 422 | Password admin terlalu lemah. |
| `ADMIN_PASSWORD_CHANGE_REQUIRED` | 403 | Ganti password terlebih dahulu. |
| `ADMIN_NOT_FOUND` | 404 | Admin tidak ditemukan. |
| `ADMIN_EMAIL_ALREADY_USED` | 409 | Email admin sudah dipakai. |
| `ROLE_NOT_FOUND` | 404 | Peran tidak ditemukan. |
| `CANNOT_MODIFY_SELF` | 409 | Tidak bisa mengubah akun admin sendiri. |
| `LAST_SUPERADMIN` | 409 | Harus ada minimal satu superadmin aktif. |
| `SETTING_NOT_FOUND` | 404 | Pengaturan tidak ditemukan. |
| `SETTING_VERSION_CONFLICT` | 409 | Pengaturan sudah diubah orang lain. Muat ulang. |
| `SETTING_VALUE_INVALID` | 422 | Nilai pengaturan tidak valid. |
| `RECOVERY_REQUEST_NOT_FOUND` | 404 | Pengajuan pemulihan tidak ditemukan. |
| `RECOVERY_REQUEST_ALREADY_DECIDED` | 409 | Pengajuan sudah diputuskan. |

Total kode di app: 142. Tambahan usulan: 31.


---

## 3. Skema database Fase 2 [usulan]

PostgreSQL 16. Primary key UUID (`gen_random_uuid()`), `created_at` dan `updated_at` (timestamptz) di semua tabel. ID yang tampil ke app diberi prefiks (`usr_`, `dev_`, `otp_`, dst.) di lapisan API.

```sql
CREATE TYPE user_level   AS ENUM ('BASIC','PREMIUM');
CREATE TYPE user_status  AS ENUM ('ACTIVE','LOCKED','SUSPENDED');
CREATE TYPE kyc_status   AS ENUM ('NONE','DRAFT','PENDING','VERIFIED','REJECTED');
CREATE TYPE otp_purpose  AS ENUM ('LOGIN','REGISTER','FORGOT_PIN','CHANGE_PHONE','STEPUP');

CREATE TABLE users (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone            varchar(16) NOT NULL UNIQUE,          -- format 08xxxxxxxxxx
  name             varchar(100) NOT NULL,
  email            varchar(150) UNIQUE,
  gender           varchar(6) CHECK (gender IN ('MALE','FEMALE')),
  avatar_key       text,
  level            user_level  NOT NULL DEFAULT 'BASIC',
  kyc_status       kyc_status  NOT NULL DEFAULT 'NONE',
  status           user_status NOT NULL DEFAULT 'ACTIVE',
  pin_hash         text,                                   -- Argon2id
  pin_failed_count smallint NOT NULL DEFAULT 0,
  pin_locked_until timestamptz,
  biometric_login  boolean NOT NULL DEFAULT false,         -- use_for_login
  terms_accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE devices (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id),
  device_id     varchar(64) NOT NULL,                     -- X-Device-Id dari app
  name          varchar(100) NOT NULL,
  platform      varchar(8)  NOT NULL CHECK (platform IN ('IOS','ANDROID','WEB')),
  os_version    varchar(32),
  app_version   varchar(32),
  push_token    text,
  last_ip       inet,
  last_location varchar(100),
  last_active_at timestamptz NOT NULL DEFAULT now(),
  revoked_at    timestamptz,
  UNIQUE (user_id, device_id)
);

CREATE TABLE otp_sessions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone         varchar(16) NOT NULL,
  user_id       uuid REFERENCES users(id),
  purpose       otp_purpose NOT NULL,
  channel       varchar(10) NOT NULL DEFAULT 'WHATSAPP' CHECK (channel = 'WHATSAPP'),
  code_hash     text NOT NULL,
  attempts      smallint NOT NULL DEFAULT 0,
  resend_count  smallint NOT NULL DEFAULT 0,
  context       jsonb,                                     -- mis. data register, recovery_id
  expires_at    timestamptz NOT NULL,
  verified_at   timestamptz,
  last_sent_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE verification_tokens (                         -- hasil OTP verify, sekali pakai
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash  text NOT NULL UNIQUE,
  otp_session_id uuid NOT NULL REFERENCES otp_sessions(id),
  purpose     otp_purpose NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);

CREATE TABLE refresh_tokens (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  device_id   uuid NOT NULL REFERENCES devices(id),
  family_id   uuid NOT NULL,
  token_hash  text NOT NULL UNIQUE,
  expires_at  timestamptz NOT NULL,
  revoked_at  timestamptz,
  replaced_by uuid REFERENCES refresh_tokens(id)
);

CREATE TABLE user_biometrics (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id),
  device_id    uuid NOT NULL REFERENCES devices(id),
  type         varchar(11) NOT NULL CHECK (type IN ('FINGERPRINT','FACE')),
  public_key   text NOT NULL,                              -- verifikasi tanda tangan challenge
  registered_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, device_id, type)
);

CREATE TABLE biometric_challenges (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  device_id   uuid NOT NULL REFERENCES devices(id),
  type        varchar(11) NOT NULL,
  challenge   text NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);

CREATE TABLE pin_tokens (                                  -- hasil /me/pin/verify
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  token_hash  text NOT NULL UNIQUE,
  purpose     varchar(20) NOT NULL,                        -- TRANSACTION | POINT_REDEEM | ENROLL_BIOMETRIC
  preview_id  text,                                        -- terikat ke transaksi (Fase 5)
  expires_at  timestamptz NOT NULL,                        -- 120 detik
  used_at     timestamptz
);

CREATE TABLE phone_recoveries (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id),
  attempts_left   smallint NOT NULL DEFAULT 3,
  liveness_session_id text,
  face_verified   boolean NOT NULL DEFAULT false,
  new_phone       varchar(16),
  expires_at      timestamptz NOT NULL,
  completed_at    timestamptz
);

CREATE TABLE security_events (                             -- untuk /me/security/activities
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  type        varchar(20) NOT NULL,                        -- PIN_FAILED | FACE_FAILED | NEW_DEVICE | PIN_CHANGED | PASSWORD_RESET
  severity    varchar(6)  NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH')),
  device_id   uuid REFERENCES devices(id),
  description text,
  read_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE whatsapp_messages (                          -- log pengiriman OTP lewat Fonnte
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  otp_session_id  uuid REFERENCES otp_sessions(id),
  phone           varchar(16) NOT NULL,
  provider        varchar(10) NOT NULL DEFAULT 'FONNTE',
  provider_msg_id varchar(40),                             -- id[0] dari respons Fonnte
  request_id      bigint,                                  -- requestid dari Fonnte
  status          varchar(20) NOT NULL DEFAULT 'QUEUED',   -- QUEUED | SENT | PENDING | INVALID | FAILED | EXPIRED | PROVIDER_ERROR
  provider_status text,                                    -- nilai status mentah dari webhook
  failure_reason  text,                                    -- reason dari Fonnte bila status:false
  sent_at         timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON whatsapp_messages (provider_msg_id);
-- isi pesan OTP TIDAK disimpan (hanya metadata), supaya kode tidak bocor lewat database/log.

-- Admin
CREATE TABLE roles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(50) UNIQUE NOT NULL);
CREATE TABLE permissions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code varchar(80) UNIQUE NOT NULL);
CREATE TABLE role_permissions (role_id uuid REFERENCES roles(id), permission_id uuid REFERENCES permissions(id), PRIMARY KEY (role_id, permission_id));
CREATE TABLE admins (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         varchar(150) NOT NULL UNIQUE,
  name          varchar(100) NOT NULL,
  password_hash text NOT NULL,                             -- Argon2id
  totp_secret   text,                                      -- terenkripsi
  role_id       uuid NOT NULL REFERENCES roles(id),
  status        varchar(10) NOT NULL DEFAULT 'ACTIVE',
  failed_count  smallint NOT NULL DEFAULT 0,
  locked_until  timestamptz
);
CREATE TABLE admin_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), admin_id uuid NOT NULL REFERENCES admins(id),
  token_hash text NOT NULL UNIQUE, expires_at timestamptz NOT NULL, revoked_at timestamptz, ip inet
);

CREATE TABLE audit_logs (                                  -- append-only
  id          bigserial PRIMARY KEY,
  actor_type  varchar(6) NOT NULL CHECK (actor_type IN ('USER','ADMIN','SYSTEM')),
  actor_id    uuid,
  action      varchar(80) NOT NULL,
  entity      varchar(50),
  entity_id   text,
  before      jsonb,
  after       jsonb,
  ip          inet,
  request_id  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
-- cegah UPDATE/DELETE pada audit_logs lewat trigger atau REVOKE.

CREATE TABLE app_settings (
  key         varchar(80) PRIMARY KEY,
  value       jsonb NOT NULL,
  version     integer NOT NULL DEFAULT 1,
  updated_by  uuid REFERENCES admins(id),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
```

Indeks penting: `devices(user_id)`, `otp_sessions(phone, created_at)`, `refresh_tokens(family_id)`, `audit_logs(actor_type, actor_id, created_at)`, `security_events(user_id, created_at DESC)`.

---

## 4. Endpoint

## A. Autentikasi (Publik kecuali dinyatakan lain)

### 4.1 Minta OTP

`POST /auth/otp/request` · Auth: Publik

Mengirim kode OTP ke WhatsApp. Untuk `LOGIN` dan `FORGOT_PIN` nomor harus sudah terdaftar; untuk `REGISTER` nomor harus belum terdaftar. Untuk `CHANGE_PHONE` dipakai lewat endpoint pemulihan nomor (bagian B), bukan langsung.

**Request**

```json
{
  "phone": "081234567890",
  "purpose": "LOGIN",
  "channel": "WHATSAPP"
}
```

Validasi:

- `phone`: 9–13 digit, diawali 08 atau 62 (backend menormalkan ke 08…)
- `purpose`: `LOGIN` | `FORGOT_PIN` | `REGISTER` | `CHANGE_PHONE`
- `channel`: hanya `WHATSAPP` (default `WHATSAPP`)

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode OTP dikirim.",
  "data": {
    "otp_session_id": "otp_Qm81xZ3a",
    "purpose": "LOGIN",
    "masked_phone": "0812****7890",
    "channel": "WHATSAPP",
    "expires_in": 300,
    "resend_available_in": 30,
    "max_attempts": 5
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `INVALID_PHONE` | Nomor HP tidak valid. | Format nomor salah (juga muncul di `errors[]` bersama `VALIDATION_ERROR`) | — |
| 404 | `PHONE_NOT_REGISTERED` | Nomor HP belum terdaftar. | Purpose `LOGIN`/`FORGOT_PIN` dan nomor belum terdaftar | — |
| 409 | `PHONE_ALREADY_REGISTERED` | Nomor HP sudah terdaftar. | Purpose `REGISTER` dan nomor sudah terdaftar | — |
| 429 | `OTP_RATE_LIMITED` | Terlalu banyak permintaan OTP. Coba lagi nanti. | Lebih dari 5 permintaan OTP per jam untuk nomor ini | `{ "retry_after": 1800 }` |
| 422 | `OTP_TARGET_NOT_WHATSAPP` | Nomor ini tidak terdaftar di WhatsApp. | Fonnte menolak target (`target invalid`) atau status pesan `invalid` | — |
| 503 | `OTP_PROVIDER_UNAVAILABLE` | Layanan pengiriman OTP sedang gangguan. | Fonnte gagal, timeout, device terputus, atau kuota habis (lihat bagian H.3) | — |
| 403 | `ACCOUNT_SUSPENDED` | Akun dibekukan. Hubungi bantuan. | Akun dibekukan | — |

---

### 4.2 Verifikasi OTP

`POST /auth/otp/verify` · Auth: Publik

Memeriksa kode OTP. Bila benar, backend menerbitkan `verification_token` sekali pakai yang terikat pada `purpose` OTP tersebut dan dipakai oleh langkah berikutnya (login PIN, register complete, reset PIN, dsb.).

**Request**

```json
{
  "otp_session_id": "otp_Qm81xZ3a",
  "code": "482913"
}
```

Validasi:

- `code`: tepat 6 digit angka
- `otp_session_id`: wajib

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "verification_token": "vt_c91f0b6a7e24...",
    "purpose": "LOGIN",
    "expires_in": 600,
    "next_step": "PIN",
    "preferred_method": "PIN",
    "available_methods": ["PIN", "FINGERPRINT", "FACE"]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

`next_step`: `PIN` (login), `SET_PIN` (register), `NEW_PIN` (forgot pin). `preferred_method` dan `available_methods` hanya terisi untuk `LOGIN`, berdasarkan biometrik yang terdaftar di perangkat (`X-Device-Id`) dan `use_for_login`.

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `OTP_INVALID` | Kode OTP salah. | Kode salah | `{ "attempts_left": 3 }` |
| 410 | `OTP_EXPIRED` | Kode OTP sudah kedaluwarsa. Minta kode baru. | Lewat 300 detik | — |
| 404 | `OTP_SESSION_NOT_FOUND` | Sesi OTP tidak ditemukan. Minta kode baru. | `otp_session_id` tidak dikenal atau sudah terpakai | — |
| 429 | `OTP_ATTEMPTS_EXCEEDED` | Terlalu banyak percobaan. Minta kode baru. | 5 kali salah; sesi dibatalkan | `{ "retry_after": 900 }` |

---

### 4.3 Kirim ulang OTP

`POST /auth/otp/resend` · Auth: Publik

Membuat kode baru pada sesi OTP yang sama.

**Request**

```json
{
  "otp_session_id": "otp_Qm81xZ3a"
}
```

Validasi:

- `otp_session_id`: wajib

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode OTP dikirim ulang.",
  "data": {
    "otp_session_id": "otp_Qm81xZ3a",
    "expires_in": 300,
    "resend_available_in": 30,
    "resend_remaining": 2
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `OTP_SESSION_NOT_FOUND` | Sesi OTP tidak ditemukan. Minta kode baru. | Sesi tidak ada atau sudah diverifikasi | — |
| 429 | `OTP_RESEND_TOO_SOON` | Tunggu sebentar sebelum minta kode lagi. | Belum lewat 30 detik sejak pengiriman terakhir | `{ "retry_after": 18 }` |
| 429 | `OTP_RESEND_LIMIT` | Batas kirim ulang OTP tercapai. | Sudah 3 kali kirim ulang | — |
| 422 | `OTP_TARGET_NOT_WHATSAPP` | Nomor ini tidak terdaftar di WhatsApp. | Nomor tidak terdaftar di WhatsApp | — |
| 503 | `OTP_PROVIDER_UNAVAILABLE` | Layanan pengiriman OTP sedang gangguan. | Fonnte gagal atau tidak merespons (lihat bagian H) | — |

---

### 4.4 Login dengan PIN

`POST /auth/login/pin` · Auth: Publik (butuh `verification_token` purpose `LOGIN`)

Langkah kedua login setelah OTP. Perangkat didaftarkan atau diperbarui di tabel `devices`. Perangkat baru memicu `security_events` tipe `NEW_DEVICE`.

**Request**

```json
{
  "verification_token": "vt_c91f0b6a7e24...",
  "pin": "123456",
  "device": {
    "device_id": "dev_and_91ab3c",
    "name": "Pixel 8",
    "platform": "ANDROID",
    "os_version": "15",
    "app_version": "1.0.0",
    "push_token": null
  }
}
```

Validasi:

- `pin`: 6 digit angka
- `device.platform`: `IOS` | `ANDROID` | `WEB`
- `device.device_id` harus sama dengan header `X-Device-Id`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil masuk.",
  "data": {
    "user": {
      "id": "usr_01J9Z3K7QX",
      "name": "Koko",
      "phone": "081234567890",
      "email": null,
      "gender": "MALE",
      "avatar_url": null,
      "level": "BASIC",
      "verification_status": "UNVERIFIED",
      "kyc_status": "NONE",
      "points": 0,
      "member_since": "2026-10-18"
    },
    "tokens": {
      "access_token": "eyJhbGciOiJFZERTQSIs...",
      "refresh_token": "rt_9b2e41c7d0aa...",
      "token_type": "Bearer",
      "expires_in": 900,
      "refresh_expires_in": 2592000
    }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak dikenal, sudah dipakai, atau bukan milik nomor ini | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Lewat 600 detik | — |
| 422 | `VERIFICATION_PURPOSE_MISMATCH` | Token verifikasi tidak untuk keperluan ini. | Token bukan untuk `LOGIN` | — |
| 401 | `PIN_INVALID` | PIN salah. | PIN salah | `{ "attempts_left": 3 }` |
| 423 | `PIN_LOCKED` | PIN terkunci karena terlalu banyak percobaan. | 5 kali salah berturut-turut | `{ "retry_after": 900, "locked_until": "2026-10-18T05:45:00Z" }` |
| 423 | `ACCOUNT_LOCKED` | Akun dikunci sementara. | Akun dikunci oleh sistem keamanan | `{ "retry_after": 3600 }` |
| 403 | `ACCOUNT_SUSPENDED` | Akun dibekukan. Hubungi bantuan. | Akun dibekukan | — |

---

### 4.5 Daftar akun (langkah 1)

`POST /auth/register` · Auth: Publik

Menyimpan data pendaftaran sementara di sesi OTP dan mengirim OTP. Akun baru dibuat pada langkah 4.6.

**Request**

```json
{
  "name": "Koko",
  "phone": "081234567890",
  "gender": "MALE",
  "accept_terms": true
}
```

Validasi:

- `name`: 3–100 karakter, huruf dan spasi
- `phone`: 9–13 digit, diawali 08 atau 62 (backend menormalkan ke 08…)
- `gender`: `MALE` | `FEMALE`
- `accept_terms`: harus `true`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode OTP dikirim.",
  "data": {
    "otp_session_id": "otp_Qm81xZ3a",
    "purpose": "REGISTER",
    "masked_phone": "0812****7890",
    "channel": "WHATSAPP",
    "expires_in": 300,
    "resend_available_in": 30,
    "max_attempts": 5
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `TERMS_NOT_ACCEPTED` | Syarat dan ketentuan harus disetujui. | `accept_terms` bukan true | — |
| 409 | `PHONE_ALREADY_REGISTERED` | Nomor HP sudah terdaftar. | Nomor sudah terdaftar | — |
| 429 | `OTP_RATE_LIMITED` | Terlalu banyak permintaan OTP. Coba lagi nanti. | Terlalu banyak permintaan OTP | `{ "retry_after": 1800 }` |
| 422 | `OTP_TARGET_NOT_WHATSAPP` | Nomor ini tidak terdaftar di WhatsApp. | Nomor tidak terdaftar di WhatsApp | — |
| 503 | `OTP_PROVIDER_UNAVAILABLE` | Layanan pengiriman OTP sedang gangguan. | Fonnte gagal atau tidak merespons (lihat bagian H) | — |

---

### 4.6 Selesaikan pendaftaran (langkah 2)

`POST /auth/register/complete` · Auth: Publik (butuh `verification_token` purpose `REGISTER`)

Membuat akun `BASIC`, menyimpan hash PIN, mendaftarkan perangkat, dan langsung mengembalikan token (pengguna otomatis masuk). Status HTTP 201.

**Request**

```json
{
  "verification_token": "vt_77d1e0...",
  "pin": "135790",
  "pin_confirmation": "135790",
  "device": {
    "device_id": "dev_and_91ab3c",
    "name": "Pixel 8",
    "platform": "ANDROID",
    "os_version": "15",
    "app_version": "1.0.0",
    "push_token": null
  }
}
```

Validasi:

- `pin` dan `pin_confirmation`: 6 digit angka
- PIN ditolak bila berurutan (123456), berulang (111111), atau sama dengan 6 digit belakang nomor HP

**Respons sukses** — HTTP 201

```json
{
  "success": true,
  "code": "OK",
  "message": "Pendaftaran berhasil.",
  "data": {
    "user": {
      "id": "usr_01J9Z3K7QX",
      "name": "Koko",
      "phone": "081234567890",
      "email": null,
      "gender": "MALE",
      "avatar_url": null,
      "level": "BASIC",
      "verification_status": "UNVERIFIED",
      "kyc_status": "NONE",
      "points": 0,
      "member_since": "2026-10-18"
    },
    "tokens": {
      "access_token": "eyJhbGciOiJFZERTQSIs...",
      "refresh_token": "rt_9b2e41c7d0aa...",
      "token_type": "Bearer",
      "expires_in": 900,
      "refresh_expires_in": 2592000
    }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid atau sudah dipakai | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 422 | `VERIFICATION_PURPOSE_MISMATCH` | Token verifikasi tidak untuk keperluan ini. | Token bukan untuk `REGISTER` | — |
| 422 | `PIN_MISMATCH` | PIN dan konfirmasi PIN tidak sama. | `pin` ≠ `pin_confirmation` | — |
| 422 | `PIN_TOO_WEAK` | PIN terlalu mudah ditebak. | PIN mudah ditebak | — |
| 409 | `PHONE_ALREADY_REGISTERED` | Nomor HP sudah terdaftar. | Nomor didaftarkan orang lain di antara langkah 1 dan 2 | — |

---

### 4.7 Challenge biometrik

`POST /auth/biometric/challenge` · Auth: Publik (butuh `verification_token` purpose `LOGIN`)

Menerbitkan challenge acak untuk ditandatangani app memakai private key biometrik (tersimpan di Keystore/Secure Enclave). Berlaku 120 detik dan sekali pakai.

**Request**

```json
{
  "verification_token": "vt_c91f0b6a7e24...",
  "type": "FINGERPRINT"
}
```

Validasi:

- `type`: `FINGERPRINT` | `FACE` (default `FINGERPRINT`)
- `device_id`: opsional. Bila tidak dikirim, backend memakai header `X-Device-Id`. Bila dikirim, nilainya harus sama dengan header tersebut.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "challenge_id": "chl_5Tq0aV",
    "challenge": "n8S2m0cV1x...",
    "expires_in": 120
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 404 | `BIOMETRIC_NOT_REGISTERED` | Biometrik belum didaftarkan. | Biometrik `type` belum terdaftar di perangkat ini | — |
| 423 | `BIOMETRIC_LOCKED` | Biometrik dinonaktifkan sementara. | Biometrik dinonaktifkan sementara setelah gagal berulang | `{ "retry_after": 900 }` |

---

### 4.8 Login dengan sidik jari

`POST /auth/login/fingerprint` · Auth: Publik (butuh `verification_token` purpose `LOGIN`)

Backend memverifikasi `signature` terhadap `public_key` terdaftar dan `challenge`.

**Request**

```json
{
  "verification_token": "vt_c91f0b6a7e24...",
  "challenge_id": "chl_5Tq0aV",
  "signature": "MEUCIQDx...",
  "device": {
    "device_id": "dev_and_91ab3c",
    "name": "Pixel 8",
    "platform": "ANDROID",
    "os_version": "15",
    "app_version": "1.0.0",
    "push_token": null
  }
}
```

Validasi:

- `signature`: base64 dari tanda tangan atas `challenge`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil masuk.",
  "data": {
    "user": {
      "id": "usr_01J9Z3K7QX",
      "name": "Koko",
      "phone": "081234567890",
      "email": null,
      "gender": "MALE",
      "avatar_url": null,
      "level": "BASIC",
      "verification_status": "UNVERIFIED",
      "kyc_status": "NONE",
      "points": 0,
      "member_since": "2026-10-18"
    },
    "tokens": {
      "access_token": "eyJhbGciOiJFZERTQSIs...",
      "refresh_token": "rt_9b2e41c7d0aa...",
      "token_type": "Bearer",
      "expires_in": 900,
      "refresh_expires_in": 2592000
    }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 410 | `CHALLENGE_EXPIRED` | Sesi biometrik berakhir. | Challenge lewat 120 detik atau sudah dipakai | — |
| 401 | `BIOMETRIC_SIGNATURE_INVALID` | Biometrik tidak dikenali. | Tanda tangan tidak cocok | — |
| 404 | `BIOMETRIC_NOT_REGISTERED` | Biometrik belum didaftarkan. | Biometrik belum terdaftar | — |
| 423 | `BIOMETRIC_LOCKED` | Biometrik dinonaktifkan sementara. | Terlalu banyak gagal | `{ "retry_after": 900 }` |

---

### 4.9 Login dengan wajah

`POST /auth/login/face` · Auth: Publik (butuh `verification_token` purpose `LOGIN`)

Sama seperti sidik jari; kunci publik wajah didaftarkan lewat `/me/biometrics/face`.

**Request**

```json
{
  "verification_token": "vt_c91f0b6a7e24...",
  "challenge_id": "chl_5Tq0aV",
  "signature": "MEUCIQDx...",
  "device": {
    "device_id": "dev_and_91ab3c",
    "name": "Pixel 8",
    "platform": "ANDROID",
    "os_version": "15",
    "app_version": "1.0.0",
    "push_token": null
  }
}
```

Validasi:

- `signature`: base64 dari tanda tangan atas `challenge`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil masuk.",
  "data": {
    "user": {
      "id": "usr_01J9Z3K7QX",
      "name": "Koko",
      "phone": "081234567890",
      "email": null,
      "gender": "MALE",
      "avatar_url": null,
      "level": "BASIC",
      "verification_status": "UNVERIFIED",
      "kyc_status": "NONE",
      "points": 0,
      "member_since": "2026-10-18"
    },
    "tokens": {
      "access_token": "eyJhbGciOiJFZERTQSIs...",
      "refresh_token": "rt_9b2e41c7d0aa...",
      "token_type": "Bearer",
      "expires_in": 900,
      "refresh_expires_in": 2592000
    }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 410 | `CHALLENGE_EXPIRED` | Sesi biometrik berakhir. | Challenge lewat 120 detik atau sudah dipakai | — |
| 401 | `BIOMETRIC_SIGNATURE_INVALID` | Biometrik tidak dikenali. | Tanda tangan tidak cocok | — |
| 401 | `FACE_NOT_MATCH` | Wajah tidak cocok. | Tanda tangan sah tetapi verifikasi wajah perangkat gagal | — |
| 404 | `BIOMETRIC_NOT_REGISTERED` | Biometrik belum didaftarkan. | Biometrik belum terdaftar | — |
| 423 | `BIOMETRIC_LOCKED` | Biometrik dinonaktifkan sementara. | Terlalu banyak gagal | `{ "retry_after": 900 }` |

---

### 4.10 Perbarui token

`POST /auth/token/refresh` · Auth: Publik (memakai refresh token)

Dipanggil otomatis oleh app saat menerima `TOKEN_EXPIRED`. Refresh token lama langsung tidak berlaku dan diganti yang baru (rotasi). Catatan: path di app adalah `/auth/token/refresh`.

**Request**

```json
{
  "refresh_token": "rt_9b2e41c7d0aa...",
  "device_id": "dev_and_91ab3c"
}
```

Validasi:

- `device_id` harus cocok dengan perangkat pemilik token

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Token diperbarui.",
  "data": {
    "access_token": "eyJhbGciOiJFZERTQSIs...",
    "refresh_token": "rt_9b2e41c7d0aa...",
    "token_type": "Bearer",
    "expires_in": 900,
    "refresh_expires_in": 2592000
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `REFRESH_TOKEN_INVALID` | Sesi tidak valid. Silakan login kembali. | Token tidak dikenal atau sudah kedaluwarsa. App langsung logout. | — |
| 401 | `REFRESH_TOKEN_REVOKED` | Sesi dihentikan. Silakan login kembali. | Token lama dipakai ulang (indikasi pencurian) atau sesi dicabut. Seluruh keluarga token dicabut dan app logout. | — |
| 422 | `DEVICE_MISMATCH` | Perangkat tidak cocok dengan sesi. | `device_id` berbeda dari perangkat token | — |
| 403 | `ACCOUNT_SUSPENDED` | Akun dibekukan. Hubungi bantuan. | Akun dibekukan | — |

---

### 4.11 Keluar

`POST /auth/logout` · Auth: Bearer

Mencabut refresh token perangkat ini; dengan `all_devices: true` mencabut semua perangkat.

**Request**

```json
{
  "all_devices": false
}
```

Validasi:

- `all_devices`: boolean, default `false`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil keluar.",
  "data": null,
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

### 4.12 Reset PIN (lupa PIN)

`POST /auth/pin/reset` · Auth: Publik (butuh `verification_token` purpose `FORGOT_PIN`)

Mengganti PIN setelah OTP. Seluruh sesi di semua perangkat dicabut; pengguna diarahkan login ulang. Event `PIN_CHANGED` dicatat.

**Request**

```json
{
  "verification_token": "vt_3a0c9e...",
  "new_pin": "246810",
  "pin_confirmation": "246810"
}
```

Validasi:

- `new_pin` dan `pin_confirmation`: 6 digit

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "PIN berhasil direset.",
  "data": {
    "redirect": "LOGIN",
    "sessions_revoked": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 422 | `VERIFICATION_PURPOSE_MISMATCH` | Token verifikasi tidak untuk keperluan ini. | Token bukan untuk `FORGOT_PIN` | — |
| 422 | `PIN_MISMATCH` | PIN dan konfirmasi PIN tidak sama. | PIN dan konfirmasi berbeda | — |
| 422 | `PIN_TOO_WEAK` | PIN terlalu mudah ditebak. | PIN mudah ditebak | — |
| 422 | `PIN_SAME_AS_OLD` | PIN baru tidak boleh sama dengan PIN lama. | PIN baru sama dengan PIN lama | — |

---

## B. Pemulihan nomor HP (nomor lama hilang) — Publik

Empat langkah berurutan: mulai (NIK + tanggal lahir) → verifikasi wajah → nomor baru + OTP → selesai. Membutuhkan akun yang sudah KYC (NIK tersimpan). Verifikasi wajah memakai penyedia liveness yang sama dengan KYC (Fase 6); di Fase 2 cukup siapkan antarmuka dan pakai penyedia mock di sisi server.

### 4.13 Mulai pemulihan nomor

`POST /auth/phone-recovery` · Auth: Publik

Mencocokkan NIK dan tanggal lahir dengan data KYC. Jawaban sengaja sama untuk NIK yang tidak ada supaya tidak membocorkan keberadaan akun; gagal dihitung di `attempts_left` per perangkat dan per IP.

**Request**

```json
{
  "nik": "3171234567890001",
  "birth_date": "1995-04-17"
}
```

Validasi:

- `nik`: 16 digit
- `birth_date`: `YYYY-MM-DD`, usia ≥ 17

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "recovery_id": "rec_Lm0aP9",
    "liveness_session_id": "lv_8dK2xQ",
    "expires_in": 900,
    "attempts_left": 3
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `KYC_NOT_FOUND` | Data pengajuan tidak ditemukan. | NIK atau tanggal lahir tidak cocok, atau akun belum KYC | `{ "attempts_left": 2 }` |
| 422 | `RECOVERY_ATTEMPTS_EXCEEDED` | Percobaan pemulihan habis. Hubungi bantuan. | Percobaan habis | `{ "retry_after": 86400 }` |

---

### 4.14 Verifikasi wajah pemulihan

`POST /auth/phone-recovery/{recovery_id}/face` · Auth: Publik

Mencocokkan hasil liveness dengan foto KYC.

**Request**

```json
{
  "liveness_session_id": "lv_8dK2xQ"
}
```

Validasi:

- `liveness_session_id`: wajib

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "recovery_id": "rec_Lm0aP9",
    "face_verified": true,
    "expires_in": 780
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `RECOVERY_NOT_FOUND` | Sesi pemulihan tidak ditemukan. | `recovery_id` tidak ada | — |
| 410 | `RECOVERY_EXPIRED` | Sesi pemulihan berakhir. Mulai lagi. | Sesi berakhir (900 detik) | — |
| 422 | `LIVENESS_SESSION_INVALID` | Sesi verifikasi wajah tidak valid atau kedaluwarsa. | Sesi liveness tidak valid atau kedaluwarsa | — |
| 422 | `FACE_LIVENESS_FAILED` | Verifikasi wajah gagal. Ikuti instruksi. | Liveness gagal | — |
| 422 | `FACE_QUALITY_LOW` | Kualitas gambar kurang baik. | Kualitas gambar kurang | — |
| 422 | `FACE_KTP_MISMATCH` | Wajah tidak cocok dengan foto KTP. | Wajah tidak cocok dengan foto KTP | `{ "attempts_left": 2 }` |
| 422 | `RECOVERY_ATTEMPTS_EXCEEDED` | Percobaan pemulihan habis. Hubungi bantuan. | Percobaan habis | — |

---

### 4.15 Kirim OTP ke nomor baru

`POST /auth/phone-recovery/{recovery_id}/phone` · Auth: Publik

Hanya bisa setelah wajah terverifikasi. Mengirim OTP WhatsApp ke nomor baru (purpose `CHANGE_PHONE`).

**Request**

```json
{
  "new_phone": "081298765432"
}
```

Validasi:

- `phone`: 9–13 digit, diawali 08 atau 62 (backend menormalkan ke 08…)

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode OTP dikirim.",
  "data": {
    "otp_session_id": "otp_Qm81xZ3a",
    "purpose": "CHANGE_PHONE",
    "masked_phone": "0812****5432",
    "channel": "WHATSAPP",
    "expires_in": 300,
    "resend_available_in": 30,
    "max_attempts": 5
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `RECOVERY_NOT_FOUND` | Sesi pemulihan tidak ditemukan. | `recovery_id` tidak ada | — |
| 410 | `RECOVERY_EXPIRED` | Sesi pemulihan berakhir. Mulai lagi. | Sesi berakhir | — |
| 422 | `RECOVERY_STEP_INVALID` | Langkah pemulihan belum bisa dilakukan. | Wajah belum terverifikasi | — |
| 409 | `PHONE_ALREADY_REGISTERED` | Nomor HP sudah terdaftar. | Nomor baru sudah dipakai akun lain | — |
| 422 | `PHONE_SAME_AS_CURRENT` | Nomor baru sama dengan nomor lama. | Nomor baru sama dengan nomor lama | — |
| 429 | `OTP_RATE_LIMITED` | Terlalu banyak permintaan OTP. Coba lagi nanti. | Terlalu banyak permintaan OTP | `{ "retry_after": 1800 }` |
| 422 | `OTP_TARGET_NOT_WHATSAPP` | Nomor ini tidak terdaftar di WhatsApp. | Nomor tidak terdaftar di WhatsApp | — |
| 503 | `OTP_PROVIDER_UNAVAILABLE` | Layanan pengiriman OTP sedang gangguan. | Fonnte gagal atau tidak merespons (lihat bagian H) | — |

---

### 4.16 Selesaikan pemulihan nomor

`POST /auth/phone-recovery/{recovery_id}/complete` · Auth: Publik (butuh `verification_token` purpose `CHANGE_PHONE`)

Mengganti nomor akun dan mencabut semua sesi. Event keamanan dicatat dan notifikasi dikirim ke nomor lama bila masih bisa dihubungi.

**Request**

```json
{
  "verification_token": "vt_b04e1f..."
}
```

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Nomor berhasil diganti.",
  "data": {
    "new_phone": "081298765432",
    "redirect": "LOGIN",
    "sessions_revoked": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `RECOVERY_NOT_FOUND` | Sesi pemulihan tidak ditemukan. | `recovery_id` tidak ada | — |
| 410 | `RECOVERY_EXPIRED` | Sesi pemulihan berakhir. Mulai lagi. | Sesi berakhir | — |
| 422 | `RECOVERY_STEP_INVALID` | Langkah pemulihan belum bisa dilakukan. | Wajah atau OTP nomor baru belum selesai | — |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 422 | `VERIFICATION_PURPOSE_MISMATCH` | Token verifikasi tidak untuk keperluan ini. | Token bukan untuk `CHANGE_PHONE` | — |
| 409 | `PHONE_ALREADY_REGISTERED` | Nomor HP sudah terdaftar. | Nomor diambil akun lain sebelum selesai | — |

---

## C. Profil (Bearer)

### 4.17 Ambil profil

`GET /me` · Auth: Bearer

Mengembalikan profil pengguna saat ini.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "id": "usr_01J9Z3K7QX",
    "name": "Koko",
    "phone": "081234567890",
    "email": null,
    "gender": "MALE",
    "avatar_url": null,
    "level": "BASIC",
    "verification_status": "UNVERIFIED",
    "kyc_status": "NONE",
    "points": 0,
    "member_since": "2026-10-18"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

### 4.18 Ubah profil

`PATCH /me` · Auth: Bearer

Mengubah sebagian field. Nama terkunci setelah KYC terverifikasi.

**Request**

```json
{
  "name": "Koko Wijaya",
  "email": "koko@example.com",
  "gender": "MALE"
}
```

Validasi:

- Semua field opsional, minimal satu harus ada
- `name`: 3–100 karakter
- `email`: format email valid
- `gender`: `MALE` | `FEMALE`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Profil diperbarui.",
  "data": {
    "id": "usr_01J9Z3K7QX",
    "name": "Koko Wijaya",
    "phone": "081234567890",
    "email": "koko@example.com",
    "gender": "MALE",
    "avatar_url": null,
    "level": "BASIC",
    "verification_status": "UNVERIFIED",
    "kyc_status": "NONE",
    "points": 0,
    "member_since": "2026-10-18"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `INVALID_EMAIL` | Format email tidak valid. | Format email salah (bersama `VALIDATION_ERROR`) | — |
| 409 | `EMAIL_ALREADY_USED` | Email sudah dipakai akun lain. | Email dipakai akun lain | — |
| 409 | `NAME_LOCKED` | Nama tidak bisa diubah setelah KTP terverifikasi. | Nama diubah setelah KYC terverifikasi | — |

---

### 4.19 Unggah foto profil

`POST /me/avatar` · Auth: Bearer

Mengunggah foto (maksimal 5 MB, JPEG atau PNG). Backend memeriksa tipe file dari isinya (bukan dari ekstensi), memperkecil gambar, dan menyimpan ke object storage.

**Request**

`multipart/form-data` dengan field `photo`.

Validasi:

- Field form `photo`: file gambar

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Foto profil diperbarui.",
  "data": {
    "avatar_url": "https://cdn.poinqu.id/avatars/usr_01J9Z3K7QX.jpg?v=1760765400"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 413 | `FILE_TOO_LARGE` | Ukuran file terlalu besar. | Lebih dari 5 MB | — |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Format file tidak didukung. | Bukan JPEG atau PNG | — |

---

### 4.20 Hapus foto profil

`DELETE /me/avatar` · Auth: Bearer

Menghapus foto profil.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Foto profil dihapus.",
  "data": {
    "avatar_url": null
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `AVATAR_NOT_FOUND` | Foto profil belum ada. | Belum punya foto profil | — |

---

## D. PIN (Bearer)

### 4.21 Ganti PIN

`POST /me/pin/change` · Auth: Bearer

Mengganti PIN. Sesi di perangkat lain dicabut (perangkat ini tetap masuk).

**Request**

```json
{
  "old_pin": "123456",
  "new_pin": "246810",
  "pin_confirmation": "246810"
}
```

Validasi:

- Semua 6 digit angka

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "PIN berhasil diganti.",
  "data": {
    "other_sessions_revoked": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `PIN_INVALID` | PIN salah. | `old_pin` salah | `{ "attempts_left": 3 }` |
| 423 | `PIN_LOCKED` | PIN terkunci karena terlalu banyak percobaan. | Terkunci karena salah berulang | `{ "retry_after": 900 }` |
| 422 | `PIN_MISMATCH` | PIN dan konfirmasi PIN tidak sama. | `new_pin` ≠ `pin_confirmation` | — |
| 422 | `PIN_TOO_WEAK` | PIN terlalu mudah ditebak. | PIN baru mudah ditebak | — |
| 422 | `PIN_SAME_AS_OLD` | PIN baru tidak boleh sama dengan PIN lama. | PIN baru sama dengan lama | — |

---

### 4.22 Verifikasi PIN

`POST /me/pin/verify` · Auth: Bearer

Dipanggil sebelum setiap transaksi atau pendaftaran biometrik. Menghasilkan `pin_token` sekali pakai berumur 120 detik. Untuk `TRANSACTION` token terikat ke `preview_id` (Fase 5); backend menolak transaksi bila token tidak ada atau tidak cocok.

**Request**

```json
{
  "pin": "123456",
  "purpose": "TRANSACTION",
  "preview_id": "prv_8Hk2xQ"
}
```

Validasi:

- `pin`: 6 digit
- `purpose`: `TRANSACTION` | `POINT_REDEEM` | `ENROLL_BIOMETRIC`
- `preview_id`: wajib bila purpose `TRANSACTION`
- `reward_id`: wajib bila purpose `POINT_REDEEM`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "PIN benar.",
  "data": {
    "pin_token": "pt_77ac10d9e3...",
    "expires_in": 120
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `PIN_INVALID` | PIN salah. | PIN salah | `{ "attempts_left": 3 }` |
| 423 | `PIN_LOCKED` | PIN terkunci karena terlalu banyak percobaan. | Terkunci | `{ "retry_after": 900 }` |
| 422 | `PIN_NOT_SET` | PIN belum dibuat. | Akun belum punya PIN | — |

---

## E. Biometrik (Bearer)

### 4.23 Status biometrik

`GET /me/biometrics` · Auth: Bearer

Status biometrik di perangkat ini dan pengaturan pemakaian untuk login.

**Request**

Tanpa body. Dihitung berdasarkan `X-Device-Id`.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "fingerprint": { "registered": true, "registered_at": "2026-10-18T05:20:00Z" },
    "face": { "registered": false, "registered_at": null },
    "use_for_login": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

### 4.24 Daftarkan sidik jari

`POST /me/biometrics/fingerprint` · Auth: Bearer + header `X-Pin-Token` (purpose `ENROLL_BIOMETRIC`)

Menyimpan public key yang dibuat di Keystore/Secure Enclave perangkat. Private key tidak pernah meninggalkan perangkat. Status HTTP 201.

**Request**

```json
{
  "device_id": "dev_and_91ab3c",
  "public_key": "MFkwEwYHKoZIzj0CAQYI..."
}
```

Validasi:

- `public_key`: kunci publik ECDSA P-256 base64

**Respons sukses** — HTTP 201

```json
{
  "success": true,
  "code": "OK",
  "message": "Sidik jari terdaftar.",
  "data": {
    "type": "FINGERPRINT",
    "registered_at": "2026-10-18T05:20:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `PIN_TOKEN_INVALID` | Verifikasi PIN diperlukan atau sudah kedaluwarsa. | `X-Pin-Token` tidak ada, salah, atau sudah dipakai | — |
| 401 | `PIN_TOKEN_EXPIRED` | Verifikasi PIN kedaluwarsa. | Lewat 120 detik | — |
| 409 | `BIOMETRIC_ALREADY_REGISTERED` | Biometrik sudah terdaftar. | Sudah terdaftar di perangkat ini | — |
| 422 | `DEVICE_MISMATCH` | Perangkat tidak cocok dengan sesi. | `device_id` ≠ `X-Device-Id` | — |

---

### 4.25 Daftarkan wajah

`POST /me/biometrics/face` · Auth: Bearer + header `X-Pin-Token` (purpose `ENROLL_BIOMETRIC`)

Sama seperti sidik jari, ditambah bukti liveness. Status HTTP 201.

**Request**

```json
{
  "device_id": "dev_and_91ab3c",
  "liveness_session_id": "lv_8dK2xQ",
  "public_key": "MFkwEwYHKoZIzj0CAQYI..."
}
```

Validasi:

- `liveness_session_id`: wajib

**Respons sukses** — HTTP 201

```json
{
  "success": true,
  "code": "OK",
  "message": "Wajah terdaftar.",
  "data": {
    "type": "FACE",
    "registered_at": "2026-10-18T05:22:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `PIN_TOKEN_INVALID` | Verifikasi PIN diperlukan atau sudah kedaluwarsa. | `X-Pin-Token` tidak valid | — |
| 401 | `PIN_TOKEN_EXPIRED` | Verifikasi PIN kedaluwarsa. | Token kedaluwarsa | — |
| 422 | `LIVENESS_SESSION_INVALID` | Sesi verifikasi wajah tidak valid atau kedaluwarsa. | Sesi liveness tidak valid | — |
| 422 | `FACE_LIVENESS_FAILED` | Verifikasi wajah gagal. Ikuti instruksi. | Liveness gagal | — |
| 422 | `FACE_QUALITY_LOW` | Kualitas gambar kurang baik. | Kualitas gambar kurang | — |
| 423 | `FACE_LOCKED` | Scan wajah dinonaktifkan sementara. | Terlalu banyak gagal | `{ "retry_after": 900 }` |
| 409 | `BIOMETRIC_ALREADY_REGISTERED` | Biometrik sudah terdaftar. | Sudah terdaftar di perangkat ini | — |
| 422 | `DEVICE_MISMATCH` | Perangkat tidak cocok dengan sesi. | `device_id` ≠ `X-Device-Id` | — |

---

### 4.26 Hapus biometrik

`DELETE /me/biometrics/{type}` · Auth: Bearer

`type` adalah `FINGERPRINT` atau `FACE`. Bila setelah dihapus tidak ada biometrik tersisa, `use_for_login` otomatis menjadi `false`.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Biometrik dihapus.",
  "data": {
    "type": "FINGERPRINT",
    "use_for_login": false
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `INVALID_BIOMETRIC_TYPE` | Tipe biometrik tidak valid. | `type` bukan FINGERPRINT atau FACE | — |
| 404 | `NO_BIOMETRIC_REGISTERED` | Daftarkan biometrik terlebih dahulu. | Biometrik tersebut belum terdaftar | — |

---

### 4.27 Pengaturan login biometrik

`PATCH /me/biometrics/settings` · Auth: Bearer

Mengaktifkan atau menonaktifkan pemakaian biometrik untuk login.

**Request**

```json
{
  "use_for_login": true
}
```

Validasi:

- `use_for_login`: boolean

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Pengaturan disimpan.",
  "data": {
    "use_for_login": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `NO_BIOMETRIC_REGISTERED` | Daftarkan biometrik terlebih dahulu. | Mengaktifkan saat belum ada biometrik terdaftar | — |

---

## F. Perangkat dan keamanan (Bearer)

### 4.28 Daftar perangkat

`GET /me/devices` · Auth: Bearer

Perangkat yang sedang punya sesi aktif.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "device_id": "dev_and_91ab3c",
        "name": "Pixel 8",
        "platform": "ANDROID",
        "location": "Jakarta, ID",
        "last_active_at": "2026-10-18T05:30:00Z",
        "is_current": true
      },
      {
        "device_id": "dev_ios_c04e7d",
        "name": "iPhone 14",
        "platform": "IOS",
        "location": null,
        "last_active_at": "2026-10-16T19:02:00Z",
        "is_current": false
      }
    ]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

### 4.29 Keluarkan satu perangkat

`DELETE /me/devices/{device_id}` · Auth: Bearer

Mencabut sesi satu perangkat.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Perangkat dikeluarkan.",
  "data": {
    "device_id": "dev_ios_c04e7d"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `DEVICE_NOT_FOUND` | Perangkat tidak ditemukan. | `device_id` tidak ada atau bukan milik pengguna | — |
| 409 | `CANNOT_REMOVE_CURRENT_DEVICE` | Perangkat yang sedang dipakai tidak bisa dikeluarkan. | Perangkat yang sedang dipakai | — |

---

### 4.30 Keluarkan semua perangkat lain

`DELETE /me/devices` · Auth: Bearer

Mencabut sesi semua perangkat selain yang sedang dipakai.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Perangkat lain dikeluarkan.",
  "data": {
    "removed_count": 2
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 404 | `NO_OTHER_DEVICES` | Tidak ada perangkat lain. | Tidak ada perangkat lain | — |

---

### 4.31 Daftarkan push token

`PUT /me/devices/current/push-token` · Auth: Bearer

Menyimpan token notifikasi push perangkat ini.

**Request**

```json
{
  "push_token": "ExponentPushToken[xxxxxxxx]",
  "platform": "ANDROID"
}
```

Validasi:

- `platform`: `IOS` | `ANDROID`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Push token disimpan.",
  "data": null,
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

### 4.32 Aktivitas keamanan

`GET /me/security/activities` · Auth: Bearer

Riwayat kejadian keamanan akun (terbaru dulu, maksimal 50).

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "id": "sec_a81f",
        "type": "NEW_DEVICE",
        "title": "Login dari perangkat baru",
        "description": "Pixel 8 masuk ke akunmu.",
        "device": "Pixel 8",
        "location": "Jakarta, ID",
        "at": "2026-10-18T05:30:00Z",
        "severity": "MEDIUM"
      }
    ],
    "unread_count": 1
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

## G. Admin panel [usulan, belum ada di app]

Panel admin Next.js memakai endpoint terpisah di bawah `/v1/admin`, token terpisah, dan RBAC. Login admin wajib 2FA TOTP. Semua aksi admin dicatat di `audit_logs`.

### 4.33 Login admin (langkah 1)

`POST /admin/auth/login` · Auth: Publik

Memeriksa email dan password. Bila benar, mengembalikan `challenge_token` untuk langkah 2FA (belum ada sesi admin).

**Request**

```json
{
  "email": "owner@poinqu.id",
  "password": "••••••••••"
}
```

Validasi:

- `email`: format email
- `password`: minimal 12 karakter saat dibuat

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Lanjut ke verifikasi 2FA.",
  "data": {
    "challenge_token": "ac_41d8e0c7...",
    "expires_in": 300,
    "twofa_required": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `ADMIN_CREDENTIALS_INVALID` | Email atau password admin salah. | Email atau password salah (pesan sama untuk keduanya) | — |
| 422 | `ADMIN_LOCKED` | Akun admin dikunci sementara. | 5 kali salah; dikunci 15 menit | `{ "retry_after": 900 }` |
| 403 | `ACCOUNT_SUSPENDED` | Akun dibekukan. Hubungi bantuan. | Admin dinonaktifkan | — |

---

### 4.34 Login admin (langkah 2: 2FA)

`POST /admin/auth/2fa/verify` · Auth: Publik (butuh `challenge_token`)

Memverifikasi kode TOTP dan menerbitkan token sesi admin.

**Request**

```json
{
  "challenge_token": "ac_41d8e0c7...",
  "code": "531902"
}
```

Validasi:

- `code`: 6 digit

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil masuk.",
  "data": {
    "admin": {
      "id": "adm_01J9Z5",
      "email": "owner@poinqu.id",
      "name": "Koko",
      "role": "SUPERADMIN",
      "permissions": ["admin.read", "admin.write", "audit.read", "settings.write"]
    },
    "tokens": {
      "access_token": "eyJhbGciOiJFZERTQSIs...",
      "refresh_token": "ar_6f20b19d...",
      "token_type": "Bearer",
      "expires_in": 900,
      "refresh_expires_in": 28800
    }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `ADMIN_2FA_INVALID` | Kode 2FA salah. | Kode TOTP salah atau kedaluwarsa | — |
| 422 | `ADMIN_2FA_REQUIRED` | Kode 2FA diperlukan. | `challenge_token` tidak valid atau kedaluwarsa; ulangi langkah 1 | — |
| 422 | `ADMIN_LOCKED` | Akun admin dikunci sementara. | Terlalu banyak salah | `{ "retry_after": 900 }` |

---

### 4.35 Perbarui token admin

`POST /admin/auth/token/refresh` · Auth: Publik (memakai refresh token admin)

Rotasi token admin, sama seperti pengguna.

**Request**

```json
{
  "refresh_token": "ar_6f20b19d..."
}
```

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Token diperbarui.",
  "data": {
    "access_token": "eyJhbGciOiJFZERTQSIs...",
    "refresh_token": "ar_c1170a54...",
    "token_type": "Bearer",
    "expires_in": 900,
    "refresh_expires_in": 28800
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `REFRESH_TOKEN_INVALID` | Sesi tidak valid. Silakan login kembali. | Token tidak valid atau kedaluwarsa | — |
| 401 | `REFRESH_TOKEN_REVOKED` | Sesi dihentikan. Silakan login kembali. | Token lama dipakai ulang atau sesi dicabut | — |

---

### 4.36 Keluar admin

`POST /admin/auth/logout` · Auth: Bearer admin

Mencabut sesi admin.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil keluar.",
  "data": null,
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |

---

### 4.37 Profil admin

`GET /admin/me` · Auth: Bearer admin

Profil, peran, dan izin admin yang sedang masuk.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "id": "adm_01J9Z5",
    "email": "owner@poinqu.id",
    "name": "Koko",
    "role": "SUPERADMIN",
    "permissions": ["admin.read", "admin.write", "audit.read", "settings.write"]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Token pengguna app dipakai di endpoint admin | — |

---

### 4.38 Audit log

`GET /admin/audit-logs?actor_type=&action=&date_from=&date_to=&cursor=&limit=` · Auth: Bearer admin, izin `audit.read`

Membaca audit log dengan filter dan paginasi cursor (default `limit` 20, maksimal 100). Hanya baca; tidak ada endpoint ubah atau hapus.

**Request**

Tanpa body.

Validasi:

- `date_from`, `date_to`: `YYYY-MM-DD`
- `actor_type`: `USER` | `ADMIN` | `SYSTEM`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "id": 90211,
        "actor_type": "ADMIN",
        "actor_id": "adm_01J9Z5",
        "action": "settings.update",
        "entity": "app_settings",
        "entity_id": "limits.balance_cap.BASIC",
        "before": { "value": 2000000, "version": 3 },
        "after": { "value": 2000000, "version": 4 },
        "ip": "103.10.20.30",
        "request_id": "req_8f3a1c2d9e",
        "created_at": "2026-10-18T05:10:00Z"
      }
    ],
    "pagination": { "next_cursor": "90211", "has_more": true, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Admin tidak punya izin `audit.read` | — |
| 422 | `INVALID_CURSOR` | Cursor tidak valid. | Cursor tidak valid | — |
| 422 | `INVALID_DATE` | Format tanggal tidak valid. | Format tanggal salah | — |

---

## H. Integrasi WhatsApp gateway: Fonnte

Semua OTP (login, daftar, lupa PIN, ganti nomor) dikirim lewat WhatsApp memakai **Fonnte**. Tidak ada SMS atau kanal lain. Bagian ini menjelaskan konfigurasi, cara backend memanggil Fonnte, pemetaan hasilnya ke respons endpoint OTP di atas, dan dua webhook yang menerima kabar dari Fonnte.

Sumber: dokumentasi Fonnte ([kirim pesan](https://docs.fonnte.com/api-send-message/), [status pesan](https://docs.fonnte.com/message-status/), [webhook status pesan](https://docs.fonnte.com/webhook-update-message-status/), [webhook status device](https://docs.fonnte.com/webhook-device-status/), [validasi nomor](https://docs.fonnte.com/api-validate-number/)), dibaca 18 Oktober 2026. Hal yang **tidak** dijelaskan dokumentasi ditandai "belum terverifikasi" dan perlu dites di akun Fonnte kamu.

### H.1 Konfigurasi

Simpan di environment/secret manager, bukan di database atau repositori:

| Variabel | Contoh | Keterangan |
| --- | --- | --- |
| `FONNTE_TOKEN` | `xxxxxxxxxxxxxxxx` | Token device dari dashboard Fonnte. Dikirim di header `Authorization` **tanpa** awalan `Bearer` |
| `FONNTE_BASE_URL` | `https://api.fonnte.com` | |
| `FONNTE_TIMEOUT_SECONDS` | `8` | Timeout permintaan ke Fonnte |
| `FONNTE_WEBHOOK_SECRET` | 32+ karakter acak | Dipakai di URL webhook (lihat H.4) |
| `FONNTE_ALLOWED_IPS` | daftar IP | Opsional; isi bila Fonnte memberi daftar IP pengirim (belum terverifikasi) |

Pengaturan yang boleh diubah admin di `app_settings` **[usulan]**: `otp.message_template`, `otp.provider` (`FONNTE`; ada supaya penyedia bisa diganti lewat adapter tanpa mengubah endpoint), dan ambang peringatan kuota.

Template pesan OTP **[usulan]**. Kode OTP hanya ada di pesan, tidak pernah di log atau database (hanya hash-nya):

```text
{code} adalah kode verifikasi Poinqu kamu. Berlaku {minutes} menit.
Jangan berikan kode ini ke siapa pun, termasuk yang mengaku dari Poinqu.
```

### H.2 Cara backend memanggil Fonnte

Dibuat sebagai adapter `WhatsAppGateway` (satu method `send_otp(phone, text) -> SendResult`), sehingga endpoint OTP tidak tahu detail Fonnte.

`POST https://api.fonnte.com/send`, header `Authorization: <FONNTE_TOKEN>`, body form atau JSON:

| Field | Nilai untuk OTP | Alasan |
| --- | --- | --- |
| `target` | `"081234567890"` (string, satu nomor) | Wajib string; nomor yang sudah dinormalkan |
| `message` | teks OTP dari template | |
| `countryCode` | `"62"` | Default Fonnte; mengganti angka 0 di depan |
| `connectOnly` | `true` | **Penting:** bila device WhatsApp terputus, permintaan ditolak, bukan diantrekan. OTP yang terkirim terlambat (berjam-jam) tidak berguna dan membingungkan |
| `typing` | `false` | Tidak perlu |
| `preview` | `false` | Tidak ada tautan di pesan |

Jangan memakai `delay`, `schedule`, atau `followup` untuk OTP.

**Respons sukses Fonnte** (HTTP 200):

```json
{
  "detail": "success! message in queue",
  "id": ["80367170"],
  "process": "pending",
  "requestid": 2937124,
  "status": true,
  "target": ["6282227097005"]
}
```

`id[0]` disimpan sebagai `whatsapp_messages.provider_msg_id`. Variasi `detail` lain: `success! message will be sent on scheduled time` (tidak dipakai) dan `success! message pending due to server issue, will be sent later`. Untuk kasus terakhir OTP tetap dianggap terkirim, tetapi `resend_available_in` jangan dipersingkat.

**Respons gagal Fonnte** (`status: false`) dan pemetaannya:

| `reason` dari Fonnte | Arti | Dipetakan ke | HTTP ke app |
| --- | --- | --- | --- |
| `target invalid` | Nomor bukan nomor valid | `OTP_TARGET_NOT_WHATSAPP` | 422 |
| `input invalid` | Parameter tidak valid | `OTP_PROVIDER_UNAVAILABLE` + alert (bug di backend kita) | 503 |
| `token invalid` | Token salah atau dicabut | `OTP_PROVIDER_UNAVAILABLE` + **alert kritis** | 503 |
| `insufficient quota` | Kuota pesan habis | `OTP_PROVIDER_UNAVAILABLE` + **alert kritis** | 503 |
| `devices must belong to an account` | Konfigurasi token salah | `OTP_PROVIDER_UNAVAILABLE` + alert | 503 |
| Timeout, 5xx, atau respons bukan JSON | Fonnte tidak sehat | `OTP_PROVIDER_UNAVAILABLE` | 503 |
| Device terputus | Dokumentasi tidak menyebut `reason`-nya untuk `connectOnly: true` (belum terverifikasi) | `OTP_PROVIDER_UNAVAILABLE` + alert | 503 |

Aturan:
- Setiap kegagalan menulis baris `whatsapp_messages` dengan `status = PROVIDER_ERROR` atau `INVALID` dan `failure_reason` berisi `reason` mentah.
- Bila pengiriman gagal, **sesi OTP tidak dihitung** ke batas permintaan per jam supaya pengguna tidak terkunci karena gangguan kita. `resend_count` juga tidak bertambah.
- Tidak ada percobaan ulang otomatis di dalam request pengguna. Satu kali coba, gagal cepat, pengguna bisa menekan kirim ulang. Percobaan ulang otomatis berisiko mengirim dua OTP.
- Timeout `FONNTE_TIMEOUT_SECONDS` lalu anggap gagal; OTP yang mungkin sudah terkirim tidak berbahaya karena kode lama tetap valid pada sesi yang sama.

Status pesan versi Fonnte dan padanannya di `whatsapp_messages.status` ([daftar status](https://docs.fonnte.com/message-status/)):

| Status Fonnte | Arti menurut Fonnte | `status` kita |
| --- | --- | --- |
| `sent` | Pesan berhasil dikirim | `SENT` |
| `processing` | Sedang dikirim | `QUEUED` |
| `pending` | Belum terkirim (device terputus atau gagal proses), dicoba ulang tiap sekitar 1 menit | `PENDING` |
| `waiting` | Terjadwal | `QUEUED` (tidak dipakai OTP) |
| `invalid` | Nomor atau parameter tidak valid | `INVALID` |
| `failed` | Isi pesan tidak bisa diproses server | `FAILED` |
| `expired` | Device terputus sehari penuh, pesan tidak dikirim | `EXPIRED` |
| `url unreachable` | URL lampiran tidak terjangkau | `FAILED` (tidak dipakai OTP) |

Dokumentasi Fonnte tidak menyebut status `delivered` atau `read`; jangan membuat logika yang menunggu status itu.

### H.3 Pengaruh ke endpoint OTP

Endpoint yang mengirim OTP (4.1 `/auth/otp/request`, 4.3 `/auth/otp/resend`, 4.5 `/auth/register`, 4.15 `/auth/phone-recovery/{recovery_id}/phone`) berurutan: (1) validasi dan cek batas, (2) buat sesi OTP di database, (3) panggil Fonnte, (4) bila Fonnte gagal, tandai sesi `dibatalkan` dan kembalikan error. Bila pemanggilan Fonnte sukses, respons ke app tetap persis seperti di bagian masing-masing (tidak ada field Fonnte yang bocor ke app).

Contoh respons gagal saat Fonnte tidak bisa dihubungi (HTTP 503):

```json
{
  "success": false,
  "code": "OTP_PROVIDER_UNAVAILABLE",
  "message": "Layanan pengiriman OTP sedang gangguan.",
  "details": { "retry_after": 30 },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Contoh nomor tidak terdaftar di WhatsApp (HTTP 422):

```json
{
  "success": false,
  "code": "OTP_TARGET_NOT_WHATSAPP",
  "message": "Nomor ini tidak terdaftar di WhatsApp.",
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Opsional **[usulan]**: sebelum mengirim OTP pendaftaran, backend boleh memanggil `POST /validate` Fonnte (`target`, maks. 500 nomor; respons `registered[]` dan `not_registered[]`) untuk memberi tahu pengguna lebih awal bila nomornya tidak punya WhatsApp. Perhatikan dokumentasinya: memanggil `/validate` bersamaan dapat mengganggu pengecekan sebelumnya, jadi panggil satu per satu dan jangan di jalur login.

### H.4 Webhook dari Fonnte ke backend kita

Dua endpoint publik di bawah `/v1/webhooks/fonnte`. URL-nya didaftarkan di dashboard Fonnte (halaman webhook; dokumentasi Fonnte tidak menjelaskan langkahnya, jadi ikuti menu di dashboard). Dokumentasi Fonnte juga **tidak menyebut tanda tangan atau header rahasia**, sehingga pengamanan kita sendiri wajib:

1. Path berisi rahasia: `https://api.poinqu.id/v1/webhooks/fonnte/<FONNTE_WEBHOOK_SECRET>/status` (dibandingkan dengan perbandingan waktu-konstan).
2. Bila Fonnte menyediakan daftar IP pengirim, batasi dengan `FONNTE_ALLOWED_IPS`.
3. Webhook hanya boleh **memperbarui status log** dan memicu alert. Webhook tidak pernah membuat atau memverifikasi OTP, tidak mengubah saldo, dan tidak melakukan aksi finansial, jadi pemalsuan webhook tidak berdampak pada uang.
4. Idempoten: pesan yang sama boleh datang berkali-kali; status hanya boleh maju, tidak mundur dari `SENT`.
5. Selalu balas HTTP 200 untuk payload yang dikenali maupun yang tidak (agar Fonnte tidak mengirim ulang terus), kecuali rahasia salah.

#### H.4.1 Webhook status pesan

`POST /webhooks/fonnte/{secret}/status` · Auth: Publik (rahasia di path)

Request dari Fonnte (field menurut [dokumentasi](https://docs.fonnte.com/webhook-update-message-status/); nilai `status` dan `state` tidak didaftar di dokumentasi, jadi simpan mentah di `provider_status` dan petakan bila cocok dengan tabel H.2):

```json
{
  "device": "6281234567890",
  "id": "80367170",
  "stateid": "3EB0A1B2C3D4",
  "status": "sent",
  "state": "sent"
}
```

Aturan pembaruan mengikuti contoh Fonnte: bila `id` dan `stateid` ada, perbarui status pesan dengan `provider_msg_id = id`; bila hanya `id`, perbarui status; bila hanya `stateid`, cari berdasarkan `stateid` (kolom tambahan `provider_state_id` **[usulan]**, tambahkan bila dipakai).

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Diterima.",
  "data": null,
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal**

| HTTP | `code` | Pesan | Kapan |
| --- | --- | --- | --- |
| 401 | `UNAUTHORIZED` | Sesi tidak valid. Silakan login kembali. | Rahasia di path salah, atau IP pengirim tidak diizinkan |
| 422 | `VALIDATION_ERROR` | Data yang dikirim tidak valid. | Body bukan JSON atau tidak punya `id` maupun `stateid` |

Pesan tidak dikenal (id tidak ada di `whatsapp_messages`) tetap dijawab 200 dan diabaikan.

#### H.4.2 Webhook status device

`POST /webhooks/fonnte/{secret}/device` · Auth: Publik (rahasia di path)

Dipakai untuk mendeteksi nomor WhatsApp pengirim terputus (penyebab utama OTP gagal).

```json
{
  "device": "6281234567890",
  "status": "disconnect",
  "timestamp": "2026-10-18T05:12:00Z",
  "reason": "logged out from phone"
}
```

`status` hanya `connect` atau `disconnect`; `reason` opsional (menurut [dokumentasi](https://docs.fonnte.com/webhook-device-status/)). Efek di backend:
- `disconnect`: tulis `audit_logs` (actor `SYSTEM`, action `whatsapp.device.disconnect`), kirim alert ke developer, dan set flag `otp.provider_healthy = false` di `app_settings`. Selama flag false, endpoint OTP langsung membalas `OTP_PROVIDER_UNAVAILABLE` tanpa menunggu timeout.
- `connect`: set flag kembali `true` dan catat di `audit_logs`.

Respons sukses dan gagal sama seperti H.4.1.

### H.5 Operasional

- **Alert kritis:** `token invalid`, `insufficient quota`, device `disconnect`, atau lebih dari 20% pengiriman OTP gagal dalam 5 menit.
- **Kuota:** Fonnte menolak pengiriman bila kuota habis (`insufficient quota`) dan dokumentasinya tidak menyebut batas kecepatan numerik. Pantau sisa kuota di dashboard Fonnte dan isi ulang sebelum habis; saran: alert di 20% sisa kuota.
- **Satu nomor, satu titik gagal:** satu device Fonnte = satu nomor WhatsApp. Bila terputus, semua login dan pendaftaran berhenti. Siapkan nomor cadangan: Fonnte mengizinkan beberapa token dipisah koma (pengiriman dibagi acak antar device) dan punya [rotator](https://docs.fonnte.com/api-rotator/); evaluasi sebelum rilis.
- **Risiko blokir WhatsApp:** pesan massal atau berulang ke banyak nomor dapat membuat nomor pengirim dibatasi. Batas 5 OTP per nomor per jam dan batas kirim ulang di bagian 1 membantu; jangan memakai `delay` acak sebagai pengganti pembatasan.
- **Log:** simpan hanya metadata di `whatsapp_messages`; jangan pernah mencatat isi pesan atau kode OTP ke log aplikasi.

### H.6 Tes tambahan untuk Fonnte

- Sukses: `id` tersimpan, sesi OTP aktif, respons app sama seperti bagian 4.1.
- Gagal per `reason` pada tabel H.2: kode error ke app benar, `resend_count` dan batas jam tidak bertambah.
- Timeout dan respons rusak: `OTP_PROVIDER_UNAVAILABLE` dalam waktu kurang dari `FONNTE_TIMEOUT_SECONDS` + 1 detik.
- Webhook: rahasia salah → 401; pesan tidak dikenal → 200; status tidak mundur dari `SENT`; `disconnect` mematikan pengiriman OTP sampai `connect`.
- Kode OTP tidak muncul di log, database, atau respons mana pun.
- Gunakan server palsu Fonnte (WireMock atau FastAPI kecil) di CI; tes ke Fonnte asli hanya manual di staging karena memakai kuota.

---


### H.7 Perubahan hasil review

Bagian ini mencatat perubahan setelah review Fase 2. **Bila ada pertentangan dengan bagian 1–4 dan H.1–H.6, H.7 yang berlaku.** Bagian lama sengaja tidak ditulis ulang agar riwayat perubahan terlihat.

Catatan penting: saya **belum melihat kode backend Fase 2 yang sudah kamu tulis**, jadi kolom "dampak ke kode" di bawah adalah perkiraan dari spesifikasi. Cocokkan dengan kodemu; kalau kamu kirim kodenya, saya bisa memeriksa yang mana yang benar-benar perlu diubah.

Keputusan pemilik proyek yang melatarbelakangi:
- Login di perangkat yang sudah dikenal cukup PIN atau biometrik, tanpa OTP. OTP hanya untuk perangkat baru, daftar, lupa PIN, dan ganti nomor.
- Fonnte dipakai dulu; penyedia untuk produksi dipertimbangkan nanti.
- Saran lain dari review disetujui: anti-enumerasi akun, pemulihan nomor untuk akun tanpa KYC, perangkat tepercaya, dan tambahan keamanan.

#### H.7.0 Ringkasan perubahan

| # | Perubahan | Menggantikan | Dampak ke kode backend | Dampak ke app |
| --- | --- | --- | --- | --- |
| 1 | Login tanpa OTP di perangkat tepercaya, endpoint baru `POST /auth/login/start` | Alur login 4.1 → 4.2 → 4.4 untuk perangkat dikenal | Kolom `devices.trusted_at`, endpoint baru, aturan cabut kepercayaan | `LoginScreen` memanggil `login/start` dulu |
| 2 | Anti-enumerasi akun: `/auth/otp/request` dan `/auth/register` selalu membalas sukses | Kode `PHONE_NOT_REGISTERED` dan `PHONE_ALREADY_REGISTERED` di 4.1 dan 4.5 | Ubah cabang validasi di dua endpoint, tambah batas per IP dan perangkat | Kecil: layar tidak membaca dua kode itu secara khusus |
| 3 | Pemulihan nomor untuk akun tanpa KYC lewat pengajuan ke admin, saldo ditahan | Jalur pemulihan 4.13–4.16 yang hanya untuk akun ber-KYC | Tabel `recovery_requests`, 2 endpoint publik + 2 endpoint admin, flag `users.recovery_hold` | Layar `LostPhone` perlu cabang "ajukan ke tim kami" |
| 4 | Fonnte tetap dipakai; daftar syarat sebelum produksi | H.5 | Tidak ada perubahan kode | Tidak ada |
| 5 | Pencabutan token langsung berlaku (`sid` + Redis) | Pencabutan hanya lewat refresh token | Klaim `sid`, middleware cek Redis | Tidak ada |
| 6 | Kunci PIN per perangkat dengan eskalasi | Kunci PIN per akun (bagian 1) | Tabel `pin_attempts`, ubah logika kunci | Tidak ada |
| 7 | Verifikasi integritas perangkat (Play Integrity, App Attest) | `X-Device-Id` saja | Verifier di backend, flag konfigurasi | App mengirim `X-Attestation` |
| 8 | Endpoint admin tambahan (password dan 2FA admin, kelola admin, peran, pengaturan, pencarian pengguna) | Hanya login admin (bagian G) | 10 endpoint baru | Tidak ada (hanya panel admin) |

#### H.7.1 Login tanpa OTP di perangkat tepercaya

**Perangkat tepercaya** adalah baris `devices` dengan `trusted_at` terisi dan belum dicabut. Sebuah perangkat menjadi tepercaya setelah login sukses lewat OTP + PIN, atau setelah `register/complete`.

Kepercayaan dicabut (set `trusted_at = NULL`) saat: keluar dari semua perangkat, reset PIN, pemulihan nomor, perangkat dikeluarkan dari `/me/devices`, `REFRESH_TOKEN_REVOKED` terdeteksi, akun dibekukan, atau perangkat tidak aktif lebih dari `security.trusted_device_idle_days` (default 90). Keluar dari satu perangkat **tidak** mencabut kepercayaan perangkat itu.

Alur baru, memakai ulang endpoint lama sesudah langkah pertama:
1. App memanggil `POST /auth/login/start` dengan nomor dan `device_id`.
2. Bila `method = "PIN"`, respons sudah berisi `verification_token` (purpose `LOGIN`, terikat ke `device_id`), jadi app langsung ke `/auth/login/pin` atau `/auth/biometric/challenge` → `/auth/login/fingerprint|face` **tanpa OTP**.
3. Bila `method = "OTP"`, alurnya seperti sebelumnya: `/auth/otp/request` → `/auth/otp/verify` → `/auth/login/pin`.

Respons `login/start` sengaja **berbentuk sama** untuk nomor yang tidak terdaftar dan untuk perangkat yang tidak dikenal (selalu `OTP`). Dengan begitu endpoint ini tidak membocorkan apakah nomor punya akun. Perangkat tepercaya tidak bisa ditebak karena `device_id` acak dan, bila H.7.7 aktif, dibuktikan dengan attestation.

Token dari `login/start` terikat ke `device_id`. Bila dipakai dengan `device.device_id` berbeda, `/auth/login/pin` membalas `DEVICE_MISMATCH`.

Pengaturan di `app_settings`: `security.trusted_device_idle_days` (90).


#### H.7-E1 Mulai login (cek perangkat)

`POST /auth/login/start` · Auth: Publik

Menentukan apakah login cukup PIN/biometrik (perangkat tepercaya) atau perlu OTP. Selalu membalas HTTP 200 dengan bentuk data yang sama, apa pun status nomor.

**Request**

```json
{
  "phone": "081234567890",
  "device_id": "dev_and_91ab3c"
}
```

Validasi:

- `phone`: 9–13 digit, diawali 08 atau 62 (backend menormalkan ke 08…)
- `device_id`: sama dengan header `X-Device-Id`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "method": "PIN",
    "masked_phone": "0812****7890",
    "verification_token": "vt_5e0b7d41a9c2...",
    "expires_in": 600,
    "preferred_method": "FINGERPRINT",
    "available_methods": ["PIN", "FINGERPRINT"]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Contoh `data` untuk perangkat baru atau nomor tidak terdaftar (bentuk identik, tanpa token):

```json
{
  "method": "OTP",
  "masked_phone": "0812****7890",
  "verification_token": null,
  "expires_in": null,
  "preferred_method": null,
  "available_methods": []
}
```

Perubahan di endpoint lama: `/auth/login/pin`, `/auth/biometric/challenge`, `/auth/login/fingerprint`, dan `/auth/login/face` tidak berubah bentuknya. Hanya asal `verification_token` yang bertambah (dari `login/start` selain dari `otp/verify`).

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `INVALID_PHONE` | Nomor HP tidak valid. | Format nomor salah (bersama `VALIDATION_ERROR`) | — |
| 403 | `ACCOUNT_SUSPENDED` | Akun dibekukan. Hubungi bantuan. | Akun dibekukan dan perangkat ini tepercaya | — |
| 423 | `ACCOUNT_LOCKED` | Akun dikunci sementara. | Akun dikunci dan perangkat ini tepercaya | `{ "retry_after": 3600 }` |
| 422 | `DEVICE_ATTESTATION_FAILED` | Perangkat gagal diverifikasi keamanannya. | Attestation gagal bila `security.attestation_required` aktif | — |
| 429 | `RATE_LIMITED` | Terlalu banyak permintaan. Coba lagi nanti. | Batas per IP dan per perangkat terlampaui | `{ "retry_after": 60 }` |

---


#### H.7.2 Anti-enumerasi akun

Tujuan: siapa pun tidak bisa memastikan apakah sebuah nomor punya akun lewat endpoint publik.

Perubahan perilaku:

| Endpoint | Sebelumnya | Sekarang |
| --- | --- | --- |
| `POST /auth/otp/request` purpose `LOGIN` atau `FORGOT_PIN`, nomor tidak terdaftar | 404 `PHONE_NOT_REGISTERED` | HTTP 200 dengan respons yang sama seperti nomor terdaftar (sesi OTP palsu, **tidak ada pesan WhatsApp dikirim**). `otp/verify` pada sesi itu selalu membalas `OTP_INVALID` |
| `POST /auth/register`, nomor sudah terdaftar | 409 `PHONE_ALREADY_REGISTERED` | HTTP 200 dengan respons yang sama. Yang dikirim ke nomor itu adalah pesan WhatsApp pemberitahuan (bukan OTP): "Nomor ini sudah punya akun Poinqu. Silakan masuk, atau pakai Lupa PIN bila perlu." |
| Waktu respons | Berbeda antara jalur ada dan tidak ada | Disamakan: jalur "tidak dikirim" menunggu waktu acak seperti panggilan Fonnte (200–600 ms) |

Kode `PHONE_NOT_REGISTERED` dan `PHONE_ALREADY_REGISTERED` tetap ada di daftar error tetapi **tidak lagi dikembalikan** oleh endpoint OTP publik. Boleh dipakai di tempat yang sudah terautentikasi, misalnya `phone-recovery/{id}/phone` (nomor baru sudah dipakai) karena penelepon sudah lolos verifikasi wajah.

Akibat di app: pesan "nomor belum terdaftar" tidak muncul lagi. Layar login menampilkan "Jika nomor terdaftar, kode telah dikirim ke WhatsApp". Menurut pengecekan kode app, tidak ada layar yang bercabang pada dua kode itu, jadi dampaknya kecil.

Batas laju OTP ditambah dua cakupan selain per nomor (nilai di `app_settings`):

| Cakupan | Batas default | Kunci pengaturan |
| --- | --- | --- |
| Per nomor | 5 per jam | `otp.rate.per_phone_hour` |
| Per perangkat (`X-Device-Id`) | 10 per jam | `otp.rate.per_device_hour` |
| Per IP | 20 per jam | `otp.rate.per_ip_hour` |

Respons `OTP_RATE_LIMITED` tidak menyebut cakupan mana yang terlampaui. Sesi OTP palsu juga dihitung ke batas agar tidak bisa dipakai menguji nomor.

#### H.7.3 Pemulihan nomor untuk akun tanpa KYC

Pemulihan di 4.13–4.16 butuh NIK dan wajah dari KYC. Akun Basic yang belum KYC tidak punya data itu. Kebijakan baru:

- Akun **ber-KYC** memakai alur lama (4.13–4.16).
- Akun **tanpa KYC** mengajukan permintaan ke admin. Pemilik membuktikan penguasaan nomor baru lewat OTP WhatsApp, lalu admin memeriksa identitas secara manual (misalnya selfie dengan kertas bertanggal, riwayat transaksi terakhir, dan nominal saldo).
- Selama pengajuan `PENDING_REVIEW`: **saldo ditahan**. Semua transaksi keluar ditolak dengan `ACCOUNT_RESTRICTED` dan `details.reason = "RECOVERY_PENDING"`. Pengguna tetap bisa login dan melihat saldo.
- Setelah disetujui: nomor diganti, semua sesi dicabut, kepercayaan perangkat dicabut, dan **transaksi keluar ditahan 24 jam** (`users.transfer_blocked_until`, nilai di `recovery.cooldown_hours`), supaya pengambilalihan akun tidak langsung bisa menguras saldo.
- Untuk menghindari enumerasi, dua endpoint publik di bawah selalu membalas sukses meskipun nomor lama tidak ada.

Tabel baru ada di H.7.10.

#### H.7-E2 Ajukan pemulihan tanpa KYC (langkah 1)

`POST /auth/phone-recovery/support` · Auth: Publik

Mengirim OTP WhatsApp ke **nomor baru** (purpose `CHANGE_PHONE`). Selalu membalas sukses, termasuk bila nomor lama tidak terdaftar.

**Request**

```json
{
  "old_phone": "081234567890",
  "new_phone": "081298765432",
  "name": "Koko Wijaya"
}
```

Validasi:

- `old_phone` dan `new_phone`: 9–13 digit, diawali 08 atau 62 (backend menormalkan ke 08…)
- `name`: 3–100 karakter
- `new_phone` ≠ `old_phone`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode OTP dikirim.",
  "data": {
    "otp_session_id": "otp_Qm81xZ3a",
    "purpose": "CHANGE_PHONE",
    "masked_phone": "0812****5432",
    "channel": "WHATSAPP",
    "expires_in": 300,
    "resend_available_in": 30,
    "max_attempts": 5
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `PHONE_SAME_AS_CURRENT` | Nomor baru sama dengan nomor lama. | `new_phone` sama dengan `old_phone` | — |
| 422 | `OTP_TARGET_NOT_WHATSAPP` | Nomor ini tidak terdaftar di WhatsApp. | Nomor baru tidak terdaftar di WhatsApp | — |
| 429 | `OTP_RATE_LIMITED` | Terlalu banyak permintaan OTP. Coba lagi nanti. | Batas OTP terlampaui | `{ "retry_after": 1800 }` |
| 503 | `OTP_PROVIDER_UNAVAILABLE` | Layanan pengiriman OTP sedang gangguan. | Fonnte gagal atau tidak merespons | — |

---

#### H.7-E3 Ajukan pemulihan tanpa KYC (langkah 2)

`POST /auth/phone-recovery/support/submit` · Auth: Publik (butuh `verification_token` purpose `CHANGE_PHONE`)

Mengirim pengajuan ke admin. Bila `old_phone` cocok dengan akun, `users.recovery_hold` diset `true` (saldo ditahan). Respons identik untuk nomor yang tidak cocok. Status HTTP 201.

**Request**

```json
{
  "verification_token": "vt_b04e1f...",
  "last_transaction_hint": "Pulsa Telkomsel 10.000, 12 Oktober",
  "balance_hint": 450000,
  "note": "HP hilang di angkot"
}
```

Validasi:

- `last_transaction_hint`: opsional, maks. 200 karakter
- `balance_hint`: opsional, integer rupiah
- `note`: opsional, maks. 500 karakter

**Respons sukses** — HTTP 201

```json
{
  "success": true,
  "code": "OK",
  "message": "Pengajuan diterima.",
  "data": {
    "ticket_id": "rcv_Zk20aV",
    "status": "PENDING_REVIEW",
    "estimated_hours": 24,
    "balance_on_hold": true
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Bentuk data sama untuk nomor lama yang tidak ditemukan. Nilai `balance_on_hold` dan `status` tetap diisi seperti di atas; pembeda hanya ada di database.

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 401 | `VERIFICATION_TOKEN_INVALID` | Sesi verifikasi tidak valid. | Token tidak valid atau sudah dipakai | — |
| 401 | `VERIFICATION_TOKEN_EXPIRED` | Sesi verifikasi sudah kedaluwarsa. | Token kedaluwarsa | — |
| 422 | `VERIFICATION_PURPOSE_MISMATCH` | Token verifikasi tidak untuk keperluan ini. | Token bukan untuk `CHANGE_PHONE` | — |
| 429 | `RATE_LIMITED` | Terlalu banyak permintaan. Coba lagi nanti. | Terlalu banyak pengajuan dari IP atau perangkat yang sama | `{ "retry_after": 3600 }` |

---

#### H.7-E4 Daftar pengajuan pemulihan (admin)

`GET /admin/recovery-requests?status=&cursor=&limit=` · Auth: Bearer admin, izin `recovery.review`

Antrean pengajuan. Nomor disamarkan; `account_found` memberi tahu admin apakah nomor lama cocok dengan akun.

**Request**

Tanpa body.

Validasi:

- `status`: `PENDING_REVIEW` | `APPROVED` | `REJECTED`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "id": "rcv_Zk20aV",
        "status": "PENDING_REVIEW",
        "name": "Koko Wijaya",
        "old_phone": "0812****7890",
        "new_phone": "0812****5432",
        "account_found": true,
        "last_transaction_hint": "Pulsa Telkomsel 10.000, 12 Oktober",
        "balance_hint": 450000,
        "note": "HP hilang di angkot",
        "created_at": "2026-10-18T05:40:00Z",
        "decided_at": null
      }
    ],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `recovery.review` | — |
| 422 | `INVALID_CURSOR` | Cursor tidak valid. | Cursor tidak valid | — |

---

#### H.7-E5 Putuskan pengajuan pemulihan (admin)

`POST /admin/recovery-requests/{id}/decision` · Auth: Bearer admin, izin `recovery.review`

Menyetujui atau menolak. Persetujuan mengganti nomor, mencabut semua sesi dan kepercayaan perangkat, melepas `recovery_hold`, mengisi `transfer_blocked_until` (+24 jam), dan mengirim pemberitahuan WhatsApp ke nomor baru. Penolakan melepas `recovery_hold` dan mengirim pemberitahuan ke nomor baru.

**Request**

```json
{
  "decision": "APPROVE",
  "reason": "Selfie dan riwayat transaksi cocok"
}
```

Validasi:

- `decision`: `APPROVE` | `REJECT`
- `reason`: wajib, 10–300 karakter

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Keputusan disimpan.",
  "data": {
    "id": "rcv_Zk20aV",
    "status": "APPROVED",
    "decided_at": "2026-10-18T09:00:00Z",
    "transfer_blocked_until": "2026-10-19T09:00:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `recovery.review` | — |
| 404 | `RECOVERY_REQUEST_NOT_FOUND` | Pengajuan pemulihan tidak ditemukan. | `id` tidak ada | — |
| 409 | `RECOVERY_REQUEST_ALREADY_DECIDED` | Pengajuan sudah diputuskan. | Sudah disetujui atau ditolak | — |
| 409 | `PHONE_ALREADY_REGISTERED` | Nomor HP sudah terdaftar. | Nomor baru sudah dipakai akun lain saat persetujuan (hanya terlihat oleh admin) | — |

---


#### H.7.4 Fonnte tetap dipakai: daftar syarat sebelum produksi

Keputusan: tahap pengembangan dan beta memakai Fonnte (bagian H). Yang perlu dikerjakan **sebelum rilis publik**:

- [ ] Putuskan penyedia produksi: tetap Fonnte atau WhatsApp Business API resmi. Alasannya sudah di H.5: nomor pengirim bisa dibatasi WhatsApp dan satu nomor adalah satu titik gagal.
- [ ] Siapkan minimal satu nomor cadangan dan uji perpindahan otomatis saat webhook `disconnect` diterima.
- [ ] Baca ketentuan layanan Fonnte soal pemakaian untuk OTP aplikasi keuangan.
- [ ] Pastikan antarmuka `WhatsAppGateway` masih satu-satunya tempat yang tahu soal Fonnte, supaya penggantian tidak menyentuh endpoint.
- [ ] Tes beban pengiriman OTP dan pastikan kuota cukup untuk perkiraan login perangkat baru per hari (login perangkat dikenal tidak lagi memakai OTP, jadi kebutuhan pesan turun).

#### H.7.5 Pencabutan token langsung berlaku

Access token memuat klaim `sub` (user), `sid` (= `refresh_tokens.family_id`), `did` (device), `iat`, `exp`, dan `jti`. Saat sesi dicabut (keluar, ganti PIN untuk perangkat lain, reset PIN, ganti nomor, perangkat dikeluarkan, akun dibekukan, `REFRESH_TOKEN_REVOKED`), backend menulis ke Redis:

| Kunci Redis | Isi | TTL | Dipakai untuk |
| --- | --- | --- | --- |
| `rev:sid:<family_id>` | `1` | umur access token (900 detik) | Mencabut satu sesi |
| `rev:user:<user_id>` | timestamp `iat_before` | umur access token | Mencabut semua sesi pengguna: token dengan `iat` lebih lama ditolak |

Middleware memeriksa dua kunci itu di setiap request terautentikasi (dua `GET`/`MGET` Redis). Bila Redis tidak bisa dihubungi: **tolak** (fail closed) untuk endpoint yang mengubah uang (mulai Fase 3), dan **izinkan dengan peringatan** untuk endpoint baca. Token yang dicabut membalas `UNAUTHORIZED` (401), bukan `TOKEN_EXPIRED`, sehingga app tidak mencoba refresh.

#### H.7.6 Kunci PIN per perangkat

Menggantikan kunci PIN per akun. Tujuannya: orang yang menebak PIN dari perangkat lain tidak bisa mengunci akun korban di perangkat korban sendiri.

| Cakupan | Aturan | Hasil |
| --- | --- | --- |
| Per akun + perangkat | 5 kali salah → kunci 15 menit; kunci berulang naik bertingkat 15 menit → 1 jam → 24 jam (`pin_attempts.lockout_level`) | `PIN_LOCKED` dengan `details.retry_after` |
| Per akun (semua perangkat) | 15 kali salah dalam 1 jam | `ACCOUNT_LOCKED`; pemilik harus lewat OTP (Lupa PIN) |

Hitungan perangkat direset saat PIN benar. `PIN_INVALID` membawa `details.attempts_left` untuk perangkat tersebut. Pengaturan: `security.pin.max_attempts` (5), `security.pin.lock_minutes` (15), `security.pin.account_max_attempts_hour` (15). Kolom `users.pin_failed_count` dan `users.pin_locked_until` menjadi cadangan untuk kunci per akun.

#### H.7.7 Verifikasi integritas perangkat

Dua header baru pada endpoint auth publik (`login/start`, `login/*`, `register/complete`, `otp/request`):

| Header | Nilai |
| --- | --- |
| `X-Attestation-Provider` | `PLAY_INTEGRITY` (Android) atau `APP_ATTEST` (iOS) |
| `X-Attestation` | Token Play Integrity atau assertion App Attest dari app |

Backend memverifikasi token ke penyedianya, mencocokkan nonce dan identitas app, lalu menyimpan `devices.attestation_provider` dan `attested_at`. Gagal → `DEVICE_ATTESTATION_FAILED` (403). Dikendalikan flag `security.attestation_required`: **false** di dev dan staging, **true** di produksi. Pekerjaan sisi app (modul native Expo, kunci Google Cloud) adalah tugas tersendiri.

#### H.7.8 Endpoint admin tambahan

Semua memakai bentuk respons bagian 1 dan menulis `audit_logs` (aksi tulis menyimpan `before` dan `after`). Izin yang dipakai: `admin.read`, `admin.write`, `settings.read`, `settings.write`, `users.read`, `recovery.review`, `audit.read`.

Perubahan di login admin (bagian G, langkah 1): respons ditambah `next_step` agar admin baru bisa menyelesaikan penyiapan:

| `next_step` | Arti | Langkah berikut |
| --- | --- | --- |
| `CHANGE_PASSWORD` | Password sementara dari pembuatan akun | `POST /admin/auth/password/change` memakai `challenge_token` |
| `SETUP_2FA` | 2FA belum aktif | `POST /admin/auth/2fa/setup` lalu `/admin/auth/2fa/enable` |
| `VERIFY_2FA` | Normal | `POST /admin/auth/2fa/verify` (bagian G) |


#### H.7-E6 Ganti password admin (pertama kali atau rutin)

`POST /admin/auth/password/change` · Auth: `challenge_token` dari login langkah 1, atau Bearer admin

Mengganti password. Wajib dilakukan sebelum 2FA bila `must_change_password`.

**Request**

```json
{
  "challenge_token": "ac_41d8e0c7...",
  "old_password": "••••••••••",
  "new_password": "••••••••••••••••"
}
```

Validasi:

- `new_password`: minimal 12 karakter, bukan 5 password terakhir, bukan mengandung email

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Password diganti.",
  "data": {
    "next_step": "SETUP_2FA",
    "challenge_token": "ac_9a7b2c10...",
    "expires_in": 300
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `ADMIN_CREDENTIALS_INVALID` | Email atau password admin salah. | `old_password` salah | — |
| 422 | `ADMIN_PASSWORD_WEAK` | Password admin terlalu lemah. | Tidak memenuhi aturan | — |
| 422 | `ADMIN_2FA_REQUIRED` | Kode 2FA diperlukan. | `challenge_token` tidak valid atau kedaluwarsa | — |

---

#### H.7-E7 Mulai pasang 2FA admin

`POST /admin/auth/2fa/setup` · Auth: `challenge_token` atau Bearer admin

Membuat rahasia TOTP baru (belum aktif sampai dikonfirmasi).

**Request**

```json
{
  "challenge_token": "ac_9a7b2c10..."
}
```

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Rahasia 2FA dibuat.",
  "data": {
    "otpauth_uri": "otpauth://totp/Poinqu:owner@poinqu.id?secret=JBSWY3DPEHPK3PXP&issuer=Poinqu",
    "secret": "JBSWY3DPEHPK3PXP",
    "expires_in": 300
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `ADMIN_2FA_REQUIRED` | Kode 2FA diperlukan. | `challenge_token` tidak valid atau kedaluwarsa | — |
| 422 | `ADMIN_PASSWORD_CHANGE_REQUIRED` | Ganti password terlebih dahulu. | Password sementara belum diganti | — |

---

#### H.7-E8 Aktifkan 2FA admin

`POST /admin/auth/2fa/enable` · Auth: `challenge_token` atau Bearer admin

Mengonfirmasi kode TOTP pertama, mengaktifkan 2FA, lalu menerbitkan token sesi seperti `2fa/verify`.

**Request**

```json
{
  "challenge_token": "ac_9a7b2c10...",
  "code": "531902"
}
```

Validasi:

- `code`: 6 digit

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "2FA aktif.",
  "data": {
    "admin": {
      "id": "adm_01J9Z5",
      "email": "owner@poinqu.id",
      "name": "Koko",
      "role": "SUPERADMIN",
      "permissions": ["admin.read", "admin.write", "audit.read", "settings.write"]
    },
    "tokens": {
      "access_token": "eyJhbGciOiJFZERTQSIs...",
      "refresh_token": "ar_6f20b19d...",
      "token_type": "Bearer",
      "expires_in": 900,
      "refresh_expires_in": 28800
    }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `ADMIN_2FA_INVALID` | Kode 2FA salah. | Kode TOTP salah | — |
| 422 | `ADMIN_2FA_REQUIRED` | Kode 2FA diperlukan. | `challenge_token` tidak valid atau kedaluwarsa | — |
| 422 | `ADMIN_LOCKED` | Akun admin dikunci sementara. | Terlalu banyak salah | `{ "retry_after": 900 }` |

---

#### H.7-E9 Daftar admin

`GET /admin/admins?cursor=&limit=` · Auth: Bearer admin, izin `admin.read`

Daftar akun admin.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [{
        "id": "adm_01J9Z5",
        "email": "owner@poinqu.id",
        "name": "Koko",
        "role": "SUPERADMIN",
        "status": "ACTIVE",
        "totp_enabled": true,
        "last_login_at": "2026-10-18T05:30:00Z",
        "created_at": "2026-10-01T02:00:00Z"
      }],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `admin.read` | — |
| 422 | `INVALID_CURSOR` | Cursor tidak valid. | Cursor tidak valid | — |

---

#### H.7-E10 Buat admin

`POST /admin/admins` · Auth: Bearer admin, izin `admin.write`

Membuat admin dengan password sementara yang hanya muncul sekali di respons. Admin baru wajib ganti password dan memasang 2FA saat login pertama. Status HTTP 201.

**Request**

```json
{
  "email": "cs@poinqu.id",
  "name": "Tim CS",
  "role_id": "role_cs"
}
```

Validasi:

- `email`: valid dan unik
- `role_id`: ID peran yang ada

**Respons sukses** — HTTP 201

```json
{
  "success": true,
  "code": "OK",
  "message": "Admin dibuat.",
  "data": {
    "admin": {
      "id": "adm_01J9Z5",
      "email": "cs@poinqu.id",
      "name": "Tim CS",
      "role": "CS",
      "status": "ACTIVE",
      "totp_enabled": false,
      "last_login_at": null,
      "created_at": "2026-10-01T02:00:00Z"
    },
    "temporary_password": "Qm8x-Zt3k-Lp0a-Rw5n"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `admin.write` | — |
| 409 | `ADMIN_EMAIL_ALREADY_USED` | Email admin sudah dipakai. | Email sudah dipakai | — |
| 404 | `ROLE_NOT_FOUND` | Peran tidak ditemukan. | `role_id` tidak ada | — |

---

#### H.7-E11 Ubah admin (peran atau status)

`PATCH /admin/admins/{id}` · Auth: Bearer admin, izin `admin.write`

Mengubah peran atau status (`ACTIVE` | `DISABLED`). Menonaktifkan admin mencabut seluruh sesinya.

**Request**

```json
{
  "role_id": "role_finance",
  "status": "ACTIVE"
}
```

Validasi:

- Minimal satu field
- `status`: `ACTIVE` | `DISABLED`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Admin diperbarui.",
  "data": {
    "id": "adm_01J9Z5",
    "email": "owner@poinqu.id",
    "name": "Koko",
    "role": "SUPERADMIN",
    "status": "ACTIVE",
    "totp_enabled": true,
    "last_login_at": "2026-10-18T05:30:00Z",
    "created_at": "2026-10-01T02:00:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `admin.write` | — |
| 404 | `ADMIN_NOT_FOUND` | Admin tidak ditemukan. | `id` tidak ada | — |
| 404 | `ROLE_NOT_FOUND` | Peran tidak ditemukan. | `role_id` tidak ada | — |
| 422 | `CANNOT_MODIFY_SELF` | Tidak bisa mengubah akun admin sendiri. | Admin mengubah peran atau statusnya sendiri | — |
| 422 | `LAST_SUPERADMIN` | Harus ada minimal satu superadmin aktif. | Perubahan membuat tidak ada superadmin aktif | — |

---

#### H.7-E12 Daftar peran dan izin

`GET /admin/roles` · Auth: Bearer admin, izin `admin.read`

Peran beserta izinnya.

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      { "id": "role_super", "name": "SUPERADMIN", "permissions": ["admin.read", "admin.write", "settings.read", "settings.write", "users.read", "recovery.review", "audit.read"] },
      { "id": "role_cs", "name": "CS", "permissions": ["users.read", "recovery.review"] }
    ]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `admin.read` | — |

---

#### H.7-E13 Daftar pengaturan

`GET /admin/settings?prefix=` · Auth: Bearer admin, izin `settings.read`

Semua pengaturan, bisa difilter awalan kunci (misalnya `limits.`, `security.`, `otp.`).

**Request**

Tanpa body.

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [{
        "key": "limits.balance_cap.BASIC",
        "value": 2000000,
        "version": 4,
        "description": "Saldo maksimal akun Basic (rupiah)",
        "updated_by": "adm_01J9Z5",
        "updated_at": "2026-10-18T05:10:00Z"
      }
    ]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `settings.read` | — |

---

#### H.7-E14 Ubah pengaturan

`PUT /admin/settings/{key}` · Auth: Bearer admin, izin `settings.write`

Mengubah satu pengaturan dengan kontrol versi (optimistic concurrency): `version` yang dikirim harus sama dengan versi saat ini. Nilai divalidasi menurut skema tiap kunci (tipe dan rentang). Perubahan berlaku untuk transaksi baru; transaksi berjalan memakai nilai lama. Menulis audit log berisi `before`, `after`, dan `reason`.

**Request**

```json
{
  "value": 2500000,
  "version": 4,
  "reason": "Penyesuaian kebijakan batas saldo"
}
```

Validasi:

- `value`: tipe sesuai kunci
- `version`: integer, wajib
- `reason`: wajib, 10–300 karakter

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Pengaturan diperbarui.",
  "data": {
    "key": "limits.balance_cap.BASIC",
    "value": 2500000,
    "version": 5,
    "description": "Saldo maksimal akun Basic (rupiah)",
    "updated_by": "adm_01J9Z5",
    "updated_at": "2026-10-18T05:10:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `settings.write` | — |
| 404 | `SETTING_NOT_FOUND` | Pengaturan tidak ditemukan. | `key` tidak dikenal | — |
| 422 | `SETTING_VERSION_CONFLICT` | Pengaturan sudah diubah orang lain. Muat ulang. | `version` tidak sama dengan versi saat ini | `{ "current_version": 5 }` |
| 422 | `SETTING_VALUE_INVALID` | Nilai pengaturan tidak valid. | Nilai di luar skema kunci tersebut | `{ "expected": "integer >= 0" }` |

---

#### H.7-E15 Cari pengguna

`GET /admin/users?q=&status=&level=&cursor=&limit=` · Auth: Bearer admin, izin `users.read`

Mencari pengguna (nomor, nama, atau ID). Data disamarkan; saldo dan transaksi baru tersedia setelah Fase 3.

**Request**

Tanpa body.

Validasi:

- `q`: minimal 4 karakter
- `status`: `ACTIVE` | `LOCKED` | `SUSPENDED`
- `level`: `BASIC` | `PREMIUM`

**Respons sukses** — HTTP 200

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "id": "usr_01J9Z3K7QX",
        "name": "Koko Wijaya",
        "phone_masked": "0812****7890",
        "level": "BASIC",
        "kyc_status": "NONE",
        "status": "ACTIVE",
        "recovery_hold": false,
        "created_at": "2026-10-18T05:00:00Z",
        "last_active_at": "2026-10-18T05:30:00Z"
      }
    ],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

**Respons gagal** (selain error umum bagian 1.3). Bentuk body selalu seperti bagian 1.2.

| HTTP | `code` | Pesan | Kapan | `details` |
| --- | --- | --- | --- | --- |
| 422 | `FORBIDDEN` | Tidak punya izin untuk aksi ini. | Tidak punya izin `users.read` | — |
| 422 | `INVALID_LENGTH` | Panjang tidak valid. | `q` kurang dari 4 karakter (bersama `VALIDATION_ERROR`) | — |
| 422 | `INVALID_CURSOR` | Cursor tidak valid. | Cursor tidak valid | — |

---


#### H.7.9 Pekerjaan yang masih tersisa

| Pekerjaan | Status | Catatan |
| --- | --- | --- |
| File OpenAPI dari FastAPI | Belum | Perlu untuk membuat klien TypeScript otomatis dan tes kontrak; FastAPI membuatnya otomatis dari model Pydantic |
| Menjalankan SQL skema di PostgreSQL | Belum | SQL di bagian 3 dan H.7.10 belum pernah dijalankan; jalankan lewat Alembic di database kosong dan perbaiki bila ada salah sintaks |
| Angka konfigurasi (kunci PIN, batas OTP, hari kepercayaan perangkat) | Usulan | Tinjau dan sesuaikan di `app_settings` |
| Endpoint app yang belum dipetakan ke fase | Belum | `legal` (syarat dan ketentuan, dibutuhkan saat daftar, sebaiknya Fase 2 akhir), `notifications`, `support`, `savedNumbers`, `reminders`, `points`, `promos`, `requests`, `transfers`, `catalog`, `kyc`, dan konfigurasi SDUI |
| Kebijakan data pribadi (UU PDP) | Belum | Retensi KTP dan selfie, persetujuan, hak hapus akun, dan masa simpan log |
| Pemulihan nomor lewat penyedia liveness asli | Ditunda ke Fase 6 | Di Fase 2 memakai penyedia palsu di server |
| Step-up (`/me/stepup/*`) | Ditunda ke Fase 7 | |

#### H.7.10 Migrasi database

```sql
-- Perangkat tepercaya dan attestation
ALTER TABLE devices
  ADD COLUMN trusted_at timestamptz,
  ADD COLUMN attestation_provider varchar(20),
  ADD COLUMN attested_at timestamptz;

-- Token verifikasi: asal dan perangkat
ALTER TABLE verification_tokens
  ADD COLUMN via varchar(20) NOT NULL DEFAULT 'OTP' CHECK (via IN ('OTP','TRUSTED_DEVICE')),
  ADD COLUMN device_id text;

-- Penahanan saldo dan jeda setelah pemulihan
ALTER TABLE users
  ADD COLUMN recovery_hold boolean NOT NULL DEFAULT false,
  ADD COLUMN transfer_blocked_until timestamptz;

-- Kunci PIN per perangkat
CREATE TABLE pin_attempts (
  user_id       uuid NOT NULL REFERENCES users(id),
  device_id     uuid NOT NULL REFERENCES devices(id),
  failed_count  smallint NOT NULL DEFAULT 0,
  lockout_level smallint NOT NULL DEFAULT 0,        -- 0:15 menit, 1:1 jam, 2:24 jam
  locked_until  timestamptz,
  last_failed_at timestamptz,
  PRIMARY KEY (user_id, device_id)
);

-- Pemulihan nomor tanpa KYC
CREATE TABLE recovery_requests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid REFERENCES users(id),           -- NULL bila nomor lama tidak ditemukan
  old_phone     varchar(16) NOT NULL,
  new_phone     varchar(16) NOT NULL,
  name          varchar(100) NOT NULL,
  last_transaction_hint varchar(200),
  balance_hint  bigint,
  note          varchar(500),
  status        varchar(14) NOT NULL DEFAULT 'PENDING_REVIEW' CHECK (status IN ('PENDING_REVIEW','APPROVED','REJECTED')),
  decided_by    uuid REFERENCES admins(id),
  decision_reason text,
  decided_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON recovery_requests (status, created_at);

-- Admin
ALTER TABLE admins
  ADD COLUMN must_change_password boolean NOT NULL DEFAULT true,
  ADD COLUMN totp_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN last_login_at timestamptz;
CREATE TABLE admin_password_history (
  admin_id uuid NOT NULL REFERENCES admins(id), password_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);

-- Pengaturan baru (isi awal)
INSERT INTO app_settings (key, value) VALUES
  ('security.trusted_device_idle_days', '90'),
  ('security.pin.max_attempts', '5'),
  ('security.pin.lock_minutes', '15'),
  ('security.pin.account_max_attempts_hour', '15'),
  ('security.attestation_required', 'false'),
  ('otp.rate.per_phone_hour', '5'),
  ('otp.rate.per_device_hour', '10'),
  ('otp.rate.per_ip_hour', '20'),
  ('otp.provider_healthy', 'true'),
  ('recovery.cooldown_hours', '24');
```

#### H.7.11 Tes tambahan

- **Perangkat tepercaya:** `login/start` untuk perangkat tepercaya mengembalikan token; untuk perangkat baru dan nomor tidak terdaftar bentuknya identik (bandingkan seluruh field dan waktu respons). Kepercayaan hilang setelah reset PIN, keluar semua perangkat, pemulihan nomor, dan 90 hari tidak aktif. Token dari `login/start` ditolak bila `device_id` berbeda.
- **Anti-enumerasi:** `otp/request` LOGIN untuk nomor tidak terdaftar tidak memanggil Fonnte dan membalas sama seperti nomor terdaftar; `otp/verify` pada sesi itu selalu `OTP_INVALID`. `register` untuk nomor terdaftar mengirim pesan pemberitahuan, bukan OTP.
- **Batas laju:** tiga cakupan (nomor, perangkat, IP) berdiri sendiri; sesi OTP palsu ikut terhitung.
- **Pemulihan tanpa KYC:** saldo ditahan saat pengajuan, transaksi keluar ditolak `ACCOUNT_RESTRICTED`; setelah disetujui, sesi dicabut, kepercayaan dicabut, dan transaksi keluar tertahan 24 jam; respons publik identik untuk nomor yang tidak cocok.
- **Token:** token yang dicabut ditolak dalam satu request; Redis mati → endpoint baca jalan, endpoint uang ditolak.
- **PIN:** salah dari perangkat A tidak mengunci perangkat B; 15 salah dalam sejam di banyak perangkat mengunci akun; kunci bertingkat 15 menit, 1 jam, 24 jam.
- **Attestation:** flag mati → lolos tanpa header; flag nyala → `DEVICE_ATTESTATION_FAILED` untuk token palsu atau kedaluwarsa.
- **Admin:** tidak bisa mengubah akun sendiri; tidak bisa menghapus superadmin terakhir; `PUT /admin/settings/{key}` dengan versi lama → `SETTING_VERSION_CONFLICT`; semua aksi tulis muncul di audit log dengan `before` dan `after`.

---


## 5. Urutan alur utama

1. **Daftar:** `/auth/register` → `/auth/otp/verify` → `/auth/register/complete` → masuk.
2. **Login:** `/auth/otp/request` (LOGIN) → `/auth/otp/verify` → `/auth/login/pin` (atau `/auth/biometric/challenge` lalu `/auth/login/fingerprint` atau `/auth/login/face`).
3. **Sesi:** access token kedaluwarsa → app menerima `TOKEN_EXPIRED` → `/auth/token/refresh` → request diulang satu kali. Refresh gagal → logout.
4. **Lupa PIN:** `/auth/otp/request` (FORGOT_PIN) → `/auth/otp/verify` → `/auth/pin/reset` → login ulang.
5. **Nomor hilang:** `/auth/phone-recovery` → `.../face` → `.../phone` → `/auth/otp/verify` → `.../complete`.

## 6. Tes wajib sebelum Fase 2 dianggap selesai

- OTP: salah, kedaluwarsa, 5 kali salah, kirim ulang terlalu cepat, batas kirim ulang, batas 5 permintaan per jam.
- PIN: 5 kali salah mengunci akun; hitungan reset setelah benar; PIN lemah ditolak.
- Refresh token: rotasi; pemakaian ulang token lama mencabut seluruh keluarga.
- `verification_token`: sekali pakai, terikat purpose, kedaluwarsa.
- Biometrik: tanda tangan salah, challenge dipakai dua kali, challenge kedaluwarsa.
- Perangkat: tidak bisa mengeluarkan perangkat sendiri; akses dengan `X-Device-Id` berbeda ditolak.
- Admin: kunci setelah gagal berulang, 2FA wajib, setiap aksi tercatat di audit log, endpoint admin menolak token pengguna dan sebaliknya.
- Kontrak: respons backend divalidasi terhadap tipe TypeScript app (`ApiResponse<T>`) lewat tes kontrak.
