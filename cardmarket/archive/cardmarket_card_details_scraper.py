"""
Cardmarket Yu-Gi-Oh! Card Details Scraper
=========================================

Extracts detailed price information for cards from Cardmarket.com
Two-phase architecture: Fast parallel run + careful recovery

Version: 1.4.2 - Fixed N/A priority check
"""

import json
import cloudscraper
from bs4 import BeautifulSoup
import time
import re
import random
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from pathlib import Path

# Configuration
INPUT_FILE = 'cardmarket_card_list.json'
OUTPUT_FILE = 'cardmarket_card_details.json'
REJECTION_FILE = 'cardmarket_card_details_rejection.json'
CHECKPOINT_FILE = 'cardmarket_card_details_checkpoint.json'
RECOVERY_CHECKPOINT_FILE = 'cardmarket_card_details_recovery_checkpoint.json'

# PHASE 1: Optimized speed
PHASE1_MAX_WORKERS = 20
PHASE1_REQUESTS_PER_SECOND = 8
PHASE1_MAX_RETRIES = 3
PHASE1_RETRY_DELAY = (3, 5)

# PHASE 2: Careful recovery
PHASE2_MAX_WORKERS = 1
PHASE2_REQUESTS_PER_SECOND = 1
PHASE2_MAX_RETRIES = 5
PHASE2_RETRY_DELAYS = [15, 30, 45, 60, 90]

# Session settings
SESSION_REUSE_COUNT = 15
RANDOM_JITTER = 0.1

# Save and display intervals
SAVE_INTERVAL = 100
DISPLAY_INTERVAL = 100

# Locks
file_lock = threading.Lock()
session_lock = threading.Lock()

# User agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
]


class RateLimiter:
    """Rate limiter with configurable speed"""
    
    def __init__(self, requests_per_second):
        self.min_interval = 1.0 / requests_per_second
        self.last_request = 0
        self.lock = threading.Lock()
    
    def wait(self, jitter=0.1):
        """Wait with minimal jitter"""
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
    """Session pool with extended reuse"""
    
    def __init__(self, num_workers):
        self.sessions = {}
        self.session_uses = {}
        self.lock = threading.Lock()
        self.num_workers = num_workers
        self.last_403_time = {}
    
    def get_session(self, worker_id):
        """Get or create session"""
        with self.lock:
            if worker_id in self.last_403_time:
                if time.time() - self.last_403_time[worker_id] < 30:
                    if worker_id in self.sessions:
                        del self.sessions[worker_id]
                        del self.session_uses[worker_id]
            
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
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0'
            })
            
            self.sessions[worker_id] = scraper
            self.session_uses[worker_id] = 1
            
            return scraper, True
    
    def mark_403(self, worker_id):
        """Mark that worker got 403"""
        with self.lock:
            self.last_403_time[worker_id] = time.time()
    
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
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    })
    
    return scraper


def parse_price(price_text):
    """
    Parse price from any currency format to float
    Returns: (price_value, is_na)
    - price_value: float or None
    - is_na: True if original text was "N/A"
    """
    try:
        if not price_text:
            return None, False
        
        # Check for N/A explicitly
        lower = price_text.lower().strip()
        if lower in ['n/a', 'n.a.', 'na', '--', '---', '–', '—']:
            return None, True
        
        # Extract numeric part
        cleaned = ''.join(c for c in price_text if c.isdigit() or c in '.,-')
        
        if not cleaned or cleaned in ['.', ',', '-', '.-', ',-']:
            return None, False
        
        # Decimal detection
        dot_count = cleaned.count('.')
        comma_count = cleaned.count(',')
        
        # Fast cases
        if comma_count == 0 and dot_count <= 1:
            return float(cleaned), False
        elif comma_count == 1 and dot_count == 0:
            return float(cleaned.replace(',', '.')), False
        
        # Complex cases
        if dot_count > 0 and comma_count > 0:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif dot_count > 1:
            cleaned = cleaned.replace('.', '')
        elif comma_count > 1:
            cleaned = cleaned.replace(',', '')
        
        return float(cleaned), False
        
    except:
        return None, False


