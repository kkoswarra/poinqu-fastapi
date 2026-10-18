# Dokumentasi Poinqu API

Indeks dokumen. Mulai dari sini sebelum membaca kontrak atau menulis kode.

---

## 1. Status proyek

- **Fase 2** — fondasi auth, PIN, perangkat, profil, biometric, admin, webhook
  Fonnte. Sudah berjalan.
- **Fase 2.1** — pivot produk ke **pulsa & PPOB** dan rework auth
  (email/nomor HP, hapus face, hapus recovery di app). **Sedang diputuskan.**
- **Fase 3A** — draft wallet/top-up/KYC/read bootstrap. **Belum final**;
  menunggu keputusan D-10 (apakah wallet/top-up/KYC tetap dipakai setelah
  pivot).

Jangan implementasi Fase 3 sebelum keputusan yang memblokir di
`DECISIONS.md` selesai.

---

## 2. Urutan baca

### Untuk owner/produk

1. `PLAN.md` — visi, aturan bisnis, fase (perhatikan banner pivot).
2. `DECISIONS.md` — keputusan yang sudah dan belum final.
3. `FASE-2.1-PIVOT.md` — perubahan produk/auth terbaru.
4. `FASE-3-API.md` — scope fase berikutnya (draft).

### Untuk backend

1. `FASE-2-API.md` — kontrak fondasi yang sudah berjalan.
2. `FASE-2.1-PIVOT.md` — perubahan yang harus diimplementasikan.
3. `APP-FLOW-MAP.md` — endpoint yang benar-benar dipanggil app.
4. `FASE-3-API.md` — kontrak berikutnya (setelah keputusan).
5. `FASE-3-TASKS.md` — checklist implementasi.

### Untuk mobile

1. `APP-FLOW-MAP.md` — layar → hook → endpoint.
2. `FASE-2.1-PIVOT.md` — perubahan auth/akun.
3. `FASE-3-FLOW.md` — flow fase berikutnya.
4. `FASE-3-API.md` — bentuk request/response.

### Untuk QA

1. `FASE-2-API.md` + `FASE-2.1-PIVOT.md` — kontrak yang diuji.
2. `FASE-3-API.md` — endpoint dan error.
3. `FASE-3-TASKS.md` — test wajib dan definition of done.

---

## 3. Peta dokumen

| Dokumen | Status | Isi |
| --- | --- | --- |
| `PLAN.md` | hidup, **ada banner pivot** | Visi produk, aturan bisnis, rencana fase |
| `DECISIONS.md` | hidup | Satu-satunya log keputusan (D-01, D-02, …) |
| `FASE-2-API.md` | **baseline** | Kontrak Fase 2 yang sudah berjalan |
| `FASE-2.1-PIVOT.md` | **change spec** | Pivot PPOB + rework auth email/phone, tanpa face/recovery |
| `APP-FLOW-MAP.md` | referensi | Peta flow app dan cakupan backend |
| `FASE-3-API.md` | **draft** | Kontrak Fase 3A: wallet/top-up/KYC/read bootstrap |
| `FASE-3-FLOW.md` | **draft** | Flow app untuk Fase 3A |
| `FASE-3-TASKS.md` | **draft** | Checklist implementasi Fase 3A |

---

## 4. Sumber kebenaran

Urutan prioritas saat ada pertentangan:

1. **`DECISIONS.md`** — keputusan produk/scope.
2. **Kontrak fase yang berlaku**:
   - Fase 2 → `FASE-2-API.md`
   - perubahan Fase 2 → `FASE-2.1-PIVOT.md`
   - Fase 3 → `FASE-3-API.md` (setelah keputusan)
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
2. Update kontrak fase (`FASE-2-API.md`, `FASE-2.1-PIVOT.md`, atau
   `FASE-3-API.md`).
3. Update `APP-FLOW-MAP.md` bila flow app berubah.
4. Update `FASE-3-FLOW.md`/`FASE-3-TASKS.md` bila scope fase berubah.
5. Baru implementasi kode.
6. Commit dokumen bersama kode agar kontrak dan implementasi tidak drift.

---

## 6. Konvensi dokumen

- Bahasa: Indonesia; istilah teknis boleh Inggris.
- Uang: integer rupiah.
- Waktu: ISO 8601 UTC; bulan limit memakai WIB.
- Kode error: HARUS ada di `FASE-2-API.md`/`FASE-3-API.md` dan app
  `src/lib/errors.ts`.
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
4. Setelah Fase 2.1 stabil, finalkan `FASE-3-API.md` dan mulai implementasi.
