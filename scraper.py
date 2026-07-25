import json
import time
import cloudscraper
from bs4 import BeautifulSoup

def get_all_skins_data():
    print("Initializing Cloudflare bypass...")
    
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'android',
            'desktop': False
        }
    )
    
    all_skins = []
    page = 1
    
    while True:
        # Append the page number to the URL to handle pagination
        url = f"https://laby.net/skins?order=most_used&page={page}"
        print(f"Fetching page {page}...")
        
        try:
            response = scraper.get(url)
            
            if response.status_code != 200:
                print(f"Failed to load page {page}. Cloudflare block or server error. Status code: {response.status_code}")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            skin_cards = soup.find_all("a", href=lambda h: h and h.startswith("/skins/"))
            
            # If no skins are found on the current page, we have reached the end of the database
            if not skin_cards:
                print("No more skins found. Reached the end of the list!")
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
            
            print(f"Successfully scraped page {page}.")
            
            # Increment to the next page
            page += 1
            
            # IMPORTANT: Polite delay to avoid IP bans
            time.sleep(2)
            
        except Exception as e:
            print(f"An error occurred on page {page}: {e}")
            break

    # Deduplicate the final massive list
    unique_skins = list({res['skin_url']: res for res in all_skins}.values())
    print(f"\nFinished! Collected a total of {len(unique_skins)} skins.")

    # Save to a master JSON file
    with open("all_skins_data.json", "w") as f:
        json.dump(unique_skins, f, indent=4)
        
    print("Data successfully saved to all_skins_data.json.")

if __name__ == "__main__":
    get_all_skins_data()
