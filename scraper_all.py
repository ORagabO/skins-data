import os
import json
import time
import re
import random
import sys
from collections import defaultdict

# ==========================================================================
# Multi-source Minecraft skin collector with INITIAL BACKFILL + INCREMENTAL.
#
#   * First run  (skins_all.json missing/empty): scrape a large batch (~50k).
#   * Later runs (skins_all.json exists):        only ADD newly-added skins.
#
# On incremental runs each source walks from the top of its "newest" feed and
# stops as soon as it hits a run of skins already in the file, so updates are
# fast. Everything is merged into skins_all.json (existing entries kept), then
# optionally shuffled.
#
# Sources: laby.net (API), The Skindex (browser), NameMC (browser),
#          minecraftskins.net (HTML). Common shape per entry:
#   {"source","name","image_url","download_url","downloads","id"}
# ==========================================================================

# ---- toggles -------------------------------------------------------------
ENABLE_LABY = True
ENABLE_SKINDEX = True
ENABLE_NAMEMC = True
ENABLE_MCNET = True

# ---- INITIAL run depths (aim ~50k total; tune to taste) ------------------
INIT_LABY = 40000     # laby API paginates deep; the bulk of the 50k
INIT_SKINDEX = 200    # ~48/page  -> ~9.6k   (browser; may be blocked)
INIT_NAMEMC = 200     # namemc pages         (browser; may be blocked)
INIT_MCNET = 25       # ~12/page  -> ~300    (all main pages)

# ---- INCREMENTAL run depths (small; early-stop ends them sooner) ---------
UPD_LABY = 1500
UPD_SKINDEX = 25
UPD_NAMEMC = 25
UPD_MCNET = 8

STOP_AFTER_KNOWN_PAGES = 2   # incremental: stop a source after N all-known pages

