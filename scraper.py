import time
import json
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
def get_most_used_skins():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # --- NEW ANTI-BOT MEASURES ---
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    # -----------------------------
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # ... (Keep the rest of your code exactly the same) ...
def get_most_used_skins():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Initialize WebDriver directly (No webdriver_manager)
    driver = webdriver.Chrome(options=chrome_options)
    
    print("Loading laby.net...")
    driver.get("https://laby.net/skins?order=most_used")
    
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/skin/']"))
        )
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        skin_cards = soup.find_all("a", href=lambda h: h and h.startswith("/skin/"))
        
        results = []
        for card in skin_cards:
            skin_url = f"https://laby.net{card['href']}"
            img = card.find("img")
            img_url = img['src'] if img and 'src' in img.attrs else None
            
            if img_url:
                results.append({"skin_url": skin_url, "image_url": img_url})
        
        unique_results = {res['skin_url']: res for res in results}.values()
        print(f"Scraped {len(unique_results)} skins successfully.")
        
        with open("skins_data.json", "w") as f:
            json.dump(list(unique_results), f, indent=4)
            
    except Exception as e:
        print(f"An error occurred: {e}")
        driver.save_screenshot("error_screenshot.png") # Takes a picture of the screen to see if we got blocked
        raise e # <--- THIS IS THE NEW LINE. It forces the script to report the failure.
    finally:
        driver.quit()

if __name__ == "__main__":
    get_most_used_skins()
