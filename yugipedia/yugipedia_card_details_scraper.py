import json
import cloudscraper
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import random


# Configuration following Wikimedia Foundation User-Agent Policy
USER_AGENT = 'YugipediaCardBot/1.0 (https://github.com/egera24; egera24@gmail.com) requests/2.31.0'
INPUT_FILE = 'yugipedia_passcode_list.json'
OUTPUT_FILE = 'yugipedia_all_cards.json'
REJECTED_FILE = 'yugipedia_rejected_cards.json'


# Concurrent settings - OPTIMIZED for speed while respecting server
MAX_WORKERS = 8
REQUESTS_PER_SECOND = 3
MIN_REQUEST_INTERVAL = 1.0 / REQUESTS_PER_SECOND


# Retry configuration - IMPROVED for handling server errors
MAX_RETRIES = 5  # Increased from 3 to 5
REQUEST_TIMEOUT = 60  # Increased from 30 to 60 seconds
RETRY_DELAYS = [3, 5, 10, 15, 20]  # Progressive delays for each retry


# Rarity code mapping - FIXED: Added 10000 Secret Rare
RARITY_CODES = {
    'Common': 'C', 'Rare': 'R', 'Super Rare': 'SR', 'Ultra Rare': 'UR',
    'Secret Rare': 'ScR', 'Ultimate Rare': 'UtR', 'Ghost Rare': 'GR',
    'Holographic Rare': 'HR', 'Gold Rare': 'GR', "Collector's Rare": 'CR',
    'Starlight Rare': 'StR', 'Prismatic Secret Rare': 'PSR', 'Platinum Rare': 'PlR',
    'Quarter Century Secret Rare': 'QCR', 'Parallel Rare': 'PR', 'Starfoil Rare': 'SFR',
    'Mosaic Rare': 'MR', 'Duel Terminal Rare': 'DTR',
    '10000 Secret Rare': '10000ScR'  # ADDED: New rarity mapping
}


MONSTER_TYPES = ['Aqua', 'Beast', 'Beast-Warrior', 'Cyberse', 'Dinosaur', 'Divine-Beast',
                 'Dragon', 'Fairy', 'Fiend', 'Fish', 'Insect', 'Machine', 'Plant',
                 'Psychic', 'Pyro', 'Reptile', 'Rock', 'Sea Serpent', 'Spellcaster',
                 'Thunder', 'Warrior', 'Winged Beast', 'Wyrm', 'Zombie', 'Illusion']


MONSTER_MECHANICS = ['Normal', 'Ritual', 'Fusion', 'Synchro', 'Xyz', 'Pendulum',
                     'Link', 'Flip', 'Union', 'Gemini', 'Toon', 'Spirit']


LINK_MARKER_MAP = {
    'Top-Left': 'Top-Left', 'Top-Center': 'Top', 'Top-Right': 'Top-Right',
    'Middle-Left': 'Left', 'Middle-Right': 'Right', 'Bottom-Left': 'Bottom-Left',
    'Bottom-Center': 'Bottom', 'Bottom-Right': 'Bottom-Right'
}


class RateLimiter:
    """Thread-safe rate limiter using token bucket algorithm"""
    def __init__(self, rate):
        self.rate = rate
        self.lock = threading.Lock()
        self.last_request_time = 0

    def acquire(self):
        """Wait if necessary to respect rate limit"""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.rate:
                sleep_time = self.rate - time_since_last
                time.sleep(sleep_time)
            self.last_request_time = time.time()


rate_limiter = RateLimiter(MIN_REQUEST_INTERVAL)


def create_scraper():
    """Create CloudScraper instance that bypasses Cloudflare"""
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    scraper.headers.update({'User-Agent': USER_AGENT})
    return scraper


