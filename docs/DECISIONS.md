# DECISIONS — Log Keputusan Produk, Auth, dan Fase

Status: **hidup** · 18 Oktober 2026

Dokumen ini adalah **satu-satunya tempat** untuk keputusan yang memengaruhi
kontrak API, flow app, dan scope fase. Dokumen lain merujuk ke ID di sini.

Status:

- **CONFIRMED** — sudah diputuskan, boleh diimplementasikan.
- **OPEN** — belum diputuskan, jangan diasumsikan.
- **DEFERRED** — diputuskan untuk ditunda ke fase tertentu.
- **N/A** — tidak berlaku karena keputusan lain.

---

## 1. Keputusan yang sudah dikonfirmasi

| ID | Keputusan | Dampak |
| --- | --- | --- |
| D-01 | Produk dipivot dari dompet digital menjadi **penjualan pulsa & PPOB**. | Branding, scope, prioritas fitur |
| D-02 | **Biometric wajah dihapus**; sidik jari tetap. | API face, app screen, error `FACE_*` |
| D-03 | **Scan dan transfer** menjadi pajangan/coming soon. | UI Home/tab, endpoint transfer ditunda |
| D-04 | **Pemulihan akun (Lost Phone) dihapus dari app**. | Hapus screen/flow recovery di app |
| D-05 | Register menambahkan **email**; OTP register tetap ke **WhatsApp**. | Field register, validasi email, schema user |
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
| D-17 | Fase 3A tetap memakai **Duitku VA/QRIS + instruksi pembayaran**. | Adapter/payment channel |

> D-13 dan D-16 berarti `kyc_status`, `level=PREMIUM`, endpoint KYC, dan
> error `KYC_*` tidak dipakai lagi. Untuk kompatibilitas data lama, kolomnya
> boleh tetap ada di database tetapi tidak diekspos/dipakai di API baru.

---

## 2. Keputusan terbuka — memblokir Fase 2.1

| ID | Pertanyaan | Rekomendasi | Kenapa penting |
| --- | --- | --- | --- |
| D-18 | Apakah **email wajib** saat register? | Wajib untuk user baru; nullable untuk data lama. | Validasi register + migrasi |
| D-19 | Provider email OTP: **Resend, SendGrid, atau SMTP**? | Pilih satu + adapter. | OTP email belum bisa dikirim tanpa ini |
| D-20 | Ganti nomor HP butuh apa? | PIN + OTP nomor baru + notifikasi email terverifikasi. | Endpoint change phone |
| D-21 | Ganti email butuh apa? | PIN + OTP email baru; email lama dinotifikasi. | Endpoint change email |
| D-22 | Endpoint recovery backend: **hapus total atau deprecated**? | Deprecated dulu; hapus setelah app lama tidak dipakai. | Attack surface vs kompatibilitas |

---

## 3. Keputusan terbuka — memblokir Fase 3

| ID | Pertanyaan | Rekomendasi | Kenapa penting |
| --- | --- | --- | --- |
| D-24 | Detail channel dan signature callback **Duitku**? | Verifikasi di sandbox. | Top-up production |
| D-25 | Batas jumlah top-up aktif (`max_pending`) dan TTL? | Maks 3 aktif; TTL mengikuti channel. | Mencegah spam kode bayar |
| D-26 | Format bank code: **huruf (`BCA`)** atau **numerik (`014`)**? | Numerik untuk kanal. | Transfer (ditunda) |
| D-27 | Transfer > Rp5 juta wajib step-up **biometrik/OTP**? | OTP atau fingerprint. | Transfer (ditunda) |
| D-28 | Berapa batas saldo wallet setelah KYC dihapus? | Admin-configurable; default mengikuti kebutuhan PPOB. | Ledger/limit |
| D-29 | Apakah PPOB dibayar dari saldo wallet atau payment gateway per transaksi? | Saldo wallet (D-10). | Flow checkout |
| D-30 | Kapan Fase 3B (katalog/inquiry/transaksi PPOB) dimulai? | Setelah 3A wallet/top-up stabil. | Urutan fase |

---

## 4. Aturan perubahan keputusan

1. Setiap keputusan baru harus punya ID `D-xx` di dokumen ini.
2. Dokumen API/flow tidak boleh punya daftar keputusan sendiri; cukup merujuk ID.
3. Jika keputusan berubah, catat tanggal + alasan di bagian riwayat.
4. Implementasi tidak boleh dimulai untuk item berstatus **OPEN** yang
   memblokirnya.

---

## 5. Riwayat

| Tanggal | ID | Perubahan | Alasan |
| --- | --- | --- | --- |
| 2026-10-18 | D-01..D-08 | Pivot PPOB + auth email/phone | Diskusi produk |
| 2026-10-18 | D-09..D-17 | Wallet + top-up dipertahankan; KYC dihapus; domain poinqu; email OTP; top-up max admin DB | Keputusan lanjutan |
