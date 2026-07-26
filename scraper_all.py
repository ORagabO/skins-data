import json
import time
import re
import random
import sys

# ==========================================================================
# Multi-source Minecraft skin collector.
#
# Sources:
#   1. laby.net        - JSON API (cloudscraper).           Character render + Mojang texture.
#   2. The Skindex     - HTML gallery (headful Playwright). Character render + skin file.
#   3. MineSkin        - JSON API /v2/skins (requests).     Character render + Mojang texture.
#
# Every source returns entries in ONE common shape:
#   {"source", "id", "name", "image_url", "download_url"}
# so they can be mixed together. Each source runs inside try/except: if one
# fails (e.g. Skindex is Cloudflare-blocked on a CI IP), the others still run.
# At the end everything is deduplicated and SHUFFLED into a single file.
# ==========================================================================

# ---- What to collect (tune these) ----------------------------------------
ENABLE_LABY = True
ENABLE_SKINDEX = True
ENABLE_NAMEMC = True
ENABLE_MCNET = True        # minecraftskins.net (server-rendered, no browser needed)
ENABLE_MINESKIN = False    # replaced by NameMC

LABY_TARGET = 2000        # approx skins from laby.net
SKINDEX_PAGES = 40        # gallery pages (~48 skins each)
NAMEMC_PAGES = 20         # namemc pages
MCNET_PAGES = 25          # minecraftskins.net listing pages (~12 skins each, 25 = all)
MINESKIN_PAGES = 20       # (only used if ENABLE_MINESKIN)

OUTPUT = "skins_all.json"
SHUFFLE = True
MAX_TOTAL = None          # e.g. 5000 to cap the final list; None = keep all

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def render_from_hash(h):
    """A viewable CHARACTER render for a Mojang texture hash (via laby's renderer)."""
    return f"https://laby.net/api/v3/render/skin/{h}.png?height=500&width=500"


# ---------------------------------------------------------------- laby.net --
# Use laby's JSON API (reliable + fast + paginated). It returns a texture hash
# per skin; name/usage may be under keys we can't see from here, so we try
# several and print ONE raw item (DEBUG_SAMPLES) to confirm the real fields.
DEBUG_SAMPLES = True   # set False once field names are confirmed


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def scrape_laby(target):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True}
    )
    out = []
    seen = set()
    offset = 0
    size = 36
    dumped = False
    while len(out) < target:
        api = ("https://laby.net/api/v3/search/textures/skin"
               f"?order=most_used&size={size}&offset={offset}")
        try:
            r = scraper.get(api, timeout=60)
        except Exception as e:
            print(f"  [laby] request error: {e}")
            break
        if r.status_code != 200:
            print(f"  [laby] status {r.status_code}, stopping.")
            break
        data = r.json()
        lst = data if isinstance(data, list) else _first(
            data, ["results", "data", "textures", "skins", "hits"]) or []
        if not lst:
            break
        for sk in lst:
            if DEBUG_SAMPLES and not dumped:
                print("  [laby] SAMPLE ITEM KEYS:", list(sk.keys()))
                print("  [laby] SAMPLE ITEM:", json.dumps(sk)[:1000])
                dumped = True
            h = _first(sk, ["hash", "image_hash", "id", "texture_id", "texture"])
            if isinstance(h, dict):
                h = _first(h, ["hash", "id"])
            if not h or h in seen:
                continue
            seen.add(h)
            name = _first(sk, ["name", "title", "skin_name", "display_name", "label"])
            downloads = _first(sk, ["useCount", "use_count", "usages", "usage",
                                    "used", "users", "count", "uses", "downloads"])
            out.append({
                "source": "laby",
                "name": name,
                "image_url": f"https://laby.net/api/v3/render/skin/{h}.png?height=500&width=500",
                "download_url": f"https://textures.minecraft.net/texture/{h}",
                "downloads": downloads,
                "id": h,
            })
        offset += size
        time.sleep(1.2)
    return out[:target]