def fetch_page(scraper, url, retries=MAX_RETRIES):
    """
    Fetch page with enhanced retry logic for handling server errors
    
    Handles:
    - 502 Bad Gateway (temporary server issue)
    - 500 Internal Server Error (temporary server issue)
    - Read timeouts (slow server response)
    - Network errors
    
    Args:
        scraper: CloudScraper instance
        url: URL to fetch
        retries: Maximum number of retry attempts (default: 5)
        
    Returns:
        Tuple of (html_text, error_message)
    """
    for attempt in range(retries):
        try:
            # Respect rate limit
            rate_limiter.acquire()
            
            # Make request with increased timeout
            response = scraper.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            # Success!
            return response.text, None
            
        except cloudscraper.exceptions.CloudflareChallengeError as e:
            # Cloudflare challenge failed
            error_msg = f"CloudflareError: {str(e)[:100]}"
            if attempt < retries - 1:
                wait_time = RETRY_DELAYS[attempt] + random.uniform(0, 2)  # Add jitter
                time.sleep(wait_time)
                continue
            return None, error_msg
            
        except Exception as e:
            error_type = type(e).__name__
            error_str = str(e)
            
            # Check if it's a retryable error
            is_retryable = any([
                '502' in error_str,  # Bad Gateway
                '503' in error_str,  # Service Unavailable
                '500' in error_str,  # Internal Server Error
                '504' in error_str,  # Gateway Timeout
                'timeout' in error_str.lower(),  # Any timeout
                'timed out' in error_str.lower(),
                'ReadTimeout' in error_type,
                'ConnectTimeout' in error_type,
                'ConnectionError' in error_type,
            ])
            
            if is_retryable and attempt < retries - 1:
                # Use progressive delays with jitter for retryable errors
                base_wait = RETRY_DELAYS[attempt]
                jitter = random.uniform(0, 2)  # Random 0-2 second jitter
                wait_time = base_wait + jitter
                
                # Log retry attempt (only for debugging, comment out in production)
                # print(f"  ⚠ Retry {attempt + 1}/{retries} after {wait_time:.1f}s for {error_type}")
                
                time.sleep(wait_time)
                continue
            else:
                # Non-retryable error or exhausted retries
                error_msg = f"{error_type}: {error_str[:100]}"
                return None, error_msg
    
    return None, f"Failed after {retries} retry attempts"


def extract_text_only(element):
    """Extract clean text from HTML element, preserving <br> as \n"""
    if not element:
        return ""
    for br in element.find_all('br'):
        br.replace_with('\n')
    text = element.get_text()
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    return text.strip()


def find_row_by_header(soup, header_text):
    """Find table row by header text"""
    for th in soup.find_all('th'):
        if header_text in th.get_text():
            tr = th.find_parent('tr')
            if tr:
                return tr
    return None


def extract_password_from_page(soup):
    """Extract password from card page"""
    row = find_row_by_header(soup, 'Password')
    if row:
        td = row.find('td')
        if td:
            link = td.find('a')
            if link:
                return link.get_text().strip().zfill(8)
    return None


def extract_property(soup):
    """Extract property (for Spell/Trap cards)"""
    row = find_row_by_header(soup, 'Property')
    if row:
        td = row.find('td')
        if td:
            link = td.find('a')
            if link:
                return link.get_text().strip()
    return None


def extract_attribute(soup):
    """Extract attribute (for Monster cards)"""
    row = find_row_by_header(soup, 'Attribute')
    if row:
        td = row.find('td')
        if td:
            link = td.find('a')
            if link:
                return link.get_text().strip()
    return None


def extract_typeline(soup):
    """Extract typeline (Types) for Monster cards"""
    row = find_row_by_header(soup, 'Types')
    if row:
        td = row.find('td')
        if td:
            types = []
            for link in td.find_all('a'):
                type_text = link.get_text().strip()
                if type_text:
                    types.append(type_text)
            return types
    return []


def determine_monster_type(typeline):
    """Determine the monster type from typeline"""
    for t in typeline:
        if t in MONSTER_TYPES:
            return t
    return None


def determine_mechanics(typeline):
    """Determine mechanics from typeline"""
    mechanics = []
    for t in typeline:
        if t in MONSTER_MECHANICS:
            mechanics.append(t)
    return mechanics if mechanics else None


def has_effect(typeline):
    """Check if card has Effect"""
    return "yes" if "Effect" in typeline else "no"


