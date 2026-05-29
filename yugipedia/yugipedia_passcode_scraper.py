import requests
import json
import time

# User-Agent following Wikimedia Foundation Policy
USER_AGENT = 'YugipediaCardBot/1.0 (https://github.com/egera24; egera24@gmail.com) requests/2.31.0'

def get_cards_in_password_range(session, api_url, password_start, password_end):
    """
    Fetches cards within a specific password range
    Returns list of card dictionaries
    """
    cards = []
    offset = 0
    limit = 500
    max_offset = 5000  # Stay under the API limit

    print(f"\n  Querying password range: {password_start:08d} - {password_end:08d}")

    while offset < max_offset:
        # Query with password range filter
        params = {
            'action': 'ask',
            'format': 'json',
            'query': f'[[Concept:CG cards]][[Password::≥{password_start}]][[Password::≤{password_end}]]|?English name|?Card type|?Password|limit={limit}|offset={offset}|sort=Password|order=asc'
        }

        try:
            response = session.get(api_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if 'query' not in data or 'results' not in data['query']:
                break

            results = data['query']['results']
            if not results:
                break

            cards_in_batch = 0
            for page_name, page_data in results.items():
                try:
                    printouts = page_data.get('printouts', {})

                    english_names = printouts.get('English name', [])
                    card_name = english_names[0] if english_names else page_name

                    card_types = printouts.get('Card type', [])
                    if card_types:
                        if isinstance(card_types[0], dict):
                            card_type = card_types[0].get('fulltext', '')
                        else:
                            card_type = str(card_types[0])
                    else:
                        card_type = ''

                    passwords = printouts.get('Password', [])
                    password = str(passwords[0]) if passwords else ''

                    if password:
                        password = password.zfill(8)
                    else:
                        continue

                    card_url = page_data.get('fullurl', '')
                    if not card_url:
                        card_name_encoded = page_name.replace(' ', '_')
                        card_url = f"https://yugipedia.com/wiki/{card_name_encoded}"

                    card_data = {
                        "name": card_name,
                        "card_type": card_type,
                        "password": password,
                        "url": card_url
                    }

                    cards.append(card_data)
                    cards_in_batch += 1

                except Exception as e:
                    continue

            print(f"    Offset {offset}: Found {cards_in_batch} cards")

            if cards_in_batch < limit:
                # Got fewer cards than limit, reached end of this range
                break

            offset += limit
            time.sleep(1)  # Short delay between batches within same range

        except Exception as e:
            print(f"    Error at offset {offset}: {e}")
            break

    return cards

def get_all_cards_from_yugipedia():
    """
    Fetches all Yu-Gi-Oh! cards by querying in password ranges
    Returns a list of card dictionaries
    """

    print("="*70)
    print(" Yugipedia Card Fetcher")
    print(" Using Password Range Queries to Bypass Pagination Limits")
    print("="*70)
    print()
    print(f"User-Agent: {USER_AGENT}")
    print()

    api_url = "https://yugipedia.com/api.php"

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    session = requests.Session()
    session.headers.update(headers)

    print("Strategy: Query cards in password ranges of 10,000,000")
    print("This bypasses the API's pagination limit\n")

    # Define password ranges (each range is 10 million passwords)
    # Yu-Gi-Oh passwords go from 00000000 to 99999999
    password_ranges = [
        (0, 9999999),
        (10000000, 19999999),
        (20000000, 29999999),
        (30000000, 39999999),
        (40000000, 49999999),
        (50000000, 59999999),
        (60000000, 69999999),
        (70000000, 79999999),
        (80000000, 89999999),
        (90000000, 99999999)
    ]

    all_cards = []
    seen_passwords = set()

    try:
        for range_num, (start, end) in enumerate(password_ranges, 1):
            print(f"\nRange {range_num}/10: {start:08d} - {end:08d}")

            range_cards = get_cards_in_password_range(session, api_url, start, end)

            # Add cards, filtering duplicates
            new_cards = 0
            for card in range_cards:
                if card['password'] not in seen_passwords:
                    all_cards.append(card)
                    seen_passwords.add(card['password'])
                    new_cards += 1

            print(f"  ✓ Added {new_cards} unique cards from this range")
            print(f"  ✓ Total unique cards so far: {len(all_cards)}")

            # Longer delay between password ranges
            if range_num < len(password_ranges):
                print("  ⏳ Waiting 5 seconds before next range...")
                time.sleep(5)

    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

    print()
    print("="*70)
    print(f"Fetching complete! Total unique cards collected: {len(all_cards)}")
    print("="*70)

    return all_cards

def save_to_json(cards, filename="yugipedia_passcode_list.json"):
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
    print(" YUGIPEDIA CARD SCRAPER - PASSWORD RANGE METHOD")
    print(" Wikimedia Foundation Policy Compliant")
    print("="*70)
    print()
    print("This script uses:")
    print("  • Password range queries (10 ranges of 10M passwords each)")
    print("  • Bypasses pagination limit by splitting the query")
    print("  • Can fetch all 13,000+ cards")
    print("  • Compliant User-Agent with contact information")
    print("  • Polite delays between requests")
    print()
    print("Contact: egera24@gmail.com")
    print("GitHub: https://github.com/egera24")
    print()
    print("="*70)
    print()

    cards = get_all_cards_from_yugipedia()

    if cards:
        if save_to_json(cards):
            print()
            print("="*70)
            print(" SAMPLE OF FETCHED CARDS")
            print("="*70)

            for i, card in enumerate(cards[:10], 1):
                print(f"\n{i}. {card['name']}")
                print(f"   Type: {card['card_type']}")
                print(f"   Password: {card['password']}")
                print(f"   URL: {card['url']}")

            if len(cards) > 10:
                print(f"\n... and {len(cards) - 10} more cards")

            print()
            print("="*70)
            print(f" ✓ SUCCESS: {len(cards)} total cards saved!")
            print("="*70)
    else:
        print()
        print("="*70)
        print(" ✗ ERROR: No cards were fetched")
        print("="*70)
