"""
Cardmarket Yu-Gi-Oh! Card Data Scraper - Final Complete Version
===============================================================

Handles all empty scenarios:
1. "Sorry, no matches" message on page 1
2. Redirect to product page (sealed/single card)
3. Search results with only sealed products (no Singles links)

Version: 10.0 (Final Complete - All Empty Cases)
"""

import json
import cloudscraper
from bs4 import BeautifulSoup
import time
import re
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from pathlib import Path

# Configuration
BASE_URL = "https://www.cardmarket.com"
INPUT_FILE = 'cardmarket_expansion_list.json'
OUTPUT_CARD_FILE = 'cardmarket_card_list.json'
OUTPUT_EMPTY_FILE = 'cardmarket_empty_expansions.json'
OUTPUT_REJECTED_FILE = 'cardmarket_rejected_expansions.json'
CHECKPOINT_FILE = 'cardmarket_card_list_checkpoint.json'
RECOVERY_CHECKPOINT_FILE = 'cardmarket_card_list_recovery_checkpoint.json'

# PHASE 1: Fast main run
PHASE1_MAX_WORKERS = 8
PHASE1_REQUESTS_PER_SECOND = 3
PHASE1_MAX_RETRIES = 2
PHASE1_RETRY_DELAY = (12, 18)

# PHASE 2: Careful recovery
PHASE2_MAX_WORKERS = 1
PHASE2_REQUESTS_PER_SECOND = 1
PHASE2_MAX_RETRIES = 5
PHASE2_RETRY_DELAY = (20, 30)
PHASE2_SESSION_WARMUP = 10

# Session settings
SESSION_REUSE_COUNT = 10
SESSION_WARMUP_DELAY = 2
RANDOM_JITTER = 0.3

# Locks
file_lock = threading.Lock()

# #region agent log
_DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "debug-43c26a.log"

def _agent_debug_log(hypothesis_id, location, message, data=None, run_id="pre-fix"):
    import json as _json
    payload = {
        "sessionId": "43c26a",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as _f:
            _f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #endregion

# User agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]


class RateLimiter:
    """Rate limiter with configurable speed"""
    
    def __init__(self, requests_per_second):
        self.min_interval = 1.0 / requests_per_second
        self.last_request = 0
        self.lock = threading.Lock()
    
    def wait(self, jitter=0.3):
        """Wait with optional jitter"""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request
            
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)
            
            if jitter > 0:
                time.sleep(random.uniform(0, jitter))
            
            self.last_request = time.time()