def extract_level_or_rank(soup):
    """Extract Level or Rank"""
    row = find_row_by_header(soup, 'Level')
    if row:
        td = row.find('td')
        if td:
            link = td.find('a')
            if link:
                match = re.search(r'\d+', link.get_text())
                if match:
                    return {'level': int(match.group())}
    row = find_row_by_header(soup, 'Rank')
    if row:
        td = row.find('td')
        if td:
            link = td.find('a')
            if link:
                match = re.search(r'\d+', link.get_text())
                if match:
                    return {'rank': int(match.group())}
    return None


def extract_pendulum_scale(soup):
    """Extract Pendulum Scale"""
    row = find_row_by_header(soup, 'Pendulum Scale')
    if row:
        td = row.find('td')
        if td:
            link = td.find('a', href=lambda x: x and 'Pendulum_Scale_' in x)
            if link:
                match = re.search(r'\d+', link.get_text())
                if match:
                    return int(match.group())
    return None


def extract_link_markers(soup):
    """
    FIXED: Extract Link Arrows/Markers - only returns markers that exist on the card
    """
    row = find_row_by_header(soup, 'Link Arrow')
    if row:
        td = row.find('td')
        if td:
            markers = []
            # Look for the list of link arrows (hlist hcomma section)
            hlist = td.find('div', class_='hlist')
            if hlist:
                # Find all list items with links to arrow cards
                for li in hlist.find_all('li'):
                    link = li.find('a')
                    if link:
                        # Extract the arrow name from the link text
                        arrow_text = link.get_text().strip()
                        # Map the arrow name using our mapping
                        if arrow_text in LINK_MARKER_MAP:
                            mapped = LINK_MARKER_MAP[arrow_text]
                            if mapped not in markers:
                                markers.append(mapped)
            return markers if markers else None
    return None


def extract_atk_def(soup, is_link=False):
    """
    FIXED: Extract ATK and DEF (or LINK rating) - handles both integers and strings like "?"
    """
    result = {}

    if is_link:
        # For Link monsters: ATK / LINK
        row = find_row_by_header(soup, 'ATK')
        if row:
            td = row.find('td')
            if td:
                links = td.find_all('a')
                if len(links) >= 1:
                    # First link is ATK
                    atk_text = links[0].get_text().strip()
                    # Try to convert to int, if fails keep as string
                    match = re.search(r'\d+', atk_text)
                    if match:
                        result['atk'] = int(match.group())
                    else:
                        # Non-numeric value like "?"
                        result['atk'] = atk_text

                if len(links) >= 2:
                    # Second link is LINK rating
                    match = re.search(r'\d+', links[1].get_text())
                    if match:
                        result['link_rating'] = int(match.group())
    else:
        # For normal monsters: ATK / DEF
        row = find_row_by_header(soup, 'ATK')
        if row:
            td = row.find('td')
            if td:
                links = td.find_all('a')
                if len(links) >= 1:
                    # First link is ATK
                    atk_text = links[0].get_text().strip()
                    # Try to convert to int, if fails keep as string
                    match = re.search(r'\d+', atk_text)
                    if match:
                        result['atk'] = int(match.group())
                    else:
                        # Non-numeric value like "?"
                        result['atk'] = atk_text

                if len(links) >= 2:
                    # Second link is DEF
                    def_text = links[1].get_text().strip()
                    # Try to convert to int, if fails keep as string
                    match = re.search(r'\d+', def_text)
                    if match:
                        result['def'] = int(match.group())
                    else:
                        # Non-numeric value like "?"
                        result['def'] = def_text

    return result


def extract_lore_description(soup, is_pendulum=False):
    """Extract description from lore div"""
    lore_div = soup.find('div', class_='lore')
    if not lore_div:
        return None
    if is_pendulum:
        result = {}
        dl = lore_div.find('dl')
        if dl:
            current_section = None
            for child in dl.children:
                if child.name == 'dt':
                    current_section = child.get_text().strip()
                elif child.name == 'dd' and current_section:
                    text = extract_text_only(child)
                    if 'Pendulum Effect' in current_section:
                        result['pendulum_description'] = text
                    elif 'Monster Effect' in current_section:
                        result['monster_description'] = text
            if 'pendulum_description' in result and 'monster_description' in result:
                result['description'] = f"[ Pendulum Effect ]\n{result['pendulum_description']}\n\n[ Monster Effect ]\n{result['monster_description']}"
            return result
    else:
        return {'description': extract_text_only(lore_div)}


