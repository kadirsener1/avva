#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8 Link Scraper ve Otomatik Güncelleyici
Web sitelerinden m3u8 stream linklerini tarar,
bulur ve M3U dosyasına kaydeder.
Her 30 dakikada bir otomatik güncelleme yapar.
"""

import re
import os
import sys
import json
import time
import logging
import hashlib
import schedule
import requests
import m3u8 as m3u8_parser
from datetime import datetime
from urllib.parse import urljoin, urlparse, unquote
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from config import *

# ============================================
# LOGLAMA AYARLARI
# ============================================
def setup_logging():
    """Loglama sistemini yapılandır"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format=log_format,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# ============================================
# KANAL SINIFI
# ============================================
class Channel:
    """Bir TV kanalını temsil eder"""
    
    def __init__(self, name, url, group="Genel", logo="", language="tr"):
        self.name = name
        self.url = url
        self.group = group
        self.logo = logo
        self.language = language
        self.is_alive = False
        self.last_checked = None
    
    def __repr__(self):
        status = "✓" if self.is_alive else "✗"
        return f"[{status}] {self.name}: {self.url}"
    
    def __eq__(self, other):
        return self.url == other.url
    
    def __hash__(self):
        return hash(self.url)
    
    def to_m3u_entry(self):
        """M3U formatında satır döndür"""
        extinf = f'#EXTINF:-1'
        
        if self.logo:
            extinf += f' tvg-logo="{self.logo}"'
        if self.group:
            extinf += f' group-title="{self.group}"'
        if self.language:
            extinf += f' tvg-language="{self.language}"'
        
        extinf += f',{self.name}'
        
        return f"{extinf}\n{self.url}"


