"""Clean the raw Airbnb and RentCast data into two tables with the same columns.

Run this any time the raw data changes:
    .venv/bin/python clean_data.py                       # uses data/listings.csv
    .venv/bin/python clean_data.py path/to/listings.csv  # or a different Airbnb file

Rentals come from the newest dated folder in data/rentcast/ (fetch_rentals.py
makes one per download). Raw files are never changed. The clean tables are written to data/clean/:
    airbnb.csv   - active whole-home Airbnb listings
    rentals.csv  - long-term rental listings

Both tables have the same columns (see CLEAN_COLUMNS), so later steps can
treat them the same way. The script prints how many rows it dropped and why,
so with a new download you can see right away if something looks off.
"""
import glob
import json
import os
import sys

import pandas as pd

AIRBNB_FILE = "data/listings.csv"
RENTCAST_DIR = "data/rentcast"   # holds one dated folder per download
OUT_DIR = "data/clean"

CLEAN_COLUMNS = [
    "source",          # "airbnb" or "rental"
    "id",
    "latitude",
    "longitude",
    "bedrooms",        # 0 = studio
    "bathrooms",
    "property_type",   # one of PROPERTY_TYPES
    "monthly_income",  # dollars per month, before any costs
    "data_date",       # when the listing was seen
]

# Both datasets get sorted into RentCast's categories.
PROPERTY_TYPES = ["Apartment", "Condo", "Townhouse", "Single Family", "Multi-Family"]

# Airbnb's property types, mapped to the categories above.
# Types not listed here (hotel rooms, "Religious building", ...) are dropped.
AIRBNB_TYPE_MAP = {
    "Entire rental unit": "Apartment",
    "Entire serviced apartment": "Apartment",
    "Entire guest suite": "Apartment",   # usually a basement or in-law unit
    "Entire loft": "Apartment",
    "Entire condo": "Condo",
    "Entire townhouse": "Townhouse",
    "Entire home": "Single Family",
    "Entire guesthouse": "Single Family",
    "Entire vacation home": "Single Family",
    "Entire bungalow": "Single Family",
    "Entire cottage": "Single Family",
    "Entire villa": "Single Family",
    "Tiny home": "Single Family",
}

# A listing counts as an active Airbnb if it was booked at least this many nights last year.
MIN_NIGHTS_BOOKED = 30

# The app only estimates properties in this bedroom range; there are too few
# larger ones to compare against.
MAX_BEDROOMS = 6

# Drop the most extreme incomes: the bottom and top 1% of each dataset.
# These are mostly data errors or one-of-a-kind properties (like a $25k/month mansion).
TRIM_PERCENT = 1


class Report:
    """Keeps track of how many rows each cleaning step removes."""

    def __init__(self, name, df):
        self.name = name
        self.lines = [f"  {len(df):>6,}  rows read"]

    def step(self, reason, before, after):
        dropped = len(before) - len(after)
        if dropped:
            self.lines.append(f"  {-dropped:>6,}  {reason}")
        return after

    def show(self, df):
        print(self.name)
        print("\n".join(self.lines))
        print(f"  {len(df):>6,}  rows kept\n")


def require_columns(df, columns, file_name):
    """Stop with a clear message if a new download is missing a column we need."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SystemExit(f"{file_name} is missing columns: {', '.join(missing)}")


def parse_bathrooms(text):
    """Turn Airbnb's bathroom text into a number: '2.5 baths' -> 2.5, 'Half-bath' -> 0.5."""
    if pd.isna(text):
        return None
    text = str(text).lower()
    if "half-bath" in text:
        return 0.5
    number = text.split()[0]
    try:
        return float(number)
    except ValueError:
        return None


def trim_extremes(df, column):
    low, high = df[column].quantile([TRIM_PERCENT / 100, 1 - TRIM_PERCENT / 100])
    return df[df[column].between(low, high)]


def shared_cleaning(df, report):
    """Rules that apply the same way to both datasets."""
    df = report.step("missing location, bedrooms or bathrooms",
                     df, df.dropna(subset=["latitude", "longitude", "bedrooms", "bathrooms"]))
    df = report.step(f"more than {MAX_BEDROOMS} bedrooms",
                     df, df[df["bedrooms"] <= MAX_BEDROOMS])
    df = report.step("missing or zero income",
                     df, df[df["monthly_income"] > 0])
    df = report.step(f"income in the top or bottom {TRIM_PERCENT}%",
                     df, trim_extremes(df, "monthly_income"))
    df = df.drop_duplicates(subset="id")
    return df[CLEAN_COLUMNS].reset_index(drop=True)