def extract_price_data(html):
    """
    Extract all 5 price fields from HTML
    Priority: Check N/A FIRST, then missing fields, then success
    
    Returns: (prices_dict, has_na_flag)
    - prices_dict: dict with prices or None if invalid
    - has_na_flag: True if ANY price is N/A (even if fields missing)
    """
    soup = BeautifulSoup(html, 'html.parser')
    dts = soup.find_all('dt')
    
    prices = {
        'low_price': None,
        'trend_price': None,
        'avg_30_price': None,
        'avg_7_price': None,
        'avg_1_price': None
    }
    
    na_count = 0
    found_count = 0
    valid_count = 0
    
    label_map = {
        'from': 'low_price',
        'price trend': 'trend_price',
        '30-day': 'avg_30_price',
        '7-day': 'avg_7_price',
        '1-day': 'avg_1_price'
    }
    
    for dt in dts:
        dt_text = dt.get_text(strip=True).lower()
        
        for label, price_key in label_map.items():
            if label in dt_text:
                dd = dt.find_next_sibling('dd')
                if dd:
                    price_text = dd.get_text(strip=True)
                    price_value, is_na = parse_price(price_text)
                    
                    found_count += 1
                    
                    if is_na:
                        na_count += 1
                    elif price_value is not None:
                        prices[price_key] = price_value
                        valid_count += 1
                    # If price_value is None and not N/A, it's unparseable (invalid)
                break
    
    # PRIORITY 1: Check if ANY N/A exists (even if fields missing)
    if na_count > 0:
        return None, True  # Has N/A
    
    # PRIORITY 2: Check if all 5 fields were found
    if found_count < 5:
        return None, False  # Missing fields
    
    # PRIORITY 3: Check if all found prices are valid
    if valid_count < 5:
        return None, False  # Some prices unparseable
    
    # SUCCESS: All 5 prices valid
    return prices, False


def fetch_card_details(scraper, card_url, rate_limiter, worker_id, session_pool, retries=3):
    """Fetch card page"""
    for attempt in range(retries):
        try:
            rate_limiter.wait(RANDOM_JITTER)
            response = scraper.get(card_url, timeout=15)
            
            if response.status_code == 200:
                return response.text, None
            elif response.status_code == 403:
                if session_pool:
                    session_pool.mark_403(worker_id)
                    session_pool.refresh_session(worker_id)
                
                error_detail = f"HTTP 403 (attempt {attempt + 1}/{retries})"
                
                if attempt < retries - 1:
                    time.sleep(random.uniform(20, 30))
                    if session_pool:
                        scraper, _ = session_pool.get_session(worker_id)
                    continue
                return None, error_detail
            elif response.status_code == 404:
                return None, f"HTTP 404"
            elif response.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            elif response.status_code in [500, 503]:
                time.sleep(5)
                continue
            else:
                return None, f"HTTP {response.status_code}"
                
        except Exception as e:
            error_detail = f"{type(e).__name__}"
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None, error_detail
    
    return None, f"Max retries"


def validate_input_card(card):
    """Validate card"""
    required = ['expansion_id', 'expansion_name', 'expansion_code', 'card_id', 
                'card_name', 'card_number', 'card_rarity', 'card_url']
    
    for field in required:
        if field not in card:
            return False, f"Missing: {field}"
    
    if not str(card.get('expansion_code', '')).strip():
        return False, "Empty expansion_code"
    
    if not str(card.get('card_number', '')).strip():
        return False, "Empty card_number"
    
    if not card['card_url'].startswith('https://'):
        return False, "Invalid URL"
    
    return True, None


