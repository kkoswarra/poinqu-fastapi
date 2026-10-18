# RENCANA API — Fase 3A: Wallet, Top-up, KYC, dan Read Bootstrap

Versi dokumen 0.1 · 18 Oktober 2026

> **Status:** draft Fase 3A, **belum final**.
>
> Scope ini bergantung pada keputusan **D-10** di `DECISIONS.md`: apakah
> wallet/top-up/KYC tetap dipakai setelah pivot ke pulsa/PPOB. Jangan
> implementasi sebelum D-10 selesai.
>
> Indeks dokumen: `docs/README.md` · flow: `FASE-3-FLOW.md` · task:
> `FASE-3-TASKS.md`.

Dokumen ini adalah kontrak API untuk fase berikutnya setelah Fase 2.
Scope yang dipilih:

- **Wallet + ledger + limit**
- **Top-up via Duitku** dengan kanal VA/QRIS dan instruksi pembayaran
- **KYC manual review admin** (KTP + liveness)
- **Read bootstrap** untuk Home: transaksi, katalog layanan, notifikasi

Sumber kontrak app: `app-frontend/src/api/types/*` dan
`app-frontend/src/api/endpoints/*`. Dokumen ini mengikuti bentuk data yang
sudah dipakai app, bukan `app-frontend/openapi.json` yang lama.

Kode yang belum ada di app ditandai **[usulan]**. Hal yang perlu dipastikan
ke vendor/regulasi ditandai **[perlu dicek]**.

---

## 1. Konvensi

- Base URL: `/v1`, JSON UTF-8, waktu ISO 8601 UTC, uang integer rupiah.
- Header sama seperti Fase 2: `Authorization: Bearer <token>` dan
  `X-Device-Id`.
- **`Idempotency-Key` wajib** untuk semua POST yang membuat/mengubah uang:
  `POST /wallet/topups`.
- Arti idempotency:
  - key + payload sama → kembalikan respons tersimpan yang sama;
  - key sama + payload berbeda → `IDEMPOTENCY_KEY_REUSED`;
  - key tidak ada → `IDEMPOTENCY_KEY_REQUIRED`.
- Pagination memakai cursor:
  `{ "next_cursor": "20", "has_more": true, "limit": 20 }`.
- Bulan limit memakai kalender **WIB** (`YYYY-MM`), bukan UTC.
- Envelope sukses/gagal sama seperti Fase 2.
- `201` dipakai untuk pembuatan resource (top-up, KYC draft).

---

## 2. Kode error tambahan

Kode yang sudah ada di `app-frontend/src/lib/errors.ts` tetap dipakai.
Berikut kode yang relevan untuk Fase 3A.

| HTTP | Kode | Pesan | Kapan |
| --- | --- | --- | --- |
| 422 | `INSUFFICIENT_BALANCE` | Saldo tidak cukup. | Saldo < total (dipakai untuk transaksi berikutnya) |
| 422 | `BALANCE_LIMIT_EXCEEDED` | Saldo melebihi batas maksimal akun. | Saldo + nominal top-up > batas level |
| 422 | `MONTHLY_INCOMING_LIMIT_EXCEEDED` | Batas dana masuk bulan ini tercapai. | Dana masuk bulan berjalan + nominal > batas |
| 422 | `AMOUNT_TOO_LOW` | Nominal terlalu kecil. | Di bawah minimum channel |
| 422 | `AMOUNT_TOO_HIGH` | Nominal terlalu besar. | Di atas maksimum channel/limit |
| 422 | `AMOUNT_OUT_OF_RANGE` | Nominal di luar batas. | Di luar aturan channel |
| 404 | `TOPUP_NOT_FOUND` | Data isi saldo tidak ditemukan. | `topup_id` tidak ada/bukan milik user |
| 422 | `TOPUP_PENDING_LIMIT` | Kamu punya terlalu banyak kode pembayaran aktif. | Jumlah top-up aktif melebihi batas |
| 409 | `TOPUP_ALREADY_PAID` | Pembayaran sudah diterima. | Cancel setelah PAID |
| 422 | `TOPUP_NOT_CANCELLABLE` | Kode pembayaran tidak bisa dibatalkan. | Status bukan `WAITING_PAYMENT` |
| 410 | `TOPUP_EXPIRED` | Kode pembayaran sudah kedaluwarsa. | `expires_at` lewat |
| 503 | `CHANNEL_NOT_AVAILABLE` | Metode ini sedang tidak tersedia. | Channel `available=false` |
| 502 | `PAYMENT_PROVIDER_ERROR` | Gagal membuat kode pembayaran. | Duitku menolak/error saat create |
| 504 | `PROVIDER_TIMEOUT` | Penyedia layanan tidak merespons. | Timeout saat create/status |
| 422 | `IDEMPOTENCY_KEY_REQUIRED` | Header Idempotency-Key wajib diisi. | Header tidak ada |
| 422 | `IDEMPOTENCY_KEY_REUSED` | Idempotency-Key sudah dipakai untuk transaksi berbeda. | Key sama, payload beda |
| 409 | `KYC_ALREADY_VERIFIED` | Akun sudah Premium. | KYC saat status VERIFIED |
| 409 | `KYC_PENDING` | Pengajuan sebelumnya masih diproses. | KYC saat status PENDING |
| 404 | `KYC_NOT_FOUND` | Data pengajuan tidak ditemukan. | `kyc_id` tidak ada/bukan milik user |
| 422 | `KYC_NOT_DRAFT` | Pengajuan sudah dikirim sebelumnya. | Face/update saat bukan DRAFT |
| 410 | `KYC_DRAFT_EXPIRED` | Sesi pengisian data berakhir. | Draft lewat `expires_at` |
| 409 | `NIK_ALREADY_USED` | NIK sudah terdaftar pada akun lain. | Hash NIK sudah dipakai |
| 422 | `KTP_IMAGE_UNREADABLE` | Foto KTP tidak terbaca. | File bukan gambar/KTP tidak jelas |
| 422 | `KTP_DATA_MISMATCH` | NIK atau nama tidak sesuai dengan foto KTP. | Mode provider eKYC; manual memakai alasan reject |
| 409 | `NAME_LOCKED` | Nama tidak bisa diubah setelah KTP terverifikasi. | Ubah nama setelah KYC VERIFIED |
| 409 | `EMAIL_ALREADY_USED` | Email sudah dipakai akun lain. | Profil/email |
| 413 | `FILE_TOO_LARGE` | Ukuran file terlalu besar. | KTP melebihi batas |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Format file tidak didukung. | Bukan JPEG/PNG |
| 409 | `KYC_ALREADY_DECIDED` | Pengajuan sudah diputuskan. | Admin decision kedua **[usulan]** |
| 401 | `INVALID_SIGNATURE` | Tanda tangan tidak valid. | Callback Duitku **[usulan]** |

