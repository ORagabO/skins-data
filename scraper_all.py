import os
import json
import time
import re
import random
import sys
from collections import defaultdict
from bs4 import BeautifulSoup

# ==========================================================================
# Multi-source Minecraft skin collector with INITIAL BACKFILL + INCREMENTAL.
#
# Sources: TLauncher, Xyrios, The Skindex, NameMC, minecraftskins.net
#
# OUTPUT schema (only these fields, per request):
#   {
#     "source": <site>,
#     "name":   <str or null>,
#     "image":  <url or null>,
#     "download": <url>          # key OMITTED entirely when not available
#   }
#
# Internally each scraper still produces an "id" (+ image_url/download_url) so
# de-duplication and incremental "add-only-new" keep working. Ids are stripped
# at save time and re-derived from the stored URLs on the next run.
# ==========================================================================

# ---- toggles -------------------------------------------------------------
ENABLE_TLAUNCHER = True
ENABLE_XYRIOS = True
ENABLE_SKINDEX = True
ENABLE_NAMEMC = True
ENABLE_MCNET = True

# ---- INITIAL run depths — set HIGH to pull the MAXIMUM number of skins ----
# Each source paginates until it runs out or hits its cap. Raise for more.
INIT_TLAUNCHER = 1000
INIT_XYRIOS = 1000
INIT_SKINDEX = 1000
INIT_NAMEMC = 1000
INIT_MCNET = 100

# ---- INCREMENTAL run depths (small; early-stop ends them sooner) ---------
UPD_TLAUNCHER = 30
UPD_XYRIOS = 30
UPD_SKINDEX = 40
UPD_NAMEMC = 40
UPD_MCNET = 30

STOP_AFTER_KNOWN_PAGES = 2   # incremental: stop a source after N all-known pages

