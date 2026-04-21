from parser import get_channel_pages
from scraper import get_m3u8_links_bulk
from writer import save_to_m3u

def update():
    print("Hızlı tarama başladı...")

    pages = get_channel_pages()

    results = get_m3u8_links_bulk(pages, max_workers=5)

    channels = []
    for url, m3u8 in results:
        name = url.split("/")[-1]
        channels.append((name, m3u8))

    save_to_m3u(channels)

    print(f"{len(channels)} kanal bulundu.")

if __name__ == "__main__":
    update()
