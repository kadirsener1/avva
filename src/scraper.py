from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor

def scrape_page(context, url):
    page = context.new_page()
    links = []

    def handle_response(response):
        if ".m3u8" in response.url:
            links.append(response.url)

    page.on("response", handle_response)

    try:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(5000)
    except:
        pass

    page.close()
    return list(set(links))


def get_m3u8_links_bulk(urls, max_workers=5):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(scrape_page, context, url) for url in urls]

            for future, url in zip(futures, urls):
                try:
                    links = future.result()
                    if links:
                        results.append((url, links[0]))
                except:
                    pass

        browser.close()

    return results
