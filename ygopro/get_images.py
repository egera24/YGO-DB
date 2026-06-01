"""
DEPRECATED — Legacy offline image downloader.

The web app (ygo_app) loads card art from YGOPRODeck CDN URLs stored in the
database. It does not read local JPG folders. Do not run this script for
cloud or normal app usage; it can consume ~1–4 GB of disk space.
"""
import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import argparse

# Configuration
JSON_FILE = "all_cards.json"
FOLDER_SMALL = "image_small"
FOLDER_BIG = "image_big"
cpu_cores = os.cpu_count() // 2
MAX_WORKERS = max(8, min(16, cpu_cores * 2))

def ensure_folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)

def download_image(url, filepath):
    if os.path.exists(filepath):
        return  # Skip existing files
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
    except Exception as e:
        # Handle error silently or log to a file instead of printing
        pass

def main():
    parser = argparse.ArgumentParser(description="Download images from all_cards.json")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--small', action='store_true', help="Download only small images")
    group.add_argument('--big', action='store_true', help="Download only big images")
    group.add_argument('--both', action='store_true', help="Download both small and big images (default)")

    args = parser.parse_args()

    download_small = args.small or args.both or not (args.small or args.big or args.both)
    download_big = args.big or args.both or not (args.small or args.big or args.both)

    if download_small:
        ensure_folder(FOLDER_SMALL)
    if download_big:
        ensure_folder(FOLDER_BIG)

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cards = data.get("data", [])
    print(f"\n+++[INFO]+++ Total cards found: {len(cards)}")

    downloads = []
    for card in cards:
        card_id = str(card.get("id"))
        images = card.get("card_images", [])
        if not images:
            continue
        image_info = images[0]

        if download_small:
            url_small = image_info.get("image_url_small")
            if url_small:
                path_small = os.path.join(FOLDER_SMALL, f"{card_id}.jpg")
                downloads.append((url_small, path_small))

        if download_big:
            url_big = image_info.get("image_url")
            if url_big:
                path_big = os.path.join(FOLDER_BIG, f"{card_id}.jpg")
                downloads.append((url_big, path_big))

    print(f"\n+++[INFO]+++ Total images to download: {len(downloads)}\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(download_image, url, path) for url, path in downloads]
        with tqdm(total=len(futures), desc="+++[INFO]+++ Downloading images", unit="images") as pbar:
            for _ in as_completed(futures):
                pbar.update(1)

    print("\n+++[INFO]+++ All downloads have been completed.\n")

if __name__ == '__main__':
    main()