class SessionPool:
    """Session pool with reuse"""
    
    def __init__(self, num_workers):
        self.sessions = {}
        self.session_uses = {}
        self.lock = threading.Lock()
        self.num_workers = num_workers
    
    def get_session(self, worker_id):
        """Get or create session"""
        with self.lock:
            if worker_id in self.sessions and self.session_uses[worker_id] < SESSION_REUSE_COUNT:
                self.session_uses[worker_id] += 1
                return self.sessions[worker_id], False
            
            user_agent = USER_AGENTS[worker_id % len(USER_AGENTS)]
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                delay=10
            )
            
            scraper.headers.update({
                'User-Agent': user_agent,
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
            
            self.sessions[worker_id] = scraper
            self.session_uses[worker_id] = 1
            
            return scraper, True
    
    def refresh_session(self, worker_id):
        """Force refresh"""
        with self.lock:
            if worker_id in self.sessions:
                del self.sessions[worker_id]
                del self.session_uses[worker_id]


def create_fresh_scraper(worker_id=0):
    """Create fresh scraper for recovery phase"""
    user_agent = USER_AGENTS[worker_id % len(USER_AGENTS)]
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
        delay=10
    )
    
    scraper.headers.update({
        'User-Agent': user_agent,
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


def warmup_session(scraper, delay=SESSION_WARMUP_DELAY):
    """Warm up session"""
    try:
        warmup_url = f"{BASE_URL}/en/YuGiOh"
        response = scraper.get(warmup_url, timeout=15)
        time.sleep(delay)
        return response.status_code == 200
    except:
        return False


def fetch_page(scraper, url, rate_limiter, retries=3):
    """Fetch page with detailed error capture"""
    for attempt in range(retries):
        try:
            rate_limiter.wait()
            response = scraper.get(url, timeout=20)
            
            if response.status_code == 200:
                # #region agent log
                _html = response.text or ""
                _cf_markers = [m for m in ("_cf_chl_opt", "just a moment", "challenge-platform") if m in _html.lower()]
                _agent_debug_log(
                    "H1,H2",
                    "fetch_page:200",
                    "http_ok",
                    {
                        "url": url[-80:],
                        "final_url": (response.url or "")[-80:],
                        "html_len": len(_html),
                        "cf_markers": _cf_markers,
                        "product_row_count": len(re.findall(r"productRow\d+", _html)),
                        "gallery_box_count": _html.count("galleryBox"),
                    },
                )
                # #endregion
                return response.text, response.url, None, None
            elif response.status_code == 403:
                # #region agent log
                _agent_debug_log("H1,H5", "fetch_page:403", "http_forbidden", {"url": url[-80:], "attempt": attempt + 1})
                # #endregion
                error_detail = f"403 Forbidden (attempt {attempt + 1}/{retries})"
                if attempt < retries - 1:
                    time.sleep(20 * (attempt + 1))
                    continue
                return None, None, "403 Forbidden", error_detail
            elif response.status_code == 429:
                # #region agent log
                _agent_debug_log("H5", "fetch_page:429", "http_rate_limited", {"url": url[-80:], "attempt": attempt + 1})
                # #endregion
                error_detail = f"429 Rate Limited (attempt {attempt + 1}/{retries})"
                time.sleep(10 * (attempt + 1))
                continue
            elif response.status_code == 503:
                error_detail = f"503 Service Unavailable (attempt {attempt + 1}/{retries})"
                time.sleep(5)
                continue
            else:
                error_detail = f"HTTP {response.status_code}: {response.reason}"
                response.raise_for_status()
        except Exception as e:
            error_detail = f"{type(e).__name__}: {str(e)} (attempt {attempt + 1}/{retries})"
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return None, None, str(e), error_detail
    
    return None, None, "Max retries exceeded", f"Failed after {retries} attempts"


def check_if_product_page_redirect(html):
    """
    Check if redirected to a product page by looking for "Available items"
    Product pages (sealed or single card) have "Available items" in a <dt> tag
    Search result pages do NOT have this
    """
    if not html:
        return False
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Look for "Available items" in dt tags - this is ONLY on product pages
    dt_tags = soup.find_all('dt')
    for dt in dt_tags:
        if 'Available items' in dt.get_text():
            return True
    
    return False


def check_if_empty_on_first_page(html):
    """
    Check if page 1 explicitly says "no matches for your query"
    This check should ONLY happen on page 1
    """
    if not html:
        return False
    
    # Check for exact empty message
    if 'Sorry, no matches for your query' in html:
        return True
    
    return False


def check_if_only_sealed_products(html):
    """
    NEW: Check if page has productRows but NO Singles links
    (e.g., only sealed products like tins, structure decks, etc.)
    This means the expansion has no individual cards available
    """
    if not html:
        return False
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Check if there are product rows
    product_rows = soup.find_all('div', id=re.compile(r'^productRow\d+'))
    if not product_rows:
        return False
    
    # Check if ANY row has a Singles link
    has_singles = False
    for row in product_rows:
        singles_link = row.find('a', href=re.compile(r'/en/YuGiOh/Products/Singles/'))
        if singles_link:
            has_singles = True
            break
    
    # If we have rows but no Singles links, it's only sealed products
    return not has_singles


def extract_card_number_comprehensive(row, card_name, row_text, parts):
    """Extract card number"""
    card_number = ""
    
    # Strategy 1: After card name
    found_name = False
    for part in parts:
        if part == card_name:
            found_name = True
            continue
        
        if found_name and not card_number:
            if re.match(r'^[A-Z]{1,5}[0-9]{1,3}(-[A-Z]{2})?[0-9]{0,3}$', part, re.IGNORECASE):
                card_number = part
                break
            if re.match(r'^[A-Z]?[0-9]{1,3}[A-Z]?$', part, re.IGNORECASE):
                card_number = part
                break
            if re.match(r'^[A-Z]{1,5}-[0-9]{1,3}$', part, re.IGNORECASE):
                card_number = part
                break
            if re.match(r'^[A-Z0-9\-]{2,15}$', part):
                if part.isdigit() and int(part) > 100:
                    continue
                if '€' in part or ',' in part or '.' in part:
                    continue
                card_number = part
                break
    
    # Strategy 2: HTML structure
    if not card_number:
        try:
            main_col = row.find('div', class_='col')
            if main_col:
                nested_row = main_col.find('div', class_='row')
                if nested_row:
                    cols = nested_row.find_all('div', recursive=False)
                    for col in cols:
                        col_classes = ' '.join(col.get('class', []))
                        if 'col-md-2' in col_classes and 'd-lg-flex' in col_classes:
                            number_div = col.find('div')
                            if number_div:
                                text = number_div.get_text().strip()
                                if text and len(text) <= 20:
                                    if not (text.isdigit() and int(text) > 100):
                                        if '€' not in text and ',' not in text:
                                            card_number = text
                                            break
        except:
            pass
    
    # Strategy 3: Aggressive
    if not card_number:
        all_parts = re.split(r'[\|\s]+', row_text)
        for part in all_parts:
            part = part.strip()
            if not part or part == card_name:
                continue
            if re.match(r'^[A-Z]{1,5}[0-9]{1,4}', part, re.IGNORECASE):
                if len(part) <= 20:
                    card_number = part
                    break
            if '-' in part and re.match(r'^[A-Z0-9\-]{3,15}$', part, re.IGNORECASE):
                if '€' not in part:
                    card_number = part
                    break
    
    # Strategy 4: After expansion code
    if not card_number:
        exp_code_found = False
        for part in parts:
            if re.match(r'^[A-Z]{2,5}$', part):
                exp_code_found = True
                continue
            if exp_code_found:
                if re.match(r'^[A-Z0-9\-]{1,15}$', part):
                    if part.isdigit() and int(part) > 100:
                        continue
                    if '€' not in part and ',' not in part:
                        card_number = part
                        break
    
    return card_number


def extract_cards_from_html(html, expansion_id, expansion_name, expansion_code):
    """Extract cards"""
    cards = []
    soup = BeautifulSoup(html, 'html.parser')
    
    product_rows = soup.find_all('div', id=re.compile(r'^productRow\d+'))
    
    for row in product_rows:
        try:
            row_id = row.get('id', '')
            card_id_match = re.search(r'productRow(\d+)', row_id)
            if not card_id_match:
                continue
            card_id = int(card_id_match.group(1))
            
            card_link = row.find('a', href=re.compile(r'/en/YuGiOh/Products/Singles/'))
            if not card_link:
                continue
            
            card_name = card_link.get_text().strip()
            card_url = BASE_URL + card_link.get('href', '')
            
            row_text = row.get_text(separator='|', strip=True)
            parts = [p.strip() for p in row_text.split('|') if p.strip()]
            
            card_number = extract_card_number_comprehensive(row, card_name, row_text, parts)
            
            # Rarity
            card_rarity = ""
            rarity_svg = row.find('svg', attrs={'aria-label': True})
            if rarity_svg:
                card_rarity = rarity_svg.get('aria-label', '').strip()
            
            if not card_rarity:
                rarity_svg = row.find('svg', attrs={'data-bs-original-title': True})
                if rarity_svg:
                    card_rarity = rarity_svg.get('data-bs-original-title', '').strip()
            
            if not card_rarity:
                rarity_svg = row.find('svg', attrs={'title': True})
                if rarity_svg:
                    card_rarity = rarity_svg.get('title', '').strip()
            
            if not card_rarity:
                all_svgs = row.find_all('svg')
                for svg in all_svgs:
                    for attr, value in svg.attrs.items():
                        if isinstance(value, str) and any(word in value.lower() for word in ['rare', 'common', 'super', 'ultra', 'secret']):
                            card_rarity = value.strip()
                            break
                    if card_rarity:
                        break
            
            if not card_rarity:
                rarity_cols = row.find_all('div', class_='col-sm-2')
                for col in rarity_cols:
                    if 'd-none' in col.get('class', []) and 'd-sm-flex' in col.get('class', []):
                        svg = col.find('svg')
                        if svg:
                            for attr in ['aria-label', 'data-bs-original-title', 'title']:
                                val = svg.get(attr, '').strip()
                                if val:
                                    card_rarity = val
                                    break
            
            if not expansion_code:
                exp_symbol = row.find('a', class_='expansion-symbol')
                if exp_symbol:
                    exp_span = exp_symbol.find('span')
                    if exp_span:
                        expansion_code = exp_span.get_text().strip()
            
            cards.append({
                'expansion_id': expansion_id,
                'expansion_name': expansion_name,
                'expansion_code': expansion_code or '',
                'card_id': card_id,
                'card_name': card_name,
                'card_number': card_number,
                'card_rarity': card_rarity,
                'card_url': card_url
            })
            
        except:
            continue
    
    return cards, expansion_code


def scrape_expansion_with_retry(scraper, expansion_id, expansion_name, worker_id, rate_limiter, max_retries, retry_delay_range, is_recovery=False):
    """Scrape with comprehensive empty detection"""
    all_cards = []
    page = 1
    expansion_code = None
    fetch_issues = []
    html_errors = []
    
    while True:
        url = (
            f"{BASE_URL}/en/YuGiOh/Products/Search?"
            f"searchMode=v1&idCategory=0&idExpansion={expansion_id}"
            f"&onlyAvailable=on&idRarity=0&site={page}"
        )
        
        html, final_url, error, error_detail = fetch_page(scraper, url, rate_limiter)
        
        if error:
            fetch_issues.append(f"Page {page}: {error}")
            if error_detail:
                html_errors.append({
                    'page': page,
                    'url': url,
                    'error': error,
                    'detail': error_detail
                })
            if '403' in error:
                break
            break
        
        if not html:
            fetch_issues.append(f"Page {page}: No HTML")
            html_errors.append({
                'page': page,
                'url': url,
                'error': 'No HTML returned',
                'detail': 'Empty response from server'
            })
            break
        
        # Check 1: Redirected to product page
        if check_if_product_page_redirect(html):
            return all_cards, expansion_code, fetch_issues, html_errors, True
        
        # Check 2: "Sorry, no matches" on page 1
        if page == 1 and check_if_empty_on_first_page(html):
            return all_cards, expansion_code, fetch_issues, html_errors, True
        
        # Check 3: NEW - Only sealed products (no Singles links)
        if page == 1 and check_if_only_sealed_products(html):
            return all_cards, expansion_code, fetch_issues, html_errors, True
        
        # Check for product rows
        soup = BeautifulSoup(html, 'html.parser')
        product_rows = soup.find_all('div', id=re.compile(r'^productRow\d+'))
        
        if not product_rows:
            if page == 1:
                # #region agent log
                _agent_debug_log(
                    "H3,H4",
                    "scrape_expansion_with_retry:no_rows",
                    "page1_no_product_rows",
                    {
                        "expansion_id": expansion_id,
                        "page": page,
                        "final_url": (final_url or "")[-100:],
                        "gallery_box_count": html.count("galleryBox"),
                        "singles_link_count": len(soup.find_all("a", href=re.compile(r"/en/YuGiOh/Products/Singles/[^/]+/[^/]+"))),
                        "is_product_redirect": check_if_product_page_redirect(html),
                        "is_empty_msg": check_if_empty_on_first_page(html),
                    },
                )
                # #endregion
                fetch_issues.append(f"Page {page}: No product rows found")
                html_errors.append({
                    'page': page,
                    'url': url,
                    'final_url': final_url,
                    'error': 'No product rows',
                    'detail': 'Page loaded but no card data found',
                    'html_snippet': html[:500] if len(html) > 500 else html
                })
            break
        
        # Extract cards
        cards, exp_code = extract_cards_from_html(html, expansion_id, expansion_name, expansion_code)
        
        if not cards:
            if page == 1:
                fetch_issues.append(f"Page {page}: No cards extracted from {len(product_rows)} rows")
            break
        
        if page == 1:
            expansion_code = exp_code
        
        all_cards.extend(cards)
        page += 1
        
        if is_recovery:
            time.sleep(random.uniform(1.0, 2.0))
        else:
            time.sleep(0.4)
    
    return all_cards, expansion_code, fetch_issues, html_errors, False


def scrape_expansion_worker(worker_id, expansion, session_pool, rate_limiter, max_retries, retry_delay_range, is_recovery=False):
    """Worker function with detailed status tracking"""
    expansion_id = expansion.get('expansion_id')
    expansion_name = expansion.get('expansion_name', f'Expansion {expansion_id}')
    
    best_result = None
    best_card_count = 0
    all_attempts = []
    is_genuinely_empty = False
    
    for attempt in range(1, max_retries + 1):
        if is_recovery:
            scraper = create_fresh_scraper(worker_id)
            warmup_session(scraper, PHASE2_SESSION_WARMUP)
        else:
            scraper, is_new = session_pool.get_session(worker_id)
            if is_new:
                warmup_session(scraper)
        
        cards, expansion_code, fetch_issues, html_errors, is_empty = scrape_expansion_with_retry(
            scraper, expansion_id, expansion_name, worker_id, rate_limiter, 
            max_retries, retry_delay_range, is_recovery
        )
        
        card_count = len(cards)
        
        all_attempts.append({
            'attempt': attempt,
            'card_count': card_count,
            'issues': fetch_issues,
            'html_errors': html_errors,
            'is_empty': is_empty
        })
        
        if is_empty:
            is_genuinely_empty = True
            break
        
        if card_count > best_card_count:
            best_card_count = card_count
            best_result = {
                'cards': cards,
                'expansion_code': expansion_code,
                'attempt': attempt
            }
        
        if card_count > 0:
            break
        
        has_403 = any('403' in str(issue) for issue in fetch_issues)
        if has_403 and attempt < max_retries:
            if not is_recovery:
                session_pool.refresh_session(worker_id)
            time.sleep(random.uniform(30, 45))
        elif attempt < max_retries:
            retry_min, retry_max = retry_delay_range
            time.sleep(random.uniform(retry_min, retry_max))
    
    if best_result:
        final_cards = best_result['cards']
        final_code = best_result['expansion_code']
        successful_attempt = best_result['attempt']
        status = 'success'
    elif is_genuinely_empty:
        final_cards = []
        final_code = None
        successful_attempt = None
        status = 'empty'
    else:
        final_cards = []
        final_code = None
        successful_attempt = None
        status = 'rejected'
    
    # #region agent log
    _agent_debug_log(
        "H1,H3,H5",
        "scrape_expansion_worker:done",
        "worker_result",
        {
            "expansion_id": expansion_id,
            "status": status,
            "card_count": len(final_cards),
            "total_attempts": len(all_attempts),
            "fetch_issues": (all_attempts[-1].get("issues") if all_attempts else []),
        },
    )
    # #endregion
    return {
        'expansion': expansion,
        'cards': final_cards,
        'total_count': len(final_cards),
        'expansion_code': final_code,
        'attempts': all_attempts,
        'successful_attempt': successful_attempt,
        'total_attempts': len(all_attempts),
        'status': status,
        'is_empty': is_genuinely_empty
    }


def save_data(all_cards, expansions, empty_expansions, rejected_expansions):
    """Save all data"""
    with file_lock:
        try:
            with open(OUTPUT_CARD_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_cards, f, indent=2, ensure_ascii=False)
            
            with open(INPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(expansions, f, indent=2, ensure_ascii=False)
            
            if empty_expansions:
                with open(OUTPUT_EMPTY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(empty_expansions, f, indent=2, ensure_ascii=False)
            
            if rejected_expansions:
                with open(OUTPUT_REJECTED_FILE, 'w', encoding='utf-8') as f:
                    json.dump(rejected_expansions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Save error: {e}")


def phase1_fast_run(expansions, start_idx):
    """PHASE 1: Fast main run"""
    print("\n" + "="*70)
    print(" PHASE 1: FAST MAIN RUN")
    print("="*70)
    print(f"Workers: {PHASE1_MAX_WORKERS} | Speed: {PHASE1_REQUESTS_PER_SECOND} req/sec")
    print()
    
    session_pool = SessionPool(PHASE1_MAX_WORKERS)
    rate_limiter = RateLimiter(PHASE1_REQUESTS_PER_SECOND)
    
    remaining = expansions[start_idx:]
    all_cards = []
    empty_expansions = []
    rejected_expansions = []
    completed = 0
    stats = {'success': 0, 'empty': 0, 'rejected': 0}
    
    start_time = datetime.now()
    
    with ThreadPoolExecutor(max_workers=PHASE1_MAX_WORKERS) as executor:
        futures = {}
        for idx, expansion in enumerate(remaining):
            worker_id = idx % PHASE1_MAX_WORKERS
            future = executor.submit(
                scrape_expansion_worker, worker_id, expansion, session_pool,
                rate_limiter, PHASE1_MAX_RETRIES, PHASE1_RETRY_DELAY, False
            )
            futures[future] = (start_idx + idx, expansion)
        
        for future in as_completed(futures):
            idx, expansion = futures[future]
            
            try:
                result = future.result()
                
                expansion['total_number_of_cards'] = result['total_count']
                if result.get('expansion_code'):
                    expansion['expansion_code'] = result['expansion_code']
                
                all_cards.extend(result['cards'])
                
                if result['status'] == 'empty':
                    empty_expansions.append(expansion.copy())
                    stats['empty'] += 1
                elif result['status'] == 'rejected':
                    rejected_expansions.append({
                        'expansion_id': expansion['expansion_id'],
                        'expansion_name': expansion['expansion_name'],
                        'total_attempts': result['total_attempts'],
                        'attempts_detail': result['attempts'],
                        'timestamp': datetime.now().isoformat(),
                        'phase': 1
                    })
                    stats['rejected'] += 1
                else:
                    stats['success'] += 1
                
                completed += 1
                
                progress = (completed / len(remaining)) * 100
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = completed / elapsed * 3600 if elapsed > 0 else 0
                eta = (len(remaining) - completed) / completed * elapsed / 60 if completed > 0 else 999
                
                exp_name = expansion.get('expansion_name', '')[:28]
                exp_id = expansion.get('expansion_id')
                cards_count = result['total_count']
                
                if result['status'] == 'success':
                    status_icon = "✓ Success"
                elif result['status'] == 'empty':
                    status_icon = "⊘ Empty  "
                else:
                    status_icon = "✗ Failed "
                
                retry_marker = f"(R{result['total_attempts']})" if result['total_attempts'] > 1 else "    "
                
                print(f"[{completed:4}/{len(remaining)}] {exp_name:<28} (ID: {exp_id:5}) | {cards_count:4} cards {retry_marker} | {status_icon} | {progress:5.1f}% | {rate:4.0f}/h | ETA: {eta:4.0f}m")
                
                if completed % 50 == 0:
                    save_data(all_cards, expansions, empty_expansions, rejected_expansions)
                    with file_lock:
                        with open(CHECKPOINT_FILE, 'w') as f:
                            json.dump({'last_expansion_idx': idx}, f)
                
            except Exception as e:
                print(f"✗ Error: {e}")
                continue
    
    save_data(all_cards, expansions, empty_expansions, rejected_expansions)
    
    duration = datetime.now() - start_time
    
    print(f"\n{'='*70}")
    print(" PHASE 1 COMPLETE")
    print(f"{'='*70}")
    print(f"Total cards: {len(all_cards)}")
    print(f"Successful: {stats['success']}")
    print(f"Empty: {stats['empty']}")
    print(f"Rejected: {stats['rejected']}")
    print(f"Duration: {duration}")
    print(f"Speed: {len(remaining) / (duration.total_seconds() / 3600):.0f} exp/hour")
    
    return all_cards, empty_expansions, rejected_expansions, stats


def phase2_recovery(expansions_dict, rejected_list, all_cards):
    """PHASE 2: Careful recovery"""
    
    if not rejected_list:
        print("\n✓ No rejections to recover!")
        return all_cards, []
    
    recovery_start_idx = 0
    if Path(RECOVERY_CHECKPOINT_FILE).exists():
        with open(RECOVERY_CHECKPOINT_FILE, 'r') as f:
            recovery_checkpoint = json.load(f)
        recovery_start_idx = recovery_checkpoint.get('last_processed', 0)
        print(f"✓ Resuming recovery from rejection #{recovery_start_idx + 1}")
    
    remaining_rejected = rejected_list[recovery_start_idx:]
    
    print("\n" + "="*70)
    print(" PHASE 2: CAREFUL RECOVERY (Rejected Only)")
    print("="*70)
    print(f"Workers: {PHASE2_MAX_WORKERS} | Speed: {PHASE2_REQUESTS_PER_SECOND} req/sec")
    print(f"Retries: {PHASE2_MAX_RETRIES} | Warmup: {PHASE2_SESSION_WARMUP}s")
    print(f"Rejections to process: {len(remaining_rejected)}")
    print()
    
    rate_limiter = RateLimiter(PHASE2_REQUESTS_PER_SECOND)
    
    recovered_cards = []
    still_rejected = []
    now_empty = []
    recovered_count = 0
    
    start_time = datetime.now()
    
    for idx, rejected_exp in enumerate(remaining_rejected):
        expansion_id = rejected_exp['expansion_id']
        expansion_name = rejected_exp['expansion_name']
        
        expansion = {
            'expansion_id': expansion_id,
            'expansion_name': expansion_name
        }
        
        print(f"[{idx + 1}/{len(remaining_rejected)}] {expansion_name[:35]:<35} (ID: {expansion_id:5})", end=' ')
        
        result = scrape_expansion_worker(
            0, expansion, None, rate_limiter,
            PHASE2_MAX_RETRIES, PHASE2_RETRY_DELAY, is_recovery=True
        )
        
        if result['status'] == 'success':
            recovered_count += 1
            recovered_cards.extend(result['cards'])
            all_cards.extend(result['cards'])
            
            if expansion_id in expansions_dict:
                expansions_dict[expansion_id]['total_number_of_cards'] = result['total_count']
                if result.get('expansion_code'):
                    expansions_dict[expansion_id]['expansion_code'] = result['expansion_code']
            
            print(f"| ✓ Recovered {result['total_count']:4} cards!")
        elif result['status'] == 'empty':
            now_empty.append(rejected_exp)
            print(f"| ⊘ Confirmed empty")
        else:
            rejected_exp['phase2_attempts'] = result['attempts']
            still_rejected.append(rejected_exp)
            print(f"| ✗ Still rejected")
        
        if (idx + 1) % 10 == 0:
            save_data(all_cards, list(expansions_dict.values()), now_empty, still_rejected)
            with file_lock:
                with open(RECOVERY_CHECKPOINT_FILE, 'w') as f:
                    json.dump({'last_processed': recovery_start_idx + idx}, f)
    
    save_data(all_cards, list(expansions_dict.values()), now_empty, still_rejected)
    
    if Path(RECOVERY_CHECKPOINT_FILE).exists():
        Path(RECOVERY_CHECKPOINT_FILE).unlink()
    
    duration = datetime.now() - start_time
    
    print(f"\n{'='*70}")
    print(" PHASE 2 COMPLETE")
    print(f"{'='*70}")
    print(f"Recovered: {recovered_count}/{len(remaining_rejected)}")
    print(f"Now confirmed empty: {len(now_empty)}")
    print(f"Still rejected: {len(still_rejected)}")
    print(f"Duration: {duration}")
    
    return all_cards, now_empty, still_rejected


def main():
    """Main execution"""
    print("="*70)
    print(" CARDMARKET SCRAPER v10.0 - Complete")
    print("="*70)
    print()
    
    overall_start = datetime.now()
    
    print("="*70)
    print(" Loading Expansions")
    print("="*70)
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        expansions = json.load(f)
    print(f"✓ Loaded {len(expansions)} expansions\n")
    
    expansions_dict = {exp['expansion_id']: exp for exp in expansions}
    
    checkpoint = {'last_expansion_idx': -1}
    if Path(CHECKPOINT_FILE).exists():
        with open(CHECKPOINT_FILE, 'r') as f:
            checkpoint = json.load(f)
        start_idx = checkpoint.get('last_expansion_idx', -1) + 1
        if start_idx > 0:
            print(f"✓ Resuming Phase 1 from expansion #{start_idx + 1}\n")
    else:
        start_idx = 0
    
    all_cards, empty_expansions, rejected_list, stats = phase1_fast_run(expansions, start_idx)
    
    if Path(CHECKPOINT_FILE).exists():
        Path(CHECKPOINT_FILE).unlink()
    
    if rejected_list:
        print(f"\n⚠️  Phase 1 left {len(rejected_list)} REJECTED expansions")
        print(f"   (Empty expansions are normal and won't be retried)")
        print("   Starting Phase 2 recovery for rejected only...")
        
        all_cards, newly_empty, still_rejected = phase2_recovery(expansions_dict, rejected_list, all_cards)
        empty_expansions.extend(newly_empty)
    else:
        still_rejected = []
    
    overall_duration = datetime.now() - overall_start
    
    print("\n" + "="*70)
    print(" FINAL SUMMARY")
    print("="*70)
    print(f"Total cards: {len(all_cards)}")
    print(f"Successful expansions: {stats['success']}")
    print(f"Empty expansions: {len(empty_expansions)}")
    if rejected_list:
        recovered = len(rejected_list) - len(still_rejected)
        print(f"Phase 1 rejections: {len(rejected_list)}")
        print(f"Phase 2 recovered: {recovered}")
    print(f"Final rejections: {len(still_rejected)}")
    print(f"Overall duration: {overall_duration}")
    print("="*70)
    
    print("\n✓ Complete!")
    
    if still_rejected:
        print(f"\n⚠️  {len(still_rejected)} expansions still rejected")
        print(f"   Details with HTML errors in: {OUTPUT_REJECTED_FILE}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted - progress saved")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
