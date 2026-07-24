import time
import json
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def get_most_used_skins():
    # 1. Setup Headless Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # 2. Initialize WebDriver (Selenium Manager handles the driver automatically now)
    driver = webdriver.Chrome(options=chrome_options)
    
    print("Loading laby.net...")
    driver.get("https://laby.net/skins?order=most_used")
    
    try:
        # 3. Wait for the skin grid to render
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/skin/']"))
        )
        
        # Scroll down slightly to trigger lazy-loading
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        # 4. Parse the populated HTML
        soup = BeautifulSoup(driver.page_source, "html.parser")
        skin_cards = soup.find_all("a", href=lambda h: h and h.startswith("/skin/"))
        
        results = []
        for card in skin_cards:
            skin_url = f"https://laby.net{card['href']}"
            img = card.find("img")
            img_url = img['src'] if img and 'src' in img.attrs else None
            
            if img_url:
                results.append({
                    "skin_url": skin_url,
                    "image_url": img_url
                })
        
        # Deduplicate
        unique_results = {res['skin_url']: res for res in results}.values()
        print(f"Scraped {len(unique_results)} skins successfully.")
        
        # 5. Save the data
        with open("skins_data.json", "w") as f:
            json.dump(list(unique_results), f, indent=4)
            
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    get_most_used_skins()
