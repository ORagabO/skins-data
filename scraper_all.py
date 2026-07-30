import os
import json
import time
import re
import random
import sys
from collections import defaultdict
from bs4 import BeautifulSoup

# ==========================================================================
# Multi-source Minecraft skin collector  —  INITIAL BACKFILL + INCREMENTAL
#
# Sources: TLauncher, Xyrios, The Skindex, NameMC, minecraftskins.net,
#          SkinsMC, MineSkin
#
# OUTPUT schema:
#   { "source", "name" (or null), "image" (or null), "download" (omitted if absent) }
# ==========================================================================

ENABLE_TLAUNCHER = True
ENABLE_XYRIOS    = True
ENABLE_SKINDEX   = True
ENABLE_NAMEMC    = True
ENABLE_MCNET     = True
ENABLE_SKINSMC   = True
ENABLE_MINESKIN  = True

# ---- initial depths -------------------------------------------------------
INIT_TLAUNCHER = 200   # scroll passes (each ~15 new skins)
INIT_XYRIOS    = 8000  # pages (24 skins/page, real skins only)
INIT_SKINDEX   = 1000
INIT_NAMEMC    = 1000
INIT_MCNET     = 100
INIT_SKINSMC   = 5000  # pages (40 skins/page)
INIT_MINESKIN  = 500   # API cursor pages (50 skins/page)

# ---- incremental depths ---------------------------------------------------
UPD_TLAUNCHER = 20
UPD_XYRIOS    = 30
UPD_SKINDEX   = 40
UPD_NAMEMC    = 40
UPD_MCNET     = 30
UPD_SKINSMC   = 30
UPD_MINESKIN  = 10

STOP_AFTER_KNOWN_PAGES = 2