def process_card(scraper, card, rate_limiter, worker_id, session_pool, max_retries, is_recovery=False):
    """Process single card with N/A priority check"""
    
    is_valid, validation_error = validate_input_card(card)
    if not is_valid:
        return {
            'success': False,
            'rejection_reason': 'Failed - missing input data',
            'error_detail': validation_error,
            'card': card
        }
    
    html, error = fetch_card_details(scraper, card['card_url'], rate_limiter, worker_id, session_pool, max_retries)
    
    if not html:
        return {
            'success': False,
            'rejection_reason': 'Failed - site unreachable',
            'error_detail': error,
            'card': card
        }
    
    # Extract prices with N/A priority check
    prices, has_na = extract_price_data(html)
    
    # Check N/A first (even if fields missing)
    if has_na:
        return {
            'success': False,
            'rejection_reason': 'Failed - N/A',
            'error_detail': 'One or more price fields are N/A',
            'card': card
        }
    
    # Then check if extraction failed
    if prices is None:
        return {
            'success': False,
            'rejection_reason': 'Failed - missing data',
            'error_detail': 'Price fields missing or invalid',
            'card': card
        }
    
    exp_code = str(card['expansion_code']).strip()
    card_num = str(card['card_number']).strip()
    
    output = {
        'card_data': {
            'card_id': card['card_id'],
            'card_name': card['card_name'],
            'card_rarity': card['card_rarity'],
            'card_number': card['card_number'],
            'card_set_number': f"{exp_code}-EN{card_num}"
        },
        'expansion_data': {
            'expansion_id': card['expansion_id'],
            'expansion_name': card['expansion_name'],
            'expansion_code': card['expansion_code']
        },
        'price_data': {
            'url': card['card_url'],
            'low_price': prices['low_price'],
            'trend_price': prices['trend_price'],
            'avg_30_price': prices['avg_30_price'],
            'avg_7_price': prices['avg_7_price'],
            'avg_1_price': prices['avg_1_price'],
            'price_date': datetime.now().strftime('%Y-%m-%d'),
            'currency': 'EUR'
        }
    }
    
    return {
        'success': True,
        'data': output,
        'card': card
    }


def process_card_worker(worker_id, card, card_index, session_pool, rate_limiter, max_retries, retry_delays, is_recovery=False):
    """Worker function with retries"""
    
    attempts = []
    best_result = None
    
    for attempt in range(1, max_retries + 1):
        if is_recovery:
            scraper = create_fresh_scraper(worker_id)
        else:
            scraper, is_new = session_pool.get_session(worker_id)
        
        result = process_card(scraper, card, rate_limiter, worker_id, session_pool, 1, is_recovery)
        
        attempts.append({
            'attempt': attempt,
            'success': result['success'],
            'reason': result.get('rejection_reason', 'Success'),
            'error': result.get('error_detail', '')
        })
        
        if result['success']:
            best_result = result
            break
        
        # Don't retry for N/A (permanent condition)
        if 'N/A' in result.get('rejection_reason', ''):
            break
        
        if '403' in str(result.get('error_detail', '')):
            if attempt < max_retries:
                if is_recovery and len(retry_delays) >= attempt:
                    time.sleep(retry_delays[attempt - 1])
                else:
                    time.sleep(random.uniform(*PHASE1_RETRY_DELAY))
        elif attempt < max_retries:
            if is_recovery and len(retry_delays) >= attempt:
                time.sleep(retry_delays[attempt - 1])
            else:
                time.sleep(random.uniform(*PHASE1_RETRY_DELAY))
    
    if best_result and best_result['success']:
        return {
            'card_index': card_index,
            'status': 'success',
            'data': best_result['data'],
            'attempts': len(attempts)
        }
    else:
        last_attempt = attempts[-1]
        rejection = {
            'card_id': card['card_id'],
            'card_name': card.get('card_name', ''),
            'card_url': card.get('card_url', ''),
            'expansion_id': card.get('expansion_id'),
            'expansion_name': card.get('expansion_name', ''),
            'expansion_code': card.get('expansion_code', ''),
            'rejection_reason': last_attempt['reason'],
            'error_detail': last_attempt['error'],
            'timestamp': datetime.now().isoformat(),
            'attempts': len(attempts)
        }
        
        return {
            'card_index': card_index,
            'status': 'rejected',
            'rejection': rejection,
            'attempts': len(attempts)
        }


