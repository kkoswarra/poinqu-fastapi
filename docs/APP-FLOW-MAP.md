# PETA FLOW APP — React Native ↔ Backend

Status: **referensi hidup** · 18 Oktober 2026

Dokumen ini memetakan flow app React Native dan kontrak API yang benar-benar
dipakai app. Dokumen ini **bukan kontrak fase**. Kontrak fase ada di
`FASE-2-API.md`, `FASE-2.1-PIVOT.md`, dan `FASE-3-API.md`.

Gunakan dokumen ini untuk menjawab: “layar ini memanggil endpoint apa, dengan
tipe data apa, dan backend saat ini sudah punya atau belum?”

> **Snapshot app saat ini.** Perubahan target setelah pivot PPOB — hapus face,
> login email/nomor HP, hapus recovery, ganti nomor/email — ada di
> `FASE-2.1-PIVOT.md`. Jangan menganggap flow face/recovery di peta ini
> sebagai target akhir.

Sumber utama:

- `app-frontend/src/api/types/*` dan `app-frontend/src/api/endpoints/*` — kontrak yang benar-benar dipakai app.
- `app-frontend/src/screens/*`, `src/hooks/*`, `src/navigation/*` — flow nyata di layar.
- `poinqu-fastapi/docs/PLAN.md` — aturan bisnis dan rencana fase.
- Implementasi backend Fase 2 saat ini.

Catatan penting: `app-frontend/openapi.json` **bukan** status implementasi backend.
File itu adalah kontrak lama/terpisah dan memuat banyak endpoint yang belum ada.

---

## 1. Ringkasan

1. App default berjalan dengan **mock** (`EXPO_PUBLIC_USE_MOCK=1`).
2. Backend Fase 2 baru melayani auth, recovery, profil, PIN, devices,
   biometrics, security activities, admin, dan webhook Fonnte.
3. Domain besar yang sudah dipakai app tetapi belum ada backend:
   wallet, top-up, transfers, inquiries, catalog/SDUI, transactions,
   promos, points, saved numbers, reminders, notifications, support, KYC,
   legal, payment requests/QRIS, dan step-up.
4. Ada beberapa blocker integrasi yang harus diselesaikan sebelum Fase 3
   ditulis, terutama refresh token dan format public key biometrik.

---

## 2. Peta navigasi app

### Auth stack

`Login` → `Register` / `ForgotPin` / `LostPhone`.

### Main tabs

`Home`, `History`, `Scan`, `Promo`, `Account`.

### Root stack

- Tagihan/SDUI: `Service`, `MenuGrid`, `More`
- Transfer: `TransferBank`, `TransferBayarin`
- Wallet: `TopUp`, `TopUpCode`, `TopUpHistory`
- Request: `RequestMoney`, `RequestQR`
- Scan: `QrisPay`, `PayRequest`
- Points: `Points`
- Akun: `Profile`, `Premium`, `PremiumFace`, `PremiumPending`,
  `Saved`, `Reminders`, `ChangePin`, `Biometric`, `Devices`
- Support: `Notif`, `Help`, `Terms`, `Privacy`, `CreateTicket`
- `Receipt`

Catatan: `CheckoutScreen.tsx` tidak terdaftar di navigasi dan merupakan dead code.
Checkout aktif memakai `ConfirmSheet` → `PinSheet`/`StepUpSheet`.

---

## 3. Flow per domain