Kode yang perlu ditambahkan ke `app-frontend/src/lib/errors.ts`:
`KYC_ALREADY_DECIDED`, `INVALID_SIGNATURE` (internal webhook), dan
penyelarasan `POINTS_INSUFFICIENT` → `INSUFFICIENT_POINTS` (bukan scope 3A,
tetapi sebaiknya sekalian).

---

## 3. Skema database [usulan]

Semua tabel memakai `created_at`/`updated_at` timestamptz. Primary key UUID
memakai `gen_random_uuid()`.

```sql
-- Akun wallet. Satu user satu akun IDR.
CREATE TABLE accounts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL UNIQUE REFERENCES users(id),
  currency       char(3) NOT NULL DEFAULT 'IDR',
  balance_cached bigint NOT NULL DEFAULT 0 CHECK (balance_cached >= 0),
  status         varchar(16) NOT NULL DEFAULT 'ACTIVE'
                 CHECK (status IN ('ACTIVE','FROZEN','CLOSED')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Jurnal double-entry, append-only.
CREATE TABLE ledger_entries (
  id             bigserial PRIMARY KEY,
  account_id     uuid NOT NULL REFERENCES accounts(id),
  transaction_id uuid NOT NULL,
  direction      varchar(6) NOT NULL CHECK (direction IN ('DEBIT','CREDIT')),
  amount         bigint NOT NULL CHECK (amount > 0),
  balance_after  bigint NOT NULL,
  entry_type     varchar(30) NOT NULL, -- TOPUP, ADJUSTMENT, REVERSAL, ...
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ledger_entries (account_id, created_at DESC);
CREATE INDEX ON ledger_entries (transaction_id);

-- Header transaksi. Dipakai juga oleh top-up.
CREATE TABLE transactions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id       varchar(32) NOT NULL UNIQUE, -- txn_xxx
  user_id         uuid NOT NULL REFERENCES users(id),
  type            varchar(30) NOT NULL,        -- TOPUP, ...
  status          varchar(16) NOT NULL DEFAULT 'CREATED'
                  CHECK (status IN ('CREATED','PENDING','SUCCESS','FAILED','REVERSED')),
  amount          bigint NOT NULL CHECK (amount >= 0),
  fee             bigint NOT NULL DEFAULT 0,
  total           bigint NOT NULL CHECK (total >= 0),
  reference       varchar(64) NOT NULL UNIQUE,
  idempotency_key varchar(128),
  provider        varchar(20),
  provider_ref    varchar(100),
  metadata        jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  completed_at    timestamptz,
  UNIQUE (user_id, idempotency_key)
);

-- Channel top-up yang ditampilkan app.
CREATE TABLE topup_channels (
  code             varchar(40) PRIMARY KEY,      -- BCA_VA, QRIS, ...
  name             varchar(100) NOT NULL,
  method_type      varchar(20) NOT NULL
                   CHECK (method_type IN ('VIRTUAL_ACCOUNT','MINIMARKET','EWALLET')),
  payment_type     varchar(10) NOT NULL CHECK (payment_type IN ('NUMBER','QR','LINK')),
  provider         varchar(20) NOT NULL DEFAULT 'DUITKU',
  provider_code    varchar(40) NOT NULL,
  icon_url         text,
  fee_type         varchar(10) NOT NULL DEFAULT 'NOMINAL'
                   CHECK (fee_type IN ('NOMINAL','PERCENT')),
  fee_nominal      bigint NOT NULL DEFAULT 0,
  fee_percent      numeric(5,2) NOT NULL DEFAULT 0,
  fee_min          bigint,
  fee_max          bigint,
  min_amount       bigint NOT NULL DEFAULT 10000,
  max_amount       bigint NOT NULL DEFAULT 20000000,
  available        boolean NOT NULL DEFAULT true,
  sort_order       integer NOT NULL DEFAULT 0,
  config           jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Order top-up.
CREATE TABLE topups (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id           varchar(32) NOT NULL UNIQUE, -- top_xxx
  transaction_id      uuid NOT NULL UNIQUE REFERENCES transactions(id),
  user_id             uuid NOT NULL REFERENCES users(id),
  channel_code        varchar(40) NOT NULL REFERENCES topup_channels(code),
  status              varchar(20) NOT NULL DEFAULT 'CREATED'
                      CHECK (status IN ('CREATED','WAITING_PAYMENT','PAID','EXPIRED','CANCELLED','FAILED','REQUIRES_ACTION')),
  amount              bigint NOT NULL CHECK (amount > 0),
  fee                 bigint NOT NULL DEFAULT 0,
  total               bigint NOT NULL CHECK (total > 0),
  provider            varchar(20) NOT NULL DEFAULT 'DUITKU',
  provider_ref        varchar(100),             -- merchantOrderId
  provider_payment_id varchar(100),
  payment_code        varchar(100),
  payment_code_formatted varchar(100),
  account_name        varchar(100),
  va_number           varchar(50),
  qr_string           text,
  payment_url         text,
  deeplink            text,
  instructions        jsonb NOT NULL DEFAULT '[]',
  action              jsonb,
  expires_at          timestamptz NOT NULL,
  paid_at             timestamptz,
  raw_create          jsonb,
  raw_callback        jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ON topups (provider, provider_ref)
  WHERE provider_ref IS NOT NULL;
CREATE INDEX ON topups (user_id, created_at DESC);

-- Reservasi nominal top-up yang belum dibayar. Mencegah limit jebol paralel.
CREATE TABLE wallet_reservations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  topup_id    uuid NOT NULL UNIQUE REFERENCES topups(id),
  amount      bigint NOT NULL CHECK (amount > 0),
  status      varchar(10) NOT NULL DEFAULT 'ACTIVE'
              CHECK (status IN ('ACTIVE','CONSUMED','RELEASED')),
  expires_at  timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON wallet_reservations (user_id, status);

-- Counter dana masuk per bulan kalender WIB.
CREATE TABLE incoming_counters (
  user_id         uuid NOT NULL REFERENCES users(id),
  month           char(7) NOT NULL, -- YYYY-MM WIB
  amount          bigint NOT NULL DEFAULT 0 CHECK (amount >= 0),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, month)
);

-- KYC manual.
CREATE TABLE kyc_submissions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id          varchar(32) NOT NULL UNIQUE, -- kyc_xxx
  user_id            uuid NOT NULL REFERENCES users(id),
  status             varchar(10) NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT','PENDING','VERIFIED','REJECTED')),
  nik_hash           varchar(64) NOT NULL,
  nik_encrypted      text NOT NULL,
  nik_masked         varchar(20) NOT NULL,
  name               varchar(100) NOT NULL,
  address            text NOT NULL,
  rt                 varchar(5) NOT NULL,
  rw                 varchar(5) NOT NULL,
  village            varchar(100) NOT NULL,
  district           varchar(100) NOT NULL,
  city               varchar(100) NOT NULL,
  province           varchar(100) NOT NULL,
  ktp_file_key       text NOT NULL,
  selfie_file_key    text,
  liveness_session_id text,
  face_verified      boolean NOT NULL DEFAULT false,
  expires_at         timestamptz NOT NULL,
  submitted_at       timestamptz,
  reviewed_by        uuid REFERENCES admins(id),
  reviewed_at        timestamptz,
  reason_code        varchar(40),
  reason             text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ON kyc_submissions (nik_hash)
  WHERE status IN ('PENDING','VERIFIED');
CREATE UNIQUE INDEX ON kyc_submissions (user_id)
  WHERE status IN ('DRAFT','PENDING');

-- Notifikasi in-app.
CREATE TABLE notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  type        varchar(30) NOT NULL,
  title       varchar(150) NOT NULL,
  body        text NOT NULL,
  icon        varchar(50) NOT NULL DEFAULT 'bell',
  deep_link   text,
  read_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notifications (user_id, created_at DESC);
CREATE INDEX ON notifications (user_id, read_at);

-- Dokumen katalog read-only untuk Home (full SDUI menyusul Fase 3B).
CREATE TABLE catalog_documents (
  key            varchar(80) PRIMARY KEY, -- 'home'
  payload        jsonb NOT NULL,
  config_version varchar(40) NOT NULL,
  etag           varchar(80) NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Idempotency generik untuk mutasi uang.
CREATE TABLE idempotency_keys (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id),
  scope          varchar(40) NOT NULL, -- 'topup.create'
  key            varchar(128) NOT NULL,
  request_hash   varchar(64) NOT NULL,
  status_code    integer NOT NULL,
  response_body  jsonb NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  expires_at     timestamptz NOT NULL,
  UNIQUE (user_id, scope, key)
);

-- Log callback provider (audit + replay).
CREATE TABLE provider_events (
  id             bigserial PRIMARY KEY,
  provider       varchar(20) NOT NULL,
  event_type     varchar(40) NOT NULL,
  provider_ref   varchar(100),
  signature_valid boolean NOT NULL,
  payload        jsonb NOT NULL,
  processed_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);
```

