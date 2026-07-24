import time
import json
import subprocess
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def get_chrome_major_version():
    try:
        process = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
        version_string = process.stdout.strip()
        major_version = int(version_string.split()[2].split('.')[0])
        return major_version
    except Exception as e:
        return None

def get_skins_data():
    # --- SCRAPER SETTINGS ---
    MAX_SCROLLS = 5          # How many times to scroll the main page to load more skins
    MAX_SKINS_TO_VISIT = 20  # Limit how many individual pages to open (Prevents GitHub timeout). Set to a high number to do all.
    # ------------------------

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    major_version = get_chrome_major_version()
    driver = uc.Chrome(options=options, version_main=major_version)
    
    try:
        # ==========================================
        # PHASE 1: SCROLL & COLLECT SKIN URLS
        # ==========================================
        print("Loading laby.net main page...")
        driver.get("https://laby.net/skins?order=most_used")
        
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/skins/']"))
        )
        
        # Scroll to load pagination
        for i in range(MAX_SCROLLS):
            print(f"Scrolling down to load more cards ({i+1}/{MAX_SCROLLS})...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) # Wait for new cards to pop in
            
        soup = BeautifulSoup(driver.page_source, "html.parser")
        skin_cards = soup.find_all("a", href=lambda h: h and h.startswith("/skins/"))
        
        initial_results = []
        for card in skin_cards:
            href = card.get('href')
            img = card.find("img")
            
            if img:
                skin_url = f"https://laby.net{href}"
                img_url = img.get('src')
                skin_name = img.get('alt', 'Unknown Skin')
                
                usage_span = card.find("span", class_="font-semibold")
                usage_count = usage_span.text.strip() if usage_span else "0"

                initial_results.append({
                    "name": skin_name,
                    "uses": usage_count,
                    "skin_url": skin_url, 
                    "preview_image": img_url
                })
        
        # Deduplicate
        unique_skins = list({res['skin_url']: res for res in initial_results}.values())
        print(f"Collected {len(unique_skins)} unique skin links from the main page.\n")

        # ==========================================
        # PHASE 2: VISIT EACH CARD FOR DOWNLOAD URL
        # ==========================================
        final_data = []
        skins_to_process = unique_skins[:MAX_SKINS_TO_VISIT]
        
        print(f"Visiting {len(skins_to_process)} individual skin pages to find download links...")
        
        for index, skin in enumerate(skins_to_process):
            print(f"[{index+1}/{len(skins_to_process)}] Extracting: {skin['name']}")
            driver.get(skin['skin_url'])
            
            try:
                # Wait for the inner page to render
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "main"))
                )
                time.sleep(1) # Brief pause for dynamic React elements
                
                detail_soup = BeautifulSoup(driver.page_source, "html.parser")
                
                # Strategy: Look for an anchor tag with the 'download' attribute or containing the word 'Download'
                download_url = None
                
                # 1. Try finding a link with a 'download' attribute
                dl_element = detail_soup.find("a", attrs={"download": True})
                
                # 2. Fallback: Try finding a button/link with "Download" text
                if not dl_element:
                    dl_element = detail_soup.find("a", string=lambda text: text and "Download" in text, href=True)
                
                if dl_element:
                    href = dl_element.get('href')
                    # Ensure full URL formatting
                    download_url = f"https://laby.net{href}" if href.startswith('/') else href
                
                # Add the final download link to our data object
                skin["download_url"] = download_url or "Download button not found"
                final_data.append(skin)
                
            except Exception as e:
                print(f"  -> Failed to load download link for {skin['skin_url']}: {e}")
                skin["download_url"] = "Error loading page"
                final_data.append(skin)

        # ==========================================
        # PHASE 3: SAVE TO JSON
        # ==========================================
        with open("skins_data.json", "w") as f:
            json.dump(final_data, f, indent=4)
            
        print(f"\nSuccessfully saved {len(final_data)} complete skin records to skins_data.json")

    except Exception as e:
        print(f"A critical error occurred: {e}")
        driver.save_screenshot("error_screenshot.png")
        raise e
    finally:
        driver.quit()

if __name__ == "__main__":
    get_skins_data()
