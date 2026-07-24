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
    
    # ... [Keep the rest of your try/except block exactly the same] ...
