from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    page = browser.new_page()

    def log_request(request):
        print(request.method, request.url)

    page.on("request", log_request)

    page.goto(
        "https://laby.net/skins?order=most_used",
        wait_until="domcontentloaded",
        timeout=120000
    )

    page.wait_for_timeout(10000)

    browser.close()