| Domain | Layar/flow utama | Endpoint app | Backend Fase 2 | Catatan |
|---|---|---|---|---|
| Auth | Login, Register, ForgotPin | `/auth/*`, `/auth/login/start`, `/auth/biometric/challenge` | ✅ | blocker refresh header |
| Phone recovery | LostPhone | `/auth/phone-recovery*`, `/support*` | ✅ | perlu data KYC |
| Profil/avatar | Profile, Account | `/me`, `/me/avatar` | ✅ | |
| PIN | ChangePin, PinSheet | `/me/pin/change`, `/me/pin/verify` | ✅ | |
| Step-up | ConfirmSheet, StepUpSheet | `/me/stepup/request`, `/verify` | ❌ | wajib untuk transaksi > ambang |
| Wallet | Home, TopUp | `/wallet` | ❌ | Home butuh ini |
| Top-up | TopUp, TopUpCode, TopUpHistory | `/wallet/topups*` | ❌ | Duitku + polling status |
| Transfer | TransferBank, TransferBayarin | `/inquiries`, `/transfers/recipients*`, `/transactions*` | ❌ | butuh premium + step-up |
| Katalog/SDUI | Home, Service, MenuGrid | `/catalog/services*`, `/catalog/pages/*` | ❌ | Home & PPOB butuh ini |
| PPOB/tagihan | BillFlow, Service | `/inquiries`, `/transactions*` | ❌ | PLN, PDAM, BPJS, pulsa, data, game, dll. |
| Checkout | ConfirmSheet | `/transactions/preview`, `POST /transactions` | ❌ | PIN token + idempotency + step-up |
| Riwayat/struk | History, Receipt | `/transactions`, `/transactions/{id}`, `/receipt` | ❌ | |
| Promo | PromoScreen | `/promos`, `/promos/validate` | ❌ | validasi nyata terjadi di preview |
| Points | PointsScreen | `/points*`, `/points/redeem` | ❌ | pin token + idempotency |
| Saved numbers | SavedScreen | `/saved-numbers*` | ❌ | |
| Reminders | RemindersScreen | `/reminders*` | ❌ | |
| Notifications | NotifScreen, Home badge | `/notifications*` | ❌ | Home butuh unread count |
| Support | Help, CreateTicket | `/support/tickets`, `/support/faqs` | ❌ | |
| Legal | Terms, Privacy | `/legal/terms`, `/legal/privacy` | ❌ | |
| KYC/Premium | Premium, PremiumFace, PremiumPending | `/me/kyc*` | ❌ | hanya model `KycProfile` |
| Payment request/QRIS | RequestMoney, RequestQR, PayRequest, QrisPay | `/payment-requests*`, `/inquiries` | ❌ | |
| Devices | DevicesScreen | `/me/devices*` | ✅ | |
| Biometrics | BiometricScreen | `/me/biometrics*` | ✅ | format public key mismatch |
| Security activities | Home | `/me/security/activities` | ✅ | `PHONE_CHANGED` belum ada di tipe app |

---

## 4. Blocker integrasi sebelum fitur baru

### 4.1 Refresh token tidak mengirim `X-Device-Id`

- App: `src/api/client.ts` memakai `refreshClient` tanpa interceptor.
- Backend: semua `/v1` non-admin/webhook mewajibkan `X-Device-Id`.
- Efek: access token kedaluwarsa → refresh 422 → app logout paksa.
- Perbaikan: tambahkan `X-Device-Id` (dan versi app) ke `refreshClient`,
  atau pakai client utama dengan flag no-retry.

### 4.2 Format public key biometrik

- App mengirim **PEM** (`-----BEGIN PUBLIC KEY-----`).
- Backend `validate_ec_public_key()` mengharapkan **base64 DER**.
- Efek: enrollment fingerprint/face gagal `INVALID_VALUE`.
- Perbaikan: app mengirim base64 DER, atau backend menerima PEM secara eksplisit.

### 4.3 KYC belum punya endpoint

App memakai `POST/GET /me/kyc` dan `POST /me/kyc/{id}/face`.
Backend hanya punya model `KycProfile` (hash NIK + tanggal lahir) tanpa router.
Akibatnya upgrade Premium dan recovery jalur KYC belum punya sumber data.

### 4.4 Step-up belum ada

`ConfirmSheet` memanggil `/me/stepup/request` dan `/me/stepup/verify`
sebelum PIN untuk transaksi yang memerlukan verifikasi tambahan.
Tanpa endpoint ini, transfer besar tidak bisa diselesaikan.

### 4.5 Home butuh endpoint baca yang belum ada

`HomeScreen` memanggil:

- `GET /wallet`
- `GET /transactions?limit=3`
- `GET /catalog/services`
- `GET /notifications` (unread count)
- `GET /me/security/activities` ✅ sudah ada

Jadi Fase 3 perlu minimal **read bootstrap** untuk wallet, transaksi,
katalog, dan notifikasi agar app tidak kosong setelah login.

### 4.6 Error map app terbelah

- Runtime memakai `src/api/errors.ts` (sedikit kode).
- `src/lib/errors.ts` berisi 142 kode tetapi tidak dipakai client.
- Beberapa kode mock tidak konsisten (`POINTS_INSUFFICIENT` vs `INSUFFICIENT_POINTS`).
- `PHONE_CHANGED` belum ada di union `SecurityEventType`.

### 4.7 Idempotency key

App sudah mengirim `Idempotency-Key` untuk top-up, transaksi, dan redeem.
Namun key dibuat baru setiap mutation; untuk retry jaringan key harus sama
per attempt. Backend juga harus menyimpan hasil per key, bukan hanya
menolak key yang sudah dipakai.

### 4.8 Prefix fail-closed revocation

`MONEY_PATH_PREFIXES` backend saat ini belum mencakup path app yang sebenarnya:
`/v1/wallet/topups`, `/v1/transactions`, `/v1/inquiries`, `/v1/points/redeem`.
Perlu diselaraskan agar Redis mati → endpoint uang fail-closed.

---

## 5. Usulan urutan fase

> Ini **usulan**, bukan keputusan. Scope final ada di `DECISIONS.md`,
> khususnya D-10. Jika pivot PPOB menghapus wallet/KYC, urutan ini berubah.

### Fase 3A — Wallet, Top-up, KYC, dan read bootstrap

- Ledger double-entry + akun + saldo + limit.
- `GET /wallet`, `GET /wallet/topup-methods`, `POST /wallet/topups`,
  `GET /wallet/topups`, `GET /wallet/topups/{id}`, cancel.
- `POST /me/kyc`, `GET /me/kyc`, `POST /me/kyc/{id}/face`.
- `GET /transactions` read-only untuk Home/History.
- `GET /notifications` read-only untuk badge Home.
- `GET /catalog/services` read-only agar shortcut Home tidak kosong.
- Callback Duitku + rekonsiliasi.

### Fase 3B — Katalog/SDUI, inquiry, dan PPOB

- `/catalog/pages/{id}`, `/catalog/services/{id}/template`,
  `/catalog/services/{id}/categories`, `/catalog/services/{id}/items`.
- `POST /inquiries`.
- `POST /transactions/preview`, `POST /transactions`,
  `GET /transactions/{id}`, `GET /transactions/{id}/receipt`.
- Adapter vendor PPOB (Digiflazz/Otomax), hold/refund, callback.

### Fase 3C — Transfer, step-up, payment request, QRIS

- `/transfers/recipients*`.
- `/me/stepup/request`, `/me/stepup/verify`.
- Transfer sesama pengguna dan transfer bank (BI-FAST).
- `/payment-requests*`, QRIS inquiry.

### Fase 3D — Fitur pendukung

- Promo, points, saved numbers, reminders, notifications lengkap,
  support, legal.
- Admin panel untuk KYC review, transaksi, top-up, refund, katalog.

---

## 6. Dokumen terkait

Peta ini dipakai bersama:

- `docs/README.md` — indeks dan urutan baca.
- `docs/DECISIONS.md` — satu daftar keputusan.
- `docs/FASE-2.1-PIVOT.md` — perubahan auth setelah pivot PPOB.
- `docs/FASE-3-API.md` — draft kontrak fase berikutnya.
- `docs/FASE-3-FLOW.md` — flow app untuk fase berikutnya.
- `docs/FASE-3-TASKS.md` — checklist implementasi.

## 7. Keputusan

Jangan menambah daftar keputusan baru di dokumen ini. Semua keputusan
produk/auth/fase dicatat di `docs/DECISIONS.md` agar tidak tersebar.
