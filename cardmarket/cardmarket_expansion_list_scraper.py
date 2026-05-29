"""
Cardmarket Yu-Gi-Oh! Expansion List Extractor - TCG Only
========================================================

Extracts all Yu-Gi-Oh! expansion IDs and names from Cardmarket.com
Filters out OCG expansions, keeps only TCG expansions
Ensures no duplicate expansion IDs in output

Version: 1.3 (TCG-Only)
"""

import json
import cloudscraper
from bs4 import BeautifulSoup
import time
import re

# Configuration
BASE_URL = "https://www.cardmarket.com"
SEARCH_URL = f"{BASE_URL}/en/YuGiOh/Products/Search?searchMode=v1&idCategory=0&idExpansion=0&onlyAvailable=on&idRarity=0&perSite=1"
OUTPUT_FILE = 'cardmarket_expansion_list.json'

# User agent
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


def create_scraper():
    """Create cloudscraper instance with realistic headers"""
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
        delay=10
    )
    
    scraper.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'Referer': f"{BASE_URL}/en/YuGiOh"
    })
    
    return scraper


def is_ocg_expansion(expansion_name):
    """
    Check if expansion name contains 'OCG' (case-sensitive, uppercase only)
    Returns True if OCG expansion, False if TCG
    """
    return 'OCG' in expansion_name


def extract_expansions(html):
    """
    Extract expansion list from HTML
    FILTERS OUT OCG expansions, keeps only TCG
    ENSURES NO DUPLICATES using expansion_id as unique key
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find the expansion select dropdown by name attribute
    select_element = soup.find('select', attrs={'name': 'idExpansion'})
    
    if not select_element:
        print("✗ Could not find idExpansion select dropdown")
        return [], []
    
    # Extract ALL options (including those inside optgroups)
    options = select_element.find_all('option')
    
    print(f"Found {len(options)} total options in dropdown")
    
    # Use dictionaries to store expansions with ID as key (prevents duplicates)
    tcg_expansions_dict = {}
    ocg_expansions_dict = {}
    duplicate_count = 0
    
    for option in options:
        value = option.get('value', '').strip()
        text = option.get_text().strip()
        
        # Skip empty values or "All" option (value="0")
        if not value or value == '0':
            continue
        
        # Skip non-numeric values
        if not value.isdigit():
            continue
        
        expansion_id = int(value)
        
        # Decode HTML entities (&amp; -> &)
        expansion_name = text.replace('&amp;', '&')
        
        # Check if OCG or TCG
        is_ocg = is_ocg_expansion(expansion_name)
        
        # Select appropriate dictionary
        target_dict = ocg_expansions_dict if is_ocg else tcg_expansions_dict
        
        # Check if this ID already exists
        if expansion_id in target_dict:
            duplicate_count += 1
            continue
        
        # Store in appropriate dictionary
        target_dict[expansion_id] = {
            'expansion_id': expansion_id,
            'expansion_name': expansion_name
        }
    
    # Convert dictionary values to lists
    tcg_expansions = list(tcg_expansions_dict.values())
    ocg_expansions = list(ocg_expansions_dict.values())
    
    if duplicate_count > 0:
        print(f"⚠ Removed {duplicate_count} duplicate entries")
    
    return tcg_expansions, ocg_expansions


def main():
    """Main execution"""
    print("="*70)
    print(" CARDMARKET EXPANSION LIST EXTRACTOR v1.3 (TCG-Only)")
    print("="*70)
    print()
    
    # Create scraper
    print("Creating scraper...")
    scraper = create_scraper()
    
    # Warm up session
    print("Warming up session...")
    try:
        scraper.get(f"{BASE_URL}/en/YuGiOh", timeout=15)
        time.sleep(2)
    except Exception as e:
        print(f"⚠ Warning: Could not warm up session: {e}")
    
    # Fetch search page
    print(f"Fetching expansion list from Cardmarket...")
    print(f"URL: {SEARCH_URL}")
    print()
    
    try:
        response = scraper.get(SEARCH_URL, timeout=20)
        
        if response.status_code != 200:
            print(f"✗ Error: HTTP {response.status_code}")
            print(f"  Response: {response.reason}")
            return
        
        print(f"✓ Page loaded successfully ({len(response.text)} bytes)")
        print()
        
    except Exception as e:
        print(f"✗ Error fetching page: {e}")
        return
    
    # Extract expansions (TCG and OCG separately)
    print("Extracting expansion list...")
    tcg_expansions, ocg_expansions = extract_expansions(response.text)
    
    if not tcg_expansions and not ocg_expansions:
        print("✗ No expansions found!")
        print()
        print("Debug: Saving HTML to debug.html for inspection")
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        return
    
    total_found = len(tcg_expansions) + len(ocg_expansions)
    print(f"✓ Found {total_found} total expansions")
    print(f"  - TCG expansions: {len(tcg_expansions)}")
    print(f"  - OCG expansions (excluded): {len(ocg_expansions)}")
    print()
    
    # Display excluded OCG expansions (first 5)
    if ocg_expansions:
        print("Excluded OCG expansions (first 5):")
        for exp in ocg_expansions[:5]:
            print(f"  [{exp['expansion_id']:5}] {exp['expansion_name']}")
        if len(ocg_expansions) > 5:
            print(f"  ... and {len(ocg_expansions) - 5} more")
        print()
    
    # Display first and last TCG expansions
    print("TCG expansions to be saved:")
    print("First 5:")
    for exp in tcg_expansions[:5]:
        print(f"  [{exp['expansion_id']:5}] {exp['expansion_name']}")
    
    if len(tcg_expansions) > 10:
        print("  ...")
        print("Last 5:")
        for exp in tcg_expansions[-5:]:
            print(f"  [{exp['expansion_id']:5}] {exp['expansion_name']}")
    
    print()
    
    # Final validation - check for any remaining duplicates in TCG list
    tcg_ids = [exp['expansion_id'] for exp in tcg_expansions]
    unique_tcg_ids = set(tcg_ids)
    
    if len(tcg_ids) != len(unique_tcg_ids):
        print(f"⚠ WARNING: Found {len(tcg_ids) - len(unique_tcg_ids)} duplicates in TCG list!")
        print("  This should not happen. Performing deduplication...")
        
        # Emergency deduplication
        seen = set()
        deduplicated = []
        for exp in tcg_expansions:
            if exp['expansion_id'] not in seen:
                seen.add(exp['expansion_id'])
                deduplicated.append(exp)
        
        tcg_expansions = deduplicated
        print(f"✓ After deduplication: {len(tcg_expansions)} unique TCG expansions")
    else:
        print(f"✓ Verified: All {len(tcg_expansions)} TCG expansions are unique")
    
    print()
    
    # Save only TCG expansions to JSON
    print(f"Saving TCG expansions to {OUTPUT_FILE}...")
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(tcg_expansions, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(tcg_expansions)} TCG expansions to {OUTPUT_FILE}")
        print(f"  (Excluded {len(ocg_expansions)} OCG expansions)")
        print()
        print("="*70)
        print(" COMPLETE")
        print("="*70)
        
    except Exception as e:
        print(f"✗ Error saving file: {e}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