Catatan:

- `accounts.balance_cached` adalah cache; sumber kebenaran tetap ledger.
- `ledger_entries` dan `transactions` tidak boleh dihapus. Koreksi memakai
  transaksi `REVERSED` + jurnal pembalik.
- `nik_encrypted`/`ktp_file_key` memakai enkripsi application-level dan
  object storage privat. Jangan simpan foto KTP di filesystem Vercel `/tmp`.
- `kyc_submissions.selfie_file_key` diisi bila provider liveness menghasilkan
  selfie; untuk mode manual, KTP + status liveness cukup sebagai bukti awal.

---

## 4. Endpoint wallet

### 4.1 Ambil wallet

`GET /wallet` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "balance": 150000,
    "currency": "IDR",
    "points": 0,
    "limits": {
      "level": "BASIC",
      "balance_cap": 2000000,
      "monthly_incoming_limit": 20000000,
      "monthly_incoming_used": 500000,
      "month": "2026-10",
      "bank_transfer_free_quota": 10,
      "bank_transfer_count_month": 0,
      "bank_transfer_fee": 2500
    },
    "updated_at": "2026-10-18T05:30:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Jika akun belum ada (user lama), backend membuat akun nol secara lazy.
`points` sementara `0` sampai modul points aktif.

**Respons gagal:** error umum 401/500.

