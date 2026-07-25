import json
import time
import cloudscraper

def get_all_skins_data():
    print("Initializing Cloudscraper for GitHub Actions...")
    
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'linux',
            'desktop': True
        }
    )
    
    all_skins = []
    page = 1
    MAX_PAGES = 500 
    PAGE_SIZE = 36 # Based on the size parameter in your API URL
    
    while page <= MAX_PAGES:
        # Calculate the dynamic offset (Page 1 = 0, Page 2 = 36, Page 3 = 72...)
        offset = (page - 1) * PAGE_SIZE
        
        # Inject the dynamic offset into the exact URL you found
        api_url = f"https://laby.net/api/v3/search/textures/skin?order=most_used&size={PAGE_SIZE}&offset={offset}"
        
        print(f"Fetching API page {page}/{MAX_PAGES} (Offset: {offset})...")
        
        try:
            response = scraper.get(api_url)
            
            if response.status_code != 200:
                print(f"Failed to load API page {page}. Status code: {response.status_code}")
                break
            
            data = response.json()
            
            # The API might return a direct list or wrap it in a dictionary (e.g., {"results": [...]})
            if isinstance(data, list):
                skin_list = data
            elif isinstance(data, dict):
                # Try common keys used for JSON arrays
                skin_list = data.get("results") or data.get("data") or data.get("items") or data.get("textures", [])
            else:
                print("Unexpected JSON format.")
                break
                
            if not skin_list:
                print("No more skins found in the API response. Reached the end!")
                break
                
            for skin in skin_list:
                # API v3 typically uses "hash" or "id" for the texture identifier
                skin_hash = skin.get("hash") or skin.get("image_hash") or skin.get("id")
                
                if skin_hash:
                    skin_url = f"https://laby.net/skin/{skin_hash}"
                    direct_download_url = f"http://textures.minecraft.net/texture/{skin_hash}"
                    render_url = f"https://laby.net/api/v3/render/skin/{skin_hash}.png?height=500&width=500"

                    all_skins.append({
                        "texture_hash": skin_hash,
                        "skin_url": skin_url, 
                        "download_url": direct_download_url,
                        "3d_render_url": render_url
                    })
            
            page += 1
            time.sleep(2) # Polite delay to protect your GitHub Action runner's IP
            
        except Exception as e:
            print(f"An error occurred on page {page}: {e}")
            break

    # Deduplicate the list using the unique hash
    unique_skins = list({res['texture_hash']: res for res in all_skins}.values())
    print(f"\nFinished! Collected a total of {len(unique_skins)} unique skins.")

    # Save to JSON
    with open("skins_data.json", "w") as f:
        json.dump(unique_skins, f, indent=4)
        
    print("Data successfully saved to skins_data.json.")

if __name__ == "__main__":
    get_all_skins_data()
