import os
import csv
import json

def list_csv_files():
    files = [f for f in os.listdir('.') if f.lower().endswith('.csv')]
    if not files:
        print("\n+++[ERROR]+++ No CSV files found in the current directory.")
        return []
    print("\n+++[INFO]+++ Available CSV files, please choose the correct one:")
    for i, file in enumerate(files, 1):
        print(f"{i}: {file}")
    return files

def get_user_choice(num_files):
    while True:
        choice = input(f"\n+++[REQUEST]+++ \nEnter the number of the CSV file to process (1-{num_files}): ")
        if choice.isdigit() and 1 <= int(choice) <= num_files:
            return int(choice) - 1
        print("\n+++[ERROR]+++ Invalid choice. Please enter a valid number.")

def csv_to_custom_json(rows):
    header = rows[0]
    data_rows = rows[1:]

    result = {}
    for row in data_rows:
        row_dict = dict(zip(header, row))

        key = f"{row_dict['Card Number']} ({row_dict['Rarity']})"

        if key not in result:
            result[key] = {
                "cardInformation": [],
                "marketPrices": [],
                "setInformation": [],
                "collection": []
            }

        printing_value = row_dict.get("Printing", "")
        if printing_value == "":
            printing_value = "Unlimited"

        card_info = {
            "Card Name": row_dict.get("Card Name", ""),
            "Condition": row_dict.get("Condition", ""),
            "Printing": printing_value
        }
        
        if card_info not in result[key]["cardInformation"]:
            result[key]["cardInformation"].append(card_info)

        market_price = {
            "Price Bought": row_dict.get("Price Bought", ""),
            "Date Bought": row_dict.get("Date Bought", ""),
            "Average Price": row_dict.get("AVG", ""),
            "Lowest Price": row_dict.get("LOW", ""),
            "Trending Price": row_dict.get("TREND", "")
        }
        if market_price not in result[key]["marketPrices"]:
            result[key]["marketPrices"].append(market_price)

        set_info = {
            "Set Code": row_dict.get("Set Code", ""),
            "Set Name": row_dict.get("Set Name", "")
        }
        if set_info not in result[key]["setInformation"]:
            result[key]["setInformation"].append(set_info)

        collection = {
            "Folder Name": row_dict.get("Folder Name", ""),
            "Quantity": row_dict.get("Quantity", ""),
            "Trade Quantity": row_dict.get("Trade Quantity", "")
        }
        if collection not in result[key]["collection"]:
            result[key]["collection"].append(collection)

    return result

def load_and_process_csv(filename):
    with open(filename, 'r', encoding='utf-8-sig', newline='') as infile:
        lines = infile.readlines()

    # Remove first line if exactly '"sep=,"'
    if lines and lines[0].strip() == '"sep=,"':
        print('\n+++[INFO]+++ Found \'"sep=,"\' string in the first row, removing it now...')
        lines = lines[1:]

    reader = csv.reader(lines)
    rows = list(reader)

    expected_header = [
        "Folder Name", "Quantity", "Trade Quantity", "Card Name", "Set Code",
        "Set Name", "Card Number", "Rarity", "Condition", "Printing", "Language",
        "Price Bought", "Date Bought", "AVG", "LOW", "TREND"
    ]

    if not rows or rows[0] != expected_header:
        print("\n+++[ERROR]+++ Header does not match expected DragonShield format. Please choose the correct CSV file.")
        return None

    return csv_to_custom_json(rows)

def main():
    files = list_csv_files()
    if not files:
        return

    choice = get_user_choice(len(files))
    chosen_file = files[choice]
    print(f"\n+++[INFO]+++ Selected file: {chosen_file}")

    json_data = load_and_process_csv(chosen_file)
    if json_data is None:
        return

    output_filename = "my_cards.json"
    with open(output_filename, 'w', encoding='utf-8') as jsonfile:
        json.dump(json_data, jsonfile, indent=2, ensure_ascii=False)

    print(f"\n+++[INFO]+++ The JSON file '{output_filename}' has been created successfully.")

if __name__ == "__main__":
    main()
