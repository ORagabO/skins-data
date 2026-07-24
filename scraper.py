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

def get_most_used_skins():
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    major_version = get_chrome_major_version()
    driver = uc.Chrome(options=options, version_main=major_version)
    
    print("Loading laby.net...")
    driver.get("https://laby.net/skins?order=most_used")
    
    try:
        # Wait specifically for the new correct link structure
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/skins/']"))
        )
        
        # Scroll down a few times to trigger lazy-loaded images
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Find all links that start with "/skins/" based on the screenshot
        skin_cards = soup.find_all("a", href=lambda h: h and h.startswith("/skins/"))
        
        results = []
        
        for card in skin_cards:
            href = card.get('href')
            
            # Find the image inside the card
            img = card.find("img")
            
            if img:
                img_url = img.get('src')
                skin_name = img.get('alt', 'Unknown Skin')
                
                # Format the full URL
                skin_url = f"https://laby.net{href}"
                
                # Extract usage count from the span tag in your screenshot
                usage_span = card.find("span", class_="font-semibold")
                usage_count = usage_span.text.strip() if usage_span else "0"

                results.append({
                    "name": skin_name,
                    "uses": usage_count,
                    "skin_url": skin_url, 
                    "image_url": img_url
                })
        
        # Deduplicate the list using the skin_url as a unique key
        unique_results = {res['skin_url']: res for res in results}.values()
        print(f"Scraped {len(unique_results)} items successfully.")
        
        # Save the structured data
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
