# ============================================
# YAPILANDIRMA DOSYASI
# ============================================

# Taranacak web sitesi URL'si
TARGET_URL = "https://example.com"  # <-- Buraya hedef siteyi yazın

# Taranacak alt sayfalar (varsa)
SUB_PAGES = [
    "/canli-tv",
    "/channels",
    "/live",
    "/tv",
    "/stream",
    # İhtiyaca göre ekleyin
]

# Çıktı dosyası
OUTPUT_FILE = "channels.m3u"

# Güncelleme aralığı (dakika)
UPDATE_INTERVAL = 30

# Tarayıcı ayarları
USE_SELENIUM = True  # JavaScript render gerektiren siteler için True
HEADLESS = True       # Tarayıcıyı görünmez çalıştır

# İstek ayarları
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
DELAY_BETWEEN_REQUESTS = 2  # saniye

# User Agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# M3U8 link desenleri
M3U8_PATTERNS = [
    r'https?://[^\s\"\'\<\>]+\.m3u8[^\s\"\'\<\>]*',
    r'https?://[^\s\"\'\<\>]+/playlist\.m3u8[^\s\"\'\<\>]*',
    r'https?://[^\s\"\'\<\>]+/index\.m3u8[^\s\"\'\<\>]*',
    r'https?://[^\s\"\'\<\>]+/live[^\s\"\'\<\>]*\.m3u8[^\s\"\'\<\>]*',
    r'https?://[^\s\"\'\<\>]+/stream[^\s\"\'\<\>]*\.m3u8[^\s\"\'\<\>]*',
    r'https?://[^\s\"\'\<\>]+/hls[^\s\"\'\<\>]*\.m3u8[^\s\"\'\<\>]*',
    r'source\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'src\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'url\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'videoUrl\s*[=:]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'streamUrl\s*[=:]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'hlsUrl\s*[=:]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
]

# Loglama
LOG_FILE = "scraper.log"
LOG_LEVEL = "INFO"