---

### 4.2 Daftar metode top-up

`GET /wallet/topup-methods` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "limits": {
      "min_amount": 10000,
      "max_amount": 2000000,
      "monthly_remaining": 19500000,
      "balance_room": 1850000
    },
    "groups": [
      {
        "type": "VIRTUAL_ACCOUNT",
        "title": "Transfer Bank",
        "payment_type": "NUMBER",
        "expires_in": 3600,
        "channels": [
          {
            "code": "BCA_VA",
            "name": "BCA Virtual Account",
            "icon": "https://cdn.poinqu.id/channels/bca.png",
            "payment_type": "NUMBER",
            "fee": { "type": "NOMINAL", "nominal": 0, "percent": 0, "min": null, "max": null },
            "available": true
          }
        ]
      },
      {
        "type": "EWALLET",
        "title": "QRIS / E-Wallet",
        "payment_type": "QR",
        "expires_in": 1800,
        "channels": [
          {
            "code": "QRIS",
            "name": "QRIS",
            "icon": null,
            "payment_type": "QR",
            "fee": { "type": "NOMINAL", "nominal": 0, "percent": 0, "min": null, "max": null },
            "available": true
          }
        ]
      }
    ]
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Aturan:

- `monthly_remaining` = `monthly_incoming_limit - monthly_incoming_used -
  total reservasi aktif`.
- `balance_room` = `balance_cap - balance_cached - total reservasi aktif`.
- `max_amount` = minimum dari batas channel, `balance_room`, dan
  `monthly_remaining`.
- Channel `available=false` tetap dikirim agar UI bisa menampilkan disabled.

---

### 4.3 Buat top-up

`POST /wallet/topups` · Auth: Bearer · Header `Idempotency-Key` wajib

**Request**

```json
{
  "amount": 100000,
  "method_type": "VIRTUAL_ACCOUNT",
  "channel_code": "BCA_VA"
}
```

Validasi:

- `amount`: integer > 0, di antara `min_amount` dan `max_amount`.
- `method_type` harus cocok dengan channel.
- Channel harus `available`.
- Saldo + amount tidak melebihi `balance_cap`.
- Dana masuk bulan berjalan + amount tidak melebihi `monthly_incoming_limit`.
- Jumlah top-up aktif < `topup.max_pending` (default 3) [usulan].
- `Idempotency-Key` wajib.

**Alur backend**

1. Cek idempotency (key + hash payload).
2. Buka transaksi DB: lock `accounts` + `incoming_counters`; cek limit.
3. Buat `transactions` status `CREATED`, lalu `topups` status `CREATED` dan
   `wallet_reservations` status `ACTIVE`.
4. Commit reservasi.
5. Panggil adapter Duitku untuk membuat VA/QRIS.
6. Bila sukses: update topup `WAITING_PAYMENT`, transaksi `PENDING`, simpan
   `payment_code`, `va_number`/`qr_string`, `expires_at`, instruksi.
7. Bila gagal pasti: topup `FAILED`, transaksi `FAILED`, reservation
   `RELEASED`.
8. Bila timeout/ambigu: transaksi tetap `PENDING`, topup `REQUIRES_ACTION`
   atau `WAITING_PAYMENT`; job rekonsiliasi menentukan status akhir.

