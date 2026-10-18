# TASKS — Fase 3A: Wallet, Top-up, KYC, Read Bootstrap

> **Status:** draft, bergantung pada keputusan **D-10** di `DECISIONS.md`.
> Jangan mulai task backend sebelum scope wallet/top-up/KYC final.
>
> Kontrak: `FASE-3-API.md` · flow: `FASE-3-FLOW.md` · indeks: `README.md`.

Dokumen kerja implementasi. Urutan task dibuat agar backend, app, dan admin
bisa berjalan paralel tanpa saling menunggu.

Legenda: `[ ]` belum, `[~]` sedang, `[x]` selesai.

---

## 1. Fondasi backend

- [ ] Tambah Alembic (baseline Fase 2 + migrasi Fase 3).
- [ ] Migrasi tabel: `accounts`, `ledger_entries`, `transactions`, `topups`,
      `topup_channels`, `wallet_reservations`, `incoming_counters`,
      `kyc_submissions`, `notifications`, `catalog_documents`,
      `idempotency_keys`, `provider_events`.
- [ ] Buat service `ledger`:
  - [ ] `credit(account, amount, entry_type, transaction_id)`
  - [ ] `debit(...)`
  - [ ] `balance_cached` update atomik + row lock.
  - [ ] verifikasi `sum(ledger) == balance_cached` untuk job audit.
- [ ] Buat service `limits`:
  - [ ] hitung `balance_room` + `monthly_remaining` termasuk reservasi.
  - [ ] cek limit di dalam transaksi DB.
  - [ ] counter bulan WIB.
- [ ] Buat service `idempotency`:
  - [ ] simpan key + hash payload + respons.
  - [ ] key sama payload sama → respons tersimpan.
  - [ ] key sama payload beda → `IDEMPOTENCY_KEY_REUSED`.
- [ ] Tambah dependency `require_idempotency_key`.
- [ ] Tambah error code baru ke `app/core/errors.py`.
- [ ] Tambah permission `kyc.review` (sudah ada di seed, pastikan dipakai).
- [ ] Tambah konfigurasi `DUITKU_*`, `KYC_*`, `TOPUP_*`.

---

## 2. Wallet

- [ ] Model + repository `accounts`.
- [ ] Buat akun otomatis saat register/complete (dan lazily untuk user lama).
- [ ] `GET /wallet`:
  - [ ] saldo, currency, points (0 sementara), limits, updated_at.
  - [ ] hitung limit BASIC/PREMIUM.
- [ ] Test:
  - [ ] user baru → saldo 0.
  - [ ] limit BASIC/PREMIUM benar.
  - [ ] `balance_room`/`monthly_remaining` memperhitungkan reservasi.

---

## 3. Top-up dan Duitku

- [ ] Tabel + seed `topup_channels` (VA/QRIS minimal).
- [ ] Adapter `PaymentGateway` + `DuitkuGateway`.
- [ ] `GET /wallet/topup-methods`.
- [ ] `POST /wallet/topups`:
  - [ ] validasi amount/channel.
  - [ ] cek limit + reservasi.
  - [ ] idempotency.
  - [ ] create transaksi + topup.
  - [ ] panggil Duitku.
  - [ ] simpan instruksi/payment code.
  - [ ] mapping kegagalan provider.
- [ ] `GET /wallet/topups/{id}`.
- [ ] `GET /wallet/topups` (filter + cursor).
- [ ] `POST /wallet/topups/{id}/cancel`.
- [ ] Webhook `POST /webhooks/duitku/{secret}`:
  - [ ] secret + signature.
  - [ ] log `provider_events`.
  - [ ] idempotent PAID.
  - [ ] verifikasi nominal.
  - [ ] kredit ledger + counter + notifikasi.
- [ ] Job rekonsiliasi:
  - [ ] topup PENDING/REQUIRES_ACTION.
  - [ ] get status provider.
  - [ ] expired → release reservation.
- [ ] Job expire topup.
- [ ] Test:
  - [ ] create VA + QRIS.
  - [ ] idempotency.
  - [ ] limit paralel.
  - [ ] callback duplikat.
  - [ ] nominal mismatch.
  - [ ] signature salah.
  - [ ] cancel/expire.
  - [ ] ledger balance.

---

## 4. KYC

> **Catatan pivot:** task face di bawah hanya berlaku jika **D-14**
> mempertahankan face untuk KYC. Jika face dihapus, lewati `POST
> /me/kyc/{id}/face` dan langsung set PENDING setelah submit KTP.

- [ ] Upload file ke object storage privat (Vercel Blob/S3).
- [ ] `POST /me/kyc` multipart:
  - [ ] validasi field + file.
  - [ ] hash NIK + enkripsi NIK.
  - [ ] cek NIK duplikat.
  - [ ] cek status user.
  - [ ] buat draft + expiry.
