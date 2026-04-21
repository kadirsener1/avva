import requests
from bs4 import BeautifulSoup

BASE_URL = "https://avvasportshd1.com"

def get_channel_pages():
    url = f"{BASE_URL}/channels.html"
    r = requests.get(url, timeout=15)

    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]

        if "channel" in href:
            if not href.startswith("http"):
                href = BASE_URL + "/" + href

            links.append(href)

    return list(set(links))