# ============================================
# WEB SCRAPER SINIFI
# ============================================
class M3U8Scraper:
    """Web sitelerinden m3u8 linklerini tarar ve bulur"""
    
    def __init__(self):
        self.session = self._create_session()
        self.channels = []
        self.visited_urls = set()
        self.found_m3u8_urls = set()
        self.driver = None
    
    def _create_session(self):
        """HTTP oturumu oluştur"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': '*/*',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': TARGET_URL,
            'Origin': TARGET_URL,
        })
        
        # Retry mekanizması
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=MAX_RETRIES,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        return session
    
    def _init_selenium(self):
        """Selenium WebDriver başlat"""
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium yüklü değil. pip install selenium webdriver-manager")
            return None
        
        try:
            chrome_options = Options()
            if HEADLESS:
                chrome_options.add_argument('--headless=new')
            
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument(f'--user-agent={USER_AGENT}')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument('--window-size=1920,1080')
            
            # Log kayıtlarını etkinleştir (network trafiğini yakalamak için)
            chrome_options.set_capability(
                'goog:loggingPrefs', {'performance': 'ALL'}
            )
            chrome_options.add_experimental_option(
                'perfLoggingPrefs', {
                    'enableNetwork': True,
                    'enablePage': False
                }
            )
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(REQUEST_TIMEOUT)
            
            logger.info("Selenium WebDriver başarıyla başlatıldı")
            return driver
            
        except Exception as e:
            logger.error(f"Selenium başlatılamadı: {e}")
            return None
    
    def _close_selenium(self):
        """Selenium WebDriver kapat"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    # ----------------------------------------
    # SAYFA İÇERİĞİ ALMA
    # ----------------------------------------
    def fetch_page_requests(self, url):
        """Requests ile sayfa içeriğini al"""
        try:
            response = self.session.get(
                url, 
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Sayfa alınamadı (requests): {url} - {e}")
            return None
    
    def fetch_page_selenium(self, url):
        """Selenium ile sayfa içeriğini al (JS render dahil)"""
        if not self.driver:
            self.driver = self._init_selenium()
        
        if not self.driver:
            return None
        
        try:
            self.driver.get(url)
            
            # Sayfanın yüklenmesini bekle
            WebDriverWait(self.driver, REQUEST_TIMEOUT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Ekstra bekleme (dinamik içerik için)
            time.sleep(5)
            
            # Sayfayı aşağı kaydır (lazy load için)
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(2)
            
            return self.driver.page_source
            
        except Exception as e:
            logger.error(f"Sayfa alınamadı (selenium): {url} - {e}")
            return None
    
    def get_network_m3u8_urls(self):
        """Selenium network loglarından m3u8 URL'lerini çıkar"""
        m3u8_urls = set()
        
        if not self.driver:
            return m3u8_urls
        
        try:
            logs = self.driver.get_log('performance')
            
            for log_entry in logs:
                try:
                    log_data = json.loads(log_entry['message'])
                    message = log_data.get('message', {})
                    method = message.get('method', '')
                    
                    if method in [
                        'Network.requestWillBeSent',
                        'Network.responseReceived'
                    ]:
                        params = message.get('params', {})
                        
                        # Request URL
                        request_url = params.get('request', {}).get('url', '')
                        if '.m3u8' in request_url:
                            m3u8_urls.add(request_url.split('?')[0] + 
                                        ('?' + request_url.split('?')[1] 
                                         if '?' in request_url else ''))
                        
                        # Response URL
                        response_url = (params.get('response', {})
                                       .get('url', ''))
                        if '.m3u8' in response_url:
                            m3u8_urls.add(response_url)
                        
                        # Document URL
                        doc_url = params.get('documentURL', '')
                        if '.m3u8' in doc_url:
                            m3u8_urls.add(doc_url)
                            
                except (json.JSONDecodeError, KeyError):
                    continue
                    
        except Exception as e:
            logger.debug(f"Network logları okunamadı: {e}")
        
        return m3u8_urls
    
    def fetch_page(self, url):
        """Sayfa içeriğini al (ayarlara göre yöntem seç)"""
        if USE_SELENIUM and SELENIUM_AVAILABLE:
            content = self.fetch_page_selenium(url)
            if content:
                # Network loglarından da m3u8 URL'lerini al
                network_urls = self.get_network_m3u8_urls()
                self.found_m3u8_urls.update(network_urls)
                if network_urls:
                    logger.info(
                        f"Network'ten {len(network_urls)} m3u8 URL bulundu"
                    )
            return content
        else:
            return self.fetch_page_requests(url)
    
    # ----------------------------------------
    # M3U8 LİNK BULMA
    # ----------------------------------------
    def extract_m3u8_from_text(self, text, base_url=""):
        """Metin içinden m3u8 linklerini çıkar"""
        found_urls = set()
        
        for pattern in M3U8_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                url = match.group(1) if match.lastindex else match.group(0)
                url = url.strip().strip('"').strip("'")
                
                # Göreceli URL'yi mutlak URL'ye çevir
                if url.startswith('//'):
                    url = 'https:' + url
                elif url.startswith('/'):
                    url = urljoin(base_url, url)
                elif not url.startswith('http'):
                    url = urljoin(base_url, url)
                
                # URL temizleme
                url = url.split('"')[0].split("'")[0].split(' ')[0]
                url = url.rstrip('\\').rstrip(',').rstrip(';')
                
                if self._is_valid_m3u8_url(url):
                    found_urls.add(url)
        
        return found_urls
    
    def extract_m3u8_from_html(self, html, base_url=""):
        """HTML içinden m3u8 linklerini çıkar"""
        found_urls = set()
        
        if not html:
            return found_urls
        
        soup = BeautifulSoup(html, 'lxml')
        
        # 1. Script taglarını tara
        for script in soup.find_all('script'):
            script_text = script.string or script.get_text()
            if script_text:
                urls = self.extract_m3u8_from_text(script_text, base_url)
                found_urls.update(urls)
            
            # src attribute
            src = script.get('src', '')
            if src and not src.startswith('data:'):
                js_url = urljoin(base_url, src)
                js_content = self.fetch_page_requests(js_url)
                if js_content:
                    urls = self.extract_m3u8_from_text(js_content, base_url)
                    found_urls.update(urls)
        
        # 2. Video/Source taglarını tara
        for tag in soup.find_all(['video', 'source', 'audio']):
            for attr in ['src', 'data-src', 'data-url', 'data-stream']:
                value = tag.get(attr, '')
                if '.m3u8' in value:
                    url = urljoin(base_url, value)
                    if self._is_valid_m3u8_url(url):
                        found_urls.add(url)
        
        # 3. iframe'leri tara
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src', '') or iframe.get('data-src', '')
            if iframe_src:
                iframe_url = urljoin(base_url, iframe_src)
                if iframe_url not in self.visited_urls:
                    self.visited_urls.add(iframe_url)
                    logger.info(f"iframe taranıyor: {iframe_url}")
                    iframe_content = self.fetch_page(iframe_url)
                    if iframe_content:
                        urls = self.extract_m3u8_from_html(
                            iframe_content, iframe_url
                        )
                        found_urls.update(urls)
        
        # 4. Tüm <a> linklerini tara
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '.m3u8' in href:
                url = urljoin(base_url, href)
                if self._is_valid_m3u8_url(url):
                    found_urls.add(url)
        
        # 5. data-* attributelarını tara
        for tag in soup.find_all(True):
            for attr, value in tag.attrs.items():
                if isinstance(value, str) and '.m3u8' in value:
                    urls = self.extract_m3u8_from_text(value, base_url)
                    found_urls.update(urls)
        
        # 6. JSON-LD ve meta tagları
        for meta in soup.find_all('meta'):
            content = meta.get('content', '')
            if '.m3u8' in content:
                urls = self.extract_m3u8_from_text(content, base_url)
                found_urls.update(urls)
        
        # 7. Ham HTML'den de tara
        urls = self.extract_m3u8_from_text(html, base_url)
        found_urls.update(urls)
        
        return found_urls
    
    def _is_valid_m3u8_url(self, url):
        """M3U8 URL'sinin geçerli olup olmadığını kontrol et"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme in ('http', 'https'):
                return False
            if not parsed.netloc:
                return False
            if '.m3u8' not in parsed.path.lower():
                return False
            # Çok kısa URL'leri filtrele
            if len(url) < 20:
                return False
            return True
        except:
            return False
    
    # ----------------------------------------
    # KANAL BİLGİSİ ÇIKARMA
    # ----------------------------------------
    def extract_channel_info(self, html, base_url):
        """HTML'den kanal isimlerini ve logolarını çıkar"""
        channel_info = {}
        
        if not html:
            return channel_info
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Kanal kartlarını/listelerini bul
        selectors = [
            '.channel', '.kanal', '.tv-channel',
            '.stream-item', '.channel-item', '.live-tv-item',
            '[class*="channel"]', '[class*="kanal"]',
            '[class*="stream"]', '[class*="player"]',
            'channelsGrid', '.card', '.item'
        ]
        
        for selector in selectors:
            items = soup.select(selector)
            for item in items:
                name = None
                logo = None
                
                # İsim bul
                name_tags = item.find_all(
                    ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
                     'span', 'p', 'a', 'strong']
                )
                for tag in name_tags:
                    text = tag.get_text(strip=True)
                    if text and len(text) > 1 and len(text) < 50:
                        name = text
                        break
                
                # Logo bul
                img = item.find('img')
                if img:
                    logo = img.get('src', '') or img.get('data-src', '')
                    if logo:
                        logo = urljoin(base_url, logo)
                
                if name:
                    channel_info[name.lower()] = {
                        'name': name,
                        'logo': logo or ''
                    }
        
        return channel_info
    
    def guess_channel_name(self, url, channel_info=None):
        """URL'den kanal adını tahmin et"""
        parsed = urlparse(url)
        path = parsed.path
        
        # URL'den ipuçları çıkar
        parts = path.split('/')
        for part in reversed(parts):
            part = part.replace('.m3u8', '').replace('_', ' ').replace('-', ' ')
            part = part.strip()
            if part and len(part) > 1 and not part.isdigit():
                # Bilinen kalıpları filtrele
                skip_words = [
                    'index', 'playlist', 'live', 'stream', 
                    'hls', 'video', 'mono', 'tracks'
                ]
                if part.lower() not in skip_words:
                    return part.title()
        
        # Hostname'den tahmin
        hostname = parsed.hostname or ''
        hostname = hostname.replace('www.', '').split('.')[0]
        
        return hostname.title() if hostname else "Bilinmeyen Kanal"
    
    # ----------------------------------------
    # CANLILIK KONTROLÜ
    # ----------------------------------------
    def check_stream_alive(self, url):
        """M3U8 stream'inin canlı olup olmadığını kontrol et"""
        try:
            response = self.session.head(
                url, 
                timeout=10, 
                allow_redirects=True
            )
            if response.status_code == 200:
                return True
            
            # HEAD başarısız olursa GET dene
            response = self.session.get(
                url, 
                timeout=10, 
                stream=True,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                content = response.text[:1000]
                # M3U8 içeriği mi kontrol et
                if '#EXTM3U' in content or '#EXT-X' in content or '.ts' in content:
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Stream kontrol hatası: {url} - {e}")
            return False
    
    def check_streams_parallel(self, channels, max_workers=10):
        """Paralel olarak stream kontrolü yap"""
        logger.info(f"{len(channels)} kanal kontrol ediliyor...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_channel = {
                executor.submit(
                    self.check_stream_alive, ch.url
                ): ch for ch in channels
            }
            
            for future in as_completed(future_to_channel):
                channel = future_to_channel[future]
                try:
                    channel.is_alive = future.result()
                    channel.last_checked = datetime.now()
                    status = "✓ Aktif" if channel.is_alive else "✗ Pasif"
                    logger.debug(f"  {status}: {channel.name}")
                except Exception as e:
                    channel.is_alive = False
                    logger.debug(f"  ✗ Hata: {channel.name} - {e}")
        
        alive_count = sum(1 for ch in channels if ch.is_alive)
        logger.info(
            f"Kontrol tamamlandı: {alive_count}/{len(channels)} aktif kanal"
        )
        
        return channels
    
    # ----------------------------------------
    # KANAL SAYFA LİNKLERİNİ BULMA
    # ----------------------------------------
    def find_channel_pages(self, html, base_url):
        """Ana sayfadan kanal sayfalarının linklerini bul"""
        channel_pages = set()
        
        if not html:
            return channel_pages
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Tüm linkleri tara
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            
            # Aynı domain'de mi kontrol et
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                # Kanal sayfası olabilecek linkleri filtrele
                keywords = [
                    'channel', 'kanal', 'canli', 'live', 'tv',
                    'stream', 'watch', 'izle', 'player', 'play',
                    'yayın', 'yayin', 'video'
                ]
                
                href_lower = href.lower()
                link_text = link.get_text(strip=True).lower()
                
                for keyword in keywords:
                    if keyword in href_lower or keyword in link_text:
                        channel_pages.add(full_url)
                        break
        
        return channel_pages
    
    # ----------------------------------------
    # ANA TARAMA FONKSİYONU
    # ----------------------------------------
    def scrape(self):
        """Ana tarama fonksiyonu"""
        start_time = time.time()
        logger.info("=" * 60)
        logger.info(f"Tarama başlatıldı: {datetime.now()}")
        logger.info(f"Hedef: {TARGET_URL}")
        logger.info("=" * 60)
        
        all_m3u8_urls = set()
        all_channel_info = {}
        
        # 1. Ana sayfayı tara
        urls_to_scan = [TARGET_URL]
        
        # Alt sayfaları ekle
        for sub_page in SUB_PAGES:
            urls_to_scan.append(urljoin(TARGET_URL, sub_page))
        
        # 2. Tüm sayfaları tara
        for url in urls_to_scan:
            if url in self.visited_urls:
                continue
            
            self.visited_urls.add(url)
            logger.info(f"\nSayfa taranıyor: {url}")
            
            html = self.fetch_page(url)
            if not html:
                continue
            
            # M3U8 linklerini bul
            m3u8_urls = self.extract_m3u8_from_html(html, url)
            logger.info(f"  → {len(m3u8_urls)} m3u8 link bulundu")
            all_m3u8_urls.update(m3u8_urls)
            
            # Kanal bilgilerini çıkar
            info = self.extract_channel_info(html, url)
            all_channel_info.update(info)
            
            # Alt sayfa linklerini bul
            channel_pages = self.find_channel_pages(html, url)
            
            for page_url in channel_pages:
                if page_url not in self.visited_urls:
                    self.visited_urls.add(page_url)
                    logger.info(f"  Alt sayfa taranıyor: {page_url}")
                    
                    page_html = self.fetch_page(page_url)
                    if page_html:
                        page_urls = self.extract_m3u8_from_html(
                            page_html, page_url
                        )
                        if page_urls:
                            logger.info(
                                f"    → {len(page_urls)} m3u8 link bulundu"
                            )
                        all_m3u8_urls.update(page_urls)
                        
                        page_info = self.extract_channel_info(
                            page_html, page_url
                        )
                        all_channel_info.update(page_info)
                    
                    time.sleep(DELAY_BETWEEN_REQUESTS)
            
            time.sleep(DELAY_BETWEEN_REQUESTS)
        
        # Network'ten bulunan URL'leri ekle
        all_m3u8_urls.update(self.found_m3u8_urls)
        
        # 3. Kanalları oluştur
        self.channels = []
        for url in all_m3u8_urls:
            name = self.guess_channel_name(url, all_channel_info)
            channel = Channel(
                name=name,
                url=url,
                group=self._guess_group(name, url),
                logo=self._find_logo(name, all_channel_info)
            )
            self.channels.append(channel)
        
        # Tekrar edenleri kaldır
        self.channels = list({ch.url: ch for ch in self.channels}.values())
        
        logger.info(f"\nToplam {len(self.channels)} benzersiz kanal bulundu")
        
        # 4. Canlılık kontrolü
        if self.channels:
            self.channels = self.check_streams_parallel(self.channels)
        
        # 5. Selenium'u kapat
        self._close_selenium()
        
        # 6. Sonuçları kaydet
        self.save_m3u()
        
        elapsed = time.time() - start_time
        logger.info(f"\nTarama tamamlandı: {elapsed:.1f} saniye")
        logger.info("=" * 60)
        
        return self.channels
    
    def _guess_group(self, name, url):
        """Kanal grubunu tahmin et"""
        name_lower = name.lower()
        url_lower = url.lower()
        combined = name_lower + ' ' + url_lower
        
        groups = {
            'Haber': ['haber', 'news', 'cnn', 'ntv', 'trt haber',
                      'haberturk', 'a haber', 'habertürk'],
            'Spor': ['spor', 'sport', 'bein', 'tivibu', 's sport',
                    'futbol', 'nba', 'eurosport'],
            'Çocuk': ['çocuk', 'cocuk', 'kids', 'cartoon', 'disney',
                     'baby', 'minika', 'trt çocuk'],
            'Sinema': ['sinema', 'movie', 'film', 'cinema', 'fx',
                      'filmbox', 'tv2'],
            'Müzik': ['müzik', 'muzik', 'music', 'kral', 'power',
                     'number1'],
            'Belgesel': ['belgesel', 'documentary', 'national',
                        'discovery', 'history', 'bbc earth'],
            'Dini': ['dini', 'kuran', 'diyanet', 'semerkand'],
            'Eğlence': ['eğlence', 'show', 'star', 'kanal d', 'atv',
                       'fox', 'tv8'],
        }
        
        for group_name, keywords in groups.items():
            for keyword in keywords:
                if keyword in combined:
                    return group_name
        
        return 'Genel'
    
    def _find_logo(self, name, channel_info):
        """Kanal logosunu bul"""
        name_lower = name.lower()
        for key, info in channel_info.items():
            if key in name_lower or name_lower in key:
                return info.get('logo', '')
        return ''
    
    # ----------------------------------------
    # M3U DOSYASI OLUŞTURMA
    # ----------------------------------------
    def save_m3u(self, filepath=None):
        """Kanalları M3U dosyasına kaydet"""
        filepath = filepath or OUTPUT_FILE
        
        # Sadece aktif kanalları kaydet (hepsi pasifse tümünü kaydet)
        alive_channels = [ch for ch in self.channels if ch.is_alive]
        channels_to_save = alive_channels if alive_channels else self.channels
        
        # Gruba göre sırala
        channels_to_save.sort(key=lambda x: (x.group, x.name))
        
        # M3U dosyasını oluştur
        lines = [
            '#EXTM3U',
            f'# Güncelleme: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            f'# Toplam Kanal: {len(channels_to_save)}',
            f'# Aktif Kanal: {len(alive_channels)}',
            f'# Kaynak: {TARGET_URL}',
            ''
        ]
        
        for channel in channels_to_save:
            lines.append(channel.to_m3u_entry())
            lines.append('')
        
        content = '\n'.join(lines)
        
        # Dosyaya yaz
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"\n✓ M3U dosyası kaydedildi: {filepath}")
        logger.info(f"  Toplam: {len(channels_to_save)} kanal")
        logger.info(f"  Aktif: {len(alive_channels)} kanal")
        
        # JSON olarak da kaydet (isteğe bağlı)
        self.save_json(filepath.replace('.m3u', '.json'), channels_to_save)
        
        return filepath
    
    def save_json(self, filepath, channels):
        """Kanal bilgilerini JSON olarak kaydet"""
        data = {
            'updated': datetime.now().isoformat(),
            'source': TARGET_URL,
            'total_channels': len(channels),
            'channels': [
                {
                    'name': ch.name,
                    'url': ch.url,
                    'group': ch.group,
                    'logo': ch.logo,
                    'is_alive': ch.is_alive,
                    'last_checked': (
                        ch.last_checked.isoformat() 
                        if ch.last_checked else None
                    )
                }
                for ch in channels
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✓ JSON dosyası kaydedildi: {filepath}")


# ============================================
# ZAMANLAYICI
# ============================================
class Scheduler:
    """Otomatik güncelleme zamanlayıcısı"""
    
    def __init__(self):
        self.scraper = None
        self.run_count = 0
    
    def run_scraper(self):
        """Scraper'ı çalıştır"""
        self.run_count += 1
        logger.info(f"\n{'#' * 60}")
        logger.info(f"# Çalıştırma #{self.run_count}")
        logger.info(f"{'#' * 60}")
        
        try:
            self.scraper = M3U8Scraper()
            channels = self.scraper.scrape()
            
            if channels:
                logger.info(
                    f"\n✓ {len(channels)} kanal başarıyla güncellendi"
                )
            else:
                logger.warning("Hiç kanal bulunamadı!")
                
        except Exception as e:
            logger.error(f"Tarama hatası: {e}", exc_info=True)
        
        finally:
            if self.scraper:
                self.scraper._close_selenium()
    
    def start(self):
        """Zamanlayıcıyı başlat"""
        logger.info(f"Zamanlayıcı başlatıldı")
        logger.info(f"Güncelleme aralığı: {UPDATE_INTERVAL} dakika")
        
        # İlk çalıştırma
        self.run_scraper()
        
        # Periyodik çalıştırma
        schedule.every(UPDATE_INTERVAL).minutes.do(self.run_scraper)
        
        logger.info(
            f"\nSonraki güncelleme: {UPDATE_INTERVAL} dakika sonra"
        )
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nProgram durduruldu (Ctrl+C)")
            if self.scraper:
                self.scraper._close_selenium()


# ============================================
# GİRİŞ NOKTASI
# ============================================
def main():
    """Ana fonksiyon"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='M3U8 Link Scraper ve Otomatik Güncelleyici'
    )
    parser.add_argument(
        '--url', '-u',
        type=str,
        help='Taranacak URL',
        default=None
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Çıktı dosyası',
        default=OUTPUT_FILE
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Sadece bir kez çalıştır'
    )
    parser.add_argument(
        '--interval', '-i',
        type=int,
        help='Güncelleme aralığı (dakika)',
        default=UPDATE_INTERVAL
    )
    parser.add_argument(
        '--no-selenium',
        action='store_true',
        help='Selenium kullanma'
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Sadece mevcut M3U dosyasını kontrol et'
    )
    
    args = parser.parse_args()
    
    # Ayarları güncelle
    global TARGET_URL, OUTPUT_FILE, UPDATE_INTERVAL, USE_SELENIUM
    
    if args.url:
        TARGET_URL = args.url
    if args.output:
        OUTPUT_FILE = args.output
    if args.interval:
        UPDATE_INTERVAL = args.interval
    if args.no_selenium:
        USE_SELENIUM = False
    
    # Mevcut M3U kontrolü
    if args.check_only:
        if os.path.exists(OUTPUT_FILE):
            scraper = M3U8Scraper()
            # M3U dosyasını oku ve kontrol et
            logger.info(f"M3U dosyası kontrol ediliyor: {OUTPUT_FILE}")
            # ... (kontrol mantığı)
        else:
            logger.error(f"M3U dosyası bulunamadı: {OUTPUT_FILE}")
        return
    
    print("""
    ╔══════════════════════════════════════════════╗
    ║       M3U8 Link Scraper & Güncelleyici      ║
    ╠══════════════════════════════════════════════╣
    ║  Hedef:    {:<33}║
    ║  Çıktı:    {:<33}║
    ║  Aralık:   {:<33}║
    ║  Selenium: {:<33}║
    ╚══════════════════════════════════════════════╝
    """.format(
        TARGET_URL[:33],
        OUTPUT_FILE[:33],
        f"{UPDATE_INTERVAL} dakika",
        "Evet" if USE_SELENIUM and SELENIUM_AVAILABLE else "Hayır"
    ))
    
    if args.once:
        # Tek seferlik çalıştırma
        scraper = M3U8Scraper()
        try:
            scraper.scrape()
        finally:
            scraper._close_selenium()
    else:
        # Sürekli çalıştırma
        scheduler = Scheduler()
        scheduler.start()


if __name__ == '__main__':
    main()
