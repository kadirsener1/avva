import time
from scraper import get_m3u8_links
from parser import get_channel_pages
from writer import save_to_m3u

def update():
    print("Güncelleme başladı...")

    pages = get_channel_pages()
    channels = []

    for page in pages:
        print("Tarama:", page)

        links = get_m3u8_links(page)

        if links:
            channels.append((page.split("/")[-1], links[0]))

    save_to_m3u(channels)

    print("Tamamlandı.")

if __name__ == "__main__":
    while True:
        update()
        time.sleep(1800)  # 30 dakika