OUTPUT = "skins_all.json"
SHUFFLE = True               # shuffle the whole file after merging
MAX_TOTAL_FIRST_RUN = None   # e.g. 50000 to hard-cap the first run; None = no cap
DEBUG_SAMPLES = False        # set True to print one raw item per source

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = { runtime: {} };
"""


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def render_from_hash(h):
    return f"https://laby.net/api/v3/render/skin/{h}.png?height=500&width=500"


# ---------------------------------------------------------------- laby.net --
def scrape_laby(target, known_ids, incremental):
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True})
    out, seen = [], set()
    offset, size, known_streak, dumped = 0, 36, 0, False
    while len(out) < target:
        api = ("https://laby.net/api/v3/search/textures/skin"
               f"?order=most_used&size={size}&offset={offset}")
        try:
            r = scraper.get(api, timeout=60)
        except Exception as e:
            print(f"  [laby] request error: {e}"); break
        if r.status_code != 200:
            print(f"  [laby] status {r.status_code}, stopping."); break
        data = r.json()
        lst = data if isinstance(data, list) else _first(
            data, ["results", "data", "textures", "skins", "hits"]) or []
        if not lst:
            break
        page_new = 0
        for sk in lst:
            if DEBUG_SAMPLES and not dumped:
                print("  [laby] SAMPLE:", json.dumps(sk)[:600]); dumped = True
            h = _first(sk, ["hash", "image_hash", "id", "texture_id"])
            if not h or h in seen:
                continue
            seen.add(h)
            if h not in known_ids:
                page_new += 1
            out.append({
                "source": "laby",
                "name": _first(sk, ["name", "title", "display_name", "label"]),
                "image_url": render_from_hash(h),
                "download_url": f"https://textures.minecraft.net/texture/{h}",
                "downloads": _first(sk, ["useCount", "use_count", "usages", "usage",
                                         "used", "users", "count", "uses"]),
                "id": h,
            })
        offset += size
        if incremental:
            known_streak = known_streak + 1 if page_new == 0 else 0
            if known_streak >= STOP_AFTER_KNOWN_PAGES:
                print("  [laby] reached known skins; stopping (incremental)."); break
        time.sleep(1.2)
    return out[:target]


# ---------------------------------------------------------------- Skindex ---
SKX_BASE = "https://www.minecraftskins.com"
HREF_RE = re.compile(r'/skin/(\d+)/([^/?#"\']+)')
IMG_RE = re.compile(r'/uploads/(?:preview-)?skins/[^\s"\']*?-(\d+)\.png')


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
        imgs[m.group(1)] = clean
    return ids, imgs


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
            cleared, deadline = False, time.time() + 30
            while time.time() < deadline:
                if page.query_selector("a[href*='/skin/']"):
                    cleared = True; break
                time.sleep(1)
            if not cleared:
                print("  [skindex] challenge not cleared; skipping source."); break
            ids, imgs = _skx_extract(page)
            if not ids:
                break
            page_new = 0
            for sid, slug in ids.items():
                if sid not in known_ids:
                    page_new += 1
                out.append({
                    "source": "skindex",
                    "name": slug.replace("-", " ").strip(),
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
            cleared, deadline = False, time.time() + 30
            while time.time() < deadline:
                if page.query_selector("a[href^='/skin/']"):
                    cleared = True; break
                time.sleep(1)
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
NET_IMG_RE = re.compile(
    r'src="(/static/front_preview/([^"./]+)\.png)"[^>]*?alt="([^"]*)"', re.I)


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
        matches = NET_IMG_RE.findall(r.text)
        if not matches:
            break
        page_new = 0
        for img_path, slug, name in matches:
            if slug in seen:
                continue
            seen.add(slug)
            if slug not in known_ids:
                page_new += 1
            out.append({
                "source": "mcnet",
                "name": name or slug,
                "image_url": f"{NET_BASE}{img_path}",
                "download_url": f"{NET_BASE}/{slug}/download",
                "downloads": None,
                "id": slug,
            })
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


# -------------------------------------------------------------------- main --
def load_existing(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"WARNING: couldn't read {path} ({e}); treating as first run.")
    return []


def main():
    existing = load_existing(OUTPUT)
    first_run = len(existing) == 0
    print(f"Mode: {'FIRST RUN (backfill)' if first_run else 'INCREMENTAL (add new only)'}"
          f" | existing entries: {len(existing)}")

    existing_keys = {(e.get("source"), e.get("id")) for e in existing}
    known_by_source = defaultdict(set)
    for e in existing:
        known_by_source[e.get("source")].add(e.get("id"))

    depth = ({"laby": INIT_LABY, "skindex": INIT_SKINDEX,
              "namemc": INIT_NAMEMC, "mcnet": INIT_MCNET} if first_run else
             {"laby": UPD_LABY, "skindex": UPD_SKINDEX,
              "namemc": UPD_NAMEMC, "mcnet": UPD_MCNET})
    incremental = not first_run

    jobs = []
    if ENABLE_LABY:
        jobs.append(("laby", lambda: scrape_laby(depth["laby"], known_by_source["laby"], incremental)))
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

    # Merge: keep everything already in the file, append only genuinely new skins.
    added = 0
    for sk in scraped:
        key = (sk["source"], sk["id"])
        if key in existing_keys:
            continue
        existing_keys.add(key)
        existing.append(sk)
        added += 1

    if first_run and MAX_TOTAL_FIRST_RUN:
        existing = existing[:MAX_TOTAL_FIRST_RUN]
    if SHUFFLE:
        random.shuffle(existing)

    if not existing:
        print("\nERROR: nothing collected and no existing data. Not writing.")
        sys.exit(1)

    by_source = defaultdict(int)
    for e in existing:
        by_source[e.get("source")] += 1
    print(f"\nAdded {added} new skins. Total now: {len(existing)}. Breakdown: {dict(by_source)}")

    with open(OUTPUT, "w") as f:
        json.dump(existing, f, indent=4)
    print(f"Saved to {OUTPUT}.")


if __name__ == "__main__":
    main()
