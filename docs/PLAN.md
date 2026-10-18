# Rencana Pembangunan Dompet Digital (E-Wallet)

> **Catatan pivot 18 Oktober 2026:** arah produk sedang dipivot dari dompet
> digital menjadi **penjualan pulsa & PPOB**. Lihat `FASE-2.1-PIVOT.md` dan
> `DECISIONS.md`. Bagian dompet, transfer, dan KYC di dokumen ini belum final
> sampai keputusan D-10 selesai; jangan dianggap kontrak implementasi.
>
> Status: **Draft v0.4** — dokumen hidup, direvisi tiap fase.
> Perubahan v0.4: **koreksi limit** (PBI 20/6/PBI/2018 sudah dinaikkan oleh PADG 24/7/2022: saldo premium Rp20jt, dana masuk premium Rp40jt/bulan); kanal transfer ke bank = **BI-FAST** (bagian 2.2); semua pertanyaan terbuka diisi **rekomendasi default** (bagian 13); catatan aturan baru PBI 10/2025 & PADG 32/2025 (berlaku 31 Maret 2026).
> Perubahan v0.3: aturan limit dan kepatuhan mengacu pada regulasi BI tentang Uang Elektronik.
> Perubahan v0.2: limit bulanan kalender, fee transfer, transfer khusus premium, KYC live capture, multi-vendor PPOB (Digiflazz + Otomax H2H), OTP via WA Gateway.
> Asumsi yang perlu dikonfirmasi ditandai **[ASUMSI]**.

---

## 1. Ringkasan & Tujuan

Membangun dompet digital dengan fitur utama:

- Saldo pengguna (disimpan sendiri) dengan isi saldo (top-up) via **Duitku**.
- Transfer saldo antar pengguna.
- **PPOB** (prepaid & pascabayar) via **multi-vendor**: **Digiflazz** dan **Host to Host (Otomax)**; vendor ditentukan per item/SKU.
- Katalog layanan **dinamis**: layanan baru bisa ditambah tanpa rilis app (Server-Driven UI).
- Admin panel untuk operasional, rekonsiliasi, dan monitoring.

### Stack

| Komponen | Teknologi |
|---|---|
| Mobile app | React Native (TypeScript) |
| Backend API (app + admin) | Python **FastAPI** |
| Admin panel | Next.js (TypeScript) |
| Database utama | PostgreSQL |
| Cache / rate limit / lock | Redis |
| Antrean job & callback | Celery/RQ (atau ARQ) + Redis |
| Pembayaran top-up | Duitku |
| Vendor PPOB | Digiflazz + Host to Host (Otomax), multi-vendor |
| Pengiriman OTP | **WA Gateway** (satu-satunya kanal) |
| Transfer ke bank | **BI-FAST** lewat PJP/bank sponsor partner (lihat 2.2) |

> Keputusan: backend satu codebase FastAPI untuk app dan admin agar tidak ada dua basis kode (PHP tidak dipakai).

---

## 2. Aturan Bisnis & Limit

| Aturan | Nilai | Sumber |
|---|---|---|
| Saldo maksimum akun **non-premium** (*unregistered*) | **Rp2.000.000** | PBI 20/6/PBI/2018; PADG 24/7/2022 |
| Saldo maksimum akun **premium** (*registered*) | **Rp20.000.000** (sebelumnya Rp10jt sebelum 1 Juli 2022) | PADG 24/7/2022 |
| Total **dana masuk** per **bulan kalender** (top-up/deposit + transfer masuk dari pengguna mana pun) | **Non-premium: Rp20.000.000. Premium: Rp40.000.000.** Reset tanggal 1 pukul 00:00 WIB. **[ASUMSI: refund/reversal transaksi gagal tidak dihitung; konfirmasi ke BI]** | PADG 24/7/2022 (dihitung dari transaksi *incoming*) |
| Sumber angka limit | Angka di atas dari PADG 24/7/2022 (yang terakhir saya temukan). **Belum terverifikasi dari sumber primer apakah PBI 10/2025 + PADG 32/2025 (berlaku 31 Maret 2026) mengubahnya.** Semua limit disimpan sebagai konfigurasi berversi (`effective_date`), bukan hardcode | Keputusan desain |
| Batas harian | **Tidak ada** | Keputusan produk |
| Fitur transfer | **Hanya untuk user premium (*registered*)**. PBI membatasi fitur transfer dana dan tarik tunai untuk UE *open loop* dan *registered* (lihat 2.1) | PBI + keputusan produk |
| Transfer per transaksi | maksimum **Rp10.000.000** (batas produk; saldo premium kini bisa sampai Rp20jt sehingga batas ini berdiri sendiri) | Keputusan produk |
| Transfer > Rp5.000.000 | **Dipertahankan**: wajib verifikasi tambahan pada sesi transaksi (mis. biometrik atau liveness ulang) demi keamanan | Keputusan produk |
| Transfer ke bank | Tersedia untuk premium; maks Rp10jt per transaksi; wajib inquiry/validasi nama rekening tujuan sebelum PIN; saldo ditahan dan status `PENDING` sampai kanal mengonfirmasi **Kanal: BI-FAST (lihat 2.2)** | Keputusan produk + PBI (transfer dana) |
| Biaya transfer | **Transfer sesama pengguna: gratis**. **Transfer ke bank: 10 transaksi pertama tiap bulan kalender gratis; transaksi ke-11 dan seterusnya Rp2.500** per transaksi **[ASUMSI: transfer sesama tidak dihitung ke kuota; hanya transfer ke bank yang dihitung; transaksi gagal/reversal tidak mengurangi kuota]** | Keputusan produk. Rp2.500 = batas maksimum fee BI-FAST ke nasabah (lihat 2.2), jadi tidak boleh dinaikkan |
| Tarik dana / tarik tunai | **Tidak ada layanan tarik dana ke bank**; yang tersedia adalah **layanan Transfer ke bank** (baris di atas). Rencana masa depan (belum terencana): tarik tunai di Alfamart/Indomaret/ATM dengan kode penarikan | Keputusan produk |
| Semua transaksi (top-up, PPOB, transfer) | **Wajib PIN** | Keputusan produk |

