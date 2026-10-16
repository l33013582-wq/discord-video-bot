import os
import re
import json
import random
import logging
import asyncio
import socket
import html
import urllib.parse
import urllib.request
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# ==============================================================================
# 1. KONFIGURASI LOGGING & ENVIRONMENT VARIABLES
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("AdultVideoBot")

# Muat variabel dari file .env
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_KEY")
API_SEARCH_VIDEOS_URL = os.getenv("API_SEARCH_VIDEOS_URL", "https://www.eporner.com/api/v2/web/search/?thumbsize=big&format=json")

def parse_channel_id(env_name: str) -> Optional[int]:
    val = os.getenv(env_name)
    if not val:
        return None
    try:
        return int(val.strip())
    except ValueError:
        logger.error(f"Nilai {env_name} pada file .env harus berupa angka ID channel!")
        return None

# ==============================================================================
# 2. KONFIGURASI 4 KATEGORI / GENRE WILAYAH (JEPANG, HENTAI, ASIA, WESTERN)
# ==============================================================================
CATEGORIES: Dict[str, Dict[str, Any]] = {
    "jepang": {
        "key": "jepang",
        "name": "Jepang (JAV / Japanese)",
        "emoji": "🇯🇵",
        "channel_id": parse_channel_id("CHANNEL_JEPANG_ID"),
        "api_url": os.getenv("API_JEPANG_URL", "https://www.xvideos.com/?k=japanese&sort=uploaddate"),
        "color": discord.Color.from_rgb(255, 75, 145),  # Sakura Crimson
        "keywords": [
            "japanese", "jav uncensored", "japanese sub indo", "japanese massage",
            "japanese schoolgirl", "japanese milf", "japanese nurse", "tokyo jav",
            "japanese wife", "japanese cosplay", "japanese amateur", "jav hd",
            "japanese creampie", "japanese cheating", "japanese sister", "japanese office"
        ]
    },
    "hentai": {
        "key": "hentai",
        "name": "Hentai (Nekopoi Anime & Manga)",
        "emoji": "🌸",
        "channel_id": parse_channel_id("CHANNEL_HENTAI_ID"),
        "api_url": os.getenv("API_HENTAI_URL", "https://nekopoi.care/wp-json/wp/v2/posts?_embed=1&categories=2,81,682"),
        "color": discord.Color.from_rgb(255, 105, 180),  # Hot Pink
        "keywords": [
            "hentai", "anime hentai", "manga", "3d hentai", "sub indo",
            "kangoku senkan", "overflow", "isekai", "cosplay", "uncensored"
        ]
    },
    "asia": {
        "key": "asia",
        "name": "Asia (Non-Jepang)",
        "emoji": "🌏",
        "channel_id": parse_channel_id("CHANNEL_ASIA_ID"),
        "api_url": os.getenv("API_ASIA_URL", "https://www.xvideos.com/?k=asian&sort=uploaddate"),
        "color": discord.Color.from_rgb(255, 140, 0),   # Warm Amber
        "keywords": [
            "asian", "indonesian viral", "korean bj", "indo bokep", "chinese amateur",
            "thai massage", "filipina viral", "vietnamese girl", "asian college",
            "asian milf", "hijab indo", "korean dance", "indo pemersatu bangsa",
            "asian creampie", "malay viral", "indo mahasiswi"
        ]
    },
    "western": {
        "key": "western",
        "name": "Western (Barat / Caucasian)",
        "emoji": "🌍",
        "channel_id": parse_channel_id("CHANNEL_WESTERN_ID"),
        "api_url": os.getenv("API_WESTERN_URL", "https://www.xvideos.com/?k=western&sort=uploaddate"),
        "color": discord.Color.from_rgb(30, 144, 255),  # Dodger Blue
        "keywords": [
            "western", "blonde teen", "american milf", "stepmom", "latina big ass",
            "european amateur", "brunette college", "czech massage", "hardcore western",
            "french babe", "blonde rough", "stepdaughter", "western creampie", "office secretary"
        ]
    }
}

CACHE_FILE = "sent_videos.json"
MAX_CACHED_IDS = 10000  # Kapasitas cache deduplikasi


# ==============================================================================
# 3. HELPER KELAS PENYIMPANAN RIWAYAT VIDEO (DEDUPLIKASI)
# ==============================================================================
class VideoHistoryManager:
    """Mengelola penyimpanan ID, URL, dan identifikasi unik video yang telah dikirim ke Discord agar tidak pernah terkirim ulang."""
    def __init__(self, filename: str = CACHE_FILE):
        self.filename = filename
        self.seen_ids: Set[str] = set()
        self.load_history()

    def load_history(self) -> None:
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.seen_ids = set(map(str, data))
                        logger.info(f"Memuat {len(self.seen_ids)} riwayat video dari {self.filename}.")
            except Exception as e:
                logger.warning(f"Gagal membaca {self.filename}, membuat riwayat baru: {e}")
                self.seen_ids = set()
        else:
            self.seen_ids = set()

    def save_history(self) -> None:
        try:
            id_list = list(self.seen_ids)[-MAX_CACHED_IDS:]
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(id_list, f, indent=2)
        except Exception as e:
            logger.error(f"Gagal menyimpan riwayat video ke {self.filename}: {e}")

    def _get_keys(self, video: Any) -> List[str]:
        """Mengekstrak seluruh kunci identifikasi (ID, path URL, slug judul) agar tidak pernah dobel."""
        keys: List[str] = []
        if isinstance(video, dict):
            v_id = video.get("id")
            v_url = video.get("url")
            v_title = video.get("title")

            if v_id and str(v_id).strip():
                clean_id = str(v_id).strip()
                keys.append(clean_id)
                keys.append(f"id:{clean_id}")

            if v_url and str(v_url).strip():
                clean_url = str(v_url).strip().lower().split("?")[0]
                keys.append(clean_url)
                m = re.search(r'/video[._]?([a-zA-Z0-9]+)', clean_url)
                if m:
                    keys.append(m.group(1))
                    keys.append(f"id:{m.group(1)}")

            if v_title and str(v_title).strip():
                slug = re.sub(r'[^a-zA-Z0-9]', '', str(v_title).lower())
                if len(slug) >= 8:
                    keys.append(f"slug:{slug[:40]}")
                code = detect_jav_code(str(v_title))
                if code:
                    keys.append(f"code:{code.upper()}")
        elif isinstance(video, str) and video.strip():
            clean_str = video.strip()
            keys.append(clean_str)
            keys.append(f"id:{clean_str}")
        return keys

    def is_seen(self, video: Any) -> bool:
        """Memeriksa apakah video (berdasarkan ID, URL, atau judul) sudah pernah di-drop di server."""
        if not video:
            return False
        keys = self._get_keys(video)
        return any(k in self.seen_ids for k in keys)

    def mark_as_seen(self, video: Any) -> None:
        """Menandai video beserta varian identitasnya sebagai sudah dikirim ke Discord."""
        if not video:
            return
        keys = self._get_keys(video)
        for k in keys:
            self.seen_ids.add(k)
        self.save_history()


# ==============================================================================
# 4. KAMUS PENERJEMAHAN ISTILAH / KATEGORI BAHASA INDONESIA KE TAG INGGRIS
# ==============================================================================
INDONESIAN_TRANSLATION_MAP: Dict[str, str] = {
    # Wilayah & Ras / Kategori Utama
    "jepang": "japanese",
    "jav": "jav japanese",
    "hentai": "hentai",
    "anime": "anime hentai",
    "manga": "manga",
    "kartun": "hentai anime",
    "animasi": "3d hentai",
    "asia": "asian",
    "barat": "western",
    "bule": "western",
    "korea": "korean",
    "cina": "chinese",
    "china": "chinese",
    "indo": "indonesian",
    "indonesia": "indonesian",
    "lokal": "indonesian",

    # Usia / Karakter / Peran
    "tante": "milf",
    "stw": "mature milf",
    "ibu tiri": "stepmom",
    "mama tiri": "stepmom",
    "ibu": "mom",
    "mama": "mom",
    "anak tiri": "stepdaughter",
    "saudara tiri": "stepsister",
    "kakak tiri": "stepsister",
    "adik tiri": "stepsister",
    "sekolah": "schoolgirl",
    "siswi": "schoolgirl",
    "anak sekolah": "schoolgirl",
    "sma": "schoolgirl",
    "smp": "schoolgirl teen",
    "seragam": "uniform schoolgirl",
    "remaja": "teen",
    "gadis": "teen",
    "perawan": "virgin",
    "cewek": "girl",
    "cewe": "girl",
    "wanita": "woman",
    "mahasiswi": "college student",
    "kuliah": "college",

    # Pekerjaan / Profesi
    "perawat": "nurse",
    "suster": "nurse",
    "guru": "teacher",
    "dosen": "teacher",
    "kantor": "office",
    "sekretaris": "secretary",
    "bos": "boss",
    "pelayan": "maid",
    "pembantu": "maid",
    "polisi": "police",
    "pramugari": "flight attendant",
    "model": "model",
    "terapis": "massage therapist",
    "pijat": "massage",
    "urut": "massage",

    # Lokasi / Skenario
    "kamar": "room",
    "hotel": "hotel",
    "mandi": "shower bath",
    "toilet": "bathroom",
    "dapur": "kitchen",
    "mobil": "car",
    "pantai": "beach",
    "kolam renang": "pool",
    "kolam": "pool",
    "taman": "outdoor",
    "kantoran": "office",
    "rumah": "home",
    "tetangga": "neighbor",
    "teman": "friend",
    "sahabat": "friend",
    "selingkuh": "cheating",
    "tidur": "sleeping",
    "sembunyi": "hidden",
    "intip": "spy",
    "ketahuan": "caught",
    "terjebak": "stuck",

    # Ciri Fisik
    "toket besar": "big tits",
    "tete besar": "big tits",
    "payudara besar": "big tits",
    "montok": "chubby bbw",
    "pantat besar": "big ass",
    "pantat": "ass",
    "kacamata": "glasses",
    "mulus": "smooth",
    "pirang": "blonde",
    "hitam": "ebony",
    "kulit putih": "pale",
    "cantik": "beautiful",
    "imut": "cute",
    "rambut pendek": "short hair",
    "gemuk": "chubby bbw",

    # Pakaian & Aksesori
    "jilbab": "hijab",
    "kerudung": "hijab",
    "kebaya": "kebaya indonesian",
    "stoking": "stockings",
    "lingerie": "lingerie",
    "rok": "skirt",
    "bikini": "bikini",
    "kostum": "cosplay",

    # Gaya & Aksi
    "kasar": "hardcore",
    "lembut": "romantic",
    "kencing": "pissing",
    "goyang": "riding",
    "kocok": "handjob",
    "isap": "blowjob",
    "oral": "blowjob",
    "gengbang": "gangbang",
    "trio": "threesome",
    "rame-rame": "group sex",
    "kencan": "date",
    "mabuk": "drunk",
    "paksa": "rough",
}