**Respons sukses — HTTP 201**

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode pembayaran dibuat.",
  "data": {
    "topup_id": "top_9K2mQ1",
    "reference": "TU-20261018-9K2mQ1",
    "status": "WAITING_PAYMENT",
    "amount": 100000,
    "fee": 0,
    "total": 100000,
    "method": {
      "type": "VIRTUAL_ACCOUNT",
      "channel_code": "BCA_VA",
      "channel_name": "BCA Virtual Account",
      "icon": "https://cdn.poinqu.id/channels/bca.png",
      "payment_type": "NUMBER",
      "payment_code": "390123456789",
      "payment_code_formatted": "390 123 456 789",
      "account_name": "Poinqu",
      "va_number": "390123456789",
      "qr_string": null,
      "payment_url": null,
      "deeplink": null
    },
    "instructions": [
      "Buka aplikasi BCA",
      "Pilih Transfer > Virtual Account",
      "Masukkan nomor VA 390123456789",
      "Bayar sebelum 18 Oktober 2026 06:30 WIB"
    ],
    "created_at": "2026-10-18T05:30:00Z",
    "expires_at": "2026-10-18T06:30:00Z",
    "action": null
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

`total = amount + fee`. Saldo yang dikreditkan saat callback adalah `amount`,
bukan `total`.

**Respons gagal**

| HTTP | Kode | Kapan |
| --- | --- | --- |
| 422 | `AMOUNT_TOO_LOW` / `AMOUNT_TOO_HIGH` / `AMOUNT_OUT_OF_RANGE` | Nominal tidak valid |
| 422 | `BALANCE_LIMIT_EXCEEDED` | Saldo + nominal > batas level |
| 422 | `MONTHLY_INCOMING_LIMIT_EXCEEDED` | Dana masuk bulan ini penuh |
| 422 | `TOPUP_PENDING_LIMIT` | Terlalu banyak top-up aktif |
| 503 | `CHANNEL_NOT_AVAILABLE` | Channel dimatikan/down |
| 502 | `PAYMENT_PROVIDER_ERROR` | Duitku gagal membuat pembayaran |
| 504 | `PROVIDER_TIMEOUT` | Duitku tidak merespons |
| 422 | `IDEMPOTENCY_KEY_REQUIRED` | Header tidak ada |
| 422 | `IDEMPOTENCY_KEY_REUSED` | Key sama untuk payload berbeda |

---

### 4.4 Detail top-up

`GET /wallet/topups/{topup_id}` · Auth: Bearer

Respons sama dengan `TopupOrder` di 4.3. Dipakai polling setiap 4 detik.

- `TOPUP_NOT_FOUND` 404 jika tidak ada/bukan milik user.
- Status final: `PAID`, `EXPIRED`, `CANCELLED`, `FAILED`.
- `REQUIRES_ACTION` berarti app harus membuka `action.url` atau
  `payment_url`/`deeplink` [usulan].

---

### 4.5 Riwayat top-up

`GET /wallet/topups?status=&date_from=&date_to=&cursor=&limit=` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "topup_id": "top_9K2mQ1",
        "reference": "TU-20261018-9K2mQ1",
        "status": "PAID",
        "amount": 100000,
        "fee": 0,
        "total": 100000,
        "method": {
          "type": "VIRTUAL_ACCOUNT",
          "channel_code": "BCA_VA",
          "channel_name": "BCA Virtual Account",
          "icon": "https://cdn.poinqu.id/channels/bca.png",
          "payment_type": "NUMBER",
          "payment_code": "390123456789",
          "payment_code_formatted": "390 123 456 789",
          "account_name": "Poinqu",
          "va_number": "390123456789",
          "qr_string": null,
          "payment_url": null,
          "deeplink": null
        },
        "created_at": "2026-10-18T05:30:00Z",
        "expires_at": "2026-10-18T06:30:00Z",
        "paid_at": "2026-10-18T05:35:00Z"
      }
    ],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Filter `status`: `WAITING_PAYMENT | PAID | EXPIRED | CANCELLED | FAILED | REQUIRES_ACTION`.
`date_from`/`date_to`: `YYYY-MM-DD`. `INVALID_CURSOR`/`INVALID_DATE` untuk input salah.

---

### 4.6 Batalkan top-up

`POST /wallet/topups/{topup_id}/cancel` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Kode pembayaran dibatalkan.",
  "data": { "topup_id": "top_9K2mQ1", "status": "CANCELLED" },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Aturan:

- Hanya `WAITING_PAYMENT`.
- Panggil cancel ke Duitku bila API mendukung; jika tidak, tandai lokal dan
  hentikan polling.
- `TOPUP_ALREADY_PAID` 409, `TOPUP_NOT_CANCELLABLE` 422,
  `TOPUP_EXPIRED` 410, `TOPUP_NOT_FOUND` 404.
- Reservation `ACTIVE` → `RELEASED`.

---

## 5. Integrasi Duitku

### 5.1 Konfigurasi

Environment/secret manager:

| Variabel | Keterangan |
| --- | --- |
| `DUITKU_MERCHANT_CODE` | Merchant code Duitku |
| `DUITKU_API_KEY` | API key Duitku |
| `DUITKU_BASE_URL` | Base URL sandbox/production |
| `DUITKU_CALLBACK_URL` | `https://api.poinqu.id/v1/webhooks/duitku/<secret>` |
| `DUITKU_RETURN_URL` | Halaman kembali app |
| `DUITKU_WEBHOOK_SECRET` | Rahasia di path callback |

Detail endpoint, signature, dan daftar channel mengikuti dokumentasi
Duitku yang aktif. **[perlu dicek]** Jangan mengarang format vendor sebelum
sandbox diverifikasi.

### 5.2 Adapter

Buat antarmuka `PaymentGateway`:

```python
class PaymentGateway(Protocol):
    def create_topup(self, order: TopupOrder) -> ProviderPayment: ...
    def get_status(self, provider_ref: str) -> ProviderStatus: ...
    def cancel(self, provider_ref: str) -> ProviderStatus: ...
    def verify_callback(self, raw_body: bytes, headers: Mapping[str, str]) -> PaymentEvent: ...
```

Implementasi awal: `DuitkuGateway`. Endpoint tidak boleh tahu detail Duitku.

### 5.3 Callback

`POST /webhooks/duitku/{secret}` · Auth: Publik (rahasia path + signature)

Aturan:

1. Bandingkan secret path dengan waktu-konstan.
2. Verifikasi signature Duitku pada raw body.
3. Simpan `provider_events` dengan raw payload.
4. Cari topup berdasarkan `merchantOrderId`/`reference`.
5. Idempoten: callback PAID berulang tidak boleh mengkredit dua kali.
6. Verifikasi nominal callback == `topup.total`.
7. Dalam satu transaksi DB: lock akun + counter, cek limit sekali lagi,
   kredit ledger, update `balance_cached`, update `incoming_counters`,
   ubah topup `PAID`, transaksi `SUCCESS`, reservation `CONSUMED`.
