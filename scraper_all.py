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
            # Page 1 uses the base URL. Page 2 uses /2/, Page 3 uses /3/, etc.
            url = f"{TL_BASE}/" if n == 1 else f"{TL_BASE}/{n}/"
            print(f"  [tlauncher] Navigating to page {n}/{max_pages} -> {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # Instead of waiting for a specific class that might change, just give 
                # the page 3 full seconds to load and bypass any Cloudflare checks.
                page.wait_for_timeout(3000) 
            except Exception as e:
                print(f"  [tlauncher] Navigation error: {e}")
                break

            content = page.content()
            found_ids = set()
            
            # Scrape IDs directly from the raw HTML structure
            for m in re.finditer(r'/download/(\d+)\.png', content):
                found_ids.add(m.group(1))

            print(f"  [tlauncher] DEBUG: Found {len(found_ids)} total skins on this page.")

            if not found_ids:
                print("  [tlauncher] DEBUG: 0 skins found. The page might be empty or blocked. Stopping.")
                break
                
            page_new = 0
            
            for sid in found_ids:
                # Skip if we already grabbed it during this exact run
                if sid in seen:
                    continue
                seen.add(sid)
                
                # Check if it's genuinely new (not in the JSON file)
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

            # Stop logic
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