def translate_indonesian_query(query: str) -> str:
    """Menerjemahkan kata kunci pencarian dari Bahasa Indonesia ke istilah tag bahasa Inggris untuk XVideos."""
    if not query:
        return ""
    translated = query.lower()
    for id_phrase, en_term in sorted(INDONESIAN_TRANSLATION_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = r"\b" + re.escape(id_phrase) + r"\b"
        translated = re.sub(pattern, en_term, translated)
    return " ".join(translated.split())


# ------------------------------------------------------------------------------
# PENGATURAN DURASI & DETEKSI KODE NUKLIR JAV
# ------------------------------------------------------------------------------
VALID_DURATIONS: Set[str] = {"all", "hours", "20min_more", "10-20min", "3-10min", "1-3min"}
VALID_CATEGORIES: Set[str] = {"auto", "jepang", "hentai", "asia", "western", "semua"}

DURATION_LABELS: Dict[str, str] = {
    "hours": "🎬 Jam-jaman / Film Panjang (20m+ Sort Durasi)",
    "20min_more": "⌛ Panjang (20+ Menit)",
    "10-20min": "⏱️ Sedang (10 - 20 Menit)",
    "3-10min": "⚡ Pendek (3 - 10 Menit)",
    "1-3min": "⚡ Sangat Singkat (1 - 3 Menit)",
}

DURATION_TEXT_PATTERNS = [
    (re.compile(r'\b(jam[- ]?jaman|berjam[- ]?jam|film[- ]?panjang|full[- ]?movie|full[- ]?jav|full[- ]?film)\b', re.IGNORECASE), "hours"),
    (re.compile(r'\b(durasi[- ]?sedang|10[- ]?(?:sampai|ke|to|-)?[- ]?20\s*(?:menit|min))\b', re.IGNORECASE), "10-20min"),
    (re.compile(r'\b(sangat[- ]?singkat|1[- ]?(?:sampai|ke|to|-)?[- ]?3\s*(?:menit|min))\b', re.IGNORECASE), "1-3min"),
    (re.compile(r'\b(durasi[- ]?pendek|durasi[- ]?singkat|3[- ]?(?:sampai|ke|to|-)?[- ]?10\s*(?:menit|min))\b', re.IGNORECASE), "3-10min"),
    (re.compile(r'\b(durasi[- ]?panjang|20\+?\s*(?:menit|min)(\s*keatas)?|20min_more|>20\s*min)\b', re.IGNORECASE), "20min_more"),
]

JAV_CODE_REGEX = re.compile(
    r'\b(?:FC2[-_ ]?PPV[-_ ]?\d{4,8}|FC2[-_ ]?\d{4,8}|HEYZO[-_ ]?\d{4,6}|[A-Za-z]{2,6}[-_ ]?\d{2,6})\b',
    re.IGNORECASE
)
FALSE_CODE_POSITIVES: Set[str] = {
    "top10", "mp4", "1080p", "720p", "4k", "3d", "h264", "h265", "part1", "part2", "vol1", "vol2", "no1", "10min", "20min", "3min"
}

def detect_jav_code(text: str) -> Optional[str]:
    """Mendeteksi apakah kata kunci mengandung kode nuklir JAV (contoh: SSIS-878, ALDN-056, FC2-PPV-1234567)."""
    if not text:
        return None
    matches = JAV_CODE_REGEX.findall(text)
    for m in matches:
        clean = re.sub(r'[\s_]+', '-', m).upper()
        has_letters = any(c.isalpha() for c in clean)
        has_digits = any(c.isdigit() for c in clean)
        if has_letters and has_digits:
            raw_alphanumeric = re.sub(r'[^A-Za-z0-9]', '', clean).lower()
            if raw_alphanumeric not in FALSE_CODE_POSITIVES:
                if '-' not in clean:
                    split_match = re.match(r'^([A-Z]+)(\d+)$', clean)
                    if split_match:
                        clean = f"{split_match.group(1)}-{split_match.group(2)}"
                return clean
    return None

def resolve_search_parameters(
    raw_durasi: Optional[str] = None,
    raw_kategori: Optional[str] = None,
    raw_keyword: Optional[str] = None
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Mengurai parameter durasi, kategori, dan kata kunci secara fleksibel untuk mendukung
    baik Slash Command (pilihan dropdown) maupun teks bebas / Prefix command.
    Mengembalikan (combined_kw, dur_val, cat_val, detected_code).
    """
    kw_parts = []
    dur_val = None
    cat_val = None

    tokens = [t for t in [raw_durasi, raw_kategori] if t]
    for token in tokens:
        tl = token.lower()
        if tl in VALID_DURATIONS and dur_val is None:
            dur_val = tl
        elif tl in VALID_CATEGORIES and cat_val is None:
            cat_val = tl
        else:
            kw_parts.append(token)

    if raw_keyword:
        kw_parts.append(raw_keyword)

    combined_kw = " ".join(kw_parts).strip()

    # Jika durasi belum dipilih dari dropdown, cek apakah user mengetik durasi dalam teks
    if not dur_val or dur_val == "all":
        for pattern, dur_key in DURATION_TEXT_PATTERNS:
            if pattern.search(combined_kw):
                dur_val = dur_key
                combined_kw = pattern.sub("", combined_kw).strip()
                break

    combined_kw = re.sub(r"\s+", " ", combined_kw).strip()
    detected_code = detect_jav_code(combined_kw)

    return combined_kw, dur_val, cat_val, detected_code


# ==============================================================================
# 5. HELPER PARSER DATA API & HTML SCRAPER (XVIDEOS / EPORNER / REDTUBE)
# ==============================================================================
def parse_xvideos_html(html_text: str, default_category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Mengekstrak daftar video langsung dari halaman pencarian atau kategori XVideos."""
    soup = BeautifulSoup(html_text, "html.parser")
    results = []

    # XVideos menggunakan class thumb-block untuk setiap video card
    blocks = soup.find_all("div", class_="thumb-block")
    for block in blocks:
        try:
            # Dapatkan elemen judul dan link video
            title_p = block.find("p", class_="title")
            if not title_p:
                continue
            a_tag = title_p.find("a")
            if not a_tag:
                continue

            title = a_tag.get("title") or a_tag.text.strip()
            href = a_tag.get("href", "")
            if not href or href == "#":
                continue
            url = f"https://www.xvideos.com{href}" if href.startswith("/") else href

            # Ekstrak ID video unik dari href (/video12345/ atau /video.abcde/)
            video_id = None
            id_match = re.search(r'/video[._]?([a-zA-Z0-9]+)', href)
            if id_match:
                video_id = id_match.group(1)
            elif block.get("data-id") and str(block.get("data-id")).strip().isdigit():
                video_id = str(block.get("data-id")).strip()
            elif block.get("id") and str(block.get("id")).startswith("video_"):
                video_id = str(block.get("id")).replace("video_", "").strip()
            else:
                video_id = url

            # Abaikan ID generik jika tertangkap tombol UI
            if video_id in ["anc-tst-first_video-btn", "first_video-btn", "btn"]:
                video_id = url

            # Dapatkan poster gambar / thumbnail
            img_tag = block.find("img")
            thumbnail = None
            if img_tag:
                thumbnail = img_tag.get("data-src") or img_tag.get("data-thumb") or img_tag.get("src")

            # Dapatkan durasi video
            duration_span = block.find("span", class_="duration")
            duration = duration_span.text.strip() if duration_span else "N/A"

            results.append({
                "id": str(video_id),
                "title": str(title),
                "url": str(url),
                "thumbnail": str(thumbnail) if thumbnail else None,
                "duration": str(duration),
                "tags": default_category or "XVideos",
                "rate": None,
                "views": None,
                "category": default_category
            })
        except Exception:
            continue

    return results


# ==============================================================================
# RESOLVER DNS ANTI-BLOKIR (DOH GOOGLE / CLOUDFLARE FALLBACK)
# ==============================================================================
DOH_CACHE: Dict[str, List[str]] = {
    "nekopoi.care": ["104.21.14.33", "172.67.157.174"],
    "roshy.tv": ["104.21.76.232", "172.67.202.18"]
}

class CustomDoHResolver(aiohttp.resolver.AbstractResolver):
    """
    Resolver DNS cerdas dengan dukungan DoH (DNS-over-HTTPS Google/Cloudflare).
    Memungkinkan bot mengakses nekopoi.care dan roshy.tv secara langsung tanpa
    terpengaruh DNS poisoning / pemblokiran ISP lokal di Indonesia maupun server production.
    """
    def __init__(self, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        self._default = aiohttp.resolver.ThreadedResolver(self._loop)

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> List[Dict[str, Any]]:
        # 1. Gunakan cache IP Cloudflare yang sudah terverifikasi jika tersedia
        if host in DOH_CACHE:
            return [{
                "hostname": host,
                "host": ip,
                "port": port,
                "family": family,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST
            } for ip in DOH_CACHE[host]]

        # 2. Coba resolver standar sistem
        try:
            return await self._default.resolve(host, port, family)
        except Exception:
            # 3. Fallback DoH Google jika DNS sistem diblokir / gagal
            try:
                doh_url = f"https://dns.google/resolve?name={host}&type=A"
                req = urllib.request.Request(doh_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode())
                    answers = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
                    if answers:
                        DOH_CACHE[host] = answers
                        return [{
                            "hostname": host,
                            "host": ip,
                            "port": port,
                            "family": family,
                            "proto": 0,
                            "flags": socket.AI_NUMERICHOST
                        } for ip in answers]
            except Exception:
                pass
            raise

    async def close(self) -> None:
        await self._default.close()


# ==============================================================================
# 5.1 SCRAPER KHUSUS NEKOPOI.CARE (HENTAI ANIME & MANGA)
# ==============================================================================
async def fetch_nekopoi_posts(session: aiohttp.ClientSession, query: Optional[str] = None, page: int = 1) -> List[Dict[str, Any]]:
    """
    Mengambil data konten Hentai Anime, 3D Hentai, dan Manga/Animasi dari nekopoi.care melalui REST API.
    Mendukung pencarian kata kunci maupun feed rilis terbaru.
    """
    try:
        if query:
            url = f"https://nekopoi.care/wp-json/wp/v2/posts?_embed=1&search={urllib.parse.quote_plus(query)}&page={page}&per_page=8"
        else:
            url = f"https://nekopoi.care/wp-json/wp/v2/posts?_embed=1&categories=2,81,682&page={page}&per_page=8"

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            posts = await resp.json()
            if not isinstance(posts, list):
                return []

            results = []
            for p in posts:
                post_id = p.get("id", "")
                raw_title = p.get("title", {}).get("rendered", "Hentai Video")
                title = html.unescape(raw_title).strip()
                link = p.get("link", "")

                # Ekstraksi featured poster image
                thumb = None
                media = p.get("_embedded", {}).get("wp:featuredmedia", [])
                if media and isinstance(media, list) and len(media) > 0:
                    thumb = media[0].get("source_url")

                # Ekstraksi sinopsis / deskripsi cerita
                content = p.get("content", {}).get("rendered", "")
                synopsis = ""
                m_syn = re.search(r'<b>Sinopsis</b>\s*</p>\s*<p[^>]*>(.*?)</p>', content, re.DOTALL | re.IGNORECASE)
                if m_syn:
                    synopsis = re.sub(r'<[^>]+>', '', m_syn.group(1)).strip()
                if not synopsis:
                    excerpt = p.get("excerpt", {}).get("rendered", "")
                    synopsis = re.sub(r'<[^>]+>', '', excerpt).strip()

                results.append({
                    "id": f"nekopoi-{post_id}",
                    "title": title,
                    "url": link,
                    "thumbnail": thumb,
                    "duration": "Full Episode",
                    "tags": "Anime Hentai, Sub Indo",
                    "description": synopsis[:240] if synopsis else None,
                    "category": "Hentai (Nekopoi Anime & Manga)",
                    "source": "nekopoi"
                })
            return results
    except Exception as e:
        logger.warning(f"Gagal mengambil feed dari Nekopoi: {e}")
        return []


# ==============================================================================
# 5.2 SCRAPER KHUSUS ROSHY.TV (DECENSORED JAV DENGAN SUBTITLE)
# ==============================================================================
async def fetch_roshy_videos(session: aiohttp.ClientSession, query: Optional[str] = None, page: int = 1) -> List[Dict[str, Any]]:
    """
    Mengambil data video JAV Tanpa Sensor (Decensored) dan Subtitle dari platform https://roshy.tv/.
    Mendukung pencarian Kode Nuklir JAV (misal: SSIS-878, ALDN-056, LULU-345) dan feed terbaru.
    """
    try:
        if query:
            url = f"https://roshy.tv/page/{page}/?s={urllib.parse.quote_plus(query)}" if page > 1 else f"https://roshy.tv/?s={urllib.parse.quote_plus(query)}"
        else:
            url = f"https://roshy.tv/page/{page}/" if page > 1 else "https://roshy.tv/"

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            html_text = await resp.text()
            soup = BeautifulSoup(html_text, "html.parser")
            results = []

            for post in soup.select(".post-item"):
                a_tag = post.select_one("a.blog-img-link") or post.select_one("h2 a") or post.select_one("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                href = a_tag.get("href")
                raw_title = a_tag.get("title") or (post.select_one("h2").text.strip() if post.select_one("h2") else a_tag.text.strip())
                title = html.unescape(raw_title).strip()

                img_tag = post.select_one("img")
                thumb = img_tag.get("data-src") or img_tag.get("src") if img_tag else None

                dur_tag = post.select_one(".beeteam368-bt-to-img") or post.select_one(".duration")
                dur = dur_tag.text.strip().replace("\n", " ") if dur_tag else "Full JAV"

                post_id = a_tag.get("data-post-id") or post.get("id", href)

                results.append({
                    "id": f"roshy-{post_id}",
                    "title": title,
                    "url": href,
                    "thumbnail": thumb,
                    "duration": dur,
                    "tags": "Decensored JAV, Eng Sub",
                    "description": None,
                    "category": "Jepang (JAV / Japanese)",
                    "source": "roshy"
                })
            return results
    except Exception as e:
        logger.warning(f"Gagal mengambil video dari Roshy.tv: {e}")
        return []


BLOCKED_FILEHOST_DOMAINS: Set[str] = {
    "k2s.cc", "keep2share", "uploadgig.com", "rapidgator.net",
    "filemoon", "kamehaus", "katfile", "mexashare", "nitroflare",
    "turbobit", "alfafile", "rosefile", "ddownload"
}

def is_valid_playable_video_url(url: Optional[str]) -> bool:
    """Memastikan URL benar-benar streaming video langsung (bukan web hosting / paywall filehost)."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False
    url_lower = url.lower()
    for blocked in BLOCKED_FILEHOST_DOMAINS:
        if blocked in url_lower:
            return False
    # Valid CDN streaming video asli (xvideos-cdn.com, eporner, dll)
    if "xvideos-cdn.com" in url_lower or "eporner" in url_lower:
        return True
    if any(ext in url_lower for ext in [".mp4", ".webm"]):
        # Hindari link web locker yang menyertakan ekstensi di path URL
        if not any(indicator in url_lower for indicator in ["/file/", "/download/", "drive.google", "mega.nz", "mediafire", "upload"]):
            return True
    return False


async def extract_direct_mp4_url(session: aiohttp.ClientSession, video_page_url: str, proxy: Optional[str] = None) -> Optional[str]:
    """Mengekstrak direct URL video .mp4 langsung yang 100% bisa di-play di Discord sebagai native player."""
    if not video_page_url or not video_page_url.startswith("http"):
        return None
    try:
        # 1. Jika halaman XVideos:
        if "xvideos.com" in video_page_url:
            async with session.get(video_page_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    html_text = await resp.text()
                    # Cek konfigurasi html5player XVideos
                    match = re.search(r"html5player\.setVideoUrlHigh\('([^']+)'\)", html_text)
                    if not match:
                        match = re.search(r"html5player\.setVideoUrlLow\('([^']+)'\)", html_text)
                    if match and is_valid_playable_video_url(match.group(1)):
                        return match.group(1)

                    # Cari URL mp4 CDN XVideos
                    for u in re.findall(r"https?://[^\s\"']+\.mp4[^\s\"']*", html_text):
                        if is_valid_playable_video_url(u) and "xvideos-cdn.com" in u:
                            return u

        # 2. Jika halaman Eporner
        elif "eporner.com" in video_page_url:
            async with session.get(video_page_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    html_text = await resp.text()
                    for u in re.findall(r"https?://[^\s\"']+\.mp4[^\s\"']*", html_text):
                        if is_valid_playable_video_url(u):
                            return u

        # 3. Halaman lain (selain filehost yang diblokir)
        elif not any(b in video_page_url.lower() for b in BLOCKED_FILEHOST_DOMAINS):
            async with session.get(video_page_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    html_text = await resp.text()
                    for u in re.findall(r"https?://[^\s\"']+\.mp4[^\s\"']*", html_text):
                        if is_valid_playable_video_url(u):
                            return u
    except Exception as e:
        logger.warning(f"Gagal mengekstrak direct mp4 dari {video_page_url}: {e}")
    return None


async def resolve_video_direct_mp4(
    session: aiohttp.ClientSession,
    video: Dict[str, Any],
    proxy: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """
    Menemukan direct MP4 streaming yang 100% playable di Discord beserta URL aksi untuk tombol interaktif.
    Mendukung integrasi Roshy.tv -> mencari stream kode JAV di XVideos agar video bisa diputar langsung di server Discord.
    Mengembalikan: (direct_mp4_url, action_button_url) atau None jika tidak ada stream video langsung.
    """
    if not video or not isinstance(video, dict):
        return None

    video_url = video.get("url") or ""
    video_title = video.get("title") or ""
    source = video.get("source") or ""

    # 1. Jika video dari Roshy.tv:
    if source == "roshy" or "roshy.tv" in video_url.lower():
        code = detect_jav_code(video_title)
        if code:
            try:
                # Cari kode nuklir JAV tersebut di XVideos
                xv_search_url = f"https://www.xvideos.com/?k={urllib.parse.quote_plus(code)}"
                async with session.get(xv_search_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        html_text = await resp.text()
                        xv_items = parse_xvideos_html(html_text)
                        target_xv_item = None
                        code_clean = code.upper().replace("-", "")
                        for it in xv_items:
                            it_title_clean = re.sub(r'[^A-Za-z0-9]', '', it.get("title", "").upper())
                            if code_clean in it_title_clean:
                                target_xv_item = it
                                break
                        if not target_xv_item and xv_items:
                            target_xv_item = xv_items[0]

                        if target_xv_item and target_xv_item.get("url"):
                            direct_mp4 = await extract_direct_mp4_url(session, target_xv_item["url"], proxy=proxy)
                            if direct_mp4 and is_valid_playable_video_url(direct_mp4):
                                return direct_mp4, video_url
            except Exception as e:
                logger.debug(f"Pencarian kode JAV XVideos untuk Roshy '{code}' gagal: {e}")
        return None

    # 2. Jika video dari XVideos / Eporner / lainnya:
    if video_url.startswith("http"):
        direct_mp4 = await extract_direct_mp4_url(session, video_url, proxy=proxy)
        if direct_mp4 and is_valid_playable_video_url(direct_mp4):
            return direct_mp4, video_url

    return None


def normalize_video_data(raw_item: Dict[str, Any], default_category: Optional[str] = None) -> Dict[str, Any]:
    """Menormalisasi data respons JSON API (mendukung Nekopoi, Roshy.tv, Eporner, Redtube, dan XVideos)."""
    item = raw_item.get("video") if isinstance(raw_item.get("video"), dict) else raw_item

    video_id = (
        item.get("id") or 
        item.get("video_id") or 
        item.get("slug") or 
        item.get("url")
    )

    title = (
        item.get("title") or 
        item.get("name") or 
        "Video Tanpa Judul"
    )

    url = (
        item.get("url") or 
        item.get("video_url") or 
        item.get("link") or 
        (f"https://www.eporner.com/video-{video_id}/" if video_id else "")
    )

    # Ekstraksi thumbnail (mendukung dict, thumb, default_thumb, poster)
    raw_thumb = item.get("default_thumb") or item.get("thumb") or item.get("thumbnail") or item.get("preview_image") or item.get("poster")
    thumbnail = None
    if isinstance(raw_thumb, dict):
        thumbnail = raw_thumb.get("src") or raw_thumb.get("url")
    elif isinstance(raw_thumb, str):
        thumbnail = raw_thumb

    # Ekstraksi durasi
    duration = item.get("length_min") or item.get("duration")
    if not duration and item.get("length_sec"):
        try:
            sec = int(item["length_sec"])
            duration = f"{sec // 60}:{sec % 60:02d}"
        except Exception:
            duration = "N/A"
    if not duration:
        duration = "N/A"

    # Ekstraksi tags / keywords (mendukung list of dicts Redtube atau string/list)
    raw_tags = item.get("keywords") or item.get("tags") or item.get("categories") or []
    if isinstance(raw_tags, str):
        tags_str = ", ".join([t.strip() for t in raw_tags.split(",")[:4]])
    elif isinstance(raw_tags, list):
        tag_list = []
        for t in raw_tags[:4]:
            if isinstance(t, dict):
                tag_list.append(t.get("tag_name") or t.get("name") or str(t))
            else:
                tag_list.append(str(t))
        tags_str = ", ".join(tag_list) if tag_list else "Umum"
    else:
        tags_str = "Umum"

    # Rating & Views
    rate = item.get("rate") or item.get("rating")
    views = item.get("views")

    return {
        "id": str(video_id) if video_id else None,
        "title": str(title),
        "url": str(url),
        "thumbnail": str(thumbnail) if thumbnail else None,
        "duration": str(duration),
        "tags": tags_str if tags_str else "Umum",
        "description": item.get("description"),
        "source": item.get("source"),
        "rate": str(rate) if rate else None,
        "views": f"{int(views):,}" if str(views).isdigit() else str(views) if views else None,
        "category": item.get("category") or default_category
    }


def create_video_embed(video: Dict[str, Any], category_info: Optional[Dict[str, Any]] = None, is_search: bool = False) -> discord.Embed:
    """Membuat Discord Embed yang terstruktur, menarik, sesuai kategori daerah dan berlabel 18+."""
    if category_info:
        embed_color = category_info["color"]
        category_name = f"{category_info['emoji']} {category_info['name']}"
    else:
        embed_color = discord.Color.from_rgb(220, 20, 60) if not is_search else discord.Color.from_rgb(255, 69, 0)
        category_name = "Umum / Campuran"

    # Jika tersedia sinopsis cerita (khususnya Nekopoi Anime/Manga), tampilkan secara estetik
    desc = video.get("description")
    if desc:
        desc_text = f"📖 *{desc}*\n\n[🔗 **Klik di sini untuk menonton / membaca**]({video['url']})"
    else:
        desc_text = f"[🔗 **Klik di sini untuk menonton**]({video['url']})" if video["url"] else "Tautan video tidak tersedia"

    embed = discord.Embed(
        title=f"🔞 {video['title'][:250]}",
        url=video["url"] if video["url"].startswith("http") else None,
        description=desc_text,
        color=embed_color,
        timestamp=datetime.now(timezone.utc)
    )

    # Set poster preview / thumbnail
    if video.get("thumbnail") and video["thumbnail"].startswith("http"):
        embed.set_image(url=video["thumbnail"])

    # Detail field
    embed.add_field(name="🌐 Wilayah / Genre", value=f"`{category_name}`", inline=True)
    embed.add_field(name="⏱️ Durasi", value=f"`{video.get('duration', 'N/A')}`", inline=True)
    embed.add_field(name="🏷️ Tag / Genre", value=f"`{video.get('tags', 'Umum')}`", inline=True)

    if video.get("rate"):
        embed.add_field(name="⭐ Rating", value=f"`{video['rate']}/5`", inline=True)
    if video.get("views"):
        embed.add_field(name="👁️ Ditonton", value=f"`{video['views']}` kali", inline=True)
    embed.add_field(name="⚠️ Batasan", value="`18+ (Dewasa)`", inline=True)

    # Footer penanda konten dewasa
    badge = "Pencarian Video" if is_search else "Auto-Update Berkala"
    embed.set_footer(text=f"🔞 Konten Dewasa 18+ • {category_name} • {badge}")

    return embed


# ==============================================================================
# DISCORD UI VIEW: TOMBOL INTERAKTIF TONTON VIDEO
# ==============================================================================
class VideoActionView(discord.ui.View):
    """Membuat tombol interaktif Discord yang bisa langsung diklik untuk menonton."""
    def __init__(self, video_url: str):
        super().__init__(timeout=None)
        if video_url and video_url.startswith("http"):
            if "nekopoi.care" in video_url:
                label = "🌸 Buka di Nekopoi"
                emoji = "🔞"
            elif "roshy.tv" in video_url:
                label = "▶️ Nonton di Roshy.tv"
                emoji = "🇯🇵"
            else:
                label = "▶️ Tonton Video"
                emoji = "🔞"

            self.add_item(discord.ui.Button(
                label=label,
                url=video_url,
                style=discord.ButtonStyle.link,
                emoji=emoji
            ))


# ==============================================================================
# 5. CUSTOM BOT CLIENT & MULTI-CHANNEL AUTO-UPDATE
# ==============================================================================
class MultiChannelAdultBot(commands.Bot):
    """Subclass Discord Bot untuk mengelola multi-channel background update dan lifecycle."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=["/", "!"],  # Mendukung awalan / (utama) dan ! (fallback)
            intents=intents,
            help_command=None
        )

        self.session: Optional[aiohttp.ClientSession] = None
        self.history = VideoHistoryManager(CACHE_FILE)

    async def setup_hook(self) -> None:
        """Inisialisasi sesi HTTP asinkron, sinkronisasi Slash Command, dan memulai task."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8"
        }
        if API_KEY:
            headers["Authorization"] = f"Bearer {API_KEY}"

        # Cek jika ada proxy di .env (misal: http://127.0.0.1:10809 atau socks5)
        proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
        timeout = aiohttp.ClientTimeout(total=25)
        resolver = CustomDoHResolver()
        connector = aiohttp.TCPConnector(resolver=resolver, ssl=False) if not proxy else aiohttp.TCPConnector(ssl=False)
        
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector
        )
        self.proxy = proxy
        if self.proxy:
            logger.info(f"Menggunakan Proxy untuk request API: {self.proxy}")
        logger.info("Sesi aiohttp.ClientSession berhasil dibuat (Didukung DoH Anti-Blokir).")

        # Sinkronisasi native Discord Slash Command (/)
        try:
            synced = await self.tree.sync()
            logger.info(f"Berhasil mensinkronisasi {len(synced)} Slash Command (/).")
        except Exception as e:
            logger.warning(f"Gagal sinkronisasi slash command: {e}")

        # Menjalankan background task berkala
        self.auto_update_all_channels.start()

    async def close(self) -> None:
        """Membersihkan koneksi saat bot ditutup."""
        if self.auto_update_all_channels.is_running():
            self.auto_update_all_channels.cancel()
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Sesi aiohttp.ClientSession ditutup.")
        await super().close()

    async def on_ready(self) -> None:
        logger.info(f"Bot berhasil online sebagai: {self.user} (ID: {self.user.id})")
        logger.info("Status Saluran:")
        for cat_key, cat in CATEGORIES.items():
            ch_id = cat["channel_id"]
            logger.info(f"  - [{cat['name']}]: Channel ID = {ch_id if ch_id else 'BELUM DIATUR'}")

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="4 Channel | Ketik /cari"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    # --------------------------------------------------------------------------
    # AUTO-UPDATE BACKGROUND TASK (Setiap 30 Menit ke 4 Channel)
    # --------------------------------------------------------------------------
    @tasks.loop(minutes=30)
    async def auto_update_all_channels(self) -> None:
        """Melakukan pengecekan berkala dan mengunggah video ke 4 channel sesuai kategorinya."""
        logger.info("=" * 60)
        logger.info("[Auto-Update] Memulai siklus auto-update ke 4 channel (Jepang, Hentai, Asia, Western)...")

        for cat_key, cat_info in CATEGORIES.items():
            channel_id = cat_info["channel_id"]
            cat_name = cat_info["name"]

            if not channel_id:
                logger.warning(f"[Auto-Update] Channel ID untuk '{cat_name}' belum dikonfigurasi di .env. Dilewati.")
                continue

            channel = self.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    logger.error(f"[Auto-Update] Gagal menemukan channel '{cat_name}' (ID: {channel_id}): {e}")
                    continue

            # Validasi keamanan channel NSFW
            if hasattr(channel, "is_nsfw") and not channel.is_nsfw():
                logger.warning(
                    f"[Auto-Update] PERINGATAN KEAMANAN: Channel #{channel.name} ({cat_name}) bukan NSFW! "
                    "Pastikan mengaktifkan opsi 'Age-Restricted Channel' di Discord."
                )

            # Proses pengambilan data dan upload untuk kategori ini
            await self._process_category_update(channel, cat_info)

            # Jeda waktu antar kategori agar tidak membebani network / rate limit
            await asyncio.sleep(3)

        logger.info("[Auto-Update] Siklus auto-update 4 channel selesai.")
        logger.info("=" * 60)

    async def _fetch_videos_with_fallback(self, primary_url: str, fallback_query: str, default_category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Mengambil data video dengan fallback otomatis (Mendukung XVideos Scraper, Redtube API, dan Eporner API)."""
        urls_to_try = [
            primary_url,
            f"https://www.xvideos.com/?k={fallback_query}",
            f"https://api.redtube.com/?data=redtube.Videos.searchVideos&output=json&search={fallback_query}"
        ]

        for target_url in urls_to_try:
            try:
                # 1. Jika URL adalah XVideos, ambil halaman HTML dan parse dengan BeautifulSoup
                if "xvideos.com" in target_url:
                    async with self.session.get(target_url, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=12)) as response:
                        if response.status == 200:
                            html_text = await response.text()
                            xv_videos = parse_xvideos_html(html_text, default_category=default_category)
                            if xv_videos:
                                return xv_videos
                    continue

                # 2. Jika API JSON biasa (Redtube / Eporner)
                async with self.session.get(target_url, proxy=self.proxy, timeout=aiohttp.ClientTimeout(total=12)) as response:
                    if response.status != 200:
                        continue
                    try:
                        payload = await response.json(content_type=None)
                    except Exception:
                        text_data = await response.text()
                        try:
                            payload = json.loads(text_data)
                        except Exception:
                            continue

                    raw_videos = []
                    if isinstance(payload, list):
                        raw_videos = payload
                    elif isinstance(payload, dict):
                        raw_videos = payload.get("videos") or payload.get("data") or payload.get("items") or []

                    if raw_videos:
                        return raw_videos
            except Exception:
                continue

        return []

    async def _process_category_update(self, channel: discord.abc.Messageable, cat_info: Dict[str, Any]) -> None:
        """Mengambil data video/manga terbaru dan bervariasi dari API untuk kategori tertentu dan mengirimkannya."""
        cat_key = cat_info["key"]
        cat_name = cat_info["name"]

        # ======================================================================
        # 1. KHUSUS KATEGORI HENTAI -> Diambil langsung dari Nekopoi.care
        # ======================================================================
        if cat_key == "hentai":
            page_num = random.randint(1, 4)
            use_sub_kw = random.choice([True, False])
            sub_query = random.choice(cat_info["keywords"]) if use_sub_kw else None

            logger.info(f"[Auto-Update] [{cat_name}] Mengambil rilis Nekopoi.care (Query: '{sub_query or 'Terbaru'}', Page: {page_num})...")
            try:
                raw_items = await fetch_nekopoi_posts(self.session, query=sub_query, page=page_num)
                if not raw_items and sub_query:
                    raw_items = await fetch_nekopoi_posts(self.session, query=None, page=1)

                if not raw_items:
                    logger.warning(f"[Auto-Update] [{cat_name}] Tidak ada konten ditemukan dari Nekopoi.")
                    return

                new_items = [it for it in raw_items if not self.history.is_seen(it)]
                if not new_items:
                    logger.info(f"[Auto-Update] [{cat_name}] Semua rilis Nekopoi pada batch ini sudah pernah diunggah.")
                    return

                count_to_send = min(3, len(new_items))
                items_to_send = random.sample(new_items, count_to_send)

                for item in items_to_send:
                    embed = create_video_embed(item, category_info=cat_info, is_search=False)
                    view = VideoActionView(item["url"])
                    try:
                        await channel.send(embed=embed, view=view)
                        self.history.mark_as_seen(item)
                        logger.info(f"[Auto-Update] [{cat_name}] Berhasil posting Nekopoi: {item['title'][:40]} (ID: {item['id']})")
                        await asyncio.sleep(2)
                    except discord.Forbidden:
                        logger.error(f"[Auto-Update] [{cat_name}] Tidak memiliki izin kirim pesan di channel #{channel.name}!")
                        break
                    except Exception as err:
                        logger.error(f"[Auto-Update] [{cat_name}] Gagal mengirim konten Nekopoi: {err}")
            except Exception as e:
                logger.error(f"[Auto-Update] [{cat_name}] Terjadi kesalahan pada feed Nekopoi: {e}", exc_info=True)
            return

        # ======================================================================
        # 2. KHUSUS KATEGORI JEPANG (JAV) -> Paduan dari XVideos & Roshy.tv
        # ======================================================================
        if cat_key == "jepang":
            sub_query = random.choice(cat_info["keywords"])
            sort_mode = random.choices(["uploaddate", "rating", "views"], weights=[0.80, 0.12, 0.08], k=1)[0]
            page_num = random.randint(0, 3)
            xv_dynamic_url = f"https://www.xvideos.com/?k={urllib.parse.quote_plus(sub_query)}&sort={sort_mode}&p={page_num}"
            logger.info(f"[Auto-Update] [{cat_name}] Mengambil feed kombinasi XVideos & Roshy.tv (Query: '{sub_query}')...")

            try:
                # Ambil paralel dari XVideos dan Roshy.tv
                xv_task = self._fetch_videos_with_fallback(xv_dynamic_url, sub_query, default_category=cat_name)
                roshy_task = fetch_roshy_videos(self.session, page=random.randint(1, 3))
                xv_res, roshy_res = await asyncio.gather(xv_task, roshy_task, return_exceptions=True)

                raw_videos = []
                if isinstance(xv_res, list):
                    raw_videos.extend(xv_res)
                if isinstance(roshy_res, list):
                    raw_videos.extend(roshy_res)

                if not raw_videos:
                    logger.warning(f"[Auto-Update] [{cat_name}] Tidak ada video ditemukan dari XVideos maupun Roshy.tv.")
                    return

                new_videos = []
                for raw_item in raw_videos:
                    item_data = normalize_video_data(raw_item, default_category=cat_info["name"])
                    if item_data.get("url") and not self.history.is_seen(item_data):
                        new_videos.append(item_data)

                if not new_videos:
                    logger.info(f"[Auto-Update] [{cat_name}] Semua video JAV pada query ini sudah pernah diunggah.")
                    return

                # Acak kandidat untuk variasi maksimal
                random.shuffle(new_videos)

                # Kumpulkan tepat hingga 3 video yang 100% playable (punya native video player)
                playable_posts: List[Tuple[Dict[str, Any], str, str]] = []
                for video in new_videos:
                    resolved = await resolve_video_direct_mp4(self.session, video, proxy=self.proxy)
                    if resolved:
                        direct_mp4, action_url = resolved
                        playable_posts.append((video, direct_mp4, action_url))
                        if len(playable_posts) >= 3:
                            break

                # Jika belum sampai 3 video player (misal video Roshy tidak ada di XVideos), ambil dari XVideos fresh
                if len(playable_posts) < 3:
                    for extra_p in range(1, 4):
                        extra_url = f"https://www.xvideos.com/?k={urllib.parse.quote_plus(sub_query)}&sort={sort_mode}&p={extra_p}"
                        extra_items = await self._fetch_videos_with_fallback(extra_url, sub_query, default_category=cat_name)
                        for raw_it in extra_items:
                            it_data = normalize_video_data(raw_it, default_category=cat_info["name"])
                            if it_data.get("url") and not self.history.is_seen(it_data):
                                if any(p[0]["id"] == it_data["id"] for p in playable_posts):
                                    continue
                                resolved = await resolve_video_direct_mp4(self.session, it_data, proxy=self.proxy)
                                if resolved:
                                    direct_mp4, action_url = resolved
                                    playable_posts.append((it_data, direct_mp4, action_url))
                                    if len(playable_posts) >= 3:
                                        break
                        if len(playable_posts) >= 3:
                            break

                if not playable_posts:
                    logger.warning(f"[Auto-Update] [{cat_name}] Tidak ada video dengan stream MP4 yang bisa diputar.")
                    return

                # Kirim semua video langsung sebagai native inline video player di Discord!
                for video, direct_mp4, action_url in playable_posts:
                    view = VideoActionView(action_url)
                    content = (
                        f"🔞 **{video['title']}**\n"
                        f"⏱️ `{video.get('duration', 'N/A')}` • 🌐 `{cat_name}`\n"
                        f"{direct_mp4}"
                    )
                    try:
                        await channel.send(content=content, view=view)
                        self.history.mark_as_seen(video)
                        logger.info(f"[Auto-Update] [{cat_name}] Berhasil posting video player JAV: {video['title'][:40]}")
                        await asyncio.sleep(2)
                    except discord.Forbidden:
                        logger.error(f"[Auto-Update] [{cat_name}] Tidak memiliki izin kirim pesan di channel #{channel.name}!")
                        break
                    except Exception as send_err:
                        logger.error(f"[Auto-Update] [{cat_name}] Gagal mengirim video JAV: {send_err}")
            except Exception as e:
                logger.error(f"[Auto-Update] [{cat_name}] Terjadi kesalahan saat update JAV: {e}", exc_info=True)
            return

        # ======================================================================
        # 3. KATEGORI ASIA & WESTERN (XVIDEOS / FALLBACK EPORNER)
        # ======================================================================
        sub_query = random.choice(cat_info["keywords"])
        sort_mode = random.choices(["uploaddate", "rating", "views"], weights=[0.80, 0.12, 0.08], k=1)[0]
        page_num = random.randint(0, 3)
        xv_dynamic_url = f"https://www.xvideos.com/?k={urllib.parse.quote_plus(sub_query)}&sort={sort_mode}&p={page_num}"
        logger.info(f"[Auto-Update] [{cat_name}] Mengambil feed segar (Query: '{sub_query}', Sort: {sort_mode}, Page: {page_num})...")

        try:
            raw_videos = await self._fetch_videos_with_fallback(xv_dynamic_url, sub_query, default_category=cat_name)
            if not raw_videos:
                logger.warning(f"[Auto-Update] [{cat_name}] Tidak ada video ditemukan dari API.")
                return

            # Filter video baru (deduplikasi ID, URL, dan slug judul agar tidak pernah mengirim video yang sama)
            new_videos = []
            for raw_item in raw_videos:
                item_data = normalize_video_data(raw_item, default_category=cat_info["name"])
                if item_data.get("url") and not self.history.is_seen(item_data):
                    new_videos.append(item_data)

            if not new_videos:
                logger.info(f"[Auto-Update] [{cat_name}] Semua video pada query ini sudah pernah diunggah. Mencari variasi berikutnya...")
                return

            random.shuffle(new_videos)

            # Kumpulkan hingga 3 video yang 100% playable
            playable_posts: List[Tuple[Dict[str, Any], str, str]] = []
            for video in new_videos:
                resolved = await resolve_video_direct_mp4(self.session, video, proxy=self.proxy)
                if resolved:
                    direct_mp4, action_url = resolved
                    playable_posts.append((video, direct_mp4, action_url))
                    if len(playable_posts) >= 3:
                        break

            # Jika kurang dari 3, ambil halaman tambahan
            if len(playable_posts) < 3:
                for extra_p in range(1, 4):
                    extra_url = f"https://www.xvideos.com/?k={urllib.parse.quote_plus(sub_query)}&sort={sort_mode}&p={extra_p}"
                    extra_items = await self._fetch_videos_with_fallback(extra_url, sub_query, default_category=cat_name)
                    for raw_it in extra_items:
                        it_data = normalize_video_data(raw_it, default_category=cat_info["name"])
                        if it_data.get("url") and not self.history.is_seen(it_data):
                            if any(p[0]["id"] == it_data["id"] for p in playable_posts):
                                continue
                            resolved = await resolve_video_direct_mp4(self.session, it_data, proxy=self.proxy)
                            if resolved:
                                direct_mp4, action_url = resolved
                                playable_posts.append((it_data, direct_mp4, action_url))
                                if len(playable_posts) >= 3:
                                    break
                    if len(playable_posts) >= 3:
                        break

            if not playable_posts:
                logger.warning(f"[Auto-Update] [{cat_name}] Tidak ada video dengan stream MP4 yang bisa diputar.")
                return

            logger.info(f"[Auto-Update] [{cat_name}] Mengunggah {len(playable_posts)} video player langsung ke #{channel.name}...")

            for video, direct_mp4, action_url in playable_posts:
                view = VideoActionView(action_url)
                content = (
                    f"🔞 **{video['title']}**\n"
                    f"⏱️ `{video.get('duration', 'N/A')}` • 🌐 `{cat_name}`\n"
                    f"{direct_mp4}"
                )
                try:
                    await channel.send(content=content, view=view)
                    self.history.mark_as_seen(video)
                    logger.info(f"[Auto-Update] [{cat_name}] Berhasil posting video: {video['title'][:40]} (ID: {video['id']})")
                    await asyncio.sleep(2)  # Delay rate limit Discord
                except discord.Forbidden:
                    logger.error(f"[Auto-Update] [{cat_name}] Tidak memiliki izin kirim pesan di channel #{channel.name}!")
                    break
                except Exception as send_err:
                    logger.error(f"[Auto-Update] [{cat_name}] Gagal mengirim video: {send_err}")

        except asyncio.CancelledError:
            logger.info(f"[Auto-Update] [{cat_name}] Task dibatalkan.")
        except Exception as e:
            logger.error(f"[Auto-Update] [{cat_name}] Terjadi kesalahan saat memproses update: {e}", exc_info=True)

    @auto_update_all_channels.before_loop
    async def before_auto_update_all_channels(self) -> None:
        """Tunggu hingga bot selesai inisialisasi login sebelum menjalankan task."""
        await self.wait_until_ready()
        logger.info("[Auto-Update] Bot siap, loop berkala multi-channel diaktifkan.")


# Inisialisasi Instance Bot
bot = MultiChannelAdultBot()


# ==============================================================================
# ==============================================================================
# 7. PERINTAH INTERAKTIF PENCARIAN (/cari [kata_kunci])
# ==============================================================================
# 7. PERINTAH INTERAKTIF PENCARIAN (/cari)
# ==============================================================================
@bot.hybrid_command(
    name="cari",
    aliases=["search", "find"],
    description="Cari video sesuai kata kunci, kode nuklir JAV, durasi, dan kategori"
)
@discord.app_commands.describe(
    durasi="Filter durasi video (opsional: jam-jaman, 20+ min, 10-20 min, 3-10 min)",
    kategori="Pilihan kategori video (opsional: otomatis sesuai channel aktif)",
    keyword="Kata kunci pencarian atau Kode Nuklir JAV (contoh: perawat, SSIS-878, ALDN-056)"
)
@discord.app_commands.choices(
    durasi=[
        discord.app_commands.Choice(name="⏳ Semua Durasi", value="all"),
        discord.app_commands.Choice(name="🎬 Jam-jaman / Film Panjang (20m+ Sort Durasi)", value="hours"),
        discord.app_commands.Choice(name="⌛ Panjang (20+ Menit)", value="20min_more"),
        discord.app_commands.Choice(name="⏱️ Sedang (10 - 20 Menit)", value="10-20min"),
        discord.app_commands.Choice(name="⚡ Pendek (3 - 10 Menit)", value="3-10min"),
        discord.app_commands.Choice(name="⚡ Sangat Singkat (1 - 3 Menit)", value="1-3min"),
    ],
    kategori=[
        discord.app_commands.Choice(name="🔄 Otomatis (Sesuai Channel)", value="auto"),
        discord.app_commands.Choice(name="🇯🇵 Jepang (JAV & Roshy.tv)", value="jepang"),
        discord.app_commands.Choice(name="🌸 Hentai (Nekopoi Anime & Manga)", value="hentai"),
        discord.app_commands.Choice(name="🌏 Asia (Non-Jepang)", value="asia"),
        discord.app_commands.Choice(name="🌍 Western (Barat)", value="western"),
        discord.app_commands.Choice(name="🌐 Semua Kategori (Bebas)", value="semua"),
    ]
)
async def cari_video(
    ctx: commands.Context,
    durasi: Optional[str] = None,
    kategori: Optional[str] = None,
    *,
    keyword: Optional[str] = None
) -> None:
    """Perintah pencarian video. Mendukung kata kunci, kode nuklir JAV, filter durasi, dan kategori."""
    # 1. Panggil defer() segera di baris pertama agar Discord interaksi tidak pernah timeout 3 detik
    await ctx.defer()

    # 2. Validasi Keamanan: Wajib berada di Channel NSFW
    is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
    if not is_nsfw:
        warning_embed = discord.Embed(
            title="⛔ Akses Ditolak (NSFW Only)",
            description=(
                "Perintah ini hanya dapat dijalankan di channel yang berstatus **NSFW (Age-Restricted)**!\n\n"
                "Sesuai aturan Discord Community Guidelines dan Terms of Service, konten 18+ tidak boleh "
                "ditampilkan di channel non-dewasa.\n\n"
                "👉 *Silakan gunakan perintah ini di channel NSFW: **Jepang**, **Hentai**, **Asia**, atau **Western**.*"
            ),
            color=discord.Color.red()
        )
        warning_embed.set_footer(text="Discord Safety & Age-Restricted Policy")
        await ctx.send(embed=warning_embed)
        return

    # 3. Parsing parameter fleksibel (Slash command choices, input keyword, kode nuklir, dan durasi)
    combined_kw, dur_val, cat_val, detected_code = resolve_search_parameters(durasi, kategori, keyword)

    # Deteksi channel aktif
    channel_name = getattr(ctx.channel, "name", "channel")
    channel_category = None
    for cat_key, cat_data in CATEGORIES.items():
        if cat_data["channel_id"] == ctx.channel.id:
            channel_category = cat_data
            break

    # Jika keyword kosong dan ada durasi di channel tertentu, gunakan default genre channel
    if not combined_kw and not detected_code:
        if channel_category and dur_val:
            combined_kw = channel_category["keywords"][0]
        else:
            help_embed = discord.Embed(
                title="ℹ️ Cara Menggunakan Perintah /cari",
                description=(
                    "Ketik apa yang ingin Anda cari langsung di channel ini atau gunakan opsi filter!\n\n"
                    "**1. Cari Biasa:** `/cari keyword: perawat` *(otomatis sesuai channel)*\n"
                    "**2. Cari Anime/Manga Hentai:** `/cari keyword: overflow` atau `/cari keyword: kangoku` *(Nekopoi)*\n"
                    "**3. Cari Kode Nuklir JAV:** `/cari keyword: SSIS-878` atau `/cari keyword: ALDN-056` *(Roshy.tv & XVideos)*\n"
                    "**4. Filter Durasi:** `/cari durasi: Jam-jaman keyword: perawat` atau `/cari keyword: perawat 20 menit`\n"
                    "**5. Pilih Kategori:** `/cari kategori: Hentai keyword: cosplay`\n\n"
                    f"💡 *Genre Channel Saat Ini:* **{channel_category['name'] if channel_category else 'Bebas / Umum'}**"
                ),
                color=discord.Color.gold()
            )
            await ctx.send(embed=help_embed)
            return

    # 4. Tentukan kategori akhir
    current_category = None
    if cat_val and cat_val not in ["auto", "semua"]:
        current_category = CATEGORIES.get(cat_val)
    elif cat_val == "semua":
        current_category = None
    elif detected_code:
        # Jika terdeteksi Kode Nuklir JAV (misal SSIS-878, ALDN-056), otomatis jadikan kategori Jepang (JAV)
        current_category = CATEGORIES["jepang"]
    elif channel_category:
        current_category = channel_category
    else:
        # Cek nama channel
        ch_lower = channel_name.lower()
        if "hentai" in ch_lower or "nekopoi" in ch_lower:
            current_category = CATEGORIES["hentai"]
        elif "jav" in ch_lower or "jepang" in ch_lower:
            current_category = CATEGORIES["jepang"]
        elif "asia" in ch_lower:
            current_category = CATEGORIES["asia"]
        elif "western" in ch_lower or "barat" in ch_lower:
            current_category = CATEGORIES["western"]
        elif combined_kw:
            kw_lower = combined_kw.lower()
            if any(w in kw_lower for w in ["hentai", "anime", "manga", "nekopoi"]):
                current_category = CATEGORIES["hentai"]
            elif any(w in kw_lower for w in ["jepang", "jav"]):
                current_category = CATEGORIES["jepang"]
            elif any(w in kw_lower for w in ["barat", "bule", "western"]):
                current_category = CATEGORIES["western"]
            elif any(w in kw_lower for w in ["asia", "indo", "korea", "cina", "china"]):
                current_category = CATEGORIES["asia"]

    # ==========================================================================
    # KHUSUS KATEGORI HENTAI -> Cari langsung di Nekopoi.care (Anime, Manga, 3D)
    # ==========================================================================
    if current_category and current_category["key"] == "hentai":
        logger.info(f"User {ctx.author} mencari Hentai '{combined_kw}' di Nekopoi.care")
        try:
            neko_raw = await fetch_nekopoi_posts(bot.session, query=combined_kw, page=1)
            if len(neko_raw) < 3:
                more = await fetch_nekopoi_posts(bot.session, query=combined_kw, page=2)
                neko_raw.extend(more)

            fresh_results = [it for it in neko_raw if not bot.history.is_seen(it)]
            candidates = fresh_results[:3] if fresh_results else neko_raw[:3]

            if not candidates:
                embed_empty = discord.Embed(
                    title="🔍 Tidak Ada Konten Baru di Nekopoi",
                    description=f"Semua konten Hentai di Nekopoi dengan kata kunci **{combined_kw}** sudah pernah di-drop di server.",
                    color=discord.Color.from_rgb(255, 105, 180)
                )
                await ctx.send(embed=embed_empty)
                return

            for idx, item in enumerate(candidates):
                embed = create_video_embed(item, category_info=current_category, is_search=True)
                view = VideoActionView(item["url"])
                await ctx.send(embed=embed, view=view)
                bot.history.mark_as_seen(item)
                if idx < len(candidates) - 1:
                    await asyncio.sleep(1)
            return
        except Exception as neko_err:
            logger.error(f"Pencarian Nekopoi error: {neko_err}", exc_info=True)
            await ctx.send("⚠️ Terjadi gangguan saat mengambil data dari Nekopoi.care.")
            return

    # 5. Bentuk kata kunci pencarian (Untuk Kategori JAV, Asia, Western)
    if detected_code:
        query_str = combined_kw
        en_query = combined_kw
    else:
        en_query = translate_indonesian_query(combined_kw)
        if current_category:
            cat_prefix = current_category["keywords"][0]
            if cat_prefix not in en_query:
                query_str = f"{cat_prefix} {en_query}"
            else:
                query_str = en_query
        else:
            query_str = en_query

    dur_info = DURATION_LABELS.get(dur_val, dur_val) if dur_val else "Semua"
    logger.info(
        f"User {ctx.author} mencari '{combined_kw}' (Tag: '{en_query}', Final: '{query_str}', "
        f"Kode Nuklir: {detected_code or 'Tidak'}, Durasi: {dur_info}, Kategori: {current_category['name'] if current_category else 'Bebas'}) di #{channel_name}"
    )

    try:
        raw_results = []
        exact_code_matches = []

        # ======================================================================
        # PENCARIAN KATEGORI JEPANG (JAV) -> Paduan XVideos & Roshy.tv
        # ======================================================================
        if current_category and current_category["key"] == "jepang":
            # Siapkan parameter XVideos
            xv_params: Dict[str, str] = {"k": query_str}
            if dur_val == "hours":
                xv_params["durf"] = "20min_more"
                xv_params["sort"] = "length"
            elif dur_val and dur_val in ["20min_more", "10-20min", "3-10min", "1-3min"]:
                xv_params["durf"] = dur_val

            async def search_xv():
                try:
                    async with bot.session.get("https://www.xvideos.com/", params=xv_params, proxy=bot.proxy, timeout=aiohttp.ClientTimeout(total=8)) as xv_resp:
                        if xv_resp.status == 200:
                            xv_html = await xv_resp.text()
                            return parse_xvideos_html(xv_html, default_category=current_category["name"])
                except Exception as e:
                    logger.info(f"Pencarian XVideos JAV gagal: {e}")
                return []

            async def search_roshy():
                try:
                    roshy_q = detected_code or combined_kw
                    return await fetch_roshy_videos(bot.session, query=roshy_q)
                except Exception as e:
                    logger.info(f"Pencarian Roshy.tv JAV gagal: {e}")
                return []

            # Eksekusi paralel XVideos & Roshy.tv
            xv_res, roshy_res = await asyncio.gather(search_xv(), search_roshy(), return_exceptions=True)
            if isinstance(xv_res, list):
                raw_results.extend(xv_res)
            if isinstance(roshy_res, list):
                raw_results.extend(roshy_res)

        else:
            # Kategori Asia, Western, atau Umum
            xv_params: Dict[str, str] = {"k": query_str}
            if dur_val == "hours":
                xv_params["durf"] = "20min_more"
                xv_params["sort"] = "length"
            elif dur_val and dur_val in ["20min_more", "10-20min", "3-10min", "1-3min"]:
                xv_params["durf"] = dur_val

            try:
                async with bot.session.get("https://www.xvideos.com/", params=xv_params, proxy=bot.proxy, timeout=aiohttp.ClientTimeout(total=8)) as xv_resp:
                    if xv_resp.status == 200:
                        xv_html = await xv_resp.text()
                        xv_results = parse_xvideos_html(xv_html, default_category=current_category["name"] if current_category else None)
                        if xv_results:
                            raw_results = xv_results
            except Exception as xv_err:
                logger.info(f"Pencarian XVideos gagal/timeout: {xv_err}")

        # Jika mencari Kode Nuklir JAV, prioritaskan video yang judulnya memuat kode tersebut
        if detected_code and raw_results:
            code_upper = detected_code.upper()
            code_no_dash = code_upper.replace("-", "")
            code_space = code_upper.replace("-", " ")
            other_matches = []
            for item in raw_results:
                t_upper = (item.get("title") or "").upper()
                if code_upper in t_upper or code_no_dash in t_upper or code_space in t_upper:
                    exact_code_matches.append(item)
                else:
                    other_matches.append(item)
            if exact_code_matches:
                raw_results = exact_code_matches + other_matches

        # Fallback ke Redtube jika hasil kosong dan bukan kode spesifik
        if not raw_results and not detected_code:
            try:
                fallback_url = "https://api.redtube.com/"
                fallback_params = {
                    "data": "redtube.Videos.searchVideos",
                    "output": "json",
                    "search": query_str,
                    "thumbsize": "big"
                }
                async with bot.session.get(fallback_url, params=fallback_params, proxy=bot.proxy, timeout=aiohttp.ClientTimeout(total=8)) as fb_resp:
                    if fb_resp.status == 200:
                        fb_payload = json.loads(await fb_resp.text())
                        if isinstance(fb_payload, dict):
                            raw_results = fb_payload.get("videos") or []
            except Exception as fb_err:
                logger.error(f"Fallback search API gagal: {fb_err}")

        # Filter video yang belum pernah di-drop di server
        fresh_results = [item for item in raw_results if not bot.history.is_seen(item)]

        # Jika fresh_results kurang dari 3 dan bukan pencarian kode nuklir spesifik, ambil halaman tambahan (p=1)
        if len(fresh_results) < 3 and not detected_code and "xv_params" in locals():
            try:
                p1_params = dict(xv_params)
                p1_params["p"] = "1"
                async with bot.session.get("https://www.xvideos.com/", params=p1_params, proxy=bot.proxy, timeout=aiohttp.ClientTimeout(total=8)) as p1_resp:
                    if p1_resp.status == 200:
                        p1_items = parse_xvideos_html(await p1_resp.text(), default_category=current_category["name"] if current_category else None)
                        for it in p1_items:
                            if not bot.history.is_seen(it) and it not in fresh_results:
                                fresh_results.append(it)
            except Exception as p1_err:
                logger.info(f"Pencarian XVideos p=1 gagal/timeout: {p1_err}")

        # Tentukan kandidat video yang akan dikirim (prioritaskan video segar yang belum pernah di-drop)
        if fresh_results:
            candidates = fresh_results[:6]
        elif detected_code:
            # Khusus pencarian kode nuklir yang spesifik, izinkan hasil pencarian jika tidak ada varian lain
            candidates = raw_results[:6]
        else:
            candidates = []

        if not candidates:
            not_found_desc = f"Semua video dengan kata kunci **{combined_kw}** sudah pernah di-drop di server ini."
            if dur_val and dur_val in DURATION_LABELS:
                not_found_desc += f"\nFilter Durasi aktif: `{DURATION_LABELS[dur_val]}`. Coba ganti ke durasi atau kata kunci lain."

            not_found_embed = discord.Embed(
                title="🔍 Tidak Ada Video Baru",
                description=not_found_desc,
                color=discord.Color.dark_gray()
            )
            await ctx.send(embed=not_found_embed)
            return

        # Normalisasi kandidat video
        normalized_candidates = [
            normalize_video_data(it, default_category=current_category["name"] if current_category else None)
            for it in candidates
        ]

        # Ekstraksi Direct MP4 stream secara paralel untuk semua kandidat (mendukung resolusi kode JAV Roshy -> XVideos)
        resolved_results = await asyncio.gather(
            *(resolve_video_direct_mp4(bot.session, v, proxy=bot.proxy) for v in normalized_candidates)
        )

        # Prioritaskan video yang memiliki stream direct MP4 playable langsung di Discord
        playable_results = []
        fallback_results = []
        for v, res in zip(normalized_candidates, resolved_results):
            if res:
                playable_results.append((v, res[0], res[1]))
            else:
                fallback_results.append((v, None, v["url"]))

        # Pilih hingga 3 video terbaik untuk dikirim (utamakan yang punya video player)
        selected_to_send = (playable_results + fallback_results)[:3]

        # Kirim SEMUA video langsung sebagai Player Video (Inline Playable Video) atau Embed interaktif
        for idx, (video, direct_mp4, action_url) in enumerate(selected_to_send):
            is_exact_code = bool(detected_code and (exact_code_matches or detected_code.upper() in video["title"].upper()))
            header_badge = f"🎬 **[KODE NUKLIR: {detected_code}]** " if is_exact_code else ""

            lines = [
                f"🔞 {header_badge}**{video['title']}**",
                f"⏱️ `{video.get('duration', 'N/A')}` • 🌐 `{current_category['name'] if current_category else 'Bebas'}`"
            ]

            if idx == 0:
                if detected_code:
                    match_note = " *(Judul Cocok Persis)*" if exact_code_matches else ""
                    lines.append(f"🏷️ **Kode Nuklir:** `{detected_code}`{match_note}")
                elif en_query != combined_kw.lower():
                    lines.append(f"🔍 **Kata Kunci:** `{combined_kw}` (Tag: `{en_query}`)")
                if dur_val and dur_val in DURATION_LABELS:
                    lines.append(f"⏳ **Filter Durasi:** `{DURATION_LABELS[dur_val]}`")

            view = VideoActionView(action_url)

            if direct_mp4:
                lines.append(direct_mp4)
                await ctx.send(content="\n".join(lines), view=view)
            else:
                embed = create_video_embed(video, category_info=current_category, is_search=True)
                await ctx.send(embed=embed, view=view)

            # Tandai video ini sebagai sudah pernah di-drop di server agar tidak pernah di-upload ulang
            bot.history.mark_as_seen(video)

            # Jeda waktu singkat jika mengirim beberapa video agar Discord merender player secara teratur
            if idx < len(selected_to_send) - 1:
                await asyncio.sleep(1)

    except asyncio.TimeoutError:
        await ctx.send("⏱️ Permintaan ke API melebihi batas waktu (Timeout). Silakan periksa koneksi internet.")
    except Exception as e:
        logger.error(f"Error pada perintah /cari: {e}", exc_info=True)
        await ctx.send("⚠️ Terjadi kesalahan internal saat mencari video.")


# ==============================================================================
# 7. PERINTAH BANTUAN STATUS CHANNEL (/status)
# ==============================================================================
@bot.hybrid_command(
    name="status",
    aliases=["info"],
    description="Cek status dan koneksi 4 channel kategori bot (Jepang, Hentai, Asia, Western)"
)
async def status_channel(ctx: commands.Context) -> None:
    """Mengecek status dan ID keempat channel yang terhubung ke bot."""
    await ctx.defer()

    is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
    if not is_nsfw:
        await ctx.send("⛔ Perintah ini hanya bisa dicek di channel NSFW.")
        return

    embed = discord.Embed(
        title="📊 Status Konfigurasi Channel Kategori",
        description="Berikut adalah status keempat channel yang terdaftar pada sistem Auto-Update:",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )

    for cat_key, cat in CATEGORIES.items():
        ch_id = cat["channel_id"]
        ch_obj = bot.get_channel(ch_id) if ch_id else None
        
        status_str = f"✅ Terhubung ke #{ch_obj.name}" if ch_obj else ("⚠️ ID Belum Terdaftar" if not ch_id else f"❌ Channel `{ch_id}` Tidak Ditemukan")
        nsfw_str = " (NSFW: Ya)" if ch_obj and getattr(ch_obj, "is_nsfw", lambda: False)() else " (NSFW: ⚠️ Belum Diaktifkan!)" if ch_obj else ""
        
        embed.add_field(
            name=f"{cat['emoji']} {cat['name']}",
            value=f"• ID: `{ch_id if ch_id else 'None'}`\n• Status: {status_str}{nsfw_str}",
            inline=False
        )

    embed.set_footer(text="Auto-Update Interval: Setiap 30 Menit")
    await ctx.send(embed=embed)


# ==============================================================================
# 8. SISTEM PUSAT PANDUAN INTERAKTIF (/help /panduan)
# ==============================================================================
def build_help_home_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔞 Pusat Panduan Sugiono Bot",
        description=(
            "**Prefix:** `/` atau `!` (Dukung juga **Slash Command `/`**)\n"
            "────────────────────────────────────────"
        ),
        color=discord.Color.from_rgb(255, 75, 145),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="🎣 Perintah Dasar Cepat:",
        value=(
            "• `/cari [kata_kunci / kode_nuklir]` — Cari video & anime instan, dukung kode JAV (SSIS, ALDN), Hentai Nekopoi & filter durasi\n"
            "• `/status` — Cek status koneksi 4 channel kategori & verifikasi status NSFW\n"
            "• `/help` — Menampilkan pusat panduan interaktif ini"
        ),
        inline=False
    )

    embed.add_field(
        name="📺 4 Saluran Video & Anime (Auto-Update Setiap 30 Menit):",
        value=(
            "• 🇯🇵 **Channel Jepang (`#jav`)** — Feed JAV terbaru dari **XVideos & Roshy.tv (Decensored Subtitle)**\n"
            "• 🌸 **Channel Hentai (`#hentai`)** — Feed anime, 3D hentai & manga terbaru dari **Nekopoi.care**\n"
            "• 🌏 **Channel Asia (`#asia`)** — Feed video Asia Non-Jepang *(Korea, Indo, China, Thai)*\n"
            "• 🌍 **Channel Western (`#western`)** — Feed video Western / Barat / Caucasian"
        ),
        inline=False
    )

    embed.add_field(
        name="🎬 Contoh Pencarian & Kode Nuklir JAV:",
        value=(
            "• `/cari keyword: SSIS-878` — Mencari judul video yang cocok dengan Kode Nuklir JAV\n"
            "• `/cari keyword: ALDN-056` — Deteksi kode otomatis & langsung siap diputar di Discord\n"
            "• `/cari perawat jam-jaman` — Mencari film JAV berdurasi panjang jam-jaman (20m+ sort panjang)\n"
            "• `/cari tante 10-20 menit` — Mencari video dengan rentang durasi sedang 10-20 menit\n"
            "• `/cari bule pirang` — Diterjemahkan otomatis ke tag `western blonde`"
        ),
        inline=False
    )

    embed.add_field(
        name="✨ Keunggulan Sugiono Bot:",
        value=(
            "• 🎬 **Native Video Player** — Video langsung diputar di Discord (ada tombol Play di tengah)\n"
            "• 🏷️ **Kode Nuklir JAV** — Cari langsung video berdasar kode resmi (SSIS, ALDN, FC2-PPV, IPX)\n"
            "• ⏳ **Filter Durasi Lengkap** — Mulai dari klip pendek (1-10m) hingga film utuh jam-jaman\n"
            "• ⚡ **Zero-Timeout** — Respon interaksi instan < 0.1 detik, tanpa timeout interaksi Discord\n"
            "• 🔞 **Age-Restricted Safe** — Wajib channel NSFW sesuai ketentuan Discord"
        ),
        inline=False
    )

    embed.set_footer(text="Sugiono Bot • Multi-Channel Adult Video Engine | Auto-Update: Tiap 30 Menit")
    return embed


def build_help_perintah_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔍 Panduan Perintah & Cara Mencari Video",
        description=(
            "Sugiono Bot dirancang fleksibel: bisa otomatis mengikuti genre channel atau memilih manual!\n"
            "────────────────────────────────────────"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="📌 1. Perintah `/cari` Lengkap:",
        value=(
            "Mencari video & anime dewasa secara instan dengan opsi fleksibel:\n"
            "• **Keyword / Kode Nuklir JAV:** `/cari keyword: perawat` atau `/cari keyword: SSIS-878` *(XVideos & Roshy.tv)*\n"
            "• **Anime & Manga Hentai:** `/cari keyword: overflow` atau `/cari keyword: kangoku` *(Nekopoi.care)*\n"
            "• **Filter Durasi:** `/cari durasi: Jam-jaman keyword: perawat` atau `/cari keyword: perawat 20 menit`\n"
            "• **Pilihan Kategori:** `/cari kategori: Hentai (Nekopoi)` atau `/cari kategori: Jepang (JAV)`\n\n"
            "👉 *Otomatis muncul sebagai Player Video atau Card Lengkap dengan tombol tonton!*"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 2. Perintah `/status`",
        value=(
            "Menampilkan status keempat channel kategori yang terhubung ke bot (Jepang, Hentai, Asia, Western):\n"
            "• Memeriksa apakah Channel ID terdaftar di file `.env`.\n"
            "• Memverifikasi apakah toggle **Age-Restricted (NSFW)** sudah aktif."
        ),
        inline=False
    )

    embed.set_footer(text="Gunakan dropdown di bawah untuk beralih halaman panduan.")
    return embed


def build_help_nuklir_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎬 Panduan Kode Nuklir JAV & Filter Durasi",
        description=(
            "Fitur canggih Sugiono Bot untuk mencari video berdasarkan **Kode Nuklir (Production Code JAV)** "
            "dan memfilter berdasarkan **Durasi Video** (mulai dari klip singkat hingga film utuh jam-jaman).\n"
            "────────────────────────────────────────"
        ),
        color=discord.Color.from_rgb(255, 20, 147),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="🏷️ 1. Pencarian Kode Nuklir JAV:",
        value=(
            "Setiap judul video JAV resmi memiliki kode produksi unik. Cukup ketik kodenya di `/cari`:\n"
            "• `/cari keyword: SSIS-878`\n"
            "• `/cari keyword: ALDN-056`\n"
            "• `/cari keyword: FC2-PPV-3124567`\n"
            "• `/cari keyword: IPX-534`\n"
            "• `/cari keyword: MIDE-523`\n\n"
            "👉 *Bot akan langsung mencocokkan video yang judulnya memuat kode tersebut di platform dan merendernya sebagai Video Player yang siap diputar!*"
        ),
        inline=False
    )

    embed.add_field(
        name="⏳ 2. Filter Durasi Video (Pendek hingga Jam-jaman):",
        value=(
            "Gunakan dropdown `durasi` pada Slash Command atau ketik langsung di kata kunci:\n"
            "• 🎬 **Jam-jaman (20m+ Sort Durasi)**: `/cari durasi: Jam-jaman` atau `/cari perawat jam-jaman` (menampilkan film berdurasi hingga 2-4 jam)\n"
            "• ⌛ **Panjang (20+ Menit)**: `/cari durasi: Panjang` atau `/cari perawat 20 menit`\n"
            "• ⏱️ **Sedang (10 - 20 Menit)**: `/cari durasi: Sedang` atau `/cari tante 10-20 menit`\n"
            "• ⚡ **Pendek (3 - 10 Menit)**: `/cari durasi: Pendek` atau `/cari siswi durasi pendek`\n"
            "• ⚡ **Sangat Singkat (1 - 3 Menit)**: `/cari durasi: Sangat Singkat` (preview/teaser)"
        ),
        inline=False
    )

    embed.add_field(
        name="🌐 3. Pilihan Kategori Fleksibel:",
        value=(
            "• **Otomatis (Default)**: Otomatis mengikuti channel aktif (`#jav` $\\rightarrow$ Jepang, `#asia` $\\rightarrow$ Asia, `#western` $\\rightarrow$ Barat).\n"
            "• **Pilihan Manual**: Bebas memilih genre video lain melalui dropdown `kategori:` tanpa harus berpindah channel."
        ),
        inline=False
    )

    embed.set_footer(text="Gunakan dropdown di bawah untuk beralih halaman panduan.")
    return embed


def build_help_kamus_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🏷️ Kamus Tag Bahasa Indonesia Sugiono",
        description=(
            "Sugiono Bot dilengkapi kamus cerdas yang otomatis menerjemahkan istilah sehari-hari bahasa Indonesia ke tag pencarian optimal XVideos:\n"
            "────────────────────────────────────────"
        ),
        color=discord.Color.from_rgb(255, 140, 0),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="👩 Karakter & Peran:",
        value=(
            "• `tante` / `stw` $\\rightarrow$ `milf`\n"
            "• `ibu tiri` / `mama tiri` $\\rightarrow$ `stepmom`\n"
            "• `anak sekolah` / `siswi` $\\rightarrow$ `schoolgirl`\n"
            "• `perawat` / `suster` $\\rightarrow$ `nurse`\n"
            "• `guru` / `dosen` $\\rightarrow$ `teacher`\n"
            "• `pelayan` / `pembantu` $\\rightarrow$ `maid`\n"
            "• `remaja` / `gadis` $\\rightarrow$ `teen`"
        ),
        inline=True
    )

    embed.add_field(
        name="👙 Fisik & Pakaian:",
        value=(
            "• `toket besar` $\\rightarrow$ `big tits`\n"
            "• `pantat besar` $\\rightarrow$ `big ass`\n"
            "• `montok` $\\rightarrow$ `chubby bbw`\n"
            "• `pirang` / `bule` $\\rightarrow$ `blonde / western`\n"
            "• `jilbab` / `kerudung` $\\rightarrow$ `hijab`\n"
            "• `kostum` $\\rightarrow$ `cosplay`\n"
            "• `kacamata` $\\rightarrow$ `glasses`"
        ),
        inline=True
    )

    embed.add_field(
        name="🔥 Skenario & Aksi:",
        value=(
            "• `selingkuh` $\\rightarrow$ `cheating`\n"
            "• `pijat` / `urut` $\\rightarrow$ `massage`\n"
            "• `mandi` $\\rightarrow$ `shower bath`\n"
            "• `tidur` $\\rightarrow$ `sleeping`\n"
            "• `intip` $\\rightarrow$ `spy`\n"
            "• `terjebak` $\\rightarrow$ `stuck`\n"
            "• `tetangga` $\\rightarrow$ `neighbor`"
        ),
        inline=True
    )

    embed.set_footer(text="Gunakan dropdown di bawah untuk beralih halaman panduan.")
    return embed