OUTPUT = "skins_all.json"
SHUFFLE = True
MAX_TOTAL_FIRST_RUN = None
DEBUG_SAMPLES = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
"""

# -------------------------------------------------------------- TLauncher ---
# -------------------------------------------------------------- TLauncher ---
TL_BASE = "https://tlauncher.org/en/catalog/skins"

def scrape_tlauncher(max_pages, known_ids, incremental):
    from playwright.sync_api import sync_playwright
    out, seen = [], set()
    known_streak = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768}, locale="en-US")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()

        for n in range(1, max_pages + 1):
            url = f"{TL_BASE}/" if n == 1 else f"{TL_BASE}/{n}/"
            print(f"  [tlauncher] Navigating to page {n}/{max_pages} -> {url}")

          try:
                # 1. Change wait_until to "networkidle" so it waits for background APIs to finish
                page.goto(url, wait_until="networkidle", timeout=60000)
                
                # 2. Scroll to the bottom of the page to trigger any lazy-loaded XHR scripts
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                # 3. Give the DOM an extra 3 seconds to inject the skins after the scroll
                page.wait_for_timeout(3000) 
            except Exception as e:
                print(f"  [tlauncher] Navigation error or timeout: {e}")
                break

            content = page.content()
            found_ids = set()
            
            # --- THE FIX: Double Regex Net ---
            
            # 1. Grab IDs from the Download links
            for m in re.finditer(r'/download/(\d+)\.png', content):
                found_ids.add(m.group(1))
                
            # 2. Grab IDs from the Image Thumbnails (Guaranteed to be there)
            for m in re.finditer(r'/catalog/skins/(\d+)/img', content):
                found_ids.add(m.group(1))

            # ---------------------------------

            print(f"  [tlauncher] DEBUG: Found {len(found_ids)} total skins on this page.")

            if not found_ids:
                print("  [tlauncher] DEBUG: 0 skins found. The page might be empty or blocked. Stopping.")
                break
                
            page_new = 0
            
            for sid in found_ids:
                if sid in seen:
                    continue
                seen.add(sid)
                
                if sid not in known_ids:
                    page_new += 1

                dl_url = f"https://tlauncher.org/catalog/skins/download/{sid}.png"
                image_url = f"https://tlauncher.org/catalog/skins/{sid}/img/0/"

                out.append({
                    "source": "tlauncher",
                    "name": f"TLauncher Skin {sid}",
                    "image_url": image_url,
                    "download_url": dl_url,
                    "downloads": None,
                    "id": sid,
                })

            print(f"  [tlauncher] DEBUG: {page_new} of those skins were BRAND NEW.")

            if page_new == 0 and incremental:
                known_streak += 1
                print(f"  [tlauncher] DEBUG: Hit known skins. Streak: {known_streak}/{STOP_AFTER_KNOWN_PAGES}")
                if known_streak >= STOP_AFTER_KNOWN_PAGES:
                    print("  [tlauncher] Reached known skins limit. Stopping to save time."); break
            elif page_new == 0:
                print(f"  [tlauncher] DEBUG: Found {len(found_ids)} skins, but ALL of them were duplicates of Page 1. Stopping to prevent an infinite loop.")
                break
            else:
                known_streak = 0

        browser.close()
        
    return out
# -------------------------------------------------------------- Xyrios ---
XYRIOS_BASE = "https://xyrios.com/minecraft/skins"

def scrape_xyrios(max_pages, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True})
    out, seen = [], set()
    known_streak = 0

    for n in range(1, max_pages + 1):
        url = XYRIOS_BASE if n == 1 else f"{XYRIOS_BASE}?page={n}"
        print(f"  [xyrios] page {n}/{max_pages}")

        try:
            r = scraper.get(url, timeout=60)
        except Exception as e:
            print(f"  [xyrios] request error: {e}"); break

        if r.status_code != 200:
            print(f"  [xyrios] status {r.status_code}, stopping."); break

        soup = BeautifulSoup(r.text, "html.parser")
        images = soup.find_all("img", src=re.compile(r'\.png'))

        page_new = 0
        found_any = False

        for img in images:
            src = img.get("src") or img.get("data-src") or ""
            name = img.get("alt") or img.get("title") or "Xyrios Skin"

            m = re.search(r'([^/]+)\.png', src)
            sid = m.group(1) if m else None
            if not sid or sid in seen:
                continue
            seen.add(sid)
            found_any = True
            if sid not in known_ids:
                page_new += 1

            clean_src = src if src.startswith("http") else f"https://xyrios.com{src}"
            download_url = f"https://cdn.xyrios.com/skins/{sid}.png"

            out.append({
                "source": "xyrios",
                "name": name.strip(),
                "image_url": clean_src,
                "download_url": download_url,
                "downloads": None,
                "id": sid,
            })

        if not found_any:
            print("  [xyrios] No skins found on this page. Stopping.")
            break
        if page_new == 0 and incremental:
            known_streak += 1
            if known_streak >= STOP_AFTER_KNOWN_PAGES:
                print("  [xyrios] reached known skins; stopping."); break
        elif page_new == 0:
            break
        else:
            known_streak = 0
        time.sleep(1.5)

    return out

# ---------------------------------------------------------------- Skindex ---
SKX_BASE = "https://www.minecraftskins.com"
HREF_RE = re.compile(r'/skin/(\d+)/([^/?#"\']+)')
IMG_RE = re.compile(r'/uploads/(?:preview-)?skins/[^\s"\']*?-(\d+)\.png')

def _skx_extract(page):
    js = """els => els.map(a => {
        const img = a.querySelector('img');
        return {
            href: a.getAttribute('href') || '',
            name: img ? (img.getAttribute('alt') || '') : a.textContent.trim(),
            src: img ? (img.currentSrc || img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('data-original') || '') : ''
        };
    })"""
    items = page.eval_on_selector_all("a[href*='/skin/']", js)
    ids, imgs, names = {}, {}, {}
    for item in items:
        h = item.get('href', '')
        m = HREF_RE.search(h)
        if not m:
            continue
        sid = m.group(1)
        slug = m.group(2)
        ids.setdefault(sid, slug)

        extracted_name = item.get('name', '').strip()
        if extracted_name and not names.get(sid):
            names[sid] = extracted_name

        s = item.get('src', '')
        m_img = IMG_RE.search(s)
        if m_img:
            img_sid = m_img.group(1)
            clean = s.split("?")[0]
            if clean.startswith("/"):
                clean = SKX_BASE + clean
            imgs[img_sid] = clean

    return ids, imgs, names

def scrape_skindex(max_pages, known_ids, incremental):
    from playwright.sync_api import sync_playwright
    out = []
    known_streak = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768}, locale="en-US")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()
        for n in range(1, max_pages + 1):
            print(f"  [skindex] page {n}/{max_pages}")
            try:
                page.goto(f"{SKX_BASE}/latest/{n}/",
                          wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  [skindex] nav error: {e}"); break
            cleared = False
            for attempt in range(3):
                deadline = time.time() + 25
                while time.time() < deadline:
                    if page.query_selector("a[href*='/skin/']"):
                        cleared = True; break
                    time.sleep(1)
                if cleared:
                    break
                print(f"  [skindex] challenge not cleared (attempt {attempt+1}/3); reloading...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
            if not cleared:
                print("  [skindex] challenge not cleared; skipping source."); break

            ids, imgs, names = _skx_extract(page)
            if not ids:
                break
            page_new = 0
            for sid, slug in ids.items():
                if sid not in known_ids:
                    page_new += 1
                proper_name = names.get(sid) or slug.replace("-", " ").strip()
                out.append({
                    "source": "skindex",
                    "name": proper_name,
                    "image_url": imgs.get(sid) or f"{SKX_BASE}/skin/download/{sid}",
                    "download_url": f"{SKX_BASE}/skin/download/{sid}",
                    "downloads": None,
                    "id": sid,
                })
            if incremental:
                known_streak = known_streak + 1 if page_new == 0 else 0
                if known_streak >= STOP_AFTER_KNOWN_PAGES:
                    print("  [skindex] reached known skins; stopping."); break
            time.sleep(1.5)
        browser.close()
    return out

# ----------------------------------------------------------------- NameMC ---
NMC_BASE = "https://namemc.com/minecraft-skins"
NMC_ID_RE = re.compile(r'/skin/([0-9a-fA-F]+)')
NMC_JS = """els => els.map(card => {
  const a = card.querySelector("a[href^='/skin/']");
  const img = card.querySelector('img');
  const q = (s) => { const e = card.querySelector(s); return e ? e.textContent.trim() : ''; };
  return {
    href: a ? a.getAttribute('href') : '',
    name: q('.card-header'),
    src: img ? (img.getAttribute('data-src') || img.currentSrc || img.getAttribute('src') || '') : '',
    stat_end: q('.position-absolute.bottom-0.end-0'),
  };
})"""

def scrape_namemc(max_pages, known_ids, incremental):
    from playwright.sync_api import sync_playwright
    out, seen = [], set()
    known_streak = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 900}, locale="en-US")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()
        for n in range(1, max_pages + 1):
            url = NMC_BASE if n == 1 else f"{NMC_BASE}?page={n}"
            print(f"  [namemc] page {n}/{max_pages}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  [namemc] nav error: {e}"); break
            cleared = False
            for attempt in range(3):
                deadline = time.time() + 25
                while time.time() < deadline:
                    if page.query_selector("a[href^='/skin/']"):
                        cleared = True; break
                    time.sleep(1)
                if cleared:
                    break
                print(f"  [namemc] challenge not cleared (attempt {attempt+1}/3); reloading...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
            if not cleared:
                print("  [namemc] cards not found; skipping source."); break
            cards = page.eval_on_selector_all("div.card", NMC_JS)
            if DEBUG_SAMPLES and cards:
                print("  [namemc] SAMPLE:", json.dumps(cards[0])[:400])
            page_new = 0
            for c in cards:
                m = NMC_ID_RE.search(c.get("href") or "")
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                seen.add(sid)
                if sid not in known_ids:
                    page_new += 1
                img = c.get("src") or (
                    f"https://s.namemc.com/3d/skin/body.png?id={sid}&model=slim&width=256&height=256")
                out.append({
                    "source": "namemc",
                    "name": c.get("name") or None,
                    "image_url": img,
                    "download_url": f"https://namemc.com/skin/{sid}",
                    "downloads": c.get("stat_end") or None,
                    "id": sid,
                })
            if page_new == 0 and incremental:
                known_streak += 1
                if known_streak >= STOP_AFTER_KNOWN_PAGES:
                    print("  [namemc] reached known skins; stopping."); break
            elif page_new == 0:
                break
            else:
                known_streak = 0
            time.sleep(1.5)
        browser.close()
    return out

# -------------------------------------------------------- minecraftskins.net --
NET_BASE = "https://www.minecraftskins.net"
NET_IMG_RE = re.compile(r'<img\s+[^>]*src="(/static/front_preview/([^"./]+)\.png)"[^>]*>', re.I)

def scrape_mcskins_net(max_pages, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True})
    out, seen = [], set()
    known_streak = 0
    for n in range(1, max_pages + 1):
        url = NET_BASE if n == 1 else f"{NET_BASE}/page/{n}"
        print(f"  [mcnet] page {n}/{max_pages}")
        try:
            r = scraper.get(url, timeout=60)
        except Exception as e:
            print(f"  [mcnet] request error: {e}"); break
        if r.status_code != 200:
            print(f"  [mcnet] status {r.status_code}, stopping."); break

        matches = NET_IMG_RE.finditer(r.text)
        found_any = False
        page_new = 0
        for m in matches:
            found_any = True
            img_tag = m.group(0)
            img_path = m.group(1)
            slug = m.group(2)

            alt_m = re.search(r'alt="([^"]*)"', img_tag, re.I)
            name = alt_m.group(1).strip() if alt_m else slug

            if slug in seen:
                continue
            seen.add(slug)
            if slug not in known_ids:
                page_new += 1
            out.append({
                "source": "mcnet",
                "name": name,
                "image_url": f"{NET_BASE}{img_path}",
                "download_url": f"{NET_BASE}/{slug}/download",
                "downloads": None,
                "id": slug,
            })

        if not found_any:
            break
        if page_new == 0 and incremental:
            known_streak += 1
            if known_streak >= STOP_AFTER_KNOWN_PAGES:
                print("  [mcnet] reached known skins; stopping."); break
        elif page_new == 0:
            break
        else:
            known_streak = 0
        time.sleep(1.2)
    return out


# ------------------------------------------------------------- helpers -----
def derive_id(e):
    """Re-derive a stable per-source id from a stored minimal entry's URLs,
    so incremental de-dup keeps working even though 'id' isn't saved."""
    src = e.get("source")
    img = e.get("image") or e.get("image_url") or ""
    dl = e.get("download") or e.get("download_url") or ""
    if src == "tlauncher":
        m = re.search(r'/catalog/skins/(\d+)/img', img) or re.search(r'/download/(\d+)\.png', dl)
    elif src == "xyrios":
        m = re.search(r'/([^/]+)\.png', dl) or re.search(r'/([^/]+)\.png', img)
    elif src == "skindex":
        m = re.search(r'/skin/download/(\d+)', dl) or re.search(r'-(\d+)\.png', img)
    elif src == "namemc":
        m = re.search(r'/skin/([0-9a-fA-F]+)', dl) or re.search(r'[?&]id=([0-9a-fA-F]+)', img)
    elif src == "mcnet":
        m = re.search(r'/([^/]+)/download', dl) or re.search(r'front_preview/([^/.]+)\.png', img)
    else:
        m = None
    return m.group(1) if m else (img or dl or e.get("name"))


