import requests
import json
import time

# User-Agent following Wikimedia Foundation Policy
# Format: <client name>/<version> (<contact information>) <library/framework name>/<version>
USER_AGENT = 'YugipediaCardBot/1.0 (https://github.com/egera24; egera24@gmail.com) requests/2.31.0'

def get_all_cards_from_yugipedia():
    """
    Fetches all Yu-Gi-Oh! cards from Yugipedia using MediaWiki Semantic API
    Following Wikimedia Foundation User-Agent Policy
    Returns a list of card dictionaries with Name, Card type, Password, and URL
    """

    print("="*70)
    print(" Yugipedia Card Fetcher")
    print(" Using MediaWiki API - Wikimedia Policy Compliant")
    print("="*70)
    print()
    print(f"User-Agent: {USER_AGENT}")
    print()

    # Yugipedia MediaWiki API endpoint
    api_url = "https://yugipedia.com/api.php"

    all_cards = []
    seen_passwords = set()

    # Set up headers following Wikimedia policy
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    # Create a session for connection reuse and better performance
    session = requests.Session()
    session.headers.update(headers)

    print("Querying Yugipedia for cards with passwords...")
    print("Using Semantic MediaWiki Ask API")
    print()

    # Parameters for pagination
    offset = 0
    limit = 500
    max_offset = 5020  # Based on your testing, pagination loops after this

    # Store first card for loop detection
    first_card_password = None
    first_card_name = None

    try:
        while offset < max_offset:
            print(f"Fetching cards at offset {offset}...")

            # Semantic MediaWiki Ask API query
            # Query: All cards that are "CG cards" (Card Game cards) with a password
            params = {
                'action': 'ask',
                'format': 'json',
                'query': f'[[Concept:CG cards]][[Password::+]]|?English name|?Card type|?Password|limit={limit}|offset={offset}|sort=Password|order=asc'
            }

            # Make the request with retry logic
            retry_count = 0
            max_retries = 3
            success = False
            response = None

            while retry_count < max_retries and not success:
                try:
                    response = session.get(api_url, params=params, timeout=30)
                    response.raise_for_status()
                    success = True
                except requests.exceptions.HTTPError as e:
                    if response and response.status_code == 403:
                        print(f"  ✗ HTTP 403 Forbidden - Check User-Agent compliance")
                        print(f"  Current User-Agent: {USER_AGENT}")
                        return all_cards
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = 5 * retry_count
                        print(f"  ⚠ Request failed, retrying in {wait_time} seconds...")
                        print(f"     (Attempt {retry_count}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        print(f"  ✗ Failed after {max_retries} attempts: {e}")
                        return all_cards
                except requests.exceptions.RequestException as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = 5 * retry_count
                        print(f"  ⚠ Network error, retrying in {wait_time} seconds...")
                        print(f"     (Attempt {retry_count}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        print(f"  ✗ Failed after {max_retries} attempts: {e}")
                        return all_cards

            if not success:
                print("  ✗ Could not fetch data")
                break

            # Parse the JSON response
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"  ✗ Error parsing JSON response: {e}")
                break

            # Extract results from the Semantic MediaWiki response
            if 'query' not in data or 'results' not in data['query']:
                print("  ✗ No results found in API response")
                if 'error' in data:
                    print(f"  API Error: {data['error']}")
                break

            results = data['query']['results']

            if not results:
                print("  ℹ No more results found")
                break

            cards_in_page = 0

            for page_name, page_data in results.items():
                try:
                    # Extract printouts (the requested properties)
                    printouts = page_data.get('printouts', {})

                    # Get English name
                    english_names = printouts.get('English name', [])
                    card_name = english_names[0] if english_names else page_name

                    # Get Card type
                    card_types = printouts.get('Card type', [])
                    if card_types:
                        # Card type might be a dict or string
                        if isinstance(card_types[0], dict):
                            card_type = card_types[0].get('fulltext', '')
                        else:
                            card_type = str(card_types[0])
                    else:
                        card_type = ''

                    # Get Password
                    passwords = printouts.get('Password', [])
                    password = str(passwords[0]) if passwords else ''

                    # Ensure password is 8 digits with leading zeros
                    if password:
                        password = password.zfill(8)
                    else:
                        continue  # Skip cards without passwords

                    # Check for duplicates
                    if password in seen_passwords:
                        continue

                    seen_passwords.add(password)

                    # Get the full URL
                    card_url = page_data.get('fullurl', '')
                    if not card_url:
                        # Construct URL from page name
                        card_name_encoded = page_name.replace(' ', '_')
                        card_url = f"https://yugipedia.com/wiki/{card_name_encoded}"

                    # Store first card for loop detection
                    if offset == 0 and len(all_cards) == 0:
                        first_card_password = password
                        first_card_name = card_name
                        print(f"  ℹ First card detected: {card_name} (Password: {password})")
                        print(f"  ℹ Will stop if this card appears again at later offset")
                        print()

                    # Check if we've looped back to the beginning
                    if offset > 0 and cards_in_page == 0:
                        if password == first_card_password and card_name == first_card_name:
                            print()
                            print("="*70)
                            print("*** LOOP DETECTED ***")
                            print(f"Found first card '{card_name}' (Password: {password})")
                            print(f"at offset {offset}. All available data has been fetched.")
                            print("="*70)
                            return all_cards

                    # Create card dictionary
                    card_data = {
                        "name": card_name,
                        "card_type": card_type,
                        "password": password,
                        "url": card_url
                    }

                    all_cards.append(card_data)
                    cards_in_page += 1

                except Exception as e:
                    print(f"  ⚠ Error processing card '{page_name}': {e}")
                    continue

            print(f"  ✓ Found {cards_in_page} cards. Total so far: {len(all_cards)}")

            # If no cards found on this page, we've reached the end
            if cards_in_page == 0:
                print("  ℹ No new cards found on this page. Stopping.")
                break

            # Increment offset for next page
            offset += limit

            # Be polite: wait between requests (Wikimedia recommends at least 2 seconds)
            print("  ⏳ Waiting 3 seconds before next request (respecting API rate limits)...")
            time.sleep(3)

    except KeyboardInterrupt:
        print()
        print("="*70)
        print("⚠ Interrupted by user")
        print("="*70)
    except Exception as e:
        print()
        print("="*70)
        print(f"✗ Unexpected error: {e}")
        print("="*70)
        import traceback
        traceback.print_exc()

    print()
    print("="*70)
    print(f"Fetching complete! Total cards collected: {len(all_cards)}")
    print("="*70)

    return all_cards

def save_to_json(cards, filename="yugipedia_cards.json"):
    """
    Saves the card list to a JSON file
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Data saved to {filename}")
        return True
    except Exception as e:
        print(f"\n✗ Error saving file: {e}")
        return False

if __name__ == "__main__":
    print()
    print("="*70)
    print(" YUGIPEDIA CARD SCRAPER")
    print(" Wikimedia Foundation Policy Compliant")
    print("="*70)
    print()
    print("This script uses:")
    print("  • MediaWiki Semantic API (proper API, not HTML scraping)")
    print("  • Compliant User-Agent with contact information")
    print("  • Polite 3-second delays between requests")
    print("  • Retry logic for failed requests")
    print()
    print("Contact: egera24@gmail.com")
    print("GitHub: https://github.com/egera24")
    print()
    print("="*70)
    print()

    # Fetch all cards from Yugipedia
    cards = get_all_cards_from_yugipedia()

    if cards:
        # Save to JSON
        if save_to_json(cards):
            print()
            print("="*70)
            print(" SAMPLE OF FETCHED CARDS")
            print("="*70)

            # Show first 10 cards
            for i, card in enumerate(cards[:10], 1):
                print(f"\n{i}. {card['name']}")
                print(f"   Type: {card['card_type']}")
                print(f"   Password: {card['password']}")
                print(f"   URL: {card['url']}")

            if len(cards) > 10:
                print(f"\n... and {len(cards) - 10} more cards")

            print()
            print("="*70)
            print(f" ✓ SUCCESS: {len(cards)} total cards saved to yugipedia_cards.json")
            print("="*70)
    else:
        print()
        print("="*70)
        print(" ✗ ERROR: No cards were fetched")
        print(" Check the error messages above for details")
        print("="*70)