def build_help_saluran_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌐 Sistem 4 Saluran Kategori Video & Anime",
        description=(
            "Bot Sugiono bekerja secara otomatis memilah dan mengirimkan feed video dewasa & anime ke **4 channel terpisah** setiap 30 menit:\n"
            "────────────────────────────────────────"
        ),
        color=discord.Color.from_rgb(30, 144, 255),
        timestamp=datetime.now(timezone.utc)
    )

    for cat_key, cat in CATEGORIES.items():
        ch_id = cat["channel_id"]
        ch_obj = bot.get_channel(ch_id) if ch_id else None
        status = f"Terhubung ke #{ch_obj.name}" if ch_obj else f"ID: `{ch_id or 'Belum diatur'}`"
        
        if cat_key == "hentai":
            source_desc = "Nekopoi.care (Anime Hentai & Manga/3D)"
        elif cat_key == "jepang":
            source_desc = "XVideos & Roshy.tv (Decensored JAV Subtitle)"
        else:
            source_desc = "XVideos & Eporner Engine"

        embed.add_field(
            name=f"{cat['emoji']} {cat['name']}",
            value=(
                f"• Saluran: **{status}**\n"
                f"• Auto-Update: **Maksimal 3 konten baru per 30 menit**\n"
                f"• Sumber Feed: **{source_desc}**"
            ),
            inline=False
        )

    embed.set_footer(text="Gunakan dropdown di bawah untuk beralih halaman panduan.")
    return embed


