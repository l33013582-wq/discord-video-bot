# Multi-Channel Adult Video Discord Bot (`discord.py` & `aiohttp`)

Bot Discord asinkron yang dirancang khusus untuk membagi dan mengunggah video serta anime secara otomatis dan berkala ke **4 channel terpisah berdasarkan kriteria wilayah / genre**:
1. 🇯🇵 **Jepang** (`CHANNEL_JEPANG_ID`): Konten JAV / Japanese Adult Video dari **XVideos** dan **Roshy.tv (Decensored JAV dengan Subtitle)**.
2. 🌸 **Hentai** (`CHANNEL_HENTAI_ID`): Konten Anime Hentai Sub Indo, Manga, dan 3D Animation dari **Nekopoi.care**.
3. 🌏 **Asia** (`CHANNEL_ASIA_ID`): Konten Asia Non-Jepang (Korea, China, Indonesia, Thailand, dll.).
4. 🌍 **Western** (`CHANNEL_WESTERN_ID`): Konten Barat / Amerika / Eropa / Caucasian.

---

## 🌟 Fitur Utama

1. **Auto-Update Multi-Channel (Setiap 30 Menit ke 4 Channel)**:
   - Loop latar belakang berkala memeriksa konten baru untuk keempat kategori.
   - **Jepang (JAV)**: Mengambil feed dinamis kombinasi dari **XVideos** dan **Roshy.tv**.
   - **Hentai**: Mengambil rilis anime dan manga hentai terbaru ber-sub Indo dari **Nekopoi.care**.
   - **Asia & Western**: Mengambil video segar dari engine XVideos dan Eporner.
   - Setiap channel memiliki warna Embed dan identitas emoji yang khas (Sakura Pink untuk Jepang, Hot Pink untuk Hentai, Warm Amber untuk Asia, Dodger Blue untuk Western).
   - **Sistem Deduplikasi Sentral (`sent_videos.json`)**: Memastikan tidak ada video/anime yang sudah pernah di-drop di server terkirim ulang meskipun bot di-restart.

2. **Perintah Pencarian Interaktif (`/cari [kata_kunci]`)**:
   - Hanya dapat dijalankan di channel **NSFW (Age-Restricted)**.
   - **Pencarian Hentai (Nekopoi.care)**: Cari anime/manga hentai secara instan (contoh: `/cari keyword: overflow`, `/cari keyword: kangoku senkan`).
   - **Pencarian Kode Nuklir JAV (Roshy.tv & XVideos)**: Mendukung pencarian kode produksi JAV resmi (contoh: `/cari keyword: SSIS-878`, `/cari keyword: ALDN-056`, `/cari keyword: LULU-345`). Bot mencocokkan video tanpa sensor dan ber-subtitle.
   - **Filter Durasi Lengkap**: Mendukung pencarian film berdurasi panjang jam-jaman (`jam-jaman`, `20+ menit`, `10-20 menit`, `3-10 menit`).
   - **Smart Context Detection**: Otomatis mendeteksi channel aktif (`#hentai` $\rightarrow$ Nekopoi, `#jav` $\rightarrow$ Jepang, `#asia` $\rightarrow$ Asia, `#western` $\rightarrow$ Barat).

3. **Perintah Pengecekan Sistem (`/status`)**:
   - Memeriksa konektivitas bot ke keempat channel dan memvalidasi apakah status NSFW di masing-masing channel sudah aktif.

---

## 📁 Struktur Berkas

```text
d:/bot/
├── bot.py               # Skrip utama bot Discord multi-channel
├── requirements.txt     # Dependensi Python
├── .env                 # Konfigurasi Token, 4 Channel ID, dan URL API
├── .env.example         # Template konfigurasi
├── sent_videos.json     # Cache deduplikasi ID video (terbuat otomatis)
└── README.md            # Dokumentasi panduan
```

---

## ⚙️ Konfigurasi `.env`

