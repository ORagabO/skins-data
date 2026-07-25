import json
import time
import cloudscraper
from bs4 import BeautifulSoup

def get_all_skins_data():
    print("Initializing Cloudscraper for GitHub Actions...")
    
    # Set to Linux desktop since GitHub Actions runs on Ubuntu
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'linux',
            'desktop': True
        }
    )
    
    all_skins = []
    page = 1
    
    # --- GITHUB ACTIONS SAFEGUARD ---
    # GitHub kills scripts after 6 hours. 
    # 500 pages @ 2 seconds per page = ~20 minutes of runtime. 
    # Increase this number if you want it to run longer, but keep it under 5000!
    MAX_PAGES = 500 
    # --------------------------------
    
    while page <= MAX_PAGES:
        url = f"https://laby.net/skins?order=most_used&page={page}"
        print(f"Fetching page {page}/{MAX_PAGES}...")
        
        try:
            response = scraper.get(url)
            
            if response.status_code != 200:
                print(f"Failed to load page {page}. Status code: {response.status_code}")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            skin_cards = soup.find_all("a", href=lambda h: h and h.startswith("/skins/"))
            
            if not skin_cards:
                print("No more skins found. Reached the end of the database!")
                break
                
            for card in skin_cards:
                href = card.get('href')
                img = card.find("img")
                
                if img:
                    skin_url = f"https://laby.net{href}"
                    skin_name = img.get('alt', 'Unknown Skin')
                    
                    usage_span = card.find("span", class_="font-semibold")
                    usage_count = usage_span.text.strip() if usage_span else "0"

                    skin_hash = href.split('/')[-1] 
                    direct_download_url = f"http://textures.minecraft.net/texture/{skin_hash}"
                    render_url = f"https://laby.net/api/v3/render/skin/{skin_hash}.png?height=500&width=500"

                    all_skins.append({
                        "name": skin_name,
                        "uses": usage_count,
                        "skin_url": skin_url, 
                        "texture_hash": skin_hash,
                        "download_url": direct_download_url,
                        "3d_render_url": render_url
                    })
            
            # Increment to the next page
            page += 1
            
            # Polite delay to avoid GitHub's IP getting banned by Cloudflare
            time.sleep(2)
            
        except Exception as e:
            print(f"An error occurred on page {page}: {e}")
            break

    # Deduplicate the list
    unique_skins = list({res['skin_url']: res for res in all_skins}.values())
    print(f"\nFinished! Collected a total of {len(unique_skins)} unique skins.")

    # Save to JSON
    with open("skins_data.json", "w") as f:
        json.dump(unique_skins, f, indent=4)
        
    print("Data successfully saved to skins_data.json.")

if __name__ == "__main__":
    get_all_skins_data()
