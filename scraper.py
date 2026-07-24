from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json

URL = "https://laby.net/skins?order=most_used"

skins = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    page = browser.new_page(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
    )

    page.goto(URL, wait_until="networkidle")

    # Scroll several times to load more skins
    for _ in range(20):
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(1000)

    html = page.content()

    browser.close()

soup = BeautifulSoup(html, "html.parser")

# Save HTML for debugging
with open("page.html", "w", encoding="utf-8") as f:
    f.write(html)

links = soup.find_all("a", href=True)

seen = set()

for link in links:

    href = link["href"]

    if "/skin/" not in href:
        continue

    if href.startswith("/"):
        href = "https://laby.net" + href

    if href in seen:
        continue

    seen.add(href)

    skins.append({
        "url": href
    })

with open("skins.json", "w", encoding="utf-8") as f:
    json.dump(skins, f, indent=4)

print("Found", len(skins), "skins")
