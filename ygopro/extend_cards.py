import json
import csv

# Read the CSV file and create a lookup dictionary
def read_collection_csv(filename):
    collection = {}
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Create a key combining Card Number and Rarity (with parentheses)
            card_number = row['Card Number']
            rarity = f"({row['Rarity']})"
            key = (card_number, rarity)

            # Store the row data
            collection[key] = {
                'quantity': row['Quantity'],
                'trend': row['TREND']
            }
    return collection

# Read the JSON file
def read_json(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

# Process the JSON file
def process_cards(json_data, collection):
    owned_count = 0

    for card in json_data['data']:
        if 'card_sets' in card:
            for card_set in card['card_sets']:
                set_code = card_set['set_code']
                set_rarity_code = card_set['set_rarity_code']
                key = (set_code, set_rarity_code)

                # Check if this card is in the collection
                if key in collection:
                    card_set['owned'] = 1
                    card_set['quantity'] = int(collection[key]['quantity'])
                    card_set['set_price'] = collection[key]['trend']
                    owned_count += 1
                else:
                    card_set['owned'] = 0
                    card_set['quantity'] = 0
                    # set_price remains as is

    return owned_count

# Check for cards in CSV that aren't in JSON
def find_missing_cards(collection, json_data):
    # Create a set of all (set_code, set_rarity_code) pairs in JSON
    json_cards = set()
    for card in json_data['data']:
        if 'card_sets' in card:
            for card_set in card['card_sets']:
                key = (card_set['set_code'], card_set['set_rarity_code'])
                json_cards.add(key)

    # Find cards in collection that aren't in JSON
    missing_keys = set(collection.keys()) - json_cards
    return missing_keys

# Save updated JSON
def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# Main execution
if __name__ == "__main__":
    print("Processing card collection...")

    # Read files
    collection = read_collection_csv('my_collection.csv')
    json_data = read_json('all_cards.json')

    # Process the cards
    owned_count = process_cards(json_data, collection)

    # Count total cards in JSON
    total_json_cards = sum(len(card.get('card_sets', [])) for card in json_data['data'])

    # Count cards in CSV
    csv_card_count = len(collection)

    # Find missing cards
    missing_keys = find_missing_cards(collection, json_data)

    # Save the updated JSON
    save_json('all_cards_extended.json', json_data)

    # Report statistics
    print("\n" + "="*50)
    print("PROCESSING COMPLETE")
    print("="*50)
    print(f"Total card sets in all_cards.json: {total_json_cards}")
    print(f"Total owned card sets: {owned_count}")
    print(f"Total cards in my_collection.csv: {csv_card_count}")
    print("="*50)

    # Handle missing cards
    if missing_keys:
        print(f"\n⚠️  WARNING: {len(missing_keys)} card(s) from my_collection.csv not found in all_cards.json!")
        print("Saving missing cards to rejected_cards.csv...")

        # Read the CSV again to get full row data
        with open('my_collection.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Filter rows that match missing keys
        missing_rows = []
        for row in rows:
            card_number = row['Card Number']
            rarity = f"({row['Rarity']})"
            key = (card_number, rarity)
            if key in missing_keys:
                missing_rows.append(row)

        # Save to rejected_cards.csv
        if missing_rows:
            with open('rejected_cards.csv', 'w', encoding='utf-8', newline='') as f:
                fieldnames = missing_rows[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(missing_rows)
            print(f"✓ Saved {len(missing_rows)} missing cards to rejected_cards.csv")
    else:
        print("\n✓ All cards from my_collection.csv found in all_cards.json")

    print("\n✓ Extended JSON saved as 'all_cards_extended.json'")