def extract_summoning_condition(soup, typeline):
    """Extract summoning condition for special summon monsters"""
    special_types = ['Link', 'Synchro', 'Xyz', 'Fusion']
    if not any(t in typeline for t in special_types):
        return None
    lore_div = soup.find('div', class_='lore')
    if lore_div:
        text = lore_div.get_text()
        lines = text.split('\n')
        if lines:
            first_line = lines[0].strip()
            if '.' in first_line:
                first_line = first_line.split('.')[0].strip() + '.'
            return first_line
    return None


def extract_archetype(soup):
    """Extract archetypes"""
    for dt in soup.find_all('dt'):
        if 'Archetype' in dt.get_text():
            dl = dt.find_parent('dl')
            if dl:
                archetypes = []
                for dd in dl.find_all('dd'):
                    link = dd.find('a')
                    if link:
                        archetype_text = link.get_text().strip()
                        if archetype_text and archetype_text not in archetypes:
                            archetypes.append(archetype_text)
                return archetypes if archetypes else None
    return None


def extract_card_sets(soup):
    """Extract card sets information"""
    tables = soup.find_all('table', class_='card-list')
    card_sets = []
    for table in tables:
        if 'cts--EN' not in table.get('id', ''):
            continue
        tbody = table.find('tbody')
        if not tbody:
            continue
        for row in tbody.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 4:
                release_date = cells[0].get_text().strip()
                set_code = cells[1].get_text().strip()
                set_name = cells[2].get_text().strip()
                set_name = re.sub(r'<.*?>', '', set_name)
                rarity_cell = cells[3]
                rarities = []
                br_tags = rarity_cell.find_all('br')
                if br_tags:
                    parts = str(rarity_cell).split('<br>')
                    for part in parts:
                        soup_part = BeautifulSoup(part, 'html.parser')
                        link = soup_part.find('a')
                        if link:
                            rarity_text = link.get_text().strip()
                            if rarity_text:
                                rarities.append(rarity_text)
                else:
                    link = rarity_cell.find('a')
                    if link:
                        rarity_text = link.get_text().strip()
                        if rarity_text:
                            rarities.append(rarity_text)
                for rarity in rarities:
                    rarity_code = RARITY_CODES.get(rarity, 'New')
                    card_set = {
                        'set_name': set_name,
                        'set_code': set_code,
                        'set_rarity': rarity,
                        'set_rarity_code': rarity_code,
                        'set_release_date': release_date
                    }
                    card_sets.append(card_set)
    return card_sets if card_sets else None


def parse_monster_card(soup, input_card):
    """Parse Monster Card from page"""
    card_data = {'id': input_card['password'], 'name': input_card['name']}
    try:
        page_password = extract_password_from_page(soup)
        if page_password != input_card['password']:
            return None, f"Password mismatch: expected {input_card['password']}, found {page_password}"
        typeline = extract_typeline(soup)
        if typeline:
            card_data['typeline'] = typeline
        attribute = extract_attribute(soup)
        if attribute:
            card_data['attribute'] = attribute
        monster_type = determine_monster_type(typeline)
        if monster_type:
            card_data['type'] = monster_type
        mechanics = determine_mechanics(typeline)
        if mechanics:
            card_data['mechanic'] = ', '.join(mechanics) if len(mechanics) > 1 else mechanics[0]
        card_data['effect'] = has_effect(typeline)
        level_rank = extract_level_or_rank(soup)
        if level_rank:
            card_data.update(level_rank)
        is_pendulum = 'Pendulum' in typeline
        if is_pendulum:
            pendulum_scale = extract_pendulum_scale(soup)
            if pendulum_scale is not None:
                card_data['pendulum_scale'] = pendulum_scale
        is_link = 'Link' in typeline
        if is_link:
            link_markers = extract_link_markers(soup)
            if link_markers:
                card_data['link_markers'] = link_markers
        atk_def = extract_atk_def(soup, is_link=is_link)
        card_data.update(atk_def)
        lore = extract_lore_description(soup, is_pendulum=is_pendulum)
        if lore:
            card_data.update(lore)
        summoning_cond = extract_summoning_condition(soup, typeline)
        if summoning_cond:
            card_data['summoning_condition'] = summoning_cond
        archetype = extract_archetype(soup)
        if archetype:
            card_data['archetype'] = ', '.join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data['card_sets'] = card_sets
        return card_data, None
    except Exception as e:
        return None, f"Error parsing monster card: {str(e)}"


