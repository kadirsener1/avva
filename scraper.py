from playwright.sync_api import sync_playwright

def get_m3u8_links(url):
    links = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_response(response):
            if ".m3u8" in response.url:
                links.append(response.url)

        page.on("response", handle_response)

        try:
            page.goto(url, timeout=60000)
            page.wait_for_timeout(8000)
        except Exception as e:
            print("ERROR:", e)

        browser.close()

    return list(set(links))