def clean_airbnb(path):
    raw = pd.read_csv(path, low_memory=False)  # also reads .csv.gz files
    require_columns(raw, ["id", "room_type", "property_type", "latitude", "longitude",
                          "bedrooms", "bathrooms_text", "estimated_revenue_l365d",
                          "estimated_occupancy_l365d", "last_scraped"], path)
    report = Report(f"Airbnb ({path})", raw)

    df = report.step("not a whole home/apartment",
                     raw, raw[raw["room_type"] == "Entire home/apt"])
    df = report.step(f"booked fewer than {MIN_NIGHTS_BOOKED} nights last year",
                     df, df[df["estimated_occupancy_l365d"] >= MIN_NIGHTS_BOOKED])

    df = df.assign(
        source="airbnb",
        property_type=df["property_type"].map(AIRBNB_TYPE_MAP),
        # Some exports fill in a numeric bathrooms column; otherwise parse the text.
        bathrooms=df["bathrooms"].fillna(df["bathrooms_text"].map(parse_bathrooms))
                  if "bathrooms" in df else df["bathrooms_text"].map(parse_bathrooms),
        monthly_income=(df["estimated_revenue_l365d"] / 12).round(),
        data_date=df["last_scraped"],
    )
    df = report.step("property type isn't a house or apartment (hotel room, etc.)",
                     df, df.dropna(subset=["property_type"]))

    df = shared_cleaning(df, report)
    report.show(df)
    return df


def latest_rentcast_folder(base):
    """The newest dated download folder, e.g. data/rentcast/2026-11-10."""
    folders = sorted(f for f in glob.glob(os.path.join(base, "*-*-*")) if os.path.isdir(f))
    if not folders:
        raise SystemExit(f"No RentCast downloads found in {base}. Run fetch_rentals.py first.")
    return folders[-1]  # dates in YYYY-MM-DD form sort in time order


def clean_rentals(folder):
    files = sorted(glob.glob(os.path.join(folder, "rentals_page_*.json")))
    if not files:
        raise SystemExit(f"No RentCast files in {folder}. Run fetch_rentals.py first.")
    raw = pd.DataFrame([row for f in files for row in json.load(open(f))])
    require_columns(raw, ["id", "propertyType", "latitude", "longitude",
                          "bedrooms", "bathrooms", "price", "lastSeenDate"], folder)
    report = Report(f"Rentals ({folder}, {len(files)} files)", raw)

    df = raw.assign(
        source="rental",
        property_type=raw["propertyType"],
        monthly_income=raw["price"],
        data_date=raw["lastSeenDate"].str[:10],  # keep just the date part
    )
    df = report.step("property type isn't a house or apartment",
                     df, df[df["property_type"].isin(PROPERTY_TYPES)])

    df = shared_cleaning(df, report)
    report.show(df)
    return df


def summarize(df):
    """Median monthly income by bedroom count, to sanity-check the result."""
    return df.groupby("bedrooms")["monthly_income"].agg(["count", "median"]).round(0)


def main():
    airbnb_path = sys.argv[1] if len(sys.argv) > 1 else AIRBNB_FILE
    airbnb = clean_airbnb(airbnb_path)
    rentals = clean_rentals(latest_rentcast_folder(RENTCAST_DIR))

    os.makedirs(OUT_DIR, exist_ok=True)
    airbnb.to_csv(os.path.join(OUT_DIR, "airbnb.csv"), index=False)
    rentals.to_csv(os.path.join(OUT_DIR, "rentals.csv"), index=False)
    print(f"Saved {OUT_DIR}/airbnb.csv and {OUT_DIR}/rentals.csv\n")

    print("Median monthly income by bedrooms:")
    side_by_side = summarize(airbnb).add_suffix("_airbnb").join(summarize(rentals).add_suffix("_rental"))
    print(side_by_side.to_string())


if __name__ == "__main__":
    main()
