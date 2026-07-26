import json
import time
import re
import sys

# --------------------------------------------------------------------------
# Second source: The Skindex (minecraftskins.com) — FULL-BODY player skins.
#
# The Skindex sits behind Cloudflare's *managed* challenge, which inspects the
# TLS fingerprint of the client. cloudscraper does NOT fake that fingerprint,
# so from a GitHub Actions datacenter IP it receives a challenge page with no
# skins -> empty result. We use curl_cffi with impersonate="chrome", which
# presents a real Chrome TLS/JA3 fingerprint and passes the challenge.
#
# Fallback order: curl_cffi -> cloudscraper -> plain requests.
# If we still can't get real content, we EXIT NON-ZERO so the workflow fails
# visibly instead of committing an empty [] file.
# --------------------------------------------------------------------------

BASE = "https://www.minecraftskins.com"
BASE_PATH = "latest"          # feed to walk: "latest", "" (top), "most-downloaded", ...
MAX_PAGES = 250               # ~48 skins/page -> ~12,000 skins. Lower to 5 for a quick test.
PAGE_DELAY = 1.5              # polite delay between page requests
RETRIES = 4                   # attempts per page before giving up on it

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/",
}

DETAIL_RE = re.compile(r'/skin/(\d+)/([^/"\')\s]+)/')
PREVIEW_RE = re.compile(
    r'(https://www\.minecraftskins\.com/uploads/preview-skins/[^\s"\')?]+?-(\d+)\.png)'
)

# Markers that mean Cloudflare served a challenge instead of the real page.
CHALLENGE_MARKERS = (
    "Just a moment",
    "Enable JavaScript and cookies to continue",
    "cf-mitigated",
    "challenge-platform",
    "cf_chl_opt",
)


def build_client():
    """Return a (get_fn, label) tuple. get_fn(url) -> (status_code, text)."""
    # 1) curl_cffi with Chrome impersonation (best against Cloudflare).
    try:
        from curl_cffi import requests as cr
        session = cr.Session(impersonate="chrome", headers=HEADERS, timeout=60)

        def get(url):
            r = session.get(url)
            return r.status_code, r.text

        return get, "curl_cffi(chrome)"
    except Exception as e:
        print(f"curl_cffi unavailable ({e}); trying cloudscraper...")

    # 2) cloudscraper fallback.
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )

        def get(url):
            r = scraper.get(url, headers=HEADERS, timeout=60)
            return r.status_code, r.text

        return get, "cloudscraper"
    except Exception as e:
        print(f"cloudscraper unavailable ({e}); falling back to requests...")

    # 3) plain requests (usually blocked, but last resort).
    import requests
    session = requests.Session()
    session.headers.update(HEADERS)

    def get(url):
        r = session.get(url, timeout=60)
        return r.status_code, r.text

    return get, "requests"


def looks_blocked(status, html):
    if status in (403, 429, 503):
        return True
    head = html[:4000]
    return any(marker in head for marker in CHALLENGE_MARKERS)


def fetch_page(get, url):
    """Fetch one page with retries. Returns HTML text, or None if blocked."""
    for attempt in range(1, RETRIES + 1):
        try:
            status, html = get(url)
            if status == 200 and not looks_blocked(status, html):
                return html
            reason = "challenge" if looks_blocked(status, html) else f"status {status}"
            print(f"  Attempt {attempt}/{RETRIES} blocked ({reason}).")
        except Exception as e:
            print(f"  Attempt {attempt}/{RETRIES} error: {e}")
        time.sleep(2 * attempt)  # exponential backoff
    return None


def parse_page(html):
    page_ids = {}
    for m in DETAIL_RE.finditer(html):
        page_ids.setdefault(m.group(1), m.group(2))
    previews = {m.group(2): m.group(1) for m in PREVIEW_RE.finditer(html)}
    return page_ids, previews


def get_all_skins_data():
    get, label = build_client()
    print(f"HTTP client: {label}")

    all_skins = []

    for page in range(1, MAX_PAGES + 1):
        url = f"{BASE}/{BASE_PATH}/{page}/" if BASE_PATH else f"{BASE}/{page}/"
        print(f"Fetching page {page}/{MAX_PAGES}: {url}")

        html = fetch_page(get, url)
        if html is None:
            if page == 1:
                # Never even got past the first page -> hard block. Fail loudly.
                print("\nERROR: Cloudflare blocked the very first page. "
                      "Not writing an empty file.")
                sys.exit(1)
            print("  Giving up on this page after retries; stopping.")
            break

        page_ids, previews = parse_page(html)
        if not page_ids:
            if page == 1:
                snippet = html[:300].replace("\n", " ")
                print("\nERROR: First page returned no skins. "
                      f"Response starts with: {snippet!r}")
                sys.exit(1)
            print("  No skins found on this page. Reached the end!")
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

    unique_skins = list({s["id"]: s for s in all_skins}.values())

    # Safety net: refuse to overwrite with an empty/near-empty result.
    if len(unique_skins) == 0:
        print("\nERROR: Collected 0 skins. Aborting without writing.")
        sys.exit(1)

    print(f"\nFinished! Collected {len(unique_skins)} unique full-body skins.")
    with open("skindex_data.json", "w") as f:
        json.dump(unique_skins, f, indent=4)
    print("Saved to skindex_data.json.")


if __name__ == "__main__":
    get_all_skins_data()
