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
    MAX_SCROLLS = 10  # Increase this to load even more skins from the main page!
    # ------------------------

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    major_version = get_chrome_major_version()
    driver = uc.Chrome(options=options, version_main=major_version)
    
    try:
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
        
        results = []
        for card in skin_cards:
            href = card.get('href') # Looks like: /skins/42bd21cda31e6e87aa886c576de87555
            img = card.find("img")
            
            if img:
                skin_url = f"https://laby.net{href}"
                skin_name = img.get('alt', 'Unknown Skin')
                
                usage_span = card.find("span", class_="font-semibold")
                usage_count = usage_span.text.strip() if usage_span else "0"

                # Extract the unique texture hash
                skin_hash = href.split('/')[-1] 
                
                # 1. The Raw Texture File (The 2D flattened skin for downloading)
                direct_download_url = f"http://textures.minecraft.net/texture/{skin_hash}"

                # 2. The 3D Rendered Image (Using the Laby.net API)
                # You can modify height and width here if you need a different size
                render_url = f"https://laby.net/api/v3/render/skin/{skin_hash}.png?height=500&width=500"

                results.append({
                    "name": skin_name,
                    "uses": usage_count,
                    "skin_url": skin_url, 
                    "texture_hash": skin_hash,
                    "download_url": direct_download_url,
                    "3d_render_url": render_url
                })
        
        # Deduplicate
        unique_skins = list({res['skin_url']: res for res in results}.values())
        print(f"\nSuccessfully collected and generated download/render links for {len(unique_skins)} skins!")

        # Save to JSON
        with open("skins_data.json", "w") as f:
            json.dump(unique_skins, f, indent=4)
            
        print("Data saved to skins_data.json")

    except Exception as e:
        print(f"A critical error occurred: {e}")
        driver.save_screenshot("error_screenshot.png")
        raise e
    finally:
        driver.quit()

if __name__ == "__main__":
    get_skins_data()