def build_help_keamanan_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔞 Keamanan & Kebijakan NSFW Discord",
        description=(
            "Demi mematuhi **Discord Community Guidelines** dan **Terms of Service**, Sugiono Bot menerapkan aturan keamanan ketat:\n"
            "────────────────────────────────────────"
        ),
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="⚠️ Syarat Channel Age-Restricted (18+):",
        value=(
            "• Semua perintah (`/cari`, `/status`) dan auto-update hanya diizinkan di channel yang memiliki status **NSFW (Age-Restricted)**.\n"
            "• Jika dijalankan di channel umum non-dewasa, bot akan otomatis menolak permintaan."
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Cara Mengaktifkan Status NSFW di Discord:",
        value=(
            "1. Klik kanan nama channel yang dituju (misal: `#jav` atau `#hentai`).\n"
            "2. Pilih **Edit Channel** (Ikon Gerigi).\n"
            "3. Buka tab **Overview** lalu scroll ke bawah.\n"
            "4. Nyalakan toggle **Age-Restricted Channel (NSFW)**.\n"
            "5. Klik **Save Changes**."
        ),
        inline=False
    )

    embed.set_footer(text="Gunakan dropdown di bawah untuk beralih halaman panduan.")
    return embed


class HelpDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Halaman Utama",
                emoji="🏠",
                description="Kembali ke menu pusat panduan utama",
                value="home"
            ),
            discord.SelectOption(
                label="Perintah & Cara Cari",
                emoji="🔍",
                description="Panduan perintah /cari dan /status",
                value="perintah"
            ),
            discord.SelectOption(
                label="Kode Nuklir & Durasi",
                emoji="🎬",
                description="Panduan kode JAV (SSIS, ALDN) & filter durasi",
                value="nuklir"
            ),
            discord.SelectOption(
                label="Kamus Bahasa Indonesia",
                emoji="🏷️",
                description="Daftar istilah Indonesia yang otomatis diterjemahkan",
                value="kamus"
            ),
            discord.SelectOption(
                label="4 Saluran Kategori",
                emoji="🌐",
                description="Info channel Jepang, Hentai, Asia, dan Western",
                value="saluran"
            ),
            discord.SelectOption(
                label="Keamanan & Aturan NSFW",
                emoji="🔞",
                description="Aturan konten dewasa & channel Age-Restricted",
                value="keamanan"
            ),
        ]
        super().__init__(placeholder="👇 Pilih menu untuk panduan lengkap & tips...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == "home":
            embed = build_help_home_embed()
        elif selected == "perintah":
            embed = build_help_perintah_embed()
        elif selected == "nuklir":
            embed = build_help_nuklir_embed()
        elif selected == "kamus":
            embed = build_help_kamus_embed()
        elif selected == "saluran":
            embed = build_help_saluran_embed()
        elif selected == "keamanan":
            embed = build_help_keamanan_embed()
        else:
            embed = build_help_home_embed()

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(HelpDropdown())


@bot.hybrid_command(
    name="help",
    aliases=["panduan", "bantuan"],
    description="Menampilkan pusat panduan lengkap dan fitur bot Sugiono"
)
async def help_command(ctx: commands.Context) -> None:
    """Menampilkan Pusat Panduan Sugiono Bot lengkap dengan menu dropdown interaktif."""
    await ctx.defer()
    embed = build_help_home_embed()
    view = HelpView()
    await ctx.send(embed=embed, view=view)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    content = message.content.strip().lower()
    if content in ["sugiono help", "sugiono panduan", "sugiono bantuan", "sugiono"]:
        ctx = await bot.get_context(message)
        await help_command(ctx)
        return

    await bot.process_commands(message)


# ==============================================================================
# 9. GLOBAL ERROR HANDLER & ENTRYPOINT
# ==============================================================================
@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("⚠️ Parameter perintah belum lengkap. Gunakan `!cari [kata_kunci]`.", mention_author=True)
    else:
        logger.error(f"Command Error [{ctx.command}]: {error}", exc_info=True)


def main():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_bot_token_here":
        logger.critical("DISCORD_TOKEN belum diatur di file .env!")
        return

    logger.info("Memulai bot Discord Multi-Channel...")
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Login gagal! Token Discord tidak valid.")
    except Exception as e:
        logger.critical(f"Bot berhenti karena error fatal: {e}", exc_info=True)


if __name__ == "__main__":
    main()