8. Buat notifikasi `TRANSACTION` untuk user.
9. Selalu balas HTTP 200 untuk payload valid/duplikat; 401 untuk signature
   salah.

Event ternormalisasi:

```json
{
  "provider": "DUITKU",
  "provider_ref": "TU-20261018-9K2mQ1",
  "status": "PAID",
  "paid_amount": 100000,
  "paid_at": "2026-10-18T05:35:00Z",
  "raw": {}
}
```

Status pemetaan:

| Duitku | Internal topup |
| --- | --- |
| sukses/paid | `PAID` |
| pending | `WAITING_PAYMENT`/`REQUIRES_ACTION` |
| expired | `EXPIRED` |
| failed/cancelled | `FAILED`/`CANCELLED` |

### 5.4 Rekonsiliasi

Job terjadwal (cron/worker):

- Ambil topup `WAITING_PAYMENT`/`REQUIRES_ACTION` yang lewat `expires_at`
  atau belum menerima callback.
- Panggil `get_status` ke Duitku.
- Jika PAID → proses kredit idempoten.
- Jika EXPIRED/FAILED → release reservation + update status.
- Catat hasil di `provider_events` dan audit log sistem.

---

## 6. Endpoint KYC

Mode Fase 3A: **manual review admin**. Liveness memakai adapter mock/real
yang sama dengan Fase 2; data KTP disimpan privat.

### 6.1 Ajukan KYC

`POST /me/kyc` · Auth: Bearer · `multipart/form-data`

Field:

| Field | Tipe | Wajib |
| --- | --- | --- |
| `nik` | string 16 digit | ya |
| `name` | string 3–100 | ya |
| `address` | string | ya |
| `rt` | string | ya |
| `rw` | string | ya |
| `village` | string | ya |
| `district` | string | ya |
| `city` | string | ya |
| `province` | string | ya |
| `ktp_photo` | file JPEG/PNG maks 10 MB | ya |

Validasi:

- User belum `VERIFIED` (`KYC_ALREADY_VERIFIED`).
- Tidak ada pengajuan `PENDING` (`KYC_PENDING`).
- NIK 16 digit dan belum dipakai akun lain (`NIK_ALREADY_USED`).
- File diperiksa dari isi (magic number), bukan ekstensi.
- Draft berlaku 900 detik; setelah itu `KYC_DRAFT_EXPIRED`.

**Respons sukses — HTTP 201**

