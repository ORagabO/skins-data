import requests
from bs4 import BeautifulSoup
import json

URL = "https://laby.net/skins?order=most_used"

headers = {
    "User-Agent": "Mozilla/5.0"
}

response = requests.get(URL, headers=headers)
html = response.text

soup = BeautifulSoup(html, "html.parser")

skins = []

# NOTE: You will need to adjust these selectors after inspecting the page
cards = soup.select("a")

for card in cards:
    href = card.get("href")
    if href and "/skin/" in href:
        skins.append({
            "url": "https://laby.net" + href
        })

# remove duplicates
unique = []
seen = set()

for s in skins:
    if s["url"] not in seen:
        seen.add(s["url"])
        unique.append(s)

with open("skins.json", "w", encoding="utf-8") as f:
    json.dump(unique, f, ensure_ascii=False, indent=2)

print(f"Saved {len(unique)} skins")