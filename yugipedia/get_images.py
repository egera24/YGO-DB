"""
DEPRECATED — Legacy offline image downloader (not used by ygo_app).

The web app stores YGOPRODeck CDN URLs in the database (see ygo_app.yugipedia.images).
Use: python -m ygo_app.jobs.import_catalog_yugipedia
"""
import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import argparse
from datetime import datetime


# Configuration
JSON_FILE = "yugipedia_passcode_list.json"
FOLDER_SMALL = "image_small"
FOLDER_BIG = "image_big"
MISSING_IMAGES_FILE = "missing_pictures.json"
cpu_cores = os.cpu_count()
MAX_WORKERS = max(8, min(16, (cpu_cores // 2) * 2)) if cpu_cores else 8

# YGOPRODeck image URL patterns (uses integer without leading zeros)
YGOPRODECK_SMALL_URL = "https://images.ygoprodeck.com/images/cards_small/{}.jpg"
YGOPRODECK_BIG_URL = "https://images.ygoprodeck.com/images/cards/{}.jpg"


def ensure_folder(folder):
    """Create folder if it doesn't exist"""
    if not os.path.exists(folder):
        os.makedirs(folder)


def password_to_int(password):
    """
    Convert password string to integer (removes leading zeros)
    Example: "06214163" -> 6214163
    """
    try:
        return int(password)
    except (ValueError, TypeError):
        return None


def download_image(url, filepath, password):
    """
    Download image from URL and save to filepath
    Returns tuple: (success, password, error_message)
    """
    if os.path.exists(filepath):
        return (True, password, None)  # Already exists, consider success

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
        return (True, password, None)
    except requests.exceptions.HTTPError as e:
        return (False, password, f"HTTP Error {e.response.status_code}")
    except requests.exceptions.Timeout:
        return (False, password, "Timeout")
    except requests.exceptions.RequestException as e:
        return (False, password, f"Request Error: {str(e)}")
    except Exception as e:
        return (False, password, f"Error: {str(e)}")


def save_missing_images(missing_data, filepath):
    """Save missing image data to JSON file"""
    try:
        output = {
            "timestamp": datetime.now().isoformat(),
            "total_missing": len(missing_data),
            "missing_images": missing_data
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"\n+++[ERROR]+++ Failed to save missing images file: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download Yu-Gi-Oh! card images from ygoprodeck.com based on yugipedia_passcode_list.json"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--small', action='store_true', help="Download only small images")
    group.add_argument('--big', action='store_true', help="Download only big images")
    group.add_argument('--both', action='store_true', help="Download both small and big images (default)")

    args = parser.parse_args()

    # Determine which images to download
    if args.small:
        download_small = True
        download_big = False
    elif args.big:
        download_small = False
        download_big = True
    else:  # Default or --both
        download_small = True
        download_big = True

    # Create folders
    if download_small:
        ensure_folder(FOLDER_SMALL)
    if download_big:
        ensure_folder(FOLDER_BIG)

    # Load card data
    print(f"\n+++[INFO]+++ Loading card data from {JSON_FILE}...")

    if not os.path.exists(JSON_FILE):
        print(f"\n+++[ERROR]+++ File {JSON_FILE} not found!")
        print(f"+++[ERROR]+++ Please ensure yugipedia_passcode_list.json exists in the current directory.")
        return

    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            cards = json.load(f)
    except json.JSONDecodeError as e:
        print(f"\n+++[ERROR]+++ Invalid JSON format: {e}")
        return
    except Exception as e:
        print(f"\n+++[ERROR]+++ Failed to load JSON file: {e}")
        return

    # Validate data structure
    if not isinstance(cards, list):
        print(f"\n+++[ERROR]+++ Expected list of cards, got {type(cards)}")
        return

    print(f"+++[INFO]+++ Total cards found: {len(cards)}")

    # Build download tasks
    downloads = []
    passwords_to_check = set()
    skipped_invalid = 0

    for card in cards:
        password = card.get("password")
        if not password:
            skipped_invalid += 1
            continue

        # Convert password to integer for URL (removes leading zeros)
        password_int = password_to_int(password)
        if password_int is None:
            skipped_invalid += 1
            continue

        passwords_to_check.add(password)

        if download_small:
            url_small = YGOPRODECK_SMALL_URL.format(password_int)
            path_small = os.path.join(FOLDER_SMALL, f"{password}.jpg")
            downloads.append(("small", url_small, path_small, password))

        if download_big:
            url_big = YGOPRODECK_BIG_URL.format(password_int)
            path_big = os.path.join(FOLDER_BIG, f"{password}.jpg")
            downloads.append(("big", url_big, path_big, password))

    print(f"+++[INFO]+++ Total unique passwords: {len(passwords_to_check)}")
    if skipped_invalid > 0:
        print(f"+++[WARNING]+++ Skipped {skipped_invalid} cards with invalid/missing passwords")
    print(f"+++[INFO]+++ Total images to download: {len(downloads)}")
    print(f"+++[INFO]+++ Using {MAX_WORKERS} concurrent workers\n")

    # Track results
    successful_downloads = {"small": set(), "big": set()}
    failed_downloads = {"small": {}, "big": {}}

    # Download images with progress bar
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_image, url, path, password): (img_type, password)
            for img_type, url, path, password in downloads
        }

        with tqdm(total=len(futures), desc="+++[INFO]+++ Downloading images", unit="images") as pbar:
            for future in as_completed(futures):
                img_type, password = futures[future]
                success, pwd, error = future.result()

                if success:
                    successful_downloads[img_type].add(password)
                else:
                    failed_downloads[img_type][password] = error

                pbar.update(1)

    # Analyze results
    print(f"\n+++[INFO]+++ Download summary:")

    if download_small:
        success_count = len(successful_downloads["small"])
        fail_count = len(failed_downloads["small"])
        print(f"+++[INFO]+++ Small images: {success_count} successful, {fail_count} failed")

    if download_big:
        success_count = len(successful_downloads["big"])
        fail_count = len(failed_downloads["big"])
        print(f"+++[INFO]+++ Big images: {success_count} successful, {fail_count} failed")

    # Find passwords with missing images
    missing_images = []

    for password in passwords_to_check:
        missing_types = []
        errors = {}

        if download_small and password not in successful_downloads["small"]:
            missing_types.append("small")
            errors["small"] = failed_downloads["small"].get(password, "Unknown error")

        if download_big and password not in successful_downloads["big"]:
            missing_types.append("big")
            errors["big"] = failed_downloads["big"].get(password, "Unknown error")

        if missing_types:
            missing_images.append({
                "password": password,
                "missing_types": missing_types,
                "errors": errors
            })

    # Save missing images report
    if missing_images:
        print(f"\n+++[WARNING]+++ Found {len(missing_images)} passwords with missing images")
        print(f"+++[INFO]+++ Saving missing images report to {MISSING_IMAGES_FILE}...")

        if save_missing_images(missing_images, MISSING_IMAGES_FILE):
            print(f"+++[INFO]+++ Missing images report saved successfully")
        else:
            print(f"+++[ERROR]+++ Failed to save missing images report")
    else:
        print(f"\n+++[SUCCESS]+++ All images downloaded successfully!")

    print(f"\n+++[INFO]+++ All downloads have been completed.\n")


if __name__ == '__main__':
    main()
