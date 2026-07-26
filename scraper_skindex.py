import json
import time
import re
import cloudscraper

# --------------------------------------------------------------------------
# Second source: The Skindex (minecraftskins.com) — FULL-BODY player skins.
#
# Unlike laby.net, The Skindex has no clean JSON API; it's HTML. But each
# gallery page lists ~48 skins, so you get many skins per request (few
# requests overall). For every skin we derive:
#   - the detail page URL
#   - a direct download URL for the raw 64x64 skin PNG
#   - the preview/render thumbnail
#
# These are community uploads hosted on minecraftskins.com (not on Mojang's
# texture server), so entries use the Skindex skin id instead of a
# textures.minecraft.net hash. That's expected for community skins.
#
# Listing feeds you can point BASE_PATH at:
#   latest/   -> newest skins
#   ''        -> top skins (homepage pagination, e.g. /2/, /3/ ...)
#   most-downloaded/ , trending/ , etc.
# --------------------------------------------------------------------------

BASE = "https://www.minecraftskins.com"
BASE_PATH = "latest"          # which feed to walk
MAX_PAGES = 250               # ~48 skins/page -> ~12,000 skins
PAGE_DELAY = 1.5              # polite delay between page requests

DETAIL_RE = re.compile(r'/skin/(\d+)/([^/"\')\s]+)/')
PREVIEW_RE = re.compile(
    r'(https://www\.minecraftskins\.com/uploads/preview-skins/[^\s"\')?]+?-(\d+)\.png)'
)


def get_all_skins_data():
    print("Initializing Cloudscraper for The Skindex...")
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True}
    )

    all_skins = []

    for page in range(1, MAX_PAGES + 1):
        url = f"{BASE}/{BASE_PATH}/{page}/" if BASE_PATH else f"{BASE}/{page}/"
        print(f"Fetching page {page}/{MAX_PAGES}: {url}")

        try:
            response = scraper.get(url, timeout=60)
            if response.status_code != 200:
                print(f"  Failed ({response.status_code}). Stopping.")
                break

            html = response.text

            # Collect skin ids + slugs from detail links (deduped per page).
            page_ids = {}
            for m in DETAIL_RE.finditer(html):
                page_ids.setdefault(m.group(1), m.group(2))

            # Map id -> preview thumbnail (new-format filenames end with -<id>.png).
            previews = {m.group(2): m.group(1) for m in PREVIEW_RE.finditer(html)}

            if not page_ids:
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

        except Exception as e:
            print(f"  Error on page {page}: {e}")
            break

    # Deduplicate across pages by id.
    unique_skins = list({s["id"]: s for s in all_skins}.values())
    print(f"\nFinished! Collected {len(unique_skins)} unique full-body skins.")

    with open("skindex_data.json", "w") as f:
        json.dump(unique_skins, f, indent=4)
    print("Saved to skindex_data.json.")


if __name__ == "__main__":
    get_all_skins_data()