# ---------------------------------------------------------------- Skindex ---
SKX_BASE = "https://www.minecraftskins.com"
SKX_PATH = "latest"
HREF_RE = re.compile(r'/skin/(\d+)/([^/?#"\']+)')
IMG_RE = re.compile(r'/uploads/(?:preview-)?skins/[^\s"\']*?-(\d+)\.png')
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
"""


def _skx_extract(page):
    hrefs = page.eval_on_selector_all(
        "a[href*='/skin/']", "els => els.map(e => e.getAttribute('href'))")
    srcs = page.eval_on_selector_all(
        "img", "els => els.map(e => e.currentSrc || e.getAttribute('src') "
               "|| e.getAttribute('data-src') || e.getAttribute('data-original') || '')")
    ids = {}
    for h in hrefs:
        m = HREF_RE.search(h or "")
        if m:
            ids.setdefault(m.group(1), m.group(2))
    imgs = {}
    for s in srcs:
        s = s or ""
        m = IMG_RE.search(s)
        if not m:
            continue
        clean = s.split("?")[0]
        if clean.startswith("/"):
            clean = SKX_BASE + clean
        imgs[m.group(1)] = clean   # keep /uploads/preview-skins/... = character render
    return ids, imgs


def scrape_skindex(max_pages):
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768}, locale="en-US")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()
        for n in range(1, max_pages + 1):
            url = f"{SKX_BASE}/{SKX_PATH}/{n}/"
            print(f"  [skindex] page {n}/{max_pages}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  [skindex] nav error: {e}")
                break
            # wait up to ~30s for the Cloudflare challenge to clear
            cleared = False
            deadline = time.time() + 30
            while time.time() < deadline:
                if page.query_selector("a[href*='/skin/']"):
                    cleared = True
                    break
                time.sleep(1)
            if not cleared:
                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass
                print(f"  [skindex] challenge not cleared (title: {title!r}); "
                      "skipping this source.")
                break
            ids, imgs = _skx_extract(page)
            if not ids:
                break
            for sid, slug in ids.items():
                out.append({
                    "source": "skindex",
                    "name": slug.replace("-", " ").strip(),
                    "image_url": imgs.get(sid) or f"{SKX_BASE}/skin/download/{sid}",
                    "download_url": f"{SKX_BASE}/skin/download/{sid}",
                    "downloads": None,   # shown on each skin's detail page (see note)
                    "id": sid,
                })
            time.sleep(1.5)
        browser.close()
    return out


# ----------------------------------------------------------------- NameMC ---
# NameMC skin cards (from the DOM you shared):
#   <div class="card"><a href="/skin/<id>">
#       <div class="card-header">NAME</div>
#       <div class="card-body">
#          <img data-src="https://s.namemc.com/3d/skin/body.png?id=<id>&model=slim&...">
#          <div class="position-absolute top-0 start-0">#RANK</div>
#          <div class="position-absolute bottom-0 end-0">STAT</div>
#       </div></a></div>
# NameMC is heavily Cloudflare-protected, so we use the same headful browser.
NMC_BASE = "https://namemc.com/minecraft-skins"
NMC_ID_RE = re.compile(r'/skin/([0-9a-fA-F]+)')

NMC_JS = """els => els.map(card => {
  const a = card.querySelector("a[href^='/skin/']");
  const img = card.querySelector('img');
  const q = (sel) => { const e = card.querySelector(sel); return e ? e.textContent.trim() : ''; };
  return {
    href: a ? a.getAttribute('href') : '',
    name: q('.card-header'),
    src: img ? (img.getAttribute('data-src') || img.currentSrc || img.getAttribute('src') || '') : '',
    rank: q('.position-absolute.top-0.start-0'),
    stat_end: q('.position-absolute.bottom-0.end-0'),
    stat_start: q('.position-absolute.bottom-0.start-0'),
  };
})"""


def scrape_namemc(max_pages):
    from playwright.sync_api import sync_playwright
    out = []
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"],
        )
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
                print(f"  [namemc] nav error: {e}")
                break
            # wait for skin cards (i.e. Cloudflare challenge cleared)
            cleared = False
            deadline = time.time() + 30
            while time.time() < deadline:
                if page.query_selector("a[href^='/skin/']"):
                    cleared = True
                    break
                time.sleep(1)
            if not cleared:
                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass
                print(f"  [namemc] cards not found (title: {title!r}); skipping source.")
                break

            cards = page.eval_on_selector_all("div.card", NMC_JS)
            if DEBUG_SAMPLES and cards:
                print("  [namemc] SAMPLE CARD:", json.dumps(cards[0])[:400])
            new_count = 0
            for c in cards:
                m = NMC_ID_RE.search(c.get("href") or "")
                if not m:
                    continue
                sid = m.group(1)
                if sid in seen:
                    continue
                seen.add(sid)
                new_count += 1
                img = c.get("src") or (
                    f"https://s.namemc.com/3d/skin/body.png?id={sid}&model=slim&width=256&height=256")
                # best guess for a download/usage count is the bottom-right stat;
                # rank (#1) is kept separate.
                downloads = c.get("stat_end") or c.get("stat_start") or None
                out.append({
                    "source": "namemc",
                    "name": (c.get("name") or None),
                    "image_url": img,
                    "download_url": f"https://namemc.com/skin/{sid}",
                    "downloads": downloads,
                    "id": sid,
                })
            if new_count == 0:
                print("  [namemc] no new skins; stopping.")
                break
            time.sleep(1.5)
        browser.close()
    return out


# -------------------------------------------------------- minecraftskins.net --
# Fully server-rendered (no browser needed). Each card:
#   <a href="/<slug>"><img src="/static/front_preview/<slug>.png" alt="<Name>" ...></a>
#   ...<a class="control" href="/<slug>/download">Download</a>
# So we fetch the HTML with cloudscraper and regex out slug + name + image.
NET_BASE = "https://www.minecraftskins.net"
NET_IMG_RE = re.compile(
    r'src="(/static/front_preview/([^"./]+)\.png)"[^>]*?alt="([^"]*)"', re.I)


def scrape_mcskins_net(max_pages):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True}
    )
    out = []
    seen = set()
    for n in range(1, max_pages + 1):
        url = NET_BASE if n == 1 else f"{NET_BASE}/page/{n}"
        print(f"  [mcnet] page {n}/{max_pages}")
        try:
            r = scraper.get(url, timeout=60)
        except Exception as e:
            print(f"  [mcnet] request error: {e}")
            break
        if r.status_code != 200:
            print(f"  [mcnet] status {r.status_code}, stopping.")
            break
        matches = NET_IMG_RE.findall(r.text)
        if not matches:
            print("  [mcnet] no cards found; stopping.")
            break
        new_count = 0
        for img_path, slug, name in matches:
            if slug in seen:
                continue
            seen.add(slug)
            new_count += 1
            out.append({
                "source": "mcnet",
                "name": name or slug,
                "image_url": f"{NET_BASE}{img_path}",            # front render (character)
                "download_url": f"{NET_BASE}/{slug}/download",    # real skin-file download
                "downloads": None,   # not shown on the listing
                "id": slug,
            })
        if new_count == 0:
            break
        time.sleep(1.2)
    return out


# --------------------------------------------------------------- MineSkin ---
def _mineskin_hash(it):
    tex = it.get("texture") or {}
    if isinstance(tex, dict):
        # direct hash field (a bare texture hash, no slashes)
        h = tex.get("hash")
        if isinstance(h, str) and h and "/" not in h:
            return h
        # url may be a string or a dict of urls
        url = tex.get("url")
        if isinstance(url, str) and "texture/" in url:
            return url.rsplit("/", 1)[-1]
        if isinstance(url, dict):
            for u in url.values():
                if isinstance(u, str) and "texture/" in u:
                    return u.rsplit("/", 1)[-1]
    h = it.get("hash")
    return h if isinstance(h, str) and h else None


def scrape_mineskin(max_pages):
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    out = []
    after = None
    for _ in range(max_pages):
        params = {"size": 50}
        if after:
            params["after"] = after
        try:
            r = s.get("https://api.mineskin.org/v2/skins", params=params, timeout=60)
        except Exception as e:
            print(f"  [mineskin] request error: {e}")
            break
        if r.status_code != 200:
            print(f"  [mineskin] status {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        if DEBUG_SAMPLES:
            print("  [mineskin] TOP-LEVEL KEYS:", list(data.keys())
                  if isinstance(data, dict) else type(data).__name__)
        items = (data.get("skins") or data.get("data") or data.get("results")
                 or (data if isinstance(data, list) else []))
        if DEBUG_SAMPLES and items:
            print("  [mineskin] SAMPLE ITEM:", json.dumps(items[0])[:600])
        if not items:
            break
        for it in items:
            if not isinstance(it, dict):
                continue
            h = _mineskin_hash(it)
            if not h:
                continue
            views = it.get("views")
            if views is None and isinstance(it.get("stats"), dict):
                views = it["stats"].get("views")
            out.append({
                "source": "mineskin",
                "name": it.get("name"),
                "image_url": render_from_hash(h),
                "download_url": f"https://textures.minecraft.net/texture/{h}",
                "downloads": views,
                "id": it.get("uuid") or h,
            })
        pg = data.get("pagination") or {}
        after = pg.get("next") or pg.get("after") or pg.get("cursor")
        if not after:
            break
        time.sleep(1.5)
    return out


# -------------------------------------------------------------------- main --
def main():
    jobs = []
    if ENABLE_LABY:
        jobs.append(("laby", lambda: scrape_laby(LABY_TARGET)))
    if ENABLE_SKINDEX:
        jobs.append(("skindex", lambda: scrape_skindex(SKINDEX_PAGES)))
    if ENABLE_NAMEMC:
        jobs.append(("namemc", lambda: scrape_namemc(NAMEMC_PAGES)))
    if ENABLE_MCNET:
        jobs.append(("mcnet", lambda: scrape_mcskins_net(MCNET_PAGES)))
    if ENABLE_MINESKIN:
        jobs.append(("mineskin", lambda: scrape_mineskin(MINESKIN_PAGES)))

    all_skins = []
    for name, fn in jobs:
        print(f"=== Source: {name} ===")
        try:
            got = fn()
            print(f"[{name}] collected {len(got)} skins.")
            all_skins.extend(got)
        except Exception as e:
            print(f"[{name}] FAILED, skipping: {e}")

    # Deduplicate by (source, id).
    seen = set()
    unique = []
    for sk in all_skins:
        key = (sk["source"], sk["id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(sk)

    if SHUFFLE:
        random.shuffle(unique)
    if MAX_TOTAL:
        unique = unique[:MAX_TOTAL]

    if not unique:
        print("\nERROR: no skins collected from any source. Not writing a file.")
        sys.exit(1)

    counts = {}
    for sk in unique:
        counts[sk["source"]] = counts.get(sk["source"], 0) + 1
    print(f"\nTotal unique: {len(unique)}  breakdown: {counts}")

    with open(OUTPUT, "w") as f:
        json.dump(unique, f, indent=4)
    print(f"Saved shuffled results to {OUTPUT}.")


if __name__ == "__main__":
    main()
