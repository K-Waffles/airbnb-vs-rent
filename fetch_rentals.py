"""Download active long-term rental listings in Washington, DC from RentCast.

Each request uses one of your RentCast API calls, so this script is careful:
  - It saves every page of results as soon as it arrives, in a folder named
    for today's date (for example data/rentcast/2026-11-10/).
  - A page that's already saved today is never downloaded again, so if a run
    stops partway, running it again picks up where it left off.
    Running it on a later day starts a fresh download in a new folder.
  - It asks you before every call, and stops after MAX_CALLS calls.
  - It records every call it makes in data/rentcast/call_log.txt (one log
    for all downloads, so you can track how many calls you've used).

Before running, create a file named .env in this folder containing one line:
    RENTCAST_API_KEY=your-key-here
(.env is in .gitignore, so the key never goes into git.)
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime

API_URL = "https://api.rentcast.io/v1/listings/rental/long-term"
RENTCAST_DIR = "data/rentcast"
OUT_DIR = os.path.join(RENTCAST_DIR, date.today().isoformat())
CALL_LOG = os.path.join(RENTCAST_DIR, "call_log.txt")
PAGE_SIZE = 500   # the most RentCast allows per call
MAX_CALLS = 15    # hard cap on calls in one run of this script


def read_api_key():
    """Read RENTCAST_API_KEY from the .env file."""
    with open(".env") as f:
        for line in f:
            name, _, value = line.strip().partition("=")
            if name == "RENTCAST_API_KEY" and value.strip():
                return value.strip()
    raise SystemExit("RENTCAST_API_KEY not found in .env")


def page_path(page):
    return os.path.join(OUT_DIR, f"rentals_page_{page:03d}.json")


def fetch_page(api_key, page):
    """Make one API call. Returns (listings, total number of matches)."""
    params = {
        "city": "Washington",
        "state": "DC",
        "status": "Active",
        "limit": PAGE_SIZE,
        "offset": page * PAGE_SIZE,
        "includeTotalCount": "true",
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"X-Api-Key": api_key, "Accept": "application/json"})

    with urllib.request.urlopen(request) as response:
        listings = json.load(response)
        total = response.headers.get("X-Total-Count")

    with open(CALL_LOG, "a") as log:
        log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  page {page}  got {len(listings)} listings  total={total}\n")

    return listings, int(total) if total else None


def ask(question):
    return input(question + " [y/N] ").strip().lower() == "y"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    api_key = read_api_key()
    calls_made = 0
    total = None
    page = 0

    while True:
        # Skip pages already on disk; they cost nothing.
        if os.path.exists(page_path(page)):
            with open(page_path(page)) as f:
                saved = json.load(f)
            print(f"Page {page}: already saved ({len(saved)} listings), skipping.")
            if len(saved) < PAGE_SIZE:
                break  # a short page is the last page
            page += 1
            continue

        # Stop if we already know there are no more listings.
        if total is not None and page * PAGE_SIZE >= total:
            break

        if calls_made >= MAX_CALLS:
            print(f"Reached the cap of {MAX_CALLS} calls for this run. Stopping.")
            break

        if not ask(f"Page {page}: download listings {page * PAGE_SIZE}-{(page + 1) * PAGE_SIZE - 1}? This uses 1 API call."):
            print("Stopped. Nothing else was downloaded.")
            break

        listings, total = fetch_page(api_key, page)
        calls_made += 1
        with open(page_path(page), "w") as f:
            json.dump(listings, f)

        pages_needed = -(-total // PAGE_SIZE) if total else "?"  # round up
        print(f"  Saved {len(listings)} listings. RentCast reports {total} in total ({pages_needed} pages).")

        if len(listings) < PAGE_SIZE:
            break
        page += 1

    print(f"\nDone. API calls used this run: {calls_made}")


if __name__ == "__main__":
    main()