def parse_spell_card(soup, input_card):
    """Parse Spell Card from page"""
    card_data = {'id': input_card['password'], 'name': input_card['name'], 'type': 'Spell'}
    try:
        page_password = extract_password_from_page(soup)
        if page_password != input_card['password']:
            return None, f"Password mismatch: expected {input_card['password']}, found {page_password}"
        property_val = extract_property(soup)
        if property_val:
            card_data['property'] = property_val
        lore = extract_lore_description(soup, is_pendulum=False)
        if lore and 'description' in lore:
            card_data['description'] = lore['description']
        archetype = extract_archetype(soup)
        if archetype:
            card_data['archetype'] = ', '.join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data['card_sets'] = card_sets
        return card_data, None
    except Exception as e:
        return None, f"Error parsing spell card: {str(e)}"


def parse_trap_card(soup, input_card):
    """Parse Trap Card from page"""
    card_data = {'id': input_card['password'], 'name': input_card['name'], 'type': 'Trap'}
    try:
        page_password = extract_password_from_page(soup)
        if page_password != input_card['password']:
            return None, f"Password mismatch: expected {input_card['password']}, found {page_password}"
        property_val = extract_property(soup)
        if property_val:
            card_data['property'] = property_val
        lore = extract_lore_description(soup, is_pendulum=False)
        if lore and 'description' in lore:
            card_data['description'] = lore['description']
        archetype = extract_archetype(soup)
        if archetype:
            card_data['archetype'] = ', '.join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data['card_sets'] = card_sets
        return card_data, None
    except Exception as e:
        return None, f"Error parsing trap card: {str(e)}"


def process_card(scraper, input_card, idx, total):
    """Process a single card (called by worker thread)"""
    url = input_card['url']
    card_type = input_card['card_type']

    html, error = fetch_page(scraper, url)
    if html is None:
        return {
            'success': False,
            'input_card': input_card,
            'error': error,
            'idx': idx,
            'total': total
        }

    soup = BeautifulSoup(html, 'html.parser')

    if card_type == 'Monster Card':
        card_data, error = parse_monster_card(soup, input_card)
    elif card_type == 'Spell Card':
        card_data, error = parse_spell_card(soup, input_card)
    elif card_type == 'Trap Card':
        card_data, error = parse_trap_card(soup, input_card)
    else:
        return {
            'success': False,
            'input_card': input_card,
            'error': f"Unknown card type: {card_type}",
            'idx': idx,
            'total': total
        }

    if error:
        return {
            'success': False,
            'input_card': input_card,
            'error': error,
            'idx': idx,
            'total': total
        }
    else:
        return {
            'success': True,
            'card_data': card_data,
            'input_card': input_card,
            'idx': idx,
            'total': total
        }


