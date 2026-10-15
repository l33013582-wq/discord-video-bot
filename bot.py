import os
import json
import logging
import asyncio
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

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
# 2. KONFIGURASI 3 KATEGORI / GENRE WILAYAH (JEPANG, ASIA, WESTERN)
# ==============================================================================
CATEGORIES: Dict[str, Dict[str, Any]] = {
    "jepang": {
        "key": "jepang",
        "name": "Jepang (JAV / Japanese)",
        "emoji": "🇯🇵",
        "channel_id": parse_channel_id("CHANNEL_JEPANG_ID"),
        "api_url": os.getenv("API_JEPANG_URL", "https://www.eporner.com/api/v2/web/search/?query=japanese&per_page=10&order=latest&thumbsize=big&format=json"),
        "color": discord.Color.from_rgb(255, 75, 145),  # Sakura Crimson
        "keywords": ["japanese", "jav", "japan"]
    },
    "asia": {
        "key": "asia",
        "name": "Asia (Non-Jepang)",
        "emoji": "🌏",
        "channel_id": parse_channel_id("CHANNEL_ASIA_ID"),
        "api_url": os.getenv("API_ASIA_URL", "https://www.eporner.com/api/v2/web/search/?query=asian&per_page=10&order=latest&thumbsize=big&format=json"),
        "color": discord.Color.from_rgb(255, 140, 0),   # Warm Amber
        "keywords": ["asian", "korean", "chinese", "indonesian"]
    },
    "western": {
        "key": "western",
        "name": "Western (Barat / Caucasian)",
        "emoji": "🌍",
        "channel_id": parse_channel_id("CHANNEL_WESTERN_ID"),
        "api_url": os.getenv("API_WESTERN_URL", "https://www.eporner.com/api/v2/web/search/?query=western&per_page=10&order=latest&thumbsize=big&format=json"),
        "color": discord.Color.from_rgb(30, 144, 255),  # Dodger Blue
        "keywords": ["western", "american", "european", "caucasian"]
    }
}

CACHE_FILE = "sent_videos.json"
MAX_CACHED_IDS = 2000  # Kapasitas cache deduplikasi


# ==============================================================================
# 3. HELPER KELAS PENYIMPANAN RIWAYAT VIDEO (DEDUPLIKASI)
# ==============================================================================
class VideoHistoryManager:
    """Mengelola penyimpanan ID video yang telah dikirim ke Discord."""
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

    def is_seen(self, video_id: Any) -> bool:
        return str(video_id) in self.seen_ids

    def mark_as_seen(self, video_id: Any) -> None:
        self.seen_ids.add(str(video_id))
        self.save_history()


# ==============================================================================
# 4. HELPER PARSER DATA API & PEMBUAT DISCORD EMBED
# ==============================================================================
def normalize_video_data(item: Dict[str, Any], default_category: Optional[str] = None) -> Dict[str, Any]:
    """Menormalisasi data respons JSON API (mendukung Eporner & format generik)."""
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

    # Ekstraksi thumbnail (bisa berupa dictionary src/url atau string)
    raw_thumb = item.get("default_thumb") or item.get("thumbnail") or item.get("preview_image") or item.get("poster")
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

    # Ekstraksi tags / keywords
    raw_tags = item.get("keywords") or item.get("tags") or item.get("categories") or []
    if isinstance(raw_tags, str):
        tags_str = ", ".join([t.strip() for t in raw_tags.split(",")[:4]])
    elif isinstance(raw_tags, list):
        tags_str = ", ".join(str(t) for t in raw_tags[:4])
    else:
        tags_str = "Umum"

    # Rating & Views
    rate = item.get("rate")
    views = item.get("views")

    return {
        "id": str(video_id) if video_id else None,
        "title": str(title),
        "url": str(url),
        "thumbnail": str(thumbnail) if thumbnail else None,
        "duration": str(duration),
        "tags": tags_str if tags_str else "Umum",
        "rate": str(rate) if rate else None,
        "views": f"{int(views):,}" if str(views).isdigit() else str(views) if views else None,
        "category": default_category
    }


