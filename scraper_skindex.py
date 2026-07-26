import json
import time
import re
import sys
from playwright.sync_api import sync_playwright

# --------------------------------------------------------------------------
# The Skindex (minecraftskins.com) — FULL-BODY skins, behind Cloudflare's
# "Just a moment..." JS challenge.
#
# A plain headless browser gets DETECTED and the challenge never clears. This
# version fights that with:
#   1. Headful Chromium (headless=False) run under Xvfb on the CI runner.
#   2. Stealth init script that removes automation signals (navigator.webdriver,
#      etc.) BEFORE any page script runs.
#   3. A wait loop that gives the challenge time and reloads if it's stuck.
#
# The workflow MUST run this via `xvfb-run` (see skindex.yml).
#
# Honest note: if Cloudflare escalates the Actions IP to an *interactive*
# Turnstile, no headless-runner trick passes it. In that case run this same
# file locally (home IP clears it instantly) or use the Hugging Face dataset.
# --------------------------------------------------------------------------

BASE = "https://www.minecraftskins.com"
BASE_PATH = "latest"
MAX_PAGES = 250               # lower to 5 for a quick test
PAGE_DELAY = 1.5
CHALLENGE_WAIT = 30           # seconds to let the challenge clear on a page
NAV_TIMEOUT = 60000           # ms

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = { runtime: {} };
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (
  p && p.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : origQuery(p)
);
"""

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


def wait_for_clearance(page):
    """Return True once real skin links appear; reload if stuck on challenge."""
    deadline = time.time() + CHALLENGE_WAIT
    reloaded = False
    while time.time() < deadline:
        try:
            if page.query_selector("a[href*='/skin/']"):
                return True
        except Exception:
            pass
        title = ""
        try:
            title = page.title()
        except Exception:
            pass
        if "just a moment" in title.lower() or "attention" in title.lower():
            # Give it time; try one reload halfway through.
            if not reloaded and time.time() > deadline - CHALLENGE_WAIT / 2:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                except Exception:
                    pass
                reloaded = True
        time.sleep(1)
    return bool(page.query_selector("a[href*='/skin/']"))


def get_all_skins_data():
    all_skins = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # headful under Xvfb — key to passing detection
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--start-maximized",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        context.add_init_script(STEALTH_JS)
        page = context.new_page()

        for page_num in range(1, MAX_PAGES + 1):
            url = f"{BASE}/{BASE_PATH}/{page_num}/" if BASE_PATH else f"{BASE}/{page_num}/"
            print(f"Fetching page {page_num}/{MAX_PAGES}: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            except Exception as e:
                print(f"  Navigation error: {e}")
                if page_num == 1:
                    browser.close()
                    sys.exit(1)
                break

            if not wait_for_clearance(page):
                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass
                print(f"  Challenge did not clear (title: {title!r}).")
                if page_num == 1:
                    print("\nERROR: Cloudflare challenge never cleared on the first "
                          "page. Not writing an empty file.\n"
                          "This means the Actions IP is being blocked. Run locally "
                          "or use the Hugging Face dataset instead.")
                    browser.close()
                    sys.exit(1)
                print("  Stopping.")
                break

            html = page.content()
            page_ids, previews = parse_html(html)
            if not page_ids:
                if page_num == 1:
                    browser.close()
                    print("\nERROR: First page returned no skins after challenge.")
                    sys.exit(1)
                print("  No skins found. Reached the end!")
                break

            for sid, slug in page_ids.items():
                all_skins.append({
                    "id": sid,
                    "name": slug.replace("-", " ").strip(),
                    "skin_url": f"{BASE}/skin/{sid}/{slug}/",
                    "download_url": f"{BASE}/skin/download/{sid}",
                    "preview_url": previews.get(sid),
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
