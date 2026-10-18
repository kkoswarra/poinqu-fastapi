# DECISIONS — Log Keputusan Produk, Auth, dan Fase

Status: **hidup** · 18 Oktober 2026

Dokumen ini adalah **satu-satunya tempat** untuk keputusan yang memengaruhi
kontrak API, flow app, dan scope fase. Dokumen lain merujuk ke ID di sini.

Status:

- **CONFIRMED** — sudah diputuskan, boleh diimplementasikan.
- **OPEN** — belum diputuskan, jangan diasumsikan.
- **DEFERRED** — diputuskan untuk ditunda ke fase tertentu.
- **EXTERNAL** — menunggu pihak ketiga/sandbox.

---

## 1. Keputusan yang sudah dikonfirmasi

| ID | Keputusan | Dampak |
| --- | --- | --- |
| D-01 | Produk dipivot dari dompet digital menjadi **penjualan pulsa & PPOB**. | Branding, scope, prioritas fitur |
| D-02 | **Biometric wajah dihapus**; sidik jari tetap. | API face, app screen, error `FACE_*` |
| D-03 | **Scan dan transfer** menjadi pajangan/coming soon. | UI Home/tab, endpoint transfer ditunda |
| D-04 | **Pemulihan akun (Lost Phone) dihapus dari app**. | Hapus screen/flow recovery di app |
| D-05 | Register menambahkan **email wajib**; OTP register tetap ke **WhatsApp**. | Field register, validasi email, schema user |
| D-06 | Login dan lupa PIN memakai **nomor HP atau email**. Nomor → OTP WA; email terverifikasi → OTP email. | Kontrak `login/start`, `otp/request`, `pin/reset` |
| D-07 | Verifikasi email **opsional**. Jika terverifikasi, email bisa untuk login, lupa PIN, dan ganti nomor HP. | Banner Home, endpoint verifikasi email |
| D-08 | Nomor HP dan email **bisa diganti** dari halaman akun. | Endpoint change phone/email, notifikasi |
| D-09 | Fase 3 fokus **wallet + top-up + PPOB**; **KYC dihapus**. | Scope Fase 3, hapus `/me/kyc` dan admin KYC |
| D-10 | **Wallet dipertahankan dengan top-up**. Model saldo: **saldo prabayar** untuk pembelian PPOB. | Ledger, top-up, saldo, transaksi |
| D-11 | Verifikasi email memakai **OTP** (bukan magic link). | Endpoint/template email OTP |
| D-12 | Domain final: **poinqu**. Deep link `poinqu://`, web `https://poinqu.id`. | Linking, share URL, notifikasi |
| D-13 | **KYC dihapus** dari produk dan backend. Tidak ada Premium/KYC. | Hapus `kyc_submissions`, `/me/kyc`, admin KYC |
| D-14 | Batas nominal top-up **diatur admin di database**; default **tanpa batas maksimum**. | Tabel/konfigurasi top-up, endpoint methods |
| D-15 | Scan/transfer **coming soon** (bukan dihapus dari UI). | UI disabled/coming soon |
| D-16 | Wallet memakai **satu level** (BASIC) tanpa PREMIUM/KYC. | Hapus `level=PREMIUM` dari alur aktif |
| D-17 | Fase 3A memakai **Duitku VA/QRIS + instruksi pembayaran**. | Adapter/payment channel |
| D-18 | **Email wajib saat register** untuk user baru; data lama boleh `NULL`. | Validasi register + migrasi |
| D-19 | Provider email OTP memakai **SMTP**. | Adapter email, env SMTP, template |
| D-20 | Ganti nomor HP: PIN + **OTP ke nomor baru via WhatsApp** + notifikasi ke email terverifikasi/nomor lama. | Endpoint change phone |
| D-21 | Ganti email: PIN + **OTP ke email baru via SMTP** + notifikasi ke email lama/nomor HP. | Endpoint change email |
| D-22 | Endpoint recovery backend **dihapus total**. | Hapus router/tabel recovery, admin recovery |
| D-25 | Maksimum **3 top-up aktif** per user; TTL mengikuti channel. Default: QRIS 30 menit, VA 3 jam. | Reservasi, expiry job |
| D-28 | Batas saldo wallet **Rp5.000.000**, admin-configurable di database. | Limit ledger/top-up |
| D-29 | **Semua pembelian PPOB dibayar dari saldo wallet.** | Checkout, hold/debit saldo |
| D-30 | Fase 3B (katalog/inquiry/transaksi PPOB) **ditunda** sampai Fase 2.1 dan 3A stabil. | Urutan kerja |

> D-13 dan D-16 berarti `kyc_status`, `level=PREMIUM`, endpoint KYC, dan
> error `KYC_*` tidak dipakai lagi. Kolom lama boleh dipertahankan untuk data
> historis, tetapi tidak diekspos/dipakai di API baru.
>
> D-20/D-21: OTP dikirim ke **kontak baru** (nomor/email baru). Notifikasi
> dikirim ke kontak lama/email terverifikasi. Jika yang dimaksud adalah OTP
> boleh dikirim ke salah satu kanal lama, perubahan cukup di level implementasi
> adapter—tidak mengubah bentuk respons.

---

## 2. Keputusan terbuka

| ID | Pertanyaan | Rekomendasi | Kenapa penting |
| --- | --- | --- | --- |
| D-24 | Detail channel dan signature callback **Duitku** | Verifikasi di sandbox sebelum produksi | Top-up tidak bisa production tanpa ini |
| D-31 | Alamat/from name email SMTP dan batas kirim harian | `no-reply@poinqu.id`; pantau bounce | Deliverability OTP |
| D-32 | Batas nominal minimum top-up | Admin DB; default Rp10.000 **[usulan]** | Validasi top-up |

---

## 3. Keputusan yang ditunda

| ID | Keputusan | Status | Alasan |
| --- | --- | --- | --- |
| D-26 | Format bank code transfer | **DEFERRED** | Transfer coming soon (D-03) |
| D-27 | Step-up transfer > Rp5 juta | **DEFERRED** | Transfer coming soon (D-03) |

---

## 4. Aturan perubahan keputusan

1. Setiap keputusan baru harus punya ID `D-xx` di dokumen ini.
2. Dokumen API/flow tidak boleh punya daftar keputusan sendiri; cukup merujuk ID.
3. Jika keputusan berubah, catat tanggal + alasan di bagian riwayat.
4. Implementasi tidak boleh dimulai untuk item berstatus **OPEN**/**EXTERNAL**
   yang memblokirnya.

---

## 5. Riwayat

| Tanggal | ID | Perubahan | Alasan |
| --- | --- | --- | --- |
| 2026-10-18 | D-01..D-17 | Pivot PPOB, auth email/phone, wallet + top-up, KYC dihapus | Diskusi produk |
| 2026-10-18 | D-18..D-22 | Email wajib, SMTP, change phone/email, recovery dihapus | Keputusan lanjutan |
| 2026-10-18 | D-25..D-30 | Batas top-up aktif/TTL, saldo 5jt, PPOB dari wallet, 3B ditunda | Keputusan lanjutan |
