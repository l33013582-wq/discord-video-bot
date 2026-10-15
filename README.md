# Multi-Channel Adult Video Discord Bot (`discord.py` & `aiohttp`)

Bot Discord asinkron yang dirancang khusus untuk membagi dan mengunggah video secara otomatis dan berkala ke **3 channel terpisah berdasarkan kriteria wilayah / genre**:
1. 🇯🇵 **Jepang** (`CHANNEL_JEPANG_ID`): Konten JAV / Japanese Adult Video.
2. 🌏 **Asia** (`CHANNEL_ASIA_ID`): Konten Asia Non-Jepang (Korea, China, Indonesia, Thailand, dll.).
3. 🌍 **Western** (`CHANNEL_WESTERN_ID`): Konten Barat / Amerika / Eropa / Caucasian.

---

## 🌟 Fitur Utama

1. **Auto-Update Multi-Channel (Setiap 30 Menit)**:
   - Loop latar belakang berkala memeriksa video baru untuk ketiga kategori.
   - Mengambil data dari endpoint API masing-masing wilayah (`API_JEPANG_URL`, `API_ASIA_URL`, `API_WESTERN_URL`).
   - Setiap channel memiliki warna Embed dan identitas emoji yang khas (Sakura Pink untuk Jepang, Warm Amber untuk Asia, Dodger Blue untuk Western).
   - **Sistem Deduplikasi Sentral (`sent_videos.json`)**: Memastikan tidak ada video duplikat yang terkirim meskipun bot di-restart.

2. **Perintah Pencarian Interaktif (`!cari [kata_kunci]`)**:
   - Hanya dapat dijalankan di channel **NSFW (Age-Restricted)**.
   - **Smart Context Detection**: Jika dijalankan di dalam channel `#jepang`, `#asia`, atau `#western`, bot secara cerdas memprioritaskan pencarian dan memberi label sesuai channel tersebut.

3. **Perintah Pengecekan Sistem (`!status`)**:
   - Memeriksa konektivitas bot ke ketiga channel dan memvalidasi apakah status NSFW di masing-masing channel sudah aktif.

---

## 📁 Struktur Berkas

```text
d:/bot/
├── bot.py               # Skrip utama bot Discord multi-channel
├── requirements.txt     # Dependensi Python
├── .env                 # Konfigurasi Token, 3 Channel ID, dan URL API
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
CHANNEL_ASIA_ID=222222222222222222
CHANNEL_WESTERN_ID=333333333333333333

# Endpoint API per Kategori
API_JEPANG_URL=https://api.example.com/v1/videos?category=japanese
API_ASIA_URL=https://api.example.com/v1/videos?category=asian
API_WESTERN_URL=https://api.example.com/v1/videos?category=western

# Endpoint Pencarian
API_SEARCH_VIDEOS_URL=https://api.example.com/v1/videos/search
API_KEY=your_api_key_here
```

> **Cara Mendapatkan Channel ID:**
> 1. Aktifkan **Developer Mode** di Discord (`User Settings` > `Advanced` > `Developer Mode`).
> 2. Klik kanan pada channel yang dituju (`#jepang`, `#asia`, atau `#western`) -> pilih **Copy Channel ID**.
> 3. Pastikan ketiga channel tersebut telah dicentang sebagai **Age-Restricted Channel (NSFW)** pada channel settings Discord.

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
| `/cari [kata_kunci]` | `/cari keyword: perawat` | Cukup ketik kata kunci di channel masing-masing. Genre video otomatis mengikuti channel (`#jav` = Jepang, `#asia` = Asia, `#western` = Barat). |
| `/cari [kata_kunci]` | `/cari keyword: anak sekolah` | Mendukung bahasa Indonesia (tante, perawat, sekolah, dll) dan otomatis diterjemahkan ke tag XVideos. |
| `/status` | `/status` | Menampilkan ringkasan status koneksi ke channel Jepang, Asia, dan Western. |
| `/search` / `/find` | `/search keyword: cosplay` | Alias dari perintah `/cari`. |
| `!cari` / `!status` | `!cari perawat` | Tetap didukung sebagai fallback jika Anda lebih suka tanda seru. |