Catatan desain: batas bulanan hanya menghitung **dana masuk**. Total uang keluar sebulan dibatasi tidak langsung oleh saldo: maksimal kira-kira saldo awal bulan + dana masuk bulan itu (premium: ≤ Rp20jt + Rp40jt = Rp60jt). Batas ini harus dicek **atomik di dalam transaksi DB ledger** (row lock) agar tahan terhadap request paralel.

Aturan tambahan yang disarankan:

- Penghitung limit bulanan dan jumlah transfer (untuk fee) disimpan per user per bulan kalender, diperbarui atomik di transaksi DB yang sama dengan ledger.
- Batas percobaan PIN salah: 3x → kunci sementara 30 menit, 5x → kunci akun & verifikasi ulang.
- Cooling-off untuk perangkat baru (transfer besar dibatasi 24 jam pertama).
- Level akun: **Non-premium / unregistered** (saldo maks Rp2jt, dana masuk maks Rp20jt/bulan, tanpa transfer) dan **Premium / registered** (e-KTP + selfie terverifikasi, saldo maks Rp20jt, dana masuk maks Rp40jt/bulan, transfer terbuka).

### 2.1 Kepatuhan regulasi BI (Uang Elektronik)

Acuan dasar: halaman BI [pbi-200618](https://www.bi.go.id/id/publikasi/peraturan/pages/pbi-200618.aspx) (PBI 20/6/PBI/2018, berlaku 4 Mei 2018; halaman terakhir diperbarui 15/1/2021).

**Perkembangan aturan yang ditemukan (perlu diverifikasi):**
- Batas nilai pada PBI 2018 (saldo registered Rp10jt, transaksi bulanan Rp20jt) **sudah dinaikkan** berlaku 1 Juli 2022: saldo registered Rp20jt, transaksi bulanan registered Rp40jt, unregistered tetap Rp2jt dan Rp20jt (PADG 24/7/2022). Inilah sebabnya angka Anda sebelumnya (40jt) ternyata sejalan dengan aturan.
- **PBI 10/2025 dan PADG 32/2025 tentang Pengaturan Industri Sistem Pembayaran berlaku sejak 31 Maret 2026** dan menata ulang perizinan PJP (paket aktivitas). Saya belum bisa memastikan dari sumber primer apakah PBI 20/6/PBI/2018 dicabut atau limit di atas berubah. **Wajib dicek ke BI/konsultan sebelum limit dikunci.**

Dompet ini diklasifikasikan sebagai **server based**; *registered* (premium) vs *unregistered* (non-premium); lingkup **closed loop vs open loop belum ditentukan**.

| Topik | Ketentuan (ringkasan) | Dampak ke desain |
|---|---|---|
| Batas nilai | Saldo: unregistered ≤ Rp2jt, registered ≤ Rp20jt. Transaksi *incoming* per bulan: unregistered ≤ Rp20jt, registered ≤ Rp40jt (PADG 24/7/2022; PBI 2018 awal: Rp10jt dan Rp20jt) | Limit engine konfigurabel dan berversi di ledger (bagian 2 dan 5) |
| Fitur transfer & tarik tunai | Hanya untuk UE *open loop* dan *registered* | Transfer hanya premium; **pastikan klasifikasi open loop** |
| Keamanan | Standar keamanan transaksi harus ditingkatkan untuk UE dengan batas nilai di atas Rp2jt (akun registered) | PIN, device binding, authorization token, anti-fraud (bagian 6) wajib kuat |
| Izin BI | Penyelenggara dengan **dana float ≥ Rp1 miliar wajib izin** lebih dulu (PBI 2018; PADG 32/2025 Pasal 21 memuat ambang yang sama untuk UE *closed loop* menurut ringkasan sekunder; izin diajukan sebagai **PJP**). Izin berlaku 5 tahun; entitas PT; ≥51% saham WNI/badan hukum Indonesia (untuk LSB penerbit); modal disetor naik seiring float | **Monitor float** dengan alert (mis. 50% dan 80% dari Rp1 miliar); proses izin dimulai jauh sebelum mencapai ambang |
| Dana float | Dicatat sebagai kewajiban; ≥30% di kas/giro bank BUKU 4, ≤70% di surat berharga pemerintah/BI atau rekening di BI (bagi penerbit berizin) | Laporan float harian dan rekonsiliasi dengan rekening escrow |
| Kerja sama & produk baru | Penyelenggara berizin wajib mendapat **persetujuan BI** sebelum pengembangan produk/aktivitas atau kerja sama dengan pihak lain | Berlaku untuk Duitku, vendor PPOB, dan rencana tarik tunai Alfamart/Indomaret/ATM |
| Pemrosesan domestik | Transaksi UE wajib diproses di wilayah Indonesia; rupiah saja | Hosting/region data di Indonesia |
| AML/CFT & perlindungan konsumen | Wajib diterapkan penerbit | KYC, pemantauan transaksi mencurigakan, mekanisme pengaduan |
| **Biaya** | Biaya yang boleh dikenakan penerbit: media/penggantian, **top-up**, tarik tunai *off-us*, dan **transfer antar-pengguna UE dari penerbit berbeda** | Transfer sesama pengguna **gratis**; biaya hanya untuk transfer ke bank (10 gratis per bulan, ke-11 dst Rp2.500). Transfer ke bank lewat BI-FAST: fee ke nasabah maks Rp2.500 per transaksi menurut skema harga BI (lihat 2.2), jadi Rp2.500 Anda sejalan; **tetap konfirmasi skema kuota gratis ke BI/konsultan** |
| Pelaporan & pengawasan | BI mengawasi langsung/tidak langsung, termasuk pihak yang bekerja sama | Audit log, laporan berkala, akses data untuk pemeriksaan |

> ⚠️ Ringkasan ini dari halaman BI dan sumber sekunder, **bukan nasihat hukum**. Validasi dengan konsultan regulasi/BI, terutama untuk klasifikasi open loop, model izin (lisensi sendiri atau bermitra dengan penerbit berlisensi), dan biaya transfer.

### 2.2 Transfer ke bank via BI-FAST

| Aspek | Temuan | Dampak ke desain |
|---|---|---|
| Skema harga | BI ke peserta Rp19 per transaksi; peserta ke nasabah **maks Rp2.500** | Fee Rp2.500 Anda tepat di batas maksimum. 10 transaksi gratis per bulan **ditanggung Anda** (Rp19 + biaya sponsor/partner): masukkan ke model margin |
| Nominal | Batas awal BI-FAST Rp250jt per transaksi (dievaluasi berkala) | Batas Rp10jt produk Anda jauh di bawahnya; tetap konfigurabel |
| Operasional | 24/7, real-time, setelmen **final dan tidak dapat dibatalkan** | Tidak ada pembatalan sepihak: inquiry nama rekening + konfirmasi + PIN wajib; tampilkan nama penerima sebelum PIN |
| Kepesertaan non-bank | Menurut PADG 3/2026 (berlaku 31 Maret 2026, ringkasan sekunder) PJP berbentuk lembaga selain bank ikut sebagai **Peserta Tidak Langsung lewat Bank Sponsor**, dengan syarat izin PJP dan modal disetor minimum | Jalur langsung ke BI-FAST bukan opsi awal |
| Persetujuan BI | Kerja sama/produk baru butuh persetujuan BI (lihat 2.1) | Masuk checklist Fase 0 |

**Jalur integrasi yang direkomendasikan**
1. **MVP**: bermitra dengan PJP/bank berlisensi yang menyediakan API transfer BI-FAST (inquiry, transfer, status, callback). Tercepat dan tanpa membangun konektor ISO 20022 sendiri.
2. **Jangka menengah**: setelah izin PJP sendiri, menjadi Peserta Tidak Langsung lewat Bank Sponsor pilihan. Karena memakai antarmuka `BankTransferAdapter`, penggantian jalur tidak mengubah alur aplikasi.

**Kontrak `BankTransferAdapter`**: `inquiry(bank_code, account_no) → nama pemilik`, `transfer(ref_id, bank_code, account_no, amount) → ACCEPTED | PENDING | FAILED`, `get_status(ref_id)`, dan verifikasi callback. Aturan: `FAILED` hanya bila kanal menyatakan gagal pasti; respons timeout/tidak jelas diperlakukan `PENDING` (saldo tetap ditahan) sampai `get_status` pasti; satu `ref_id` per transaksi.

---

## 3. Arsitektur Sistem

```
┌────────────┐    HTTPS/TLS    ┌──────────────────┐
│ React Native│ ──────────────▶ │  API Gateway /   │
│    App      │                 │  WAF / Rate Limit│
└────────────┘                 └────────┬─────────┘
┌────────────┐                          │
│ Next.js     │ ───────────────────────▶│
│ Admin Panel │                 ┌───────▼─────────┐
└────────────┘                 │  FastAPI Backend │
                                │ (modular monolith)│
                                └──┬─────┬──────┬──┘
                                   │     │      │
                          ┌────────▼┐ ┌──▼───┐ ┌▼────────────┐
                          │Postgres │ │Redis │ │ Job Workers │
                          └─────────┘ └──────┘ └──┬──────────┘
                                                  │
                                    ┌─────────────┴───────────┐
                                    │ Duitku      │ Digiflazz │
                                    └─────────────┴───────────┘
```

### Modul backend (modular monolith)

1. **auth** — registrasi, OTP, login, device binding, sesi/token, PIN.
2. **kyc** — verifikasi identitas, level akun.
3. **wallet/ledger** — akun, saldo, jurnal double-entry, hold/release.
4. **topup** — integrasi Duitku, callback, rekonsiliasi.
5. **transfer** — transfer antar pengguna dan transfer ke bank (adapter kanal bank).
6. **catalog** — Group → Layanan → Kategori → Item, SDUI schema.
7. **ppob** — lapisan **vendor adapter** (Digiflazz, Host to Host/Otomax), order, callback, cek status, refund otomatis.
8. **notification** — push, OTP via WA Gateway, email.
9. **risk** — rule engine fraud, velocity check, blacklist.
10. **admin** — RBAC, audit log, laporan, rekonsiliasi.

Mulai sebagai **modular monolith**; pecah menjadi service hanya bila ada kebutuhan skala nyata.

---

## 4. Katalog Dinamis & Server-Driven UI (SDUI)

### 4.1 Hierarki katalog

```
Group     → pembungkus di app (Isi Ulang, Tagihan, Finance, Voucher, Lainnya)
 └ Layanan  → Pulsa, Data, Game, PLN, PDAM, Bayar Angsuran, dst
              (punya tipe: prepaid / pascabayar)
    └ Kategori → mis. Data: Freedom Internet, Freedom Bulanan, All Internet
                 Pulsa: Indosat, Axis; Games: Mobile Legends, Free Fire
                 (sudah termasuk provider/prefix input operator;
                  jika kosong → input angka bebas)
       └ Item → mis. Pulsa 10rb, paket data harian
                (SKU internal, vendor, kode SKU vendor, harga, margin, status, dll)
                Satu produk "Pulsa 5rb" boleh punya beberapa item/SKU dengan
                vendor berbeda; tiap item terikat ke satu vendor.
```

### 4.2 Prinsip SDUI

- Server mengirim **deskripsi layar** (JSON) berisi komponen dari **daftar komponen terbatas (whitelist)** yang sudah ada di app: `input_phone`, `input_number`, `grid_items`, `list_items`, `banner`, `form_pln`, `confirm_summary`, dll.
- App hanya me-render komponen yang dikenal; komponen tidak dikenal diabaikan/fallback.
- **Versi skema** (`schema_version`) + `min_app_version` per layanan untuk kompatibilitas.
- **Tidak ada eksekusi kode dari server** (tanpa JS/WebView dinamis untuk alur transaksi).
- Alur yang menyentuh uang (konfirmasi, PIN, hasil) **tetap native & tetap** — SDUI hanya mengatur *form input & tampilan katalog*.
- Harga final **selalu dihitung ulang di server** saat order; app tidak dipercaya.

### 4.3 Contoh respons (ringkas)

```json
{
  "schema_version": 1,
  "screen": "service_form",
  "service": { "code": "PULSA", "type": "prepaid" },
  "components": [
    { "type": "input_phone", "key": "target", "detect_provider": true },
    { "type": "grid_items", "key": "sku", "source": "/catalog/items?category=auto" },
    { "type": "confirm_button", "label": "Lanjut" }
  ]
}
```

### 4.4 Alur penambahan layanan baru (tanpa rilis app)

1. Admin membuat Layanan/Kategori/Item di admin panel.
2. Memilih template form dari komponen whitelist.
3. Pilih vendor (Digiflazz atau Host to Host/Otomax) dan mapping kode SKU vendor per item.
4. Preview → publish (status `draft` → `active`).
5. App mengambil katalog terbaru (cache + ETag).

---

## 5. Desain Ledger & Transaksi (inti keamanan uang)

### 5.1 Prinsip

- **Double-entry ledger**, tabel jurnal **append-only** (tidak ada UPDATE/DELETE).
- Saldo = turunan dari jurnal (disimpan juga sebagai saldo ter-cache yang diverifikasi berkala).
- Setiap mutasi memiliki **`idempotency_key`** unik → request ulang tidak menggandakan transaksi.
- Perubahan saldo dilakukan dalam **satu transaksi DB** dengan `SELECT ... FOR UPDATE` (atau advisory lock) pada akun terkait; urutan lock konsisten untuk menghindari deadlock.
- Cek limit (saldo maks, per transaksi, harian) dilakukan **di dalam transaksi DB yang sama** agar tahan terhadap request paralel.
- Semua nominal memakai **integer (rupiah/sen)**, bukan float.

### 5.2 Skema inti (garis besar)

```
users(id, phone, status, kyc_level, created_at, ...)
devices(id, user_id, device_hash, trusted, last_seen, ...)
pins(user_id, pin_hash, failed_count, locked_until, ...)
accounts(id, user_id, type, balance_cached, currency, ...)
ledger_entries(id, txn_id, account_id, direction, amount, created_at)   -- append-only
transactions(id, type, status, amount, fee, idempotency_key UNIQUE,
             initiator_id, counterparty_id, meta, created_at, ...)
topups(id, txn_id, vendor_ref, status, paid_at, raw_callback, ...)
ppob_orders(id, txn_id, sku, target, vendor_ref, status, retry_count, ...)
catalog_groups / catalog_services / catalog_categories / catalog_items
kyc_submissions(id, user_id, level, status, reviewer_id, ...)
audit_logs(id, actor, action, entity, before, after, ip, created_at)
```

### 5.3 State machine transaksi

```
CREATED → PENDING → SUCCESS
                 ↘ FAILED → (refund) REVERSED
          PENDING → EXPIRED
```

- Saldo ditahan (**hold**) saat order PPOB/transfer dibuat; dicairkan saat sukses, dikembalikan saat gagal.
- Status final tidak boleh diubah lagi (kecuali lewat jurnal pembalik/reversal bertanda audit).

### 5.4 Alur utama

**Top-up (Duitku)**
1. User pilih nominal → server cek limit (saldo + nominal ≤ batas saldo akun, dan dana masuk bulan berjalan + nominal ≤ batas bulanan akun: Rp20jt non-premium / Rp40jt premium).
2. Server buat transaksi `PENDING` + request ke Duitku.
3. Callback Duitku → **verifikasi signature**, verifikasi nominal & referensi, cek idempotensi → kredit saldo.
4. Job rekonsiliasi berkala (cek status ke Duitku untuk transaksi `PENDING` yang lewat batas waktu).

**Transfer antar pengguna**
1. Validasi pengirim premium + PIN → validasi limit (≤ Rp10jt; >Rp5jt wajib verifikasi tambahan sesi) → hitung fee (sesama pengguna gratis; transfer antar bank/penerbit lain Rp2.500).
2. Validasi penerima (akun aktif & premium, saldo penerima + nominal ≤ Rp20jt, dana masuk bulan berjalan penerima + nominal ≤ Rp40jt).
3. Satu transaksi DB: debit pengirim, kredit penerima, tulis jurnal.
4. Notifikasi kedua pihak.

**Transfer ke bank**
1. Validasi pengirim premium → inquiry rekening tujuan (nama pemilik) lewat kanal transfer → tampilkan konfirmasi.
2. Validasi PIN (+ verifikasi tambahan bila > Rp5jt) → validasi limit (≤ Rp10jt) → hitung fee dari jumlah transfer ke bank pada bulan kalender berjalan (≤10 gratis, ke-11 dst Rp2.500).
3. Hold saldo (nominal + fee) → kirim ke kanal **BI-FAST** (lewat partner/bank sponsor) dengan `ref_id` unik (idempotent).
4. Status sukses / gagal / pending. Gagal pasti → release hold dan kuota gratis dikembalikan; pending/tidak jelas → polling/callback. Setelmen BI-FAST final dan tidak dapat dibatalkan, jadi jangan release hold sebelum kanal menyatakan gagal. Jangan retry dengan `ref_id` baru sebelum status pasti.
5. Kuota gratis bulanan dihitung atomik di transaksi DB yang sama dengan ledger.

**PPOB (multi-vendor: Digiflazz / Host to Host Otomax)**
1. Validasi PIN → hitung harga di server → hold saldo.
2. Vendor ditentukan oleh **item yang dipilih** (tanpa aturan prioritas/fallback otomatis). Kirim order lewat adapter vendor tersebut dengan `ref_id` unik (idempotent).
3. Status: sukses / gagal / **pending** → tunggu callback + polling cek status.
4. Gagal → release hold (refund otomatis). Sukses → finalisasi jurnal.
5. **Jangan pernah retry order dengan `ref_id` baru** tanpa memastikan status order sebelumnya.

---

## 6. Keamanan

### 6.1 Standar & acuan

| Area | Acuan |
|---|---|
| Aplikasi mobile | **OWASP MASVS** / MSTG |
| API | **OWASP API Security Top 10**, **OWASP ASVS** |
| Manajemen keamanan | **ISO/IEC 27001** (kontrol), 27002 |
| Data pribadi | **UU No. 27/2022 (PDP)** |
| Regulasi sistem pembayaran | **PBI 20/6/PBI/2018 tentang Uang Elektronik** (acuan utama, lihat 2.1) dan ketentuan turunannya; **OJK** bila relevan |
| Anti pencucian uang | **KYC/AML** sesuai ketentuan (PPATK) |
| Data kartu | **PCI DSS** — hanya jika kelak menyimpan/memproses data kartu (saat ini **tidak**; pakai redirect/hosted page vendor) |

### 6.2 Autentikasi & otorisasi

- Registrasi dengan **OTP via WA Gateway** (satu-satunya kanal): rate limit per nomor/perangkat/IP, masa berlaku pendek, OTP di-hash, batas percobaan, dan penanganan nomor tanpa WhatsApp / gateway down (pesan error jelas, tanpa fallback SMS).
- **Device binding**: akun terikat perangkat; perangkat baru butuh OTP + verifikasi tambahan.
- **PIN transaksi 6 digit**: di-hash **Argon2id** (+ pepper di secret manager); tidak pernah disimpan/dilog plaintext; kirim lewat TLS; wajib untuk **semua** transaksi.
- **Biometrik** hanya sebagai kemudahan membuka app/PIN lokal — tidak menggantikan validasi PIN di server untuk transaksi.
- **Access token** JWT berumur pendek (±10–15 menit) + **refresh token** rotasi, tersimpan di Keychain/Keystore, bisa dicabut (revocation list/session table).
- Verifikasi PIN menghasilkan **transaction authorization token** sekali pakai, terikat nominal/tujuan/perangkat, kedaluwarsa singkat (±60 detik).
- Admin panel: **RBAC** (least privilege), **2FA wajib** (TOTP), sesi pendek, **maker–checker** untuk aksi sensitif (ubah limit, adjustment saldo, refund manual, perubahan harga massal).

### 6.3 Keamanan aplikasi mobile (MASVS)

- Token & secret di **Keychain (iOS) / Keystore (Android)**; tidak di AsyncStorage.
- **Certificate/public-key pinning**.
- Deteksi **root/jailbreak**, emulator, debugger, hooking (Frida) — respons: batasi fitur transaksi.
- Obfuscation & proteksi build (Hermes bytecode, ProGuard/R8), tanpa secret di bundle.
- **Play Integrity / App Attest** untuk memastikan app asli.
- Cegah screenshot/screen-recording pada layar PIN & saldo; sembunyikan preview di app switcher.
- Tidak ada data sensitif di log, clipboard, atau analytics.
- Auto-logout saat idle; kunci ulang setelah background.

### 6.4 Keamanan API & backend

- **TLS 1.2+** (disarankan 1.3), HSTS; WAF & proteksi DDoS.
- **Rate limiting & throttling** per IP/akun/perangkat/endpoint (lebih ketat di OTP, login, PIN, transfer).
- Validasi input ketat (Pydantic), parameterized query/ORM → cegah SQL injection; cegah **BOLA/IDOR** (cek kepemilikan resource di setiap endpoint).
- **Idempotency-Key** wajib untuk endpoint mutasi uang.
- **Anti-replay**: nonce + timestamp pada request sensitif.
- **Callback vendor** (Duitku/Digiflazz): verifikasi signature, **IP allowlist**, validasi nominal & referensi, proses idempotent, simpan raw payload untuk audit.
- CORS ketat; header keamanan; versi API (`/v1`).
- Secret di **secret manager** (bukan di repo/ENV file); rotasi berkala; pemisahan kredensial per lingkungan.
- Dependensi dipindai (SCA: pip-audit, npm audit, Dependabot); SAST/DAST di CI.

### 6.5 Perlindungan data

- Enkripsi **at rest** (disk/DB) dan **in transit**.
- Enkripsi tingkat kolom (field-level) untuk data sensitif: **NIK, foto e-KTP/selfie** (bucket privat terenkripsi, akses via signed URL berumur pendek), nomor rekening.
- Minimisasi data; retensi & penghapusan sesuai UU PDP; masking data di admin panel (tampilkan penuh hanya dengan izin khusus + tercatat).
- Backup terenkripsi + uji restore berkala; RPO/RTO ditetapkan.
- Pemisahan lingkungan (dev/staging/prod); data produksi tidak dipakai di dev.

### 6.6 Anti-fraud & monitoring

- **Velocity checks** (jumlah/nilai transaksi per menit/jam/hari), deteksi pola (mule account, transfer bolak-balik, banyak akun satu perangkat).
- Rule engine + skor risiko; transaksi berisiko → tahan & review manual / minta KYC tambahan.
- Blacklist perangkat/nomor/NIK; notifikasi real-time ke pengguna untuk setiap transaksi.
- **Audit log** tak dapat diubah untuk semua aksi admin & perubahan sensitif.
- Logging terpusat + alert (login anomali, lonjakan gagal PIN, selisih rekonsiliasi, saldo negatif/tidak balance).
- **Rekonsiliasi harian**: ledger ↔ Duitku ↔ Digiflazz ↔ saldo bank/escrow.

### 6.7 KYC

| Level | Syarat | Catatan limit |
|---|---|---|
| Non-premium (*unregistered*) | OTP HP (WA) | saldo maks Rp2jt, dana masuk maks Rp20jt/bulan, tanpa fitur transfer |
| Premium (*registered*) | **e-KTP + selfie, keduanya diambil langsung lewat kamera in-app (bukan upload)** | saldo maks Rp20jt, dana masuk maks Rp40jt/bulan, transfer terbuka (maks Rp10jt/transaksi) |

**Pengambilan data live (bukan upload)**
- Kamera in-app saja; galeri/file picker dinonaktifkan.
- Deteksi kualitas gambar (blur, pantulan, terpotong), liveness selfie, dan anti-spoofing (foto layar/foto cetak).
- Lawan injeksi gambar: deteksi virtual camera/hooking, app attestation (Play Integrity / App Attest), metadata sesi, dan timestamp server.
- Gambar dikirim terenkripsi langsung ke bucket privat (signed URL berumur pendek); tidak disimpan di galeri perangkat.

**Mode verifikasi dinamis (pengaturan admin)**
- **Manual**: reviewer admin (maker–checker pada keputusan, masking data sensitif, semua keputusan tercatat). Ini mode awal.
- **Layanan eKYC**: OCR e-KTP, face match, liveness, dukcapil via penyedia (belum dipilih).
- Mode aktif ditampilkan sebagai indikator di halaman pengaturan admin; perpindahan mode tercatat di audit log. Desain: antarmuka `KycVerifier` dengan implementasi `ManualVerifier` dan `ProviderVerifier` sehingga penyedia bisa ditambah tanpa mengubah alur.

---

## 7. Threat Model Ringkas (STRIDE)

| Ancaman | Contoh | Mitigasi utama |
|---|---|---|
| Spoofing | Pengambilalihan akun, SIM swap | Device binding, PIN, OTP + risk check, notifikasi |
| Tampering | Ubah harga/nominal di request | Hitung ulang di server, authorization token terikat nominal |
| Repudiation | Pengguna menyangkal transaksi | Audit log, bukti PIN-authorized, jurnal append-only |
| Info disclosure | Kebocoran NIK/KTP, token | Enkripsi, masking, signed URL, secret manager |
| Denial of service | Banjir OTP/login | Rate limit, WAF, captcha adaptif |
| Elevation of privilege | IDOR, akses admin tak sah | Cek kepemilikan, RBAC, 2FA, maker–checker |
| Race condition | Double-spend, lewat limit 40jt | Row lock + cek dalam transaksi DB, idempotency |
| Callback palsu | Kredit saldo tanpa bayar | Signature + IP allowlist + verifikasi status ke vendor |

---

## 8. Admin Panel (Next.js)

- Dashboard: volume, saldo beredar (**dana float terhadap ambang Rp1 miliar**), transaksi pending/gagal, selisih rekonsiliasi.
- Manajemen **pengguna & KYC** (review, blokir, buka kunci).
- Manajemen **katalog** (Group/Layanan/Kategori/Item, SKU mapping, harga, margin, status, jadwal).
- **Transaksi** (cari, detail, retry/refund terkontrol dengan maker–checker).
- **Limit & konfigurasi** (versi & audit), termasuk **mode verifikasi KYC** (manual / layanan eKYC) dengan indikator mode aktif di halaman pengaturan.
- **Laporan** & ekspor; **audit log viewer**.
- Keamanan: 2FA, RBAC granular, IP allowlist opsional, sesi pendek, CSP ketat.

---

## 9. Infrastruktur & DevOps

- Container (Docker) + orkestrasi (mulai sederhana; Kubernetes bila perlu).
- CI/CD dengan: lint, test, SAST, SCA, secret scanning, build reproducible.
- Lingkungan: dev → staging → production, akses prod terbatas & tercatat.
- Observability: log terstruktur, metrik, tracing, alert on-call.
- HA: DB replica + backup, health check, auto-restart, zero-downtime deploy.
- Database migration terversi (Alembic).

---

## 10. Pengujian

- Unit & integration test (pytest) — fokus ledger, limit, idempotensi, race condition.
- **Concurrency/load test** untuk skenario double-spend & batas saldo.
- Test callback vendor (sandbox Duitku/Digiflazz), termasuk callback duplikat/terlambat/palsu.
- E2E mobile (Detox/Maestro).
- **Penetration test independen** + review kode keamanan sebelum rilis.
- Program bug bounty/responsible disclosure setelah rilis.

---

## 11. Fase Pengerjaan

| Fase | Cakupan | Output |
|---|---|---|
| **0. Persiapan** | Validasi regulasi BI/izin, pilih vendor KYC, kontrak Duitku & Digiflazz, threat model final, desain skema DB | Dokumen final, akses sandbox |
| **1. Fondasi** | Auth (OTP, device, PIN), akun, **ledger**, limit engine, audit log, infrastruktur dasar | Backend inti teruji |
| **2. Top-up & KYC** | Integrasi Duitku, callback, rekonsiliasi; KYC premium (live capture, mode manual/layanan) | Isi saldo berjalan |
| **3. Transfer** | Transfer antar pengguna dan transfer ke bank (khusus premium), kuota fee bulanan, limit dana masuk, notifikasi | Transfer aman |
| **4. Katalog & PPOB** | Skema katalog, SDUI, adapter vendor (Digiflazz + H2H Otomax), refund otomatis | Layanan PPOB berjalan |
| **5. Admin Panel** | Katalog, KYC review, transaksi, laporan, RBAC+2FA | Operasional siap |
| **6. Hardening** | Anti-fraud, pentest, load test, DR drill, audit kepatuhan | Siap rilis |
| **7. Rilis bertahap** | Beta terbatas → rilis publik, monitoring ketat | Go-live |

---

## 12. Risiko Utama

1. **Regulasi/izin** uang elektronik: aturan baru PBI 10/2025 dan PADG 32/2025 (berlaku 31 Maret 2026) belum diverifikasi terhadap limit, klasifikasi open loop, syarat PTL BI-FAST, dan ambang float Rp1 miliar (blocker potensial; perkiraan kasar 10.000 pengguna dengan saldo rata-rata Rp100rb sudah menyentuh ambang).
2. **Integritas saldo** (race condition, callback ganda/palsu) → ledger + idempotensi + rekonsiliasi.
3. **Fraud & penyalahgunaan akun** → KYC, risk engine, device binding.
4. **Ketergantungan vendor** (Duitku/Digiflazz down) → status pending yang aman, retry terkontrol, multi-vendor PPOB ke depan.
5. **Kebocoran data pribadi** (NIK, KTP) → enkripsi, akses minimum, kepatuhan UU PDP.

---

## 13. Pertanyaan Terbuka

**Sudah diputuskan (v0.4):** aturan limit mengikuti BI (saldo non-premium Rp2jt, premium Rp20jt; dana masuk per bulan kalender Rp20jt non-premium dan Rp40jt premium; tanpa batas harian); transfer hanya premium; fee transfer (sesama gratis; transfer ke bank 10 pertama per bulan kalender gratis, ke-11 dst Rp2.500); verifikasi tambahan di atas Rp5jt dipertahankan; tidak ada layanan tarik dana ke bank (tetapi ada layanan transfer ke bank, kanal **BI-FAST**); KYC live capture dengan mode manual/layanan; multi-vendor per item; OTP hanya WA Gateway; top-up single Duitku.

**Rekomendasi default (diisi Claude; berlaku sampai Anda ubah):**

| # | Topik | Rekomendasi | Alasan |
|---|---|---|---|
| 1 | Klasifikasi UE | Rencanakan sebagai UE ***open loop, server based***, dengan tingkat *registered* (premium) dan *unregistered* | Ada transfer ke bank; fitur transfer dana hanya untuk open loop + registered. Konfirmasi ke BI |
| 2 | Model izin | **MVP bermitra** dengan PJP/bank berlisensi (dana dan BI-FAST lewat mitra); paralel siapkan izin PJP sendiri, dimulai paling lambat saat float ±50% dari Rp1 miliar | Perizinan lama; MVP tidak boleh menunggu. Float 10.000 pengguna x Rp100rb sudah Rp1 miliar |
| 3 | Plafon transfer keluar bulanan | Sesuai keputusan Anda: **tanpa plafon**. Sediakan limit keluar bulanan **konfigurabel (default nonaktif)** plus alert velocity (mis. keluar > Rp40jt/bulan, atau > 5 penerima baru dalam 1 jam) | Menjaga keputusan produk, tetap ada rem darurat saat fraud |
| 4 | Host to Host Otomax | Bangun `VendorAdapter` generik (submit, status, callback, signature). Detail format menunggu dokumentasi dari akun Otomax Anda. **Minta ke vendor:** URL dan autentikasi, format request, daftar kode respons (sukses/gagal/pending), mekanisme callback dan verifikasinya, endpoint cek status, timeout, IP whitelist | Saya tidak mengarang spesifikasi vendor |
| 5 | WA Gateway | Pakai **WhatsApp Business Platform (Cloud API) resmi lewat BSP** dengan template OTP; hindari gateway tidak resmi. Bila WA gagal (tanpa SMS sesuai keputusan): pesan error jelas, kirim ulang dengan cooldown 60 detik dan maks 5 per jam, alert ops, siapkan penyedia WA cadangan | Gateway tidak resmi berisiko nomor diblokir dan tidak andal untuk OTP dompet |
| 6 | eKYC | Mulai **manual**. Evaluasi penyedia eKYC bila antrean > ±100-200 pengajuan/hari atau SLA review > 24 jam. Kriteria: koneksi dukcapil, liveness teruji, data di Indonesia, SLA, harga per verifikasi | Menunda keputusan vendor sampai ada data volume |
| 7 | Hosting | **Region Indonesia** (cloud region Jakarta atau DC lokal) untuk DB, backup, dan log | Pemrosesan transaksi UE wajib di wilayah Indonesia; UU PDP |
| 8 | Platform | iOS dan Android sekaligus dari satu codebase React Native; beta Android dulu, TestFlight iOS paralel | Efisien, risiko rilis kecil |
| 9 | Kapasitas **[ASUMSI]** | Tahun 1: ±10.000 pengguna aktif, ±3.000-5.000 transaksi/hari, puncak ±5 TPS; rancang mampu 10x tanpa ubah arsitektur | Modular monolith + PostgreSQL cukup; angka nyata mengoreksi |
| 10 | Transfer > Rp5jt | Verifikasi tambahan **dipertahankan** (biometrik atau liveness ulang) | Sudah diputuskan |

**Masih butuh input Anda:**
- [ ] Dokumentasi Host to Host Otomax (poin 4) dan pilihan penyedia WA Business (poin 5).
- [ ] Pilihan mitra BI-FAST / bank sponsor / penerbit berlisensi (poin 2).
- [ ] Hasil konfirmasi ke BI/konsultan tentang limit terbaru dan status PBI 20/6/PBI/2018 setelah 31 Maret 2026.
- [ ] Target pengguna dan transaksi sebenarnya (poin 9).
- [ ] Apakah batas transfer Rp10jt per transaksi tetap, mengingat saldo premium kini bisa Rp20jt?

---

*Dokumen ini adalah titik awal perencanaan dan bukan nasihat hukum/regulasi. Validasi kepatuhan dengan konsultan hukum dan regulator sebelum implementasi.*