OUTPUT         = "skins_all.json"
SHUFFLE        = True
MAX_TOTAL_FIRST_RUN = None
DEBUG_SAMPLES  = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
"""

# ===========================================================================
# TLauncher  —  single infinite-scroll page; must scroll to load all skins
# FIX: stopped using /N/ pagination (those 404). Instead scroll repeatedly.
# ===========================================================================
TL_URL = "https://tlauncher.org/en/catalog/skins/"
TL_DL_RE  = re.compile(r'/catalog/skins/download/(\d+)\.png')
TL_IMG_RE = re.compile(r'/catalog/skins/(\d+)/img')

def scrape_tlauncher(max_scrolls, known_ids, incremental):
    from playwright.sync_api import sync_playwright
    out, seen = [], set()
    known_streak = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  locale="en-US")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()

        print(f"  [tlauncher] loading {TL_URL}")
        try:
            page.goto(TL_URL, wait_until="networkidle", timeout=90000)
        except Exception as e:
            print(f"  [tlauncher] initial load error: {e}")
            browser.close()
            return out

        for scroll in range(1, max_scrolls + 1):
            # Collect all skin ids visible so far
            content = page.content()
            ids_on_page = set()
            for m in TL_DL_RE.finditer(content):
                ids_on_page.add(m.group(1))
            for m in TL_IMG_RE.finditer(content):
                ids_on_page.add(m.group(1))

            page_new = 0
            for sid in ids_on_page:
                if sid in seen:
                    continue
                seen.add(sid)
                if sid not in known_ids:
                    page_new += 1
                out.append({
                    "source": "tlauncher",
                    "name": None,  # names not present on listing page
                    "image_url": f"https://tlauncher.org/catalog/skins/{sid}/img/0/",
                    "download_url": f"https://tlauncher.org/catalog/skins/download/{sid}.png",
                    "id": sid,
                })

            print(f"  [tlauncher] scroll {scroll}/{max_scrolls} | "
                  f"visible {len(ids_on_page)} | new this scroll {page_new} | total {len(out)}")

            if page_new == 0 and incremental:
                known_streak += 1
                if known_streak >= STOP_AFTER_KNOWN_PAGES:
                    print("  [tlauncher] reached known skins; stopping."); break
            elif page_new == 0 and scroll > 3:
                # No new skins after a few scrolls = reached the end
                print("  [tlauncher] no new skins; reached end."); break
            else:
                known_streak = 0

            # Scroll to bottom to trigger lazy-load
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2500)  # wait for new batch to render

        browser.close()
    return out


# ===========================================================================
# Xyrios  —  server-rendered; 176k+ skins
# FIX: old code picked up ALL .png images (logos, icons etc.).
#      Real skin images live at i.xyrios.com/skins/<hash>.png
#      Skin page URLs are /minecraft/skins/<hash>
# ===========================================================================
XY_BASE    = "https://xyrios.com/minecraft/skins"
XY_SKIN_RE = re.compile(r'href="https://xyrios\.com/minecraft/skins/([a-f0-9]{20})"')
XY_IMG_RE  = re.compile(r'https://i\.xyrios\.com/skins/([a-f0-9]{20})\.png')
XY_NAME_RE = re.compile(r'minecraft/skins/[a-f0-9]{20}[^"]*"[^>]*>\s*(?:Rendered[^<]*\d+\s+)?([^\n<]+?)\s+(?:\d+\.?\d*[smhd]|Previous|Next)', re.S)

def scrape_xyrios(max_pages, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True})
    out, seen = [], set()
    known_streak = 0

    for n in range(1, max_pages + 1):
        url = XY_BASE if n == 1 else f"{XY_BASE}?page={n}"
        print(f"  [xyrios] page {n}/{max_pages}")
        try:
            r = scraper.get(url, timeout=60)
        except Exception as e:
            print(f"  [xyrios] request error: {e}"); break
        if r.status_code != 200:
            print(f"  [xyrios] status {r.status_code}, stopping."); break

        html = r.text
        # Extract skin hashes from skin page links (20-char hex)
        skin_hashes = XY_SKIN_RE.findall(html)
        # Also map image hash -> skin hash (they're the same value)
        img_hashes  = XY_IMG_RE.findall(html)
        all_hashes  = list(dict.fromkeys(skin_hashes + img_hashes))  # preserve order, dedup

        if not all_hashes:
            print(f"  [xyrios] no skins found on page {n}; stopping."); break

        # Parse names from alt text of rendered images
        soup  = BeautifulSoup(html, "html.parser")
        names = {}
        for img in soup.find_all("img", src=XY_IMG_RE.pattern if False else re.compile(r'i\.xyrios\.com/skins/')):
            alt = (img.get("alt") or "").strip()
            m   = XY_IMG_RE.search(img.get("src",""))
            if m and alt:
                names[m.group(1)] = alt

        page_new = 0
        for h in all_hashes:
            if h in seen:
                continue
            seen.add(h)
            if h not in known_ids:
                page_new += 1
            out.append({
                "source": "xyrios",
                "name": names.get(h),
                "image_url": f"https://i.xyrios.com/skins/{h}.png",
                "download_url": f"https://i.xyrios.com/skins/{h}.png",
                "id": h,
            })

        if not all_hashes:
            break
        if page_new == 0 and incremental:
            known_streak += 1
            if known_streak >= STOP_AFTER_KNOWN_PAGES:
                print("  [xyrios] reached known skins; stopping."); break
        elif page_new == 0:
            break
        else:
            known_streak = 0
        time.sleep(1.2)

    return out


# ===========================================================================
# The Skindex  —  Cloudflare JS challenge (browser)
# ===========================================================================
SKX_BASE = "https://www.minecraftskins.com"
HREF_RE  = re.compile(r'/skin/(\d+)/([^/?#"\']+)')
IMG_RE   = re.compile(r'/uploads/(?:preview-)?skins/[^\s"\']*?-(\d+)\.png')

def _skx_extract(page):
    js = """els => els.map(a => {
        const img = a.querySelector('img');
        return {
            href: a.getAttribute('href') || '',
            name: img ? (img.getAttribute('alt') || '') : a.textContent.trim(),
            src:  img ? (img.currentSrc || img.getAttribute('src') ||
                         img.getAttribute('data-src') || img.getAttribute('data-original') || '') : ''
        };
    })"""
    items = page.eval_on_selector_all("a[href*='/skin/']", js)
    ids, imgs, names = {}, {}, {}
    for item in items:
        m = HREF_RE.search(item.get('href',''))
        if not m:
            continue
        sid, slug = m.group(1), m.group(2)
        ids.setdefault(sid, slug)
        nm = item.get('name','').strip()
        if nm and not names.get(sid):
            names[sid] = nm
        mi = IMG_RE.search(item.get('src',''))
        if mi:
            clean = item['src'].split("?")[0]
            imgs[mi.group(1)] = clean if clean.startswith("http") else SKX_BASE + clean
    return ids, imgs, names

def _browser_wait(page, selector, label, attempts=3, wait_sec=25):
    """Wait for selector with N reload attempts. Returns True if cleared."""
    for attempt in range(attempts):
        deadline = time.time() + wait_sec
        while time.time() < deadline:
            if page.query_selector(selector):
                return True
            time.sleep(1)
        print(f"  [{label}] challenge not cleared (attempt {attempt+1}/{attempts}); reloading...")
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
    return bool(page.query_selector(selector))

def scrape_skindex(max_pages, known_ids, incremental):
    from playwright.sync_api import sync_playwright
    out, known_streak = [], 0
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
            if not _browser_wait(page, "a[href*='/skin/']", "skindex"):
                print("  [skindex] challenge not cleared; skipping source."); break
            ids, imgs, names = _skx_extract(page)
            if not ids:
                break
            page_new = 0
            for sid, slug in ids.items():
                if sid not in known_ids:
                    page_new += 1
                out.append({
                    "source": "skindex",
                    "name": names.get(sid) or slug.replace("-"," ").strip(),
                    "image_url": imgs.get(sid) or f"{SKX_BASE}/skin/download/{sid}",
                    "download_url": f"{SKX_BASE}/skin/download/{sid}",
                    "id": sid,
                })
            if incremental:
                known_streak = known_streak + 1 if page_new == 0 else 0
                if known_streak >= STOP_AFTER_KNOWN_PAGES:
                    print("  [skindex] reached known skins; stopping."); break
            time.sleep(1.5)
        browser.close()
    return out


# ===========================================================================
# NameMC  —  Cloudflare JS challenge (browser)
# ===========================================================================
NMC_BASE  = "https://namemc.com/minecraft-skins"
NMC_ID_RE = re.compile(r'/skin/([0-9a-fA-F]+)')
NMC_JS    = """els => els.map(card => {
  const a   = card.querySelector("a[href^='/skin/']");
  const img = card.querySelector('img');
  const q   = s => { const e = card.querySelector(s); return e ? e.textContent.trim() : ''; };
  return {
    href: a   ? a.getAttribute('href') : '',
    name: q('.card-header'),
    src:  img ? (img.getAttribute('data-src') || img.currentSrc || img.getAttribute('src') || '') : '',
  };
})"""

def scrape_namemc(max_pages, known_ids, incremental):
    from playwright.sync_api import sync_playwright
    out, seen, known_streak = [], set(), 0
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
            if not _browser_wait(page, "a[href^='/skin/']", "namemc"):
                print("  [namemc] challenge not cleared; skipping source."); break
            cards    = page.eval_on_selector_all("div.card", NMC_JS)
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
                    "name":   c.get("name") or None,
                    "image_url":    img,
                    "download_url": f"https://namemc.com/skin/{sid}",
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


# ===========================================================================
# minecraftskins.net  —  server-rendered HTML, no JS needed
# ===========================================================================
NET_BASE   = "https://www.minecraftskins.net"
NET_IMG_RE = re.compile(r'src="(/static/front_preview/([^"./]+)\.png)"[^>]*alt="([^"]*)"', re.I)

def scrape_mcskins_net(max_pages, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True})
    out, seen, known_streak = [], set(), 0
    for n in range(1, max_pages + 1):
        url = NET_BASE if n == 1 else f"{NET_BASE}/page/{n}"
        print(f"  [mcnet] page {n}/{max_pages}")
        try:
            r = scraper.get(url, timeout=60)
        except Exception as e:
            print(f"  [mcnet] request error: {e}"); break
        if r.status_code != 200:
            print(f"  [mcnet] status {r.status_code}, stopping."); break
        found_any = False
        page_new  = 0
        for m in NET_IMG_RE.finditer(r.text):
            found_any = True
            slug, name = m.group(2), m.group(3).strip() or m.group(2)
            if slug in seen:
                continue
            seen.add(slug)
            if slug not in known_ids:
                page_new += 1
            out.append({
                "source": "mcnet",
                "name":   name,
                "image_url":    f"{NET_BASE}{m.group(1)}",
                "download_url": f"{NET_BASE}/{slug}/download",
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


# ===========================================================================
# SkinsMC  —  server-rendered
# FIX: old base URL /latest 404s.
#      Real latest = /latest-minecraft-skins  paginates as /random-minecraft-skins/N
#      Skin IDs are numeric e.g. /skin/330661
#      Image  = https://mc-heads.net/body/{id}  (or skinsmc CDN if available)
#      Download = /skin/{id}/download
# ===========================================================================
SMC_BASE    = "https://skinsmc.org"
SMC_FIRST   = f"{SMC_BASE}/latest-minecraft-skins"
SMC_PAGE    = f"{SMC_BASE}/random-minecraft-skins/{{n}}"
SMC_ID_RE   = re.compile(r'/skin/(\d+)')
SMC_NAME_RE = re.compile(r'href="/skin/\d+"[^>]*>\s*Image of 3d skin([^<]+)<', re.I)

def scrape_skinsmc(max_pages, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True})
    out, seen, known_streak = [], set(), 0

    for n in range(1, max_pages + 1):
        url = SMC_FIRST if n == 1 else SMC_PAGE.format(n=n)
        print(f"  [skinsmc] page {n}/{max_pages}")
        try:
            r = scraper.get(url, timeout=60)
        except Exception as e:
            print(f"  [skinsmc] request error: {e}"); break
        if r.status_code != 200:
            print(f"  [skinsmc] status {r.status_code}, stopping."); break

        html = r.text
        ids  = SMC_ID_RE.findall(html)
        # names live in alt text like "Image of 3d skin<Name>"
        name_map = {}
        for m in re.finditer(r'href="/skin/(\d+)"[^>]*>[^<]*?Image of 3d skin([^<"]+)', html):
            name_map[m.group(1)] = m.group(2).strip()
        # Also try parsing from soup img alt
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href^='/skin/']"):
            img = a.find("img")
            if img:
                m = SMC_ID_RE.search(a.get("href",""))
                if m:
                    alt = img.get("alt","").replace("Image of 3d skin","").strip()
                    if alt:
                        name_map.setdefault(m.group(1), alt)

        if not ids:
            print(f"  [skinsmc] no skins found; stopping."); break

        page_new = 0
        for sid in dict.fromkeys(ids):  # preserve order, dedup
            if sid in seen:
                continue
            seen.add(sid)
            if sid not in known_ids:
                page_new += 1
            out.append({
                "source": "skinsmc",
                "name":   name_map.get(sid),
                "image_url":    f"https://mc-heads.net/body/{sid}",
                "download_url": f"{SMC_BASE}/skin/{sid}/download",
                "id": sid,
            })

        if page_new == 0 and incremental:
            known_streak += 1
            if known_streak >= STOP_AFTER_KNOWN_PAGES:
                print("  [skinsmc] reached known skins; stopping."); break
        elif page_new == 0:
            break
        else:
            known_streak = 0
        time.sleep(1.2)
    return out


# ===========================================================================
# MineSkin  —  REST API v2, cursor-based pagination
# FIX: ?page=N doesn't work — v2 uses cursor returned in each response.
# ===========================================================================
MS_API = "https://api.mineskin.org/v2/skins"

def scrape_mineskin(max_pages, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper()
    scraper.headers.update({"User-Agent": UA})
    out, seen, known_streak = [], set(), 0
    cursor = None

    for n in range(1, max_pages + 1):
        params = {"size": 50}
        if cursor:
            params["after"] = cursor
        print(f"  [mineskin] page {n}/{max_pages} cursor={cursor}")
        try:
            r = scraper.get(MS_API, params=params, timeout=30)
            if r.status_code == 429:
                print("  [mineskin] rate limited; sleeping 15s...")
                time.sleep(15); continue
            if r.status_code != 200:
                print(f"  [mineskin] status {r.status_code}, stopping."); break
            data = r.json()
        except Exception as e:
            print(f"  [mineskin] error: {e}"); break

        skins = data.get("skins") or []
        if not skins:
            print("  [mineskin] no more skins."); break

        page_new = 0
        for sk in skins:
            sid = sk.get("uuid")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            if sid not in known_ids:
                page_new += 1
            # image: try texture.data.url.skin, fall back to texture.url
            try:
                img = sk["texture"]["data"]["url"]["skin"]
            except (KeyError, TypeError):
                try:
                    img = sk["texture"]["url"]
                except (KeyError, TypeError):
                    img = None
            name = sk.get("name") or None
            out.append({
                "source": "mineskin",
                "name":   name,
                "image_url":    img,
                "download_url": img,   # same URL serves the raw PNG
                "id": sid,
            })

        # Advance cursor from pagination field
        pg     = data.get("pagination") or {}
        cursor = pg.get("next") or pg.get("after") or pg.get("cursor")
        if not cursor:
            print("  [mineskin] no next cursor; reached end."); break

        if page_new == 0 and incremental:
            known_streak += 1
            if known_streak >= STOP_AFTER_KNOWN_PAGES:
                print("  [mineskin] reached known skins; stopping."); break
        else:
            known_streak = 0
        time.sleep(3)  # respect ~20 req/min limit

    return out


# ===========================================================================
# Helpers
# ===========================================================================
def derive_id(e):
    """Re-derive a stable id from stored URLs (no 'id' field in saved JSON)."""
    src = e.get("source","")
    img = e.get("image") or e.get("image_url") or ""
    dl  = e.get("download") or e.get("download_url") or ""
    patterns = {
        "tlauncher": [r'/catalog/skins/(\d+)/img', r'/download/(\d+)\.png'],
        "xyrios":    [r'i\.xyrios\.com/skins/([a-f0-9]{20})'],
        "skindex":   [r'/skin/download/(\d+)', r'-(\d+)\.png'],
        "namemc":    [r'/skin/([0-9a-fA-F]+)', r'[?&]id=([0-9a-fA-F]+)'],
        "mcnet":     [r'/([^/]+)/download', r'front_preview/([^/.]+)\.png'],
        "skinsmc":   [r'/skin/(\d+)'],
        "mineskin":  [],
    }
    for pat in patterns.get(src, []):
        m = re.search(pat, dl) or re.search(pat, img)
        if m:
            return m.group(1)
    return img or dl or e.get("name")


def project(e):
    """Strip to the required 4-field output schema."""
    name     = e.get("name")
    image    = e.get("image") or e.get("image_url")
    download = e.get("download") or e.get("download_url")
    out = {
        "source": e.get("source"),
        "name":   name  if name  not in ("", None) else None,
        "image":  image if image not in ("", None) else None,
    }
    if download:
        out["download"] = download
    return out


# ===========================================================================
# Load / save
# ===========================================================================
def load_existing(path):
    abspath = os.path.abspath(path)
    if not os.path.exists(path):
        print(f"No existing file at {abspath} -> FIRST RUN."); return []
    try:
        with open(path) as f:
            data = json.load(f)
        lst = data.get("skins") if isinstance(data, dict) else data
        if isinstance(lst, list):
            print(f"Loaded {len(lst)} existing skins from {abspath}")
            return lst
    except Exception as e:
        print(f"WARNING: couldn't read {abspath} ({e}); treating as first run.")
    return []


def main():
    existing = load_existing(OUTPUT)
    for e in existing:
        if not e.get("id"):
            e["id"] = derive_id(e)

    prev_count  = len(existing)
    first_run   = prev_count == 0
    incremental = not first_run
    print(f"Mode: {'FIRST RUN' if first_run else 'INCREMENTAL'} | existing: {prev_count}")

    existing_keys   = {(e.get("source"), e.get("id")) for e in existing}
    known_by_source = defaultdict(set)
    for e in existing:
        known_by_source[e.get("source")].add(e.get("id"))

    depth = (dict(tlauncher=INIT_TLAUNCHER, xyrios=INIT_XYRIOS, skindex=INIT_SKINDEX,
                  namemc=INIT_NAMEMC, mcnet=INIT_MCNET, skinsmc=INIT_SKINSMC, mineskin=INIT_MINESKIN)
             if first_run else
             dict(tlauncher=UPD_TLAUNCHER, xyrios=UPD_XYRIOS, skindex=UPD_SKINDEX,
                  namemc=UPD_NAMEMC, mcnet=UPD_MCNET, skinsmc=UPD_SKINSMC, mineskin=UPD_MINESKIN))

    jobs = []
    if ENABLE_TLAUNCHER: jobs.append(("tlauncher", lambda: scrape_tlauncher(depth["tlauncher"], known_by_source["tlauncher"], incremental)))
    if ENABLE_XYRIOS:    jobs.append(("xyrios",    lambda: scrape_xyrios   (depth["xyrios"],    known_by_source["xyrios"],    incremental)))
    if ENABLE_SKINDEX:   jobs.append(("skindex",   lambda: scrape_skindex  (depth["skindex"],   known_by_source["skindex"],   incremental)))
    if ENABLE_NAMEMC:    jobs.append(("namemc",    lambda: scrape_namemc   (depth["namemc"],    known_by_source["namemc"],    incremental)))
    if ENABLE_MCNET:     jobs.append(("mcnet",     lambda: scrape_mcskins_net(depth["mcnet"],   known_by_source["mcnet"],     incremental)))
    if ENABLE_SKINSMC:   jobs.append(("skinsmc",   lambda: scrape_skinsmc  (depth["skinsmc"],   known_by_source["skinsmc"],   incremental)))
    if ENABLE_MINESKIN:  jobs.append(("mineskin",  lambda: scrape_mineskin (depth["mineskin"],  known_by_source["mineskin"],  incremental)))

    scraped = []
    for name, fn in jobs:
        print(f"\n=== Source: {name} ===")
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

    # Final dedup
    deduped, seen_keys = [], set()
    for sk in existing:
        key = (sk.get("source"), sk.get("id"))
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(sk)
    existing = deduped

    if first_run and MAX_TOTAL_FIRST_RUN:
        existing = existing[:MAX_TOTAL_FIRST_RUN]
    if SHUFFLE:
        random.shuffle(existing)
    if not existing:
        print("\nERROR: nothing collected."); sys.exit(1)
    if not first_run and len(existing) < prev_count:
        print(f"\nERROR: total ({len(existing)}) < existing ({prev_count}). Aborting."); sys.exit(1)

    by_source = defaultdict(int)
    for e in existing:
        by_source[e.get("source")] += 1

    print(f"\nAdded {added} new skins this run. Total: {len(existing)}")
    print("Skins per source:")
    for src, cnt in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  {src:<12} {cnt:>8}")

    output_data = [project(e) for e in existing]
    payload = {
        "total":   len(output_data),
        "sources": dict(by_source),
        "skins":   output_data,
    }
    with open(OUTPUT, "w") as f:
        json.dump(payload, f, indent=4)
    print(f"Saved to {OUTPUT}.")


if __name__ == "__main__":
    main()