```json
{
  "success": true,
  "code": "OK",
  "message": "Data KYC diterima. Lanjutkan verifikasi wajah.",
  "data": {
    "kyc_id": "kyc_7K2mQ1",
    "status": "DRAFT",
    "next_step": "FACE",
    "expires_in": 900,
    "created_at": "2026-10-18T05:30:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

### 6.2 Status KYC

`GET /me/kyc` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "status": "PENDING",
    "level": "BASIC",
    "kyc_id": "kyc_7K2mQ1",
    "reference": "KYC-20261018-7K2mQ1",
    "submitted_at": "2026-10-18T05:35:00Z",
    "estimated_hours": 24,
    "name": "Koko Wijaya",
    "nik_masked": "3171********0001",
    "steps": [
      { "code": "DATA", "label": "Data KTP", "state": "DONE", "at": "2026-10-18T05:30:00Z", "note": null },
      { "code": "FACE", "label": "Verifikasi wajah", "state": "DONE", "at": "2026-10-18T05:35:00Z", "note": null },
      { "code": "REVIEW", "label": "Review admin", "state": "ACTIVE", "at": null, "note": "Estimasi 1x24 jam" }
    ],
    "verified_at": null,
    "reason_code": null,
    "reason": null,
    "can_resubmit": false
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Status: `NONE`, `DRAFT`, `PENDING`, `VERIFIED`, `REJECTED`.
`level` menjadi `PREMIUM` setelah `VERIFIED`. Draft yang kedaluwarsa
dipetakan menjadi `REJECTED` dengan `reason_code="DRAFT_EXPIRED"` agar
sesuai tipe app.

### 6.3 Verifikasi wajah KYC

> **Catatan pivot:** endpoint ini hanya berlaku jika **D-14** memutuskan face
> tetap dipakai untuk KYC. Jika face dihapus, langkah ini dihapus dan KYC
> langsung PENDING setelah submit KTP.

`POST /me/kyc/{kyc_id}/face` · Auth: Bearer

**Request**

```json
{ "liveness_session_id": "lv_8dK2xQ" }
```

Aturan:

- Hanya untuk draft milik user dan belum expired.
- Liveness divalidasi lewat adapter (`mock` Fase 3A; provider asli Fase 6).
- Jika gagal: `FACE_LIVENESS_FAILED`/`FACE_QUALITY_LOW`, draft tetap.
- Jika sukses: `face_verified=true`, status `PENDING`, `submitted_at=now`,
  `next_step="WAIT_REVIEW"`.
- `KYC_NOT_FOUND`, `KYC_NOT_DRAFT`, `KYC_DRAFT_EXPIRED`,
  `LIVENESS_SESSION_INVALID`.

**Respons sukses — HTTP 200** = bentuk `KycStatusData` di 6.2.

---

## 7. Endpoint admin KYC

Semua memakai Bearer admin dan izin `kyc.review`.

### 7.1 Daftar pengajuan

`GET /admin/kyc/submissions?status=&cursor=&limit=` · Auth: Bearer admin

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "id": "kyc_7K2mQ1",
        "status": "PENDING",
        "user_id": "usr_01J9Z3K7QX",
        "name": "Koko Wijaya",
        "nik_masked": "3171********0001",
        "face_verified": true,
        "submitted_at": "2026-10-18T05:35:00Z",
        "estimated_hours": 24
      }
    ],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

### 7.2 Detail pengajuan

`GET /admin/kyc/submissions/{id}` · Auth: Bearer admin

Mengembalikan data KTP (masked/full sesuai izin), signed URL KTP/selfie
berumur pendek, liveness status, dan riwayat keputusan. Akses file dicatat
di audit log.

### 7.3 Putuskan KYC

`POST /admin/kyc/submissions/{id}/decision` · Auth: Bearer admin

**Request**

```json
{ "decision": "APPROVE", "reason": "Data KTP dan wajah cocok" }
```

Validasi:

- `decision`: `APPROVE` | `REJECT`.
- `reason`: wajib 10–300 karakter untuk `REJECT`; opsional untuk approve.
- Hanya status `PENDING`; jika sudah diputuskan → `KYC_ALREADY_DECIDED`.
- Approve: cek ulang NIK unik; set `user.kyc_status=VERIFIED`,
  `user.level=PREMIUM`, `user.name` mengikuti KYC, `name_locked`, buat
  notifikasi `KYC_RESULT`, audit log.
- Reject: set status `REJECTED`, `reason_code`, `reason`; user boleh
  resubmit; notifikasi `KYC_RESULT`.

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Keputusan disimpan.",
  "data": {
    "id": "kyc_7K2mQ1",
    "status": "VERIFIED",
    "decided_at": "2026-10-18T09:00:00Z",
    "level": "PREMIUM"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Catatan: maker-checker dua admin ditunda; Fase 3A memakai satu reviewer
dengan audit log. **[usulan]**

---

## 8. Read bootstrap untuk Home

### 8.1 Daftar transaksi

`GET /transactions?type=&status=&date_from=&date_to=&q=&cursor=&limit=`
· Auth: Bearer

Response mengikuti `TransactionsListData` app:

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "items": [
      {
        "id": "txn_01J9Z3K7QX",
        "type": "TOPUP",
        "title": "Isi Saldo",
        "target": "BCA Virtual Account",
        "status": "SUCCESS",
        "amount": 100000,
        "fee": 0,
        "discount": 0,
        "total": 100000,
        "reference": "TU-20261018-9K2mQ1",
        "points_earned": 0,
        "created_at": "2026-10-18T05:35:00Z"
      }
    ],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 10 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

`status`: `SUCCESS | PENDING | FAILED`. `type`: string bebas; app memetakan
prefix (`TOPUP`, `TRANSFER_*`, `PLN_*`, dst.). Top-up yang `EXPIRED` atau
`FAILED` dipetakan menjadi transaksi `FAILED` dengan `failure_reason`.

### 8.2 Detail transaksi

`GET /transactions/{id}` · Auth: Bearer

Response mengikuti `CreateTransactionData`:

```json
{
  "id": "txn_01J9Z3K7QX",
  "type": "TOPUP",
  "title": "Isi Saldo",
  "target": "BCA Virtual Account",
  "status": "SUCCESS",
  "amount": 100000,
  "fee": 0,
  "discount": 0,
  "total": 100000,
  "reference": "TU-20261018-9K2mQ1",
  "lines": [{ "label": "Nominal", "value": "Rp100.000" }],
  "token": null,
  "payment": { "method": "DUITKU", "paid_amount": 100000 },
  "points_earned": 0,
  "failure_reason": null,
  "refund": null,
  "created_at": "2026-10-18T05:35:00Z",
  "completed_at": "2026-10-18T05:35:05Z"
}
```

### 8.3 Struk digital

`GET /transactions/{id}/receipt?format=link|html|pdf` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "url": "https://cdn.poinqu.id/receipts/txn_01J9Z3K7QX.pdf?expires=...",
    "format": "pdf",
    "expires_at": "2026-10-18T06:30:00Z"
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Jika struk belum siap: `RECEIPT_NOT_AVAILABLE` 422. Fase 3A minimal
mendukung top-up; struk PPOB menyusul.

### 8.4 Katalog layanan Home

`GET /catalog/services` · Auth: Bearer

Response mengikuti `ServicesData` app:

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "quick_actions": [
      {
        "id": "topup",
        "label": "Isi Saldo",
        "icon": "wallet",
        "status": "ACTIVE",
        "enabled": true,
        "link": { "type": "NATIVE", "route": "topup" }
      }
    ],
    "shortcuts": [
      {
        "id": "pulsa",
        "label": "Pulsa",
        "icon": "smartphone",
        "template": "TABBED_CATALOG",
        "enabled": true,
        "status": "ACTIVE"
      }
    ],
    "groups": [],
    "features": [],
    "support_channels": []
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

Sumber: `catalog_documents` key `home`. Full SDUI menyusul Fase 3B.
Cache ETag opsional; app mengirim `If-None-Match` pada halaman katalog,
bukan pada `/catalog/services` saat ini.

### 8.5 Notifikasi

`GET /notifications?cursor=&limit=` · Auth: Bearer

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Berhasil.",
  "data": {
    "unread_count": 1,
    "items": [
      {
        "id": "ntf_01J9Z3K7QX",
        "type": "TRANSACTION",
        "title": "Top-up berhasil",
        "body": "Saldo Rp100.000 sudah masuk.",
        "icon": "wallet",
        "read": false,
        "deep_link": "bayarin://transactions/txn_01J9Z3K7QX",
        "created_at": "2026-10-18T05:35:00Z"
      }
    ],
    "pagination": { "next_cursor": null, "has_more": false, "limit": 20 }
  },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

`POST /notifications/read` · Auth: Bearer

**Request**

```json
{ "ids": ["ntf_01J9Z3K7QX"], "all": false }
```

**Respons sukses — HTTP 200**

```json
{
  "success": true,
  "code": "OK",
  "message": "Notifikasi ditandai sudah dibaca.",
  "data": { "updated": 1, "unread_count": 0 },
  "meta": { "request_id": "req_8f3a1c2d9e", "timestamp": "2026-10-18T05:30:00Z" }
}
```

`ids` dan `all` tidak boleh kosong bersamaan. `all=true` mengabaikan `ids`.
Notifikasi yang dibuat Fase 3A: `TRANSACTION` saat top-up PAID dan
`KYC_RESULT` saat keputusan admin.

---

## 9. State machine dan atomisitas

### 9.1 Top-up

```
CREATED
  ├─ provider sukses → WAITING_PAYMENT
  │     ├─ callback PAID → PAID (final, saldo dikreditkan)
  │     ├─ cancel → CANCELLED (final)
  │     ├─ lewat expires_at → EXPIRED (final)
  │     └─ provider gagal → FAILED (final)
  ├─ provider gagal pasti → FAILED (final)
  └─ timeout/ambigu → REQUIRES_ACTION / WAITING_PAYMENT
        └─ rekonsiliasi → PAID / EXPIRED / FAILED