Buka file [`.env`](file:///d:/bot/.env) dan lengkapi ID channel Discord Anda:

```ini
# Token Bot Discord
DISCORD_TOKEN=your_bot_token_here

# ID Channel Discord untuk masing-masing kriteria (Wajib Age-Restricted / NSFW!)
CHANNEL_JEPANG_ID=111111111111111111
CHANNEL_HENTAI_ID=222222222222222222
CHANNEL_ASIA_ID=333333333333333333
CHANNEL_WESTERN_ID=444444444444444444

# Endpoint API per Kategori
API_JEPANG_URL=https://www.xvideos.com/?k=japanese&sort=uploaddate
API_HENTAI_URL=https://nekopoi.care/wp-json/wp/v2/posts?_embed=1&categories=2,81,682
API_ASIA_URL=https://api.example.com/v1/videos?category=asian
API_WESTERN_URL=https://api.example.com/v1/videos?category=western

# Endpoint Pencarian
API_SEARCH_VIDEOS_URL=https://www.eporner.com/api/v2/web/search/?thumbsize=big&format=json
API_KEY=your_api_key_here
```

> **Cara Mendapatkan Channel ID:**
> 1. Aktifkan **Developer Mode** di Discord (`User Settings` > `Advanced` > `Developer Mode`).
> 2. Klik kanan pada channel yang dituju (`#jav`, `#hentai`, `#asia`, atau `#western`) -> pilih **Copy Channel ID**.
> 3. Pastikan keempat channel tersebut telah dicentang sebagai **Age-Restricted Channel (NSFW)** pada channel settings Discord.

---

## 🚀 Cara Menjalankan Bot

Pastikan dependensi sudah terpasang:
```bash
pip install -r requirements.txt
```

Jalankan skrip bot:
```bash
python bot.py
```

---

## 📖 Daftar Perintah Bot

| Perintah | Contoh | Keterangan |
| :--- | :--- | :--- |
| `/help` / `/panduan` | `/help` | Menampilkan **Pusat Panduan Sugiono Bot** lengkap dengan menu dropdown interaktif (Panduan Perintah, Kode Nuklir, Kamus Tag, 4 Saluran, Keamanan). |
| `sugiono help` | `sugiono help` | Trigger bantuan langsung lewat obrolan teks biasa. |
| `/cari [kata_kunci]` | `/cari keyword: perawat` | Cukup ketik kata kunci di channel masing-masing. Genre video otomatis mengikuti channel (`#jav` = Jepang, `#hentai` = Hentai Nekopoi, `#asia` = Asia, `#western` = Barat). |
| `/cari [anime_hentai]` | `/cari keyword: overflow` | **Pencarian Anime/Manga Hentai**: Diambil langsung dari **Nekopoi.care** lengkap dengan sinopsis dan tombol link streaming/download. |
| `/cari [kode_nuklir]` | `/cari keyword: SSIS-878` | **Pencarian Kode Nuklir JAV** (misal: `SSIS-878`, `ALDN-056`, `LULU-345`, `FC2-PPV-3124567`). Bot mencari di **Roshy.tv (Decensored Subtitle)** & **XVideos**. |
| `/cari [durasi]` | `/cari durasi: Jam-jaman keyword: perawat` | **Filter Durasi Video**: Pilihan: `Jam-jaman (20m+ Sort Durasi)`, `Panjang (20+m)`, `Sedang (10-20m)`, `Pendek (3-10m)`. Bisa juga diketik langsung di keyword (contoh: `/cari perawat jam-jaman` atau `/cari tante 10-20 menit`). |
| `/cari [kategori]` | `/cari kategori: Hentai (Nekopoi) keyword: cosplay` | **Pilihan Kategori Bebas**: Bebas memilih kategori (`Jepang`, `Hentai`, `Asia`, `Western`, `Semua`) atau biarkan `Otomatis` sesuai channel aktif. |
| `/status` | `/status` | Menampilkan ringkasan status koneksi ke 4 channel (Jepang, Hentai, Asia, Western) beserta verifikasi status NSFW. |
| `/search` / `/find` | `/search keyword: cosplay` | Alias dari perintah `/cari`. |
| `!cari` / `!status` | `!cari SSIS-878` | Tetap didukung sebagai prefix commands fallback jika Anda lebih suka tanda seru `!`. |
