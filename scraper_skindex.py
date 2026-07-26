import json
import time
import re
import sys
from playwright.sync_api import sync_playwright

# --------------------------------------------------------------------------
# Second source: The Skindex (minecraftskins.com) — FULL-BODY player skins.
#
# The Skindex is behind Cloudflare's JavaScript challenge ("Just a moment...").
# Non-browser tools (cloudscraper, curl_cffi) can't EXECUTE that challenge JS,
# so they get stuck on the interstitial. We use a real headless Chromium via
# Playwright: it runs the challenge, receives the cf_clearance cookie, and then
# loads the gallery pages normally. The cookie is reused across pages (same
# browser context), so only the first page pays the challenge cost.
#
# If the challenge never clears on the first page, we EXIT NON-ZERO instead of
# writing an empty file.
# --------------------------------------------------------------------------

BASE = "https://www.minecraftskins.com"
BASE_PATH = "latest"          # feed to walk: "latest", "" (top), "most-downloaded", ...
MAX_PAGES = 250               # ~48 skins/page -> ~12,000 skins. Lower to 5 for a quick test.
PAGE_DELAY = 1.5              # polite delay between pages
NAV_TIMEOUT = 45000          # ms to wait for a page (challenge can take a few seconds)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

DETAIL_RE = re.compile(r'/skin/(\d+)/([^/"\')\s]+)/')
PREVIEW_RE = re.compile(
    r'(https://www\.minecraftskins\.com/uploads/preview-skins/[^\s"\')?]+?-(\d+)\.png)'
)


def parse_html(html):
    page_ids = {}
    for m in DETAIL_RE.finditer(html):
        page_ids.setdefault(m.group(1), m.group(2))
    previews = {m.group(2): m.group(1) for m in PREVIEW_RE.finditer(html)}
    return page_ids, previews


def get_all_skins_data():
    all_skins = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        for page_num in range(1, MAX_PAGES + 1):
            url = f"{BASE}/{BASE_PATH}/{page_num}/" if BASE_PATH else f"{BASE}/{page_num}/"
            print(f"Fetching page {page_num}/{MAX_PAGES}: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                # Wait until real skin links appear = challenge cleared.
                page.wait_for_selector("a[href*='/skin/']", timeout=NAV_TIMEOUT)
            except Exception as e:
                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass
                print(f"  Timed out waiting for skins (page title: {title!r}). {e}")
                if page_num == 1:
                    print("\nERROR: Cloudflare challenge never cleared on the first "
                          "page. Not writing an empty file.")
                    browser.close()
                    sys.exit(1)
                print("  Stopping.")
                break

            html = page.content()
            page_ids, previews = parse_html(html)

            if not page_ids:
                if page_num == 1:
                    print("\nERROR: First page returned no skins after challenge.")
                    browser.close()
                    sys.exit(1)
                print("  No skins found. Reached the end!")
                break

            for sid, slug in page_ids.items():
                all_skins.append({
                    "id": sid,
                    "name": slug.replace("-", " ").strip(),
                    "skin_url": f"{BASE}/skin/{sid}/{slug}/",
                    "download_url": f"{BASE}/skin/download/{sid}",   # raw 64x64 PNG
                    "preview_url": previews.get(sid),                # 2D render thumbnail
                })

            print(f"  Collected {len(page_ids)} skins (running total: {len(all_skins)}).")
            time.sleep(PAGE_DELAY)

        browser.close()

    unique_skins = list({s["id"]: s for s in all_skins}.values())

    if len(unique_skins) == 0:
        print("\nERROR: Collected 0 skins. Aborting without writing.")
        sys.exit(1)

    print(f"\nFinished! Collected {len(unique_skins)} unique full-body skins.")
    with open("skindex_data.json", "w") as f:
        json.dump(unique_skins, f, indent=4)
    print("Saved to skindex_data.json.")


if __name__ == "__main__":
    get_all_skins_data()