```

Aturan:

- `PAID` tidak boleh diubah lagi.
- Kredit saldo hanya sekali; kunci idempotensi + status final.
- Cek limit dilakukan saat create **dan** saat callback PAID (di dalam
  transaksi DB yang sama dengan ledger), karena saldo bisa berubah.
- Reservation dilepas pada `CANCELLED`, `EXPIRED`, `FAILED`; dikonsumsi
  pada `PAID`.

### 9.2 KYC

```
NONE → DRAFT → PENDING → VERIFIED
                      ↘ REJECTED → (resubmit) DRAFT
DRAFT → REJECTED (reason DRAFT_EXPIRED)
```

- `DRAFT` hanya boleh diubah oleh pemilik dan belum expired.
- `PENDING` tidak boleh diedit.
- Approve menulis `users.kyc_status=VERIFIED`, `level=PREMIUM`, dan
  mengunci nama.
- Reject menyimpan alasan; user bisa membuat draft baru.

---

## 10. Test wajib

### Wallet/top-up

- Create top-up sukses VA dan QRIS; instruksi dan `expires_at` benar.
- Idempotency: request ulang key sama → respons sama, tidak membuat order baru.
- Key sama payload beda → `IDEMPOTENCY_KEY_REUSED`.
- Limit saldo dan limit dana masuk bulanan, termasuk request paralel.
- `TOPUP_PENDING_LIMIT`.
- Callback PAID: saldo bertambah tepat sekali; callback duplikat tidak
  menambah saldo.
- Callback nominal tidak cocok → tidak kredit + alert.
- Callback signature salah → 401.
- Expired/cancel melepas reservation.
- Rekonsiliasi mengubah status PENDING yang tertinggal.
- Ledger balance == `balance_cached` setelah serangkaian transaksi.

### KYC

- Submit KTP valid → DRAFT, file tersimpan privat.
- NIK duplikat → `NIK_ALREADY_USED`.
- File terlalu besar/format salah → 413/415.
- Face sukses → PENDING; face gagal → tetap DRAFT.
- Draft expired → `KYC_DRAFT_EXPIRED`.
- Admin approve → user PREMIUM, notifikasi, audit log.
- Admin reject → alasan tersimpan, user bisa resubmit.
- Admin non-`kyc.review` → `FORBIDDEN`.
- File KTP tidak bisa diakses tanpa signed URL/izin.

### Read bootstrap

- Home menerima `/wallet`, `/transactions?limit=3`, `/catalog/services`,
  `/notifications` tanpa error.
- Pagination cursor transaksi/notifikasi.
- Mark read satu/all dan `unread_count` benar.
- `GET /transactions/{id}` hanya untuk transaksi milik user.

### Integrasi app

- `EXPO_PUBLIC_USE_MOCK=0` + login → Home menampilkan saldo, transaksi,
  shortcut, badge notifikasi.
- Access token expired → refresh mengirim `X-Device-Id` dan berhasil.
- Top-up → kode bayar → polling → PAID → saldo berubah.
- KYC → PENDING → admin approve → level PREMIUM.
- Error dari backend tampil dengan `message`/`code` yang benar.

---

## 11. Keputusan

Daftar keputusan tunggal ada di `DECISIONS.md`. Yang memblokir dokumen ini:

- **D-10** — wallet/top-up/KYC tetap dipakai setelah pivot PPOB?
- **D-20** — model saldo prabayar atau bayar langsung per transaksi?
- **D-23** — detail channel + signature callback Duitku.
- **D-24/D-25/D-26** — selfie KYC, maker-checker, retensi file.
- **D-27** — domain deep link.
- **D-28** — `topup.max_pending` dan TTL.

Jangan menambah daftar keputusan baru di sini. Update `DECISIONS.md` lalu
sinkronkan dokumen ini.
