# FLOW — Fase 3A (App React Native ↔ Backend)

> **Status:** draft, bergantung pada keputusan **D-10** di `DECISIONS.md`
> (apakah wallet/top-up/KYC tetap dipakai setelah pivot PPOB).
>
> Kontrak API: `FASE-3-API.md` · task: `FASE-3-TASKS.md` · indeks:
> `README.md`.

Dokumen pendamping `FASE-3-API.md`. Fokus: flow yang sudah ada di app dan
perubahannya saat `EXPO_PUBLIC_USE_MOCK=0`.

Sumber app:

- `app-frontend/src/screens/*`
- `app-frontend/src/hooks/*`
- `app-frontend/src/api/endpoints/*`
- `app-frontend/src/api/types/*`

---

## 1. Home (read bootstrap)

### Layar

`src/screens/home/HomeScreen.tsx`

### Data yang dipanggil

| Data | Hook | Endpoint |
| --- | --- | --- |
| Saldo + limit | `useWallet` | `GET /wallet` |
| 3 transaksi terakhir | `useTransactions({limit:3})` | `GET /transactions?limit=3` |
| Shortcut/quick action/feature | `useServices` | `GET /catalog/services` |
| Badge notifikasi | `useUnreadCount` | `GET /notifications?limit=1` |
| Aktivitas keamanan | `useSecurityActivities` | `GET /me/security/activities` ✅ |

### Urutan

1. Setelah login, `RootNavigator` menampilkan `Tabs`.
2. Home memanggil empat endpoint secara paralel.
3. `wallet` menampilkan saldo dan limit.
4. `transactions` menampilkan 3 baris terakhir.
5. `services` mengisi shortcut dan quick action; jika kosong, app memakai
   `DEFAULT_QUICK_ACTIONS`.
6. `notifications` mengisi badge unread.
7. Pull-to-refresh memanggil ulang wallet, transaksi, dan services.

### Syarat backend

- `GET /wallet` selalu tersedia untuk user aktif; akun dibuat lazy bila belum ada.
- `GET /transactions` mengembalikan item bertipe `TransactionsListData`.
- `GET /catalog/services` mengembalikan `ServicesData` dari
  `catalog_documents['home']`.
- `GET /notifications?limit=1` mengembalikan `unread_count`.

---

## 2. Top-up

### Layar dan hook

- `src/screens/wallet/TopUpScreen.tsx`
- `src/screens/wallet/TopUpCodeScreen.tsx`
- `src/screens/wallet/TopUpHistoryScreen.tsx`
- `src/hooks/useTopup.ts`
- `src/api/endpoints/topup.ts`

### Flow buat kode bayar

1. `TopUpScreen` memanggil `GET /wallet/topup-methods`.
2. User memilih nominal dan channel.
3. App menghitung fee lokal dari definisi `fee`, tetapi **total final
   tetap dari server**.
4. Tombol “Buat Kode Bayar” memanggil `createTopup` dengan
   `Idempotency-Key` baru.
5. `POST /wallet/topups` mengembalikan `TopupOrder`.
6. App navigasi ke `TopUpCode` dengan `topup_id`.

### Flow kode bayar

1. `TopUpCodeScreen` memanggil `GET /wallet/topups/{id}`.
2. Polling setiap 4 detik selama `WAITING_PAYMENT` atau `REQUIRES_ACTION`.
3. Tampilkan VA/QR/deeplink, instruksi, dan countdown dari `expires_at`.
4. Status `PAID` → invalidate `GET /wallet` dan transaksi.
5. “Saya Sudah Bayar” → refetch detail.
6. “Batalkan” → `POST /wallet/topups/{id}/cancel`.
7. Status final: `PAID`, `EXPIRED`, `CANCELLED`, `FAILED`.

### Flow riwayat

1. `TopUpHistoryScreen` memanggil `GET /wallet/topups` dengan cursor.
2. Filter status/date diteruskan ke query.
3. Setiap item membuka detail transaksi/struk.

### Perubahan app yang diperlukan

- Gunakan total/fee dari respons create, jangan hanya fee lokal.
- Tampilkan `action.url` bila `status = REQUIRES_ACTION`.
- Anggap `FAILED` sebagai final (saat ini UI masih bisa menampilkan tombol).
- Simpan `Idempotency-Key` per attempt agar retry jaringan memakai key sama.

---

## 3. KYC / Premium

### Layar dan hook

- `src/screens/account/PremiumScreen.tsx`
- `src/screens/account/PremiumFaceScreen.tsx`
- `src/screens/account/PremiumPendingScreen.tsx`
- `src/hooks/useKyc.ts`
- `src/api/endpoints/kyc.ts`
- `src/lib/liveness.ts`

### Flow

1. `PremiumScreen` memanggil `GET /me/kyc`.
2. Jika `NONE`/`REJECTED` dan `can_resubmit`, tampilkan form.
3. Form mengirim multipart `POST /me/kyc` (`ktp_photo` + data KTP).
4. Respons `DRAFT` + `next_step = FACE`.
5. App pindah ke `PremiumFaceScreen`.
6. `createLivenessSessionId()` → `POST /me/kyc/{kyc_id}/face`.
7. Backend memvalidasi liveness dan mengubah status menjadi `PENDING`.
8. App pindah ke `PremiumPendingScreen`.
9. `GET /me/kyc` menampilkan langkah DATA/FACE/REVIEW.
10. Admin memutuskan; user melihat `VERIFIED` (PREMIUM) atau `REJECTED`
    dengan alasan dan opsi resubmit.

