# DECISIONS — Log Keputusan Produk, Auth, dan Fase

Status: **hidup** · 18 Oktober 2026

Dokumen ini adalah **satu-satunya tempat** untuk keputusan yang memengaruhi
kontrak API, flow app, dan scope fase. Dokumen lain merujuk ke ID di sini.

Status:

- **CONFIRMED** — sudah diputuskan, boleh diimplementasikan.
- **OPEN** — belum diputuskan, jangan diasumsikan.
- **DEFERRED** — diputuskan untuk ditunda ke fase tertentu.

---

## 1. Keputusan yang sudah dikonfirmasi

| ID | Keputusan | Dampak | Dokumen |
| --- | --- | --- | --- |
| D-01 | Produk dipivot dari dompet digital menjadi **penjualan pulsa & PPOB**. | Branding, scope, regulasi, prioritas fitur | `FASE-2.1-PIVOT.md` |
| D-02 | **Biometric wajah dihapus**; sidik jari tetap. | API face, app screen, error `FACE_*`, liveness biometrik | `FASE-2.1-PIVOT.md` |
| D-03 | **Scan dan transfer** menjadi pajangan/coming soon. | UI Home/tab, endpoint transfer ditunda | `FASE-2.1-PIVOT.md` |
| D-04 | **Pemulihan akun (Lost Phone) dihapus dari app**. | Hapus screen/flow recovery di app | `FASE-2.1-PIVOT.md` |
| D-05 | Register menambahkan **email**; OTP register tetap ke **WhatsApp**. | Field register, validasi email, schema user | `FASE-2.1-PIVOT.md` |
| D-06 | Login dan lupa PIN memakai **nomor HP atau email**. Nomor → OTP WA; email terverifikasi → OTP email. | Kontrak `login/start`, `otp/request`, `pin/reset` | `FASE-2.1-PIVOT.md` |
| D-07 | Verifikasi email **opsional**. Jika terverifikasi, email bisa untuk login, lupa PIN, dan ganti nomor HP. | Banner Home, endpoint verifikasi email | `FASE-2.1-PIVOT.md` |
| D-08 | Nomor HP dan email **bisa diganti** dari halaman akun. | Endpoint change phone/email, notifikasi | `FASE-2.1-PIVOT.md` |
| D-09 | Fase 3A sebelumnya dipilih: wallet + top-up + KYC + read bootstrap; Duitku VA/QRIS; KYC manual. | Scope Fase 3 | Dihapus sementara; disusun ulang setelah D-10 |

> D-09 perlu **dikonfirmasi ulang** setelah D-01 (pivot PPOB). Lihat D-10.

---

## 2. Keputusan terbuka — memblokir Fase 2.1

| ID | Pertanyaan | Rekomendasi | Kenapa penting |
| --- | --- | --- | --- |
| D-10 | Apakah **wallet/top-up/KYC** tetap dipakai setelah pivot PPOB? | Tentukan sebelum Fase 3. Jika PPOB hanya bayar per transaksi, wallet/KYC bisa dihapus. | Mengubah seluruh scope Fase 3 dan sebagian schema |
| D-11 | Apakah **email wajib** saat register? | Wajib untuk user baru; nullable untuk data lama. | Menentukan validasi register dan migrasi |
| D-12 | Provider email OTP: **Resend, SendGrid, atau SMTP**? | Pilih satu + adapter. | Diperlukan sebelum kode OTP email bisa dikirim |
| D-13 | Apakah **KYC/Premium** masih diperlukan? | Jika PPOB tanpa limit saldo, kemungkinan tidak perlu. | Menentukan apakah `kyc_submissions` dan `/me/kyc` dibuat |
| D-14 | Jika KYC tetap ada, apakah face liveness juga dihapus? | Hapus face; KYC manual cukup KTP + review. | Menentukan endpoint `/me/kyc/{id}/face` dan error `FACE_*` |
| D-15 | Ganti nomor HP butuh apa? | PIN + OTP nomor baru + notifikasi email terverifikasi. | Menentukan endpoint change phone |
| D-16 | Ganti email butuh apa? | PIN + OTP email baru; email lama dinotifikasi. | Menentukan endpoint change email |
| D-17 | Endpoint recovery backend: **hapus total atau deprecated**? | Deprecated dulu; hapus setelah app lama tidak dipakai. | Mengurangi attack surface vs kompatibilitas |
| D-18 | Scan/transfer: **disembunyikan total atau coming soon**? | Coming soon (disabled) agar UI tetap familiar. | Menentukan UI dan route |
| D-19 | Verifikasi email memakai **OTP atau magic link**? | OTP, konsisten dengan app. | Menentukan endpoint dan template email |

---

## 3. Keputusan terbuka — memblokir Fase 3

| ID | Pertanyaan | Rekomendasi | Kenapa penting |
| --- | --- | --- | --- |
| D-20 | Jika wallet dipertahankan, apakah modelnya **saldo prabayar** atau **pembayaran langsung per transaksi**? | Putuskan bersama D-10. | Menentukan ledger, top-up, dan limit |
| D-21 | Format bank code: **huruf (`BCA`)** atau **numerik (`014`)**? | Numerik untuk kanal, label huruf untuk UI. | Perlu untuk transfer (Fase 3C) |
| D-22 | Transfer > Rp5 juta wajib step-up **biometrik, OTP, atau salah satu**? | OTP atau fingerprint yang tersedia. | Perlu untuk Fase 3C |
| D-23 | Detail channel dan signature callback **Duitku**? | Verifikasi di sandbox; jangan hardcode sebelum cocok. | Top-up tidak bisa production tanpa ini |
| D-24 | Apakah manual reviewer KYC membutuhkan **selfie**? | App saat ini hanya mengirim `liveness_session_id`; tambah field bila perlu. | Menentukan form KYC dan object storage |
| D-25 | Maker-checker KYC: **satu reviewer atau dua admin**? | Satu reviewer dulu + audit; maker-checker menyusul. | Menentukan alur admin |
| D-26 | Retensi file KTP/selfie dan log callback? | Ikuti UU PDP; tetapkan durasi. | Kepatuhan dan biaya storage |
| D-27 | Domain deep link final: **`bayarin://` atau `poinqu://`**? | Samakan dengan `navigation/linking.ts`. | Notifikasi dan share link |
| D-28 | `topup.max_pending` dan TTL top-up? | Maks 3 aktif; TTL mengikuti channel. | Mencegah spam kode bayar |

---

## 4. Aturan perubahan keputusan

1. Setiap keputusan baru harus punya ID `D-xx` di dokumen ini.
2. Dokumen API/flow tidak boleh punya daftar keputusan sendiri; cukup merujuk ID.
3. Jika keputusan berubah, catat tanggal + alasan di kolom catatan (tambahkan
   bagian riwayat di bawah).
4. Implementasi tidak boleh dimulai untuk item berstatus **OPEN** yang
   memblokirnya.

---

## 5. Riwayat

| Tanggal | ID | Perubahan | Alasan |
| --- | --- | --- | --- |
| 2026-10-18 | D-01..D-09 | Keputusan awal pivot dan scope 3A | Hasil diskusi |
| 2026-10-18 | D-09 | Ditandai perlu konfirmasi ulang | Pivot PPOB dapat mengubah wallet/KYC |