- [ ] `GET /me/kyc`:
  - [ ] status, level, steps, reason, can_resubmit.
  - [ ] map draft expired → REJECTED/DRAFT_EXPIRED.
- [ ] `POST /me/kyc/{id}/face`:
  - [ ] cek pemilik + draft.
  - [ ] liveness adapter (mock dulu).
  - [ ] set PENDING + submitted_at.
- [ ] Job expire draft KYC.
- [ ] Test:
  - [ ] KTP valid.
  - [ ] NIK duplikat.
  - [ ] file besar/format salah.
  - [ ] face sukses/gagal.
  - [ ] draft expired.
  - [ ] akses file privat.

---

## 5. Admin KYC

- [ ] `GET /admin/kyc/submissions` (filter status + cursor).
- [ ] `GET /admin/kyc/submissions/{id}` + signed URL.
- [ ] `POST /admin/kyc/submissions/{id}/decision`.
- [ ] Approve:
  - [ ] cek NIK unik ulang.
  - [ ] `kyc_status=VERIFIED`, `level=PREMIUM`, nama terkunci.
  - [ ] notifikasi + audit.
- [ ] Reject:
  - [ ] reason_code/reason.
  - [ ] notifikasi + audit.
- [ ] Test permission `kyc.review`, double decision, NIK conflict.

---

## 6. Read bootstrap

- [ ] `GET /transactions` (list + filter + cursor).
- [ ] `GET /transactions/{id}`.
- [ ] `GET /transactions/{id}/receipt`.
- [ ] Seed `catalog_documents['home']` dengan payload `ServicesData`.
- [ ] `GET /catalog/services`.
- [ ] Tabel + service `notifications`.
- [ ] `GET /notifications`.
- [ ] `POST /notifications/read`.
- [ ] Notifikasi otomatis:
  - [ ] top-up PAID.
  - [ ] KYC decision.
- [ ] Test Home memuat 4 endpoint tanpa error.

---

## 7. App React Native

- [ ] `refreshClient` mengirim `X-Device-Id` + versi app.
- [ ] Public key biometrik: base64 DER atau backend menerima PEM.
- [ ] `UNAUTHORIZED` → logout.
- [ ] Satukan peta error `src/api/errors.ts` + `src/lib/errors.ts`.
- [ ] Top-up:
  - [ ] pakai total/fee server.
  - [ ] tangani `action`/`REQUIRES_ACTION`.
  - [ ] `FAILED` final.
  - [ ] simpan idempotency key per attempt.
- [ ] KYC:
  - [ ] kirim multipart sesuai kontrak.
  - [ ] status/steps/reason.
  - [ ] resubmit.
- [ ] Home:
  - [ ] fallback jika catalog kosong.
  - [ ] badge notifikasi.
- [ ] Deep link `bayarin://`/`poinqu://` diselaraskan.
- [ ] Switch `EXPO_PUBLIC_USE_MOCK=0` di staging.

---

## 8. Ops dan keamanan

- [ ] Secret Duitku di Vercel Environment Variables.
- [ ] Object storage privat untuk KTP.
- [ ] `MONEY_PATH_PREFIXES` mencakup `/v1/wallet`, `/v1/transactions`,
      `/v1/inquiries`, `/v1/points`.
- [ ] Alert:
  - [ ] callback signature gagal,
  - [ ] nominal mismatch,
  - [ ] rekonsiliasi selisih,
  - [ ] saldo negatif/ledger tidak balance.
- [ ] Retensi file KTP dan log callback.
- [ ] Backup/restore DB.
- [ ] Rate limit top-up/KYC.
- [ ] Pantau biaya Duitku/kuota.

---

## 9. Definition of Done Fase 3A

- [ ] App dengan `USE_MOCK=0` bisa login → Home (saldo, transaksi,
      shortcut, badge).
- [ ] Top-up VA/QRIS membuat kode, polling, dan saldo bertambah setelah PAID.
- [ ] Callback duplikat tidak menggandakan saldo; ledger balance.
- [ ] KYC KTP + face → PENDING; admin approve → PREMIUM.
- [ ] Notifikasi top-up/KYC muncul.
- [ ] Semua test backend lulus; test kontrak app lulus.
- [ ] Tidak ada file KTP di `/tmp` atau URL publik permanen.
- [ ] Dokumentasi OpenAPI memuat endpoint Fase 3A + error schema.
- [ ] `docs/FASE-3-API.md`, `FASE-3-FLOW.md`, dan `FASE-3-TASKS.md` sinkron
      dengan implementasi.