def save_data(successful_cards, rejections, checkpoint=None):
    """Save all data with thread lock"""
    with file_lock:
        try:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(successful_cards, f, indent=2, ensure_ascii=False)
            
            with open(REJECTION_FILE, 'w', encoding='utf-8') as f:
                json.dump(rejections, f, indent=2, ensure_ascii=False)
            
            if checkpoint:
                with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
                    json.dump(checkpoint, f, indent=2)
                    
        except Exception as e:
            print(f"✗ Save error: {e}")


def load_existing_data():
    """Load existing output files"""
    successful_cards = []
    rejections = []
    processed_card_ids = set()
    
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                successful_cards = json.load(f)
                processed_card_ids.update(c['card_data']['card_id'] for c in successful_cards)
        except:
            pass
    
    if os.path.exists(REJECTION_FILE):
        try:
            with open(REJECTION_FILE, 'r', encoding='utf-8') as f:
                rejections = json.load(f)
        except:
            pass
    
    return successful_cards, rejections, processed_card_ids


def phase1_fast_run(cards, start_idx):
    """PHASE 1: ULTRA-FAST parallel processing with enhanced display"""
    print("\n" + "="*70)
    print(" PHASE 1: ULTRA-FAST RUN")
    print("="*70)
    print(f"Workers: {PHASE1_MAX_WORKERS} | Speed: {PHASE1_REQUESTS_PER_SECOND} req/sec")
    print(f"Retries: {PHASE1_MAX_RETRIES} | Delay: {PHASE1_RETRY_DELAY[0]}-{PHASE1_RETRY_DELAY[1]}s")
    print(f"Display: Every {DISPLAY_INTERVAL} cards")
    print()
    
    session_pool = SessionPool(PHASE1_MAX_WORKERS)
    rate_limiter = RateLimiter(PHASE1_REQUESTS_PER_SECOND)
    
    successful_cards, rejections, processed_ids = load_existing_data()
    
    remaining = cards[start_idx:]
    completed = 0
    
    # Batch counters (reset every DISPLAY_INTERVAL)
    batch_success = 0
    batch_failed = 0
    batch_na = 0
    
    # Overall stats
    stats = {'success': 0, 'rejected_unreachable': 0, 'rejected_missing_data': 0, 
             'rejected_input': 0, 'rejected_na': 0}
    
    start_time = datetime.now()
    
    with ThreadPoolExecutor(max_workers=PHASE1_MAX_WORKERS) as executor:
        futures = {}
        for idx, card in enumerate(remaining):
            if card['card_id'] in processed_ids:
                continue
                
            worker_id = idx % PHASE1_MAX_WORKERS
            future = executor.submit(
                process_card_worker, worker_id, card, start_idx + idx,
                session_pool, rate_limiter, PHASE1_MAX_RETRIES, [], False
            )
            futures[future] = (start_idx + idx, card)
        
        for future in as_completed(futures):
            idx, card = futures[future]
            
            try:
                result = future.result()
                
                if result['status'] == 'success':
                    successful_cards.append(result['data'])
                    stats['success'] += 1
                    batch_success += 1
                else:
                    rejections.append(result['rejection'])
                    reason = result['rejection']['rejection_reason']
                    
                    # Categorize for detailed stats
                    if 'unreachable' in reason:
                        stats['rejected_unreachable'] += 1
                        batch_failed += 1
                    elif 'missing data' in reason:
                        stats['rejected_missing_data'] += 1
                        batch_failed += 1
                    elif 'missing input' in reason:
                        stats['rejected_input'] += 1
                        batch_failed += 1
                    elif 'N/A' in reason:
                        stats['rejected_na'] += 1
                        batch_na += 1
                
                completed += 1
                
                # Display every DISPLAY_INTERVAL cards
                if completed == 1 or completed % DISPLAY_INTERVAL == 0:
                    progress = (completed / len(remaining)) * 100
                    elapsed = (datetime.now() - start_time).total_seconds()
                    rate = completed / elapsed * 3600 if elapsed > 0 else 0
                    eta_seconds = (len(remaining) - completed) / completed * elapsed if completed > 0 else 999999
                    eta_hours = int(eta_seconds // 3600)
                    eta_minutes = int((eta_seconds % 3600) // 60)
                    
                    eta_display = "Calculating..." if completed < 100 else f"{eta_hours}h {eta_minutes}m"
                    
                    # Build status string (hide zeros)
                    status_parts = []
                    if batch_success > 0:
                        status_parts.append(f"Success: {batch_success}")
                    if batch_failed > 0:
                        status_parts.append(f"Failed: {batch_failed}")
                    if batch_na > 0:
                        status_parts.append(f"N/A: {batch_na}")
                    
                    status_text = " | ".join(status_parts) if status_parts else "Success: 0"
                    
                    print(f"[{completed:5}/{len(remaining):5}] {status_text:40} | {progress:5.1f}% | "
                          f"{rate:4.0f}/h | ETA: {eta_display}")
                    
                    # Reset batch counters
                    batch_success = 0
                    batch_failed = 0
                    batch_na = 0
                
                # Incremental save
                if completed % SAVE_INTERVAL == 0:
                    checkpoint = {'last_processed_index': idx, 'phase1_complete': False}
                    save_data(successful_cards, rejections, checkpoint)
                
            except Exception as e:
                print(f"✗ Worker error: {e}")
                continue
    
    # Final save
    checkpoint = {'last_processed_index': len(cards), 'phase1_complete': True}
    save_data(successful_cards, rejections, checkpoint)
    
    duration = datetime.now() - start_time
    
    print(f"\n{'='*70}")
    print(" PHASE 1 COMPLETE")
    print(f"{'='*70}")
    print(f"Processed: {completed}")
    print(f"Successful: {stats['success']}")
    print(f"Rejected (unreachable): {stats['rejected_unreachable']}")
    print(f"Rejected (missing data): {stats['rejected_missing_data']}")
    print(f"Rejected (N/A prices): {stats['rejected_na']}")
    print(f"Rejected (input data): {stats['rejected_input']}")
    print(f"Duration: {duration}")
    print(f"Speed: {completed / (duration.total_seconds() / 3600):.0f} cards/hour")
    
    return successful_cards, rejections, stats


def phase2_recovery(rejections, successful_cards):
    """PHASE 2: Careful recovery (only for 'unreachable')"""
    
    recoverable = [r for r in rejections if 'unreachable' in r.get('rejection_reason', '')]
    
    if not recoverable:
        print("\n✓ No rejections to recover - skipping Phase 2")
        return successful_cards, rejections
    
    print("\n" + "="*70)
    print(" PHASE 2: CAREFUL RECOVERY")
    print("="*70)
    print(f"Recoverable: {len(recoverable)}")
    print()
    
    rate_limiter = RateLimiter(PHASE2_REQUESTS_PER_SECOND)
    
    recovered = 0
    still_rejected = []
    
    for idx, rejection in enumerate(recoverable):
        card = {
            'card_id': rejection['card_id'],
            'card_name': rejection['card_name'],
            'card_url': rejection['card_url'],
            'expansion_id': rejection['expansion_id'],
            'expansion_name': rejection['expansion_name'],
            'expansion_code': rejection['expansion_code'],
            'card_number': '',
            'card_rarity': ''
        }
        
        result = process_card_worker(0, card, idx, None, rate_limiter, 
                                     PHASE2_MAX_RETRIES, PHASE2_RETRY_DELAYS, True)
        
        if result['status'] == 'success':
            successful_cards.append(result['data'])
            recovered += 1
            print(f"[{idx + 1:4}/{len(recoverable):4}] Card: {card['card_id']:6} | ✓ Recovered")
        else:
            rejection['rejection_reason'] = result['rejection']['rejection_reason']
            rejection['error_detail'] = result['rejection']['error_detail']
            rejection['attempts'] = result['rejection']['attempts']
            rejection['timestamp'] = result['rejection']['timestamp']
            still_rejected.append(rejection)
            
            # Check if it became N/A during recovery
            if 'N/A' in result['rejection']['rejection_reason']:
                print(f"[{idx + 1:4}/{len(recoverable):4}] Card: {card['card_id']:6} | N/A (no prices)")
            else:
                print(f"[{idx + 1:4}/{len(recoverable):4}] Card: {card['card_id']:6} | ✗ Rejected")
        
        if (idx + 1) % 10 == 0:
            non_recoverable = [r for r in rejections if 'unreachable' not in r.get('rejection_reason', '')]
            all_rejections = non_recoverable + still_rejected
            save_data(successful_cards, all_rejections, None)
    
    non_recoverable = [r for r in rejections if 'unreachable' not in r.get('rejection_reason', '')]
    final_rejections = non_recoverable + still_rejected
    save_data(successful_cards, final_rejections, None)
    
    print(f"\n{'='*70}")
    print(f"Recovered: {recovered}/{len(recoverable)}")
    
    return successful_cards, final_rejections


def main():
    """Main execution"""
    print("="*70)
    print(" CARDMARKET CARD DETAILS SCRAPER v1.4.2")
    print("="*70)
    print()
    
    overall_start = datetime.now()
    
    if not os.path.exists(INPUT_FILE):
        print(f"✗ Error: Input file not found")
        return
    
    print("Loading input file...")
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            cards = json.load(f)
    except:
        print(f"✗ Error loading file")
        return
    
    if not cards:
        print("⚠ Empty file")
        return
    
    print(f"✓ Loaded {len(cards)} cards\n")
    
    print("Checking duplicates...")
    card_ids = [c.get('card_id') for c in cards if 'card_id' in c]
    duplicate_ids = [cid for cid in set(card_ids) if card_ids.count(cid) > 1]
    
    if duplicate_ids:
        print(f"✗ ERROR: Duplicates found!")
        print(f"  IDs: {', '.join(map(str, duplicate_ids[:20]))}")
        return
    
    print(f"✓ No duplicates\n")
    
    checkpoint = {'last_processed_index': -1, 'phase1_complete': False}
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
            start_idx = checkpoint.get('last_processed_index', -1) + 1
            if start_idx > 0:
                print(f"✓ Resuming from card #{start_idx + 1}\n")
        except:
            start_idx = 0
    else:
        start_idx = 0
    
    if not checkpoint.get('phase1_complete', False):
        successful_cards, rejections, stats = phase1_fast_run(cards, start_idx)
    else:
        print("✓ Phase 1 complete, loading...")
        successful_cards, rejections, _ = load_existing_data()
    
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    
    if rejections:
        successful_cards, rejections = phase2_recovery(rejections, successful_cards)
    
    overall_duration = datetime.now() - overall_start
    
    print("\n" + "="*70)
    print(" FINAL SUMMARY")
    print("="*70)
    print(f"Total: {len(cards):,}")
    print(f"Successful: {len(successful_cards):,}")
    print(f"Rejected: {len(rejections):,}")
    
    unreachable = len([r for r in rejections if 'unreachable' in r.get('rejection_reason', '')])
    missing_data = len([r for r in rejections if 'missing data' in r.get('rejection_reason', '')])
    na_prices = len([r for r in rejections if 'N/A' in r.get('rejection_reason', '')])
    missing_input = len([r for r in rejections if 'missing input' in r.get('rejection_reason', '')])
    
    if rejections:
        print(f"  - Site unreachable: {unreachable}")
        print(f"  - Missing data: {missing_data}")
        print(f"  - N/A prices: {na_prices}")
        print(f"  - Missing input: {missing_input}")
    
    print(f"\nDuration: {overall_duration}")
    print(f"Speed: {len(cards) / (overall_duration.total_seconds() / 3600):.0f} cards/hour")
    print("="*70)
    print("\n✓ Complete!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted - progress saved")
    except Exception as e:
        print(f"\n✗ Error: {e}")
