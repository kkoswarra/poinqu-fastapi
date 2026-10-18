# Dokumentasi Poinqu API

Indeks dokumen. Mulai dari sini sebelum membaca kontrak atau menulis kode.

---

## 1. Status proyek

- **Fase 2** — fondasi auth, PIN, perangkat, profil, biometric, admin, webhook
  Fonnte. Sudah berjalan.
- **Fase 2.1** — pivot produk ke **pulsa & PPOB** dan rework auth
  (email/nomor HP, hapus face, hapus recovery di app). **Sedang diputuskan.**
- **Fase 3** — belum disusun. Draft Fase 3A lama (wallet/top-up/KYC) sudah
  dihapus karena scope-nya bergantung pada **D-10**. Dokumen baru akan dibuat
  setelah keputusan itu.

Jangan implementasi Fase 3 sebelum keputusan yang memblokir di
`DECISIONS.md` selesai.

---

## 2. Urutan baca

### Untuk owner/produk

1. `PLAN.md` — visi, aturan bisnis, fase (perhatikan banner pivot).
2. `DECISIONS.md` — keputusan yang sudah dan belum final.
3. `FASE-2.1-PIVOT.md` — perubahan produk/auth terbaru.

### Untuk backend

1. `FASE-2-API.md` — kontrak fondasi yang sudah berjalan.
2. `FASE-2.1-PIVOT.md` — perubahan yang harus diimplementasikan.
3. `APP-FLOW-MAP.md` — endpoint yang benar-benar dipanggil app.

### Untuk mobile

1. `APP-FLOW-MAP.md` — layar → hook → endpoint.
2. `FASE-2.1-PIVOT.md` — perubahan auth/akun.

### Untuk QA

1. `FASE-2-API.md` + `FASE-2.1-PIVOT.md` — kontrak yang diuji.

---

## 3. Peta dokumen

| Dokumen | Status | Isi |
| --- | --- | --- |
| `PLAN.md` | hidup, **ada banner pivot** | Visi produk, aturan bisnis, rencana fase |
| `DECISIONS.md` | hidup | Satu-satunya log keputusan (D-01, D-02, …) |
| `FASE-2-API.md` | **baseline** | Kontrak Fase 2 yang sudah berjalan |
| `FASE-2.1-PIVOT.md` | **change spec** | Pivot PPOB + rework auth email/phone, tanpa face/recovery |
| `APP-FLOW-MAP.md` | referensi | Peta flow app dan cakupan backend |

---

## 4. Sumber kebenaran

Urutan prioritas saat ada pertentangan:

1. **`DECISIONS.md`** — keputusan produk/scope.
2. **Kontrak fase yang berlaku**:
   - Fase 2 → `FASE-2-API.md`
   - perubahan Fase 2 → `FASE-2.1-PIVOT.md`
   - Fase 3 → belum ada; akan dibuat setelah D-10
3. **`app-frontend/src/api/types/*` + `src/api/endpoints/*`** — bentuk data yang
   benar-benar dipakai app. Jika app dan dokumen berbeda, catat sebagai
   keputusan/perubahan kontrak; jangan diam-diam mengikuti salah satu.
4. **Implementasi backend** — kondisi nyata. Jika berbeda dari dokumen,
   perbaiki salah satunya dan catat.
5. **`app-frontend/openapi.json`** — **bukan** sumber kebenaran. File itu
   kontrak lama dan memuat endpoint yang belum ada di backend.

Aturan: jika `FASE-2.1-PIVOT.md` bertentangan dengan `FASE-2-API.md`,
**FASE-2.1 menang** untuk area yang tercakup (auth/identitas/biometrik).

---

## 5. Alur dokumen saat ada perubahan

1. Tambah/ubah keputusan di `DECISIONS.md` (beri ID).
2. Update kontrak fase (`FASE-2-API.md` atau `FASE-2.1-PIVOT.md`).
3. Update `APP-FLOW-MAP.md` bila flow app berubah.
4. Buat/ubah dokumen Fase 3 hanya setelah D-10 selesai.
5. Baru implementasi kode.
6. Commit dokumen bersama kode agar kontrak dan implementasi tidak drift.

---

## 6. Konvensi dokumen

- Bahasa: Indonesia; istilah teknis boleh Inggris.
- Uang: integer rupiah.
- Waktu: ISO 8601 UTC; bulan limit memakai WIB.
- Kode error: HARUS ada di `FASE-2-API.md`/`FASE-2.1-PIVOT.md` (atau kontrak
  fase yang berlaku) dan app `src/lib/errors.ts`.
- Setiap endpoint baru wajib punya:
  - method + path,
  - auth/header,
  - request + validasi,
  - respons sukses,
  - respons gagal + kode,
  - idempotency/rate limit bila mutasi uang.
- Jangan menaruh daftar keputusan di dokumen selain `DECISIONS.md`.

---

## 7. Pekerjaan berikutnya

1. Jawab keputusan **D-10 s/d D-19** di `DECISIONS.md`.
2. Update `FASE-2.1-PIVOT.md` bila jawaban mengubah kontrak.
3. Implementasi Fase 2.1 (email/phone auth, hapus face/recovery di app).
4. Setelah Fase 2.1 stabil dan D-10 final, susun dokumen Fase 3 baru.
