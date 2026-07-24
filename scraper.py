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
        # Ask the operating system for the installed Chrome version
        process = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
        version_string = process.stdout.strip()
        # Extract the major version number (e.g., "Google Chrome 150.0.7871.128" -> 150)
        major_version = int(version_string.split()[2].split('.')[0])
        print(f"Detected Chrome major version: {major_version}")
        return major_version
    except Exception as e:
        print(f"Could not determine Chrome version: {e}")
        return None

def get_most_used_skins():
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    # 1. Fetch the exact Chrome version dynamically
    major_version = get_chrome_major_version()
    
    # 2. Force the driver to use the matching version
    driver = uc.Chrome(options=options, version_main=major_version)
    
    print("Loading laby.net...")
    driver.get("https://laby.net/skins?order=most_used")
    
    try:
        # Wait for ANY image to load inside the main grid
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img"))
        )
        
        # Scroll down multiple times to trigger all lazy-loaded images in the grid
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Find all anchor links on the page
        all_links = soup.find_all("a")
        
        results = []
        for card in all_links:
            href = card.get('href', '')
            
            # Look for links that lead to textures/skins
            if '/texture/' in href or '/skin/' in href:
                skin_url = f"https://laby.net{href}" if href.startswith('/') else href
                
                img = card.find("img")
                img_url = img.get('src') if img else None
                
                # Filter out small UI icons (.svg) to only keep the actual skin images
                if img_url and not img_url.endswith('.svg'):
                    results.append({
                        "skin_url": skin_url, 
                        "image_url": img_url
                    })
        
        # Deduplicate the list
        unique_results = {res['skin_url']: res for res in results}.values()
        print(f"Scraped {len(unique_results)} skins successfully.")
        
        # Save the data
        with open("skins_data.json", "w") as f:
            json.dump(list(unique_results), f, indent=4)
            
    except Exception as e:
        print(f"An error occurred: {e}")
        driver.save_screenshot("error_screenshot.png")
        raise e
    finally:
        driver.quit()

if __name__ == "__main__":
    get_most_used_skins()