def create_video_embed(video: Dict[str, Any], category_info: Optional[Dict[str, Any]] = None, is_search: bool = False) -> discord.Embed:
    """Membuat Discord Embed yang terstruktur, menarik, sesuai kategori daerah dan berlabel 18+."""
    if category_info:
        embed_color = category_info["color"]
        category_name = f"{category_info['emoji']} {category_info['name']}"
    else:
        embed_color = discord.Color.from_rgb(220, 20, 60) if not is_search else discord.Color.from_rgb(255, 69, 0)
        category_name = "Umum / Campuran"

    embed = discord.Embed(
        title=f"🔞 {video['title'][:250]}",
        url=video["url"] if video["url"].startswith("http") else None,
        description=f"[🔗 **Klik di sini untuk menonton**]({video['url']})" if video["url"] else "Tautan video tidak tersedia",
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
            "Accept": "application/json"
        }
        if API_KEY:
            headers["Authorization"] = f"Bearer {API_KEY}"

        # Cek jika ada proxy di .env (misal: http://127.0.0.1:10809 atau socks5)
        proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
        timeout = aiohttp.ClientTimeout(total=25)
        connector = aiohttp.TCPConnector(ssl=False) if proxy else None
        
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector
        )
        self.proxy = proxy
        if self.proxy:
            logger.info(f"Menggunakan Proxy untuk request API: {self.proxy}")
        logger.info("Sesi aiohttp.ClientSession berhasil dibuat.")

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
            name="3 Channel | Ketik /cari"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    # --------------------------------------------------------------------------
    # AUTO-UPDATE BACKGROUND TASK (Setiap 30 Menit ke 3 Channel)
    # --------------------------------------------------------------------------
    @tasks.loop(minutes=30)
    async def auto_update_all_channels(self) -> None:
        """Melakukan pengecekan berkala dan mengunggah video ke 3 channel sesuai kategorinya."""
        logger.info("=" * 60)
        logger.info("[Auto-Update] Memulai siklus auto-update ke 3 channel (Jepang, Asia, Western)...")

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

        logger.info("[Auto-Update] Siklus auto-update 3 channel selesai.")
        logger.info("=" * 60)

    async def _process_category_update(self, channel: discord.abc.Messageable, cat_info: Dict[str, Any]) -> None:
        """Mengambil data video terbaru dari API untuk kategori tertentu dan mengirimkannya."""
        cat_name = cat_info["name"]
        api_url = cat_info["api_url"]

        try:
            async with self.session.get(api_url, proxy=self.proxy) as response:
                if response.status != 200:
                    logger.error(f"[Auto-Update] [{cat_name}] API merespons dengan HTTP {response.status}")
                    return

                try:
                    payload = await response.json()
                except Exception as json_err:
                    logger.error(f"[Auto-Update] [{cat_name}] Format JSON tidak valid: {json_err}")
                    return

                # Ekstraksi list data
                raw_videos = []
                if isinstance(payload, list):
                    raw_videos = payload
                elif isinstance(payload, dict):
                    raw_videos = payload.get("videos") or payload.get("data") or payload.get("items") or []

                if not raw_videos:
                    logger.info(f"[Auto-Update] [{cat_name}] Tidak ada video ditemukan dari respons API.")
                    return

                # Filter video baru (deduplikasi ID)
                new_videos = []
                for raw_item in raw_videos:
                    item_data = normalize_video_data(raw_item, default_category=cat_info["name"])
                    if item_data["id"] and not self.history.is_seen(item_data["id"]):
                        new_videos.append(item_data)

                if not new_videos:
                    logger.info(f"[Auto-Update] [{cat_name}] Semua video sudah pernah diunggah.")
                    return

                logger.info(f"[Auto-Update] [{cat_name}] Ditemukan {len(new_videos)} video baru. Mengunggah ke #{channel.name}...")

                # Batasi maksimal 3 video per kategori setiap 30 menit agar feed channel rapi
                videos_to_send = list(reversed(new_videos))[-3:]

                for video in videos_to_send:
                    embed = create_video_embed(video, category_info=cat_info, is_search=False)
                    try:
                        await channel.send(embed=embed)
                        self.history.mark_as_seen(video["id"])
                        logger.info(f"[Auto-Update] [{cat_name}] Berhasil posting: {video['title'][:40]} (ID: {video['id']})")
                        await asyncio.sleep(2)  # Delay rate limit Discord
                    except discord.Forbidden:
                        logger.error(f"[Auto-Update] [{cat_name}] Tidak memiliki izin kirim pesan di channel #{channel.name}!")
                        break
                    except Exception as send_err:
                        logger.error(f"[Auto-Update] [{cat_name}] Gagal mengirim embed: {send_err}")

        except asyncio.TimeoutError:
            logger.warning(
                f"[Auto-Update] [{cat_name}] Koneksi ke API Timeout. "
                "(Catatan: Jika provider internet Anda memblokir domain dewasa, gunakan Cloudflare 1.1.1.1 / WARP / VPN)"
            )
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
# 6. PERINTAH INTERAKTIF PENCARIAN (/cari [kata_kunci])
# ==============================================================================
@bot.hybrid_command(
    name="cari",
    aliases=["search", "find"],
    description="Mencari video dewasa berdasarkan kata kunci (Wajib di channel NSFW)"
)
@discord.app_commands.describe(keyword="Kata kunci video yang ingin dicari (contoh: cosplay, blondie)")
async def cari_video(ctx: commands.Context, *, keyword: Optional[str] = None) -> None:
    """Perintah pencarian video. Menyesuaikan kategori otomatis jika dijalankan di channel spesifik."""
    # 1. Validasi Keamanan: Wajib berada di Channel NSFW
    is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
    if not is_nsfw:
        warning_embed = discord.Embed(
            title="⛔ Akses Ditolak (NSFW Only)",
            description=(
                "Perintah ini hanya dapat dijalankan di channel yang berstatus **NSFW (Age-Restricted)**!\n\n"
                "Sesuai aturan Discord Community Guidelines dan Terms of Service, konten 18+ tidak boleh "
                "ditampilkan di channel non-dewasa.\n\n"
                "👉 *Silakan gunakan perintah ini di salah satu channel: **Jepang**, **Asia**, atau **Western**.*"
            ),
            color=discord.Color.red()
        )
        warning_embed.set_footer(text="Discord Safety & Age-Restricted Policy")
        await ctx.reply(embed=warning_embed, mention_author=True)
        return

    # 2. Validasi Kata Kunci
    if not keyword or not keyword.strip():
        help_embed = discord.Embed(
            title="ℹ️ Cara Menggunakan Perintah /cari",
            description=(
                "Ketik kata kunci video yang ingin Anda cari.\n\n"
                "**Format:** `/cari [kata_kunci]`\n"
                "**Contoh:** `/cari cosplay` atau `/cari blondie`\n\n"
                "💡 *Tips: Jika dijalankan di channel khusus (Jepang / Asia / Western), hasil pencarian akan ditandai dengan kategori tersebut.*"
            ),
            color=discord.Color.gold()
        )
        await ctx.reply(embed=help_embed, mention_author=True)
        return

    keyword = keyword.strip()

    # Deteksi apakah user menjalankan perintah di dalam salah satu dari 3 channel kategori
    current_category = None
    for cat_key, cat_data in CATEGORIES.items():
        if cat_data["channel_id"] == ctx.channel.id:
            current_category = cat_data
            break

    logger.info(f"User {ctx.author} mencari '{keyword}' di #{ctx.channel.name} (Kategori: {current_category['name'] if current_category else 'Bebas'})")

    async with ctx.typing():
        try:
            # Sesuaikan query pencarian jika dijalankan di channel spesifik
            query_str = f"{current_category['keywords'][0]} {keyword}" if current_category else keyword

            params = {
                "query": query_str,
                "per_page": 5,
                "thumbsize": "big",
                "format": "json"
            }

            async with bot.session.get(API_SEARCH_VIDEOS_URL, params=params, proxy=bot.proxy) as resp:
                if resp.status != 200:
                    error_embed = discord.Embed(
                        title="❌ Gagal Menghubungi API",
                        description=f"Server video merespons status `{resp.status}`. Coba beberapa saat lagi.",
                        color=discord.Color.red()
                    )
                    await ctx.reply(embed=error_embed, mention_author=True)
                    return

                try:
                    search_payload = await resp.json()
                except Exception as json_err:
                    logger.error(f"Gagal parse JSON hasil pencarian: {json_err}")
                    await ctx.reply("❌ Respons data dari API tidak valid.", mention_author=True)
                    return

                raw_results = []
                if isinstance(search_payload, list):
                    raw_results = search_payload
                elif isinstance(search_payload, dict):
                    raw_results = search_payload.get("videos") or search_payload.get("data") or search_payload.get("items") or []

                if not raw_results:
                    not_found_embed = discord.Embed(
                        title="🔍 Hasil Pencarian Tidak Ditemukan",
                        description=f"Tidak ditemukan video dengan kata kunci: **{keyword}**.\nCobalah dengan kata kunci lain.",
                        color=discord.Color.dark_gray()
                    )
                    await ctx.reply(embed=not_found_embed, mention_author=True)
                    return

                # Normalisasi hasil teratas (Top Result)
                top_video = normalize_video_data(raw_results[0], default_category=current_category["name"] if current_category else None)
                embed = create_video_embed(top_video, category_info=current_category, is_search=True)

                # Lampirkan video tambahan jika ada
                additional_links = []
                for idx, extra_item in enumerate(raw_results[1:4], start=2):
                    extra_data = normalize_video_data(extra_item)
                    if extra_data.get("url"):
                        additional_links.append(f"**{idx}.** [{extra_data['title'][:40]}]({extra_data['url']}) (`{extra_data['duration']}`)")

                if additional_links:
                    embed.add_field(
                        name="📚 Video Terkait Lainnya",
                        value="\n".join(additional_links),
                        inline=False
                    )

                embed.set_author(
                    name=f"Hasil Pencarian untuk: '{keyword}'",
                    icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None
                )

                await ctx.reply(embed=embed, mention_author=True)

        except asyncio.TimeoutError:
            await ctx.reply("⏱️ Permintaan ke API melebihi batas waktu (Timeout). Silakan periksa koneksi internet.", mention_author=True)
        except Exception as e:
            logger.error(f"Error pada perintah !cari: {e}", exc_info=True)
            await ctx.reply("⚠️ Terjadi kesalahan internal saat mencari video.", mention_author=True)


# ==============================================================================
# 7. PERINTAH BANTUAN STATUS CHANNEL (/status)
# ==============================================================================
@bot.hybrid_command(
    name="status",
    aliases=["info"],
    description="Cek status dan koneksi 3 channel kategori bot (Jepang, Asia, Western)"
)
async def status_channel(ctx: commands.Context) -> None:
    """Mengecek status dan ID ketiga channel yang terhubung ke bot."""
    is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
    if not is_nsfw:
        await ctx.reply("⛔ Perintah ini hanya bisa dicek di channel NSFW.", mention_author=True)
        return

    embed = discord.Embed(
        title="📊 Status Konfigurasi Channel Kategori",
        description="Berikut adalah status ketiga channel yang terdaftar pada sistem Auto-Update:",
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
    await ctx.reply(embed=embed, mention_author=True)


# ==============================================================================
# 8. GLOBAL ERROR HANDLER & ENTRYPOINT
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