def project(e):
    """Reduce any entry to the required output schema:
    source, name (or null), image (or null), download (only if present)."""
    name = e.get("name")
    image = e.get("image") or e.get("image_url")
    download = e.get("download") or e.get("download_url")
    out = {
        "source": e.get("source"),
        "name": name if name not in ("", None) else None,
        "image": image if image not in ("", None) else None,
    }
    if download:
        out["download"] = download
    return out


# -------------------------------------------------------------------- main --
def load_existing(path):
    abspath = os.path.abspath(path)
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            # New format: {"total":..., "sources":..., "skins":[...]}
            if isinstance(data, dict) and isinstance(data.get("skins"), list):
                print(f"Loaded {len(data['skins'])} existing skins from {abspath}")
                return data["skins"]
            # Old format: a bare list of skins
            if isinstance(data, list):
                print(f"Loaded {len(data)} existing skins from {abspath}")
                return data
            print(f"WARNING: {abspath} has unexpected shape; treating as first run.")
        except Exception as e:
            print(f"WARNING: couldn't read {abspath} ({e}); treating as first run.")
    else:
        print(f"No existing file at {abspath} -> FIRST RUN.")
    return []

def main():
    existing = load_existing(OUTPUT)
    # Attach a working 'id' back onto minimal stored entries for de-dup.
    for e in existing:
        if not e.get("id"):
            e["id"] = derive_id(e)

    prev_count = len(existing)
    first_run = len(existing) == 0
    print(f"Mode: {'FIRST RUN (backfill)' if first_run else 'INCREMENTAL (add new only)'}"
          f" | existing entries: {len(existing)}")

    existing_keys = {(e.get("source"), e.get("id")) for e in existing}
    known_by_source = defaultdict(set)
    for e in existing:
        known_by_source[e.get("source")].add(e.get("id"))

    depth = ({"tlauncher": INIT_TLAUNCHER, "xyrios": INIT_XYRIOS, "skindex": INIT_SKINDEX,
              "namemc": INIT_NAMEMC, "mcnet": INIT_MCNET} if first_run else
             {"tlauncher": UPD_TLAUNCHER, "xyrios": UPD_XYRIOS, "skindex": UPD_SKINDEX,
              "namemc": UPD_NAMEMC, "mcnet": UPD_MCNET})
    incremental = not first_run

    jobs = []
    if ENABLE_TLAUNCHER:
        jobs.append(("tlauncher", lambda: scrape_tlauncher(depth["tlauncher"], known_by_source["tlauncher"], incremental)))
    if ENABLE_XYRIOS:
        jobs.append(("xyrios", lambda: scrape_xyrios(depth["xyrios"], known_by_source["xyrios"], incremental)))
    if ENABLE_SKINDEX:
        jobs.append(("skindex", lambda: scrape_skindex(depth["skindex"], known_by_source["skindex"], incremental)))
    if ENABLE_NAMEMC:
        jobs.append(("namemc", lambda: scrape_namemc(depth["namemc"], known_by_source["namemc"], incremental)))
    if ENABLE_MCNET:
        jobs.append(("mcnet", lambda: scrape_mcskins_net(depth["mcnet"], known_by_source["mcnet"], incremental)))

    scraped = []
    for name, fn in jobs:
        print(f"=== Source: {name} ===")
        try:
            got = fn()
            print(f"[{name}] scraped {len(got)} items.")
            scraped.extend(got)
        except Exception as e:
            print(f"[{name}] FAILED, skipping: {e}")

    added = 0
    for sk in scraped:
        key = (sk.get("source"), sk.get("id"))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        existing.append(sk)
        added += 1

    deduped, seen_keys = [], set()
    for sk in existing:
        key = (sk.get("source"), sk.get("id"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(sk)
    existing = deduped

    if first_run and MAX_TOTAL_FIRST_RUN:
        existing = existing[:MAX_TOTAL_FIRST_RUN]
    if SHUFFLE:
        random.shuffle(existing)

    if not existing:
        print("\nERROR: nothing collected and no existing data. Not writing.")
        sys.exit(1)

    if not first_run and len(existing) < prev_count:
        print(f"\nERROR: merged total ({len(existing)}) is smaller than existing "
              f"({prev_count}). Aborting to avoid replacing your data.")
        sys.exit(1)

    by_source = defaultdict(int)
    for e in existing:
        by_source[e.get("source")] += 1
    print(f"\nAdded {added} new skins this run. Total now: {len(existing)}.")
    print("Skins per source:")
    for src, cnt in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  {src:<12} {cnt}")

    # Write ONLY the required fields, with totals at the TOP of the file.
    output_data = [project(e) for e in existing]
    payload = {
        "total": len(output_data),
        "sources": dict(by_source),
        "skins": output_data,
    }
    with open(OUTPUT, "w") as f:
        json.dump(payload, f, indent=4)
    print(f"Saved {len(output_data)} skins to {OUTPUT}.")

if __name__ == "__main__":
    main()
