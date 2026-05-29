import json
import re


def load_json(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_my_cards_key(key):
    # Extract set_code-card_number and rarity_code including parentheses, e.g. "SDWD-EN041", "(ScR)"
    m = re.match(r'^([A-Z0-9]+-[A-Z0-9]+) (\(.*\))$', key)
    if not m:
        return None, None
    set_card_num, rarity_code = m.group(1), m.group(2)
    return set_card_num, rarity_code


def try_parse_float(val):
    try:
        if val is None or val == '':
            return None
        return float(val)
    except:
        return None


def main():
    all_cards_list = load_json('all_cards.json')
    my_cards = load_json('my_cards.json')

    all_cards_modified = []
    ownership_attached_count = 0
    matched_my_cards_keys = set()

    for card_data in all_cards_list:
        if not isinstance(card_data, dict):
            # Skip if not dict just in case
            continue

        card_sets = card_data.get('card_sets', [])
        for set_entry in card_sets:
            set_code = set_entry.get('set_code')
            set_rarity_code = set_entry.get('set_rarity_code', '').strip()
            if not set_code:
                set_entry['owned'] = False
                set_entry['ownershipinfo'] = []
                continue

            # Match keys from my_cards whose prefix matches set_code-card_number and rarity matches set_rarity_code exactly (including parentheses)
            matched_keys = []
            for key in my_cards.keys():
                parsed_prefix, parsed_rarity = parse_my_cards_key(key)
                if parsed_prefix is None or parsed_rarity is None:
                    continue
                # Match exact prefix set_code-card_number and rarity code (including parentheses)
                if parsed_prefix.startswith(set_code) and parsed_rarity == set_rarity_code:
                    matched_keys.append(key)

            if matched_keys:
                combined_ownership = {
                    "summary": {
                        "alteregoCount": len(matched_keys),
                        "totalQuantity": 0,
                        "averagePriceBought": 0.0,
                        "averagemarketPrice": None,
                        "lowestmarketPrice": None,
                        "trendingmarketPrice": None
                    },
                    "alteregos": []
                }
                total_qty = 0
                prices_bought = []

                for mk in matched_keys:
                    matched_my_cards_keys.add(mk)
                    alt = my_cards[mk]

                    # Calculate quantities and prices from alt
                    quantity_sum = sum(int(c.get("Quantity", 0)) for c in alt.get("collection", []))
                    total_qty += quantity_sum

                    price_boughts = []
                    for mp in alt.get("marketPrices", []):
                        try:
                            price_bought = float(mp.get("Price Bought", '0'))
                            price_boughts.append(price_bought)
                        except:
                            pass
                    avg_price_bought = round(sum(price_boughts) / len(price_boughts), 2) if price_boughts else 0.0
                    prices_bought.append(avg_price_bought)

                    # averagemarketPrice, lowestmarketPrice, trendingmarketPrice from first alterego only
                    if combined_ownership["summary"]["averagemarketPrice"] is None:
                        first_mp = alt.get("marketPrices", [{}])[0] if alt.get("marketPrices") else {}
                        avgm = try_parse_float(first_mp.get("Average Price") or first_mp.get("AVG"))
                        lowm = try_parse_float(first_mp.get("Lowest Price") or first_mp.get("LOW"))
                        trendm = try_parse_float(first_mp.get("Trending Price") or first_mp.get("TREND"))
                        combined_ownership["summary"]["averagemarketPrice"] = avgm
                        combined_ownership["summary"]["lowestmarketPrice"] = lowm
                        combined_ownership["summary"]["trendingmarketPrice"] = trendm

                    alterego = {
                        "cardInformation": {
                            "cardName": alt["cardInformation"][0].get("Card Name", "") if alt.get("cardInformation") else "",
                            "condition": alt["cardInformation"][0].get("Condition", "") if alt.get("cardInformation") else "",
                            "printing": alt["cardInformation"][0].get("Printing", "") if alt.get("cardInformation") else ""
                        },
                        "marketPrice": {
                            "priceBought": avg_price_bought,
                            "dateBought": alt.get("marketPrices", [{}])[0].get("Date Bought", "") if alt.get("marketPrices") else "",
                            "averagemarketPrice": combined_ownership["summary"]["averagemarketPrice"],
                            "lowestmarketPrice": combined_ownership["summary"]["lowestmarketPrice"],
                            "trendingmarketPrice": combined_ownership["summary"]["trendingmarketPrice"]
                        },
                        "collection": {
                            "folderName": alt["collection"][0].get("Folder Name", "") if alt.get("collection") else "",
                            "quantity": quantity_sum,
                            "tradeQuantity": alt["collection"][0].get("Trade Quantity", 0) if alt.get("collection") else 0
                        }
                    }
                    combined_ownership["alteregos"].append(alterego)

                combined_ownership["summary"]["totalQuantity"] = total_qty
                combined_ownership["summary"]["alteregoCount"] = len(matched_keys)
                combined_ownership["summary"]["averagePriceBought"] = round(sum(prices_bought) / len(prices_bought), 2) if prices_bought else 0.0

                set_entry['owned'] = True
                set_entry['ownershipinfo'] = combined_ownership
                ownership_attached_count += 1
            else:
                set_entry['owned'] = False
                set_entry['ownershipinfo'] = []

        all_cards_modified.append(card_data)

    # Find entries in my_cards not matched in all_cards
    rejected = {k: v for k, v in my_cards.items() if k not in matched_my_cards_keys}

    save_json(all_cards_modified, 'all_cards_mod.json')
    save_json(rejected, 'rejected_cards.json')

    print(f"Processed {len(all_cards_modified)} cards.")
    print(f"Attached ownership info to {ownership_attached_count} sets.")
    print(f"Created 'all_cards_mod.json' and 'rejected_cards.json'.")


if __name__ == "__main__":
    main()