> **Catatan pivot:** langkah 5–7 hanya berlaku jika **D-14** mempertahankan
> face untuk KYC. Jika face dihapus, setelah submit KTP status langsung
> `PENDING` dan app menuju `PremiumPendingScreen`.

### Perubahan app/backend yang diperlukan

- Backend harus menyediakan endpoint KYC (belum ada di Fase 2).
- File KTP disimpan di object storage privat, bukan `/tmp`.
- `liveness_session_id` Fase 3A memakai adapter mock; provider asli nanti.
- `POST /me/kyc` harus menerima multipart persis field app.
- `GET /me/kyc` harus mengembalikan `steps`, `estimated_hours`,
  `can_resubmit`, `reason_code`, `reason` seperti tipe app.

---

## 4. Admin KYC manual

### Flow reviewer

1. Admin membuka antrean `GET /admin/kyc/submissions?status=PENDING`.
2. Pilih pengajuan → `GET /admin/kyc/submissions/{id}`.
3. Admin melihat data KTP (masked/full sesuai izin), signed URL foto KTP,
   status liveness, dan data user.
4. Admin memutuskan:
   - `POST /admin/kyc/submissions/{id}/decision`
     `{ decision: "APPROVE" | "REJECT", reason }`.
5. Approve:
   - cek NIK masih unik,
   - set `users.kyc_status=VERIFIED`, `level=PREMIUM`, nama mengikuti KTP,
   - buat notifikasi `KYC_RESULT`,
   - audit log.
6. Reject:
   - simpan `reason_code`/`reason`,
   - user dapat resubmit,
   - notifikasi `KYC_RESULT`.

### Hak akses

- Permission `kyc.review`.
- File KTP hanya via signed URL berumur pendek.
- Semua akses/decision masuk audit log.

---

## 5. Penanganan error di app

| Konteks | Kode | Tindakan app |
| --- | --- | --- |
| Top-up nominal | `AMOUNT_TOO_LOW`, `AMOUNT_TOO_HIGH`, `AMOUNT_OUT_OF_RANGE` | Tampilkan pesan, jangan buat kode |
| Limit | `BALANCE_LIMIT_EXCEEDED`, `MONTHLY_INCOMING_LIMIT_EXCEEDED` | Tampilkan sisa limit, arahkan ke KYC |
| Channel | `CHANNEL_NOT_AVAILABLE` | Disable/refresh metode |
| Provider | `PAYMENT_PROVIDER_ERROR`, `PROVIDER_TIMEOUT` | Tampilkan “coba lagi”; jangan anggap gagal permanen |
| Idempotency | `IDEMPOTENCY_KEY_REUSED` | Buat key baru hanya jika payload berubah |
| KYC | `KYC_PENDING`, `KYC_NOT_DRAFT`, `KYC_DRAFT_EXPIRED` | Arahkan ke status/ulang draft |
| KYC NIK | `NIK_ALREADY_USED` | Tampilkan alasan, hubungi bantuan |
| KYC file | `FILE_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE` | Minta foto ulang |
| Umum | `UNAUTHORIZED` | Logout bila sesi dicabut (perlu perbaikan client) |

---

## 6. Blocker integrasi yang harus dibereskan

### 6.1 Refresh token

`src/api/client.ts` memakai `refreshClient` tanpa `X-Device-Id`.
Backend mewajibkan header itu. Perbaiki sebelum menguji token expiry.

### 6.2 Public key biometrik

App mengirim PEM, backend mengharapkan base64 DER.
Pilih salah satu:

- app mengirim base64 DER, atau
- backend menerima PEM.

### 6.3 `UNAUTHORIZED` tidak logout

Client hanya logout pada `REFRESH_TOKEN_INVALID/REVOKED`.
Backend mengembalikan `UNAUTHORIZED` untuk sesi yang dicabut.
Tambahkan penanganan logout untuk `UNAUTHORIZED` yang bukan dari login.

### 6.4 Error map

Satukan `src/api/errors.ts` dan `src/lib/errors.ts`; client harus memakai
peta lengkap.

### 6.5 Deep link

Samakan `share_url`/`deep_link` dengan `src/navigation/linking.ts`.
Saat ini mock memakai `poinqu.id`/`bayarin://transactions/...` yang tidak
semua terdaftar.

---

## 7. Checklist switch mock → backend

- [ ] `EXPO_PUBLIC_USE_MOCK=0`.
- [ ] `EXPO_PUBLIC_API_URL` menunjuk backend.
- [ ] `GET /wallet`, `/transactions`, `/catalog/services`, `/notifications` OK.
- [ ] Top-up create → code → polling → PAID.
- [ ] KYC submit → face → PENDING → admin decision.
- [ ] Refresh token dengan `X-Device-Id` berhasil.
- [ ] Logout pada `UNAUTHORIZED`.
- [ ] Semua toast error menampilkan `message`/`code` yang benar.