def main():
    """Main execution function"""
    print("="*70)
    print(" Yugipedia Card Details Scraper (ENHANCED RETRY v3)")
    print(" Wikimedia Foundation Policy Compliant")
    print("="*70)
    print()
    print(f"User-Agent: {USER_AGENT}")
    print(f"Max Workers: {MAX_WORKERS} concurrent threads")
    print(f"Rate Limit: {REQUESTS_PER_SECOND} requests/second")
    print()
    print("IMPROVEMENTS:")
    print("  ✓ Enhanced retry logic: 5 attempts (up from 3)")
    print("  ✓ Increased timeout: 60 seconds (up from 30)")
    print("  ✓ Progressive delays: 3s, 5s, 10s, 15s, 20s")
    print("  ✓ Smart error detection (502, 500, timeouts)")
    print("  ✓ Random jitter to avoid thundering herd")
    print()
    print("BUG FIXES:")
    print("  ✓ ATK/DEF handles string values (?, ???, etc.)")
    print("  ✓ Added rarity: 10000 Secret Rare → 10000ScR")
    print("  ✓ Link markers extraction fixed (only actual markers)")
    print()
    print(f"Input: {INPUT_FILE}")
    print(f"Output: {OUTPUT_FILE} | Rejected: {REJECTED_FILE}")
    print()

    print(f"+++[INFO]+++ Loading cards from {INPUT_FILE}...")
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            input_cards = json.load(f)
    except FileNotFoundError:
        print(f"+++[ERROR]+++ File {INPUT_FILE} not found!")
        return
    except json.JSONDecodeError as e:
        print(f"+++[ERROR]+++ Invalid JSON: {e}")
        return

    print(f"+++[INFO]+++ Loaded {len(input_cards)} cards")
    print()
    print("+++[INFO]+++ Initializing CloudScrapers...")

    scrapers = [create_scraper() for _ in range(MAX_WORKERS)]
    print(f"+++[INFO]+++ Created {MAX_WORKERS} CloudScraper instances")
    print()

    successful_cards = []
    rejected_cards = []

    print("+++[INFO]+++ Starting concurrent card processing...")
    print(f"+++[INFO]+++ Estimated time: ~{len(input_cards) / REQUESTS_PER_SECOND / 60:.1f} minutes")
    print()

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for idx, input_card in enumerate(input_cards, 1):
            scraper = scrapers[idx % MAX_WORKERS]
            future = executor.submit(process_card, scraper, input_card, idx, len(input_cards))
            futures[future] = input_card

        completed = 0
        for future in as_completed(futures):
            result = future.result()
            completed += 1

            progress_pct = (completed / len(input_cards)) * 100
            elapsed = time.time() - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (len(input_cards) - completed) / rate if rate > 0 else 0

            if result['success']:
                successful_cards.append(result['card_data'])
                status = "✓"
            else:
                rejected_entry = result['input_card'].copy()
                rejected_entry['rejection_reason'] = result['error']
                rejected_entry['rejection_timestamp'] = datetime.now().isoformat()
                rejected_cards.append(rejected_entry)
                status = "✗"

            print(f"[{completed}/{len(input_cards)} {progress_pct:5.1f}%] {status} {result['input_card']['name'][:40]:40} | Rate: {rate:.1f}/s | ETA: {eta/60:.1f}m")

    elapsed_time = time.time() - start_time

    print()
    print("="*70)
    print(" Processing Summary")
    print("="*70)
    print(f"+++[INFO]+++ Successfully processed: {len(successful_cards)} cards")
    print(f"+++[INFO]+++ Rejected: {len(rejected_cards)} cards")
    print(f"+++[INFO]+++ Total time: {elapsed_time/60:.1f} minutes")
    print(f"+++[INFO]+++ Average rate: {len(input_cards)/elapsed_time:.2f} cards/second")
    print()

    if successful_cards:
        print(f"+++[INFO]+++ Saving to {OUTPUT_FILE}...")
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(successful_cards, f, indent=2, ensure_ascii=False)
        print(f"+++[INFO]+++ Saved {len(successful_cards)} cards")

    if rejected_cards:
        print(f"+++[INFO]+++ Saving to {REJECTED_FILE}...")
        rejection_data = {
            'timestamp': datetime.now().isoformat(),
            'total_rejected': len(rejected_cards),
            'rejected_cards': rejected_cards
        }
        with open(REJECTED_FILE, 'w', encoding='utf-8') as f:
            json.dump(rejection_data, f, indent=2, ensure_ascii=False)
        print(f"+++[INFO]+++ Saved {len(rejected_cards)} rejected cards")

    print()
    print("="*70)
    print(" ✓ Processing Complete")
    print("="*70)


if __name__ == '__main__':
    main()
