"""Load the Airbnb listings and keep only active whole-home listings.

The raw file in data/ is never changed. To update the data, replace
data/listings.csv with a newer download from Inside Airbnb.
"""
import pandas as pd

DATA_FILE = "data/listings.csv"

# A listing counts as "active" if it was booked at least this many nights last year.
MIN_NIGHTS_BOOKED = 30


def load_active_homes(path=DATA_FILE):
    df = pd.read_csv(path)

    df = df[df["room_type"] == "Entire home/apt"]
    df = df[df["estimated_revenue_l365d"].notna()]
    df = df[df["estimated_occupancy_l365d"] >= MIN_NIGHTS_BOOKED]

    return df


if __name__ == "__main__":
    homes = load_active_homes()
    print("Active whole-home listings:", len(homes))
    print()
    print("Estimated yearly revenue:")
    print(homes["estimated_revenue_l365d"].describe().round(0))
