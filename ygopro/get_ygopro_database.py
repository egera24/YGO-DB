import os
import json
import requests
from datetime import datetime, timedelta
from tqdm import tqdm

CACHE_FILE = "all_cards.json"
CACHE_EXPIRATION_DAYS = 28  # 4 weeks


def is_cache_expired(filename, max_age_days):
    if not os.path.exists(filename):
        return True
    file_mod_time = os.path.getmtime(filename)
    file_date = datetime.fromtimestamp(file_mod_time)
    age = datetime.now() - file_date
    return age > timedelta(days=max_age_days)


def download_database(cache_file=CACHE_FILE):
    url = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
    print(f"\n+++[INFO]+++ Downloading YGOProDeck database from {url} ...\n")

    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024  # 1KB blocks

        with open(cache_file, 'wb') as file, tqdm(
                total=total_size, unit='iB', unit_scale=True, desc="+++[INFO]+++ Downloading DB"
        ) as bar:
            for data in response.iter_content(block_size):
                file.write(data)
                bar.update(len(data))

    print(f"\n+++[INFO]+++ Database saved to {cache_file}\n")
    print("+++[INFO]+++ Parsing JSON data, please wait...\n")
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"+++[INFO]+++ JSON loaded successfully: {len(data.get('data', []))} cards found.\n")
    return data


def load_ygoprodeck_database(cache_file=CACHE_FILE):
    print("+++[INFO]+++ Loading database from local cache...\n")
    print("+++[INFO]+++ Parsing JSON data, please wait...\n")
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"+++[INFO]+++ JSON loaded successfully: {len(data.get('data', []))} cards found.\n")
    return data


def get_database():
    if is_cache_expired(CACHE_FILE, CACHE_EXPIRATION_DAYS):
        print("\n+++[INFO]+++ Cache is missing or expired, downloading new database...")
        return download_database()
    else:
        return load_ygoprodeck_database()


if __name__ == "__main__":
    db = get_database()
    print(f"+++[INFO]+++ Loaded {len(db.get('data', []))} cards from YGOProDeck database\n")
