"""Baseline estimate: what do similar nearby properties earn?

For a property you describe, this finds Airbnbs and long-term rentals with the
same number of bedrooms near it, and reports the median monthly income of each.
This is the simple method that the regression (next step) has to beat.

Example (a 2-bedroom on Capitol Hill):
    .venv/bin/python estimate.py --lat 38.8899 --lon -76.9905 --bedrooms 2

Uses the clean tables from clean_data.py, so run that first.
"""
import argparse

import numpy as np
import pandas as pd

AIRBNB_CLEAN = "data/clean/airbnb.csv"
RENTALS_CLEAN = "data/clean/rentals.csv"

# Start with a small search circle and widen it until we have enough comps.
# Closer comps are more similar, but too few makes the median jumpy.
RADII_MILES = [0.5, 1, 1.5, 2, 3]
MIN_COMPS = 10

SHOW_COMPS = 5  # how many of the closest comps to print


def distance_miles(lat1, lon1, lat2, lon2):
    """Straight-line distance between points on the Earth (the haversine formula)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))  # 3958.8 = Earth's radius in miles


def find_comps(df, lat, lon, bedrooms):
    """Listings with the same bedroom count, in the smallest circle that has enough of them.

    Returns (comps sorted by distance, radius used in miles).
    """
    same_beds = df[df["bedrooms"] == bedrooms].copy()
    same_beds["miles"] = distance_miles(lat, lon, same_beds["latitude"], same_beds["longitude"])

    for radius in RADII_MILES:
        comps = same_beds[same_beds["miles"] <= radius]
        if len(comps) >= MIN_COMPS:
            break
    # If even the largest circle is short of MIN_COMPS, we use what it has.
    return comps.sort_values("miles"), radius


def summarize(comps, radius):
    income = comps["monthly_income"]
    return {
        "count": len(comps),
        "radius": radius,
        "median": income.median(),
        "low": income.quantile(0.25),   # middle half of comps falls
        "high": income.quantile(0.75),  # between low and high
    }


def print_side(title, comps, s):
    print(f"{title}: {s['count']} comps within {s['radius']} mi")
    if s["count"] == 0:
        print("  No comparable listings found.\n")
        return
    print(f"  Median: ${s['median']:,.0f}/month   (middle half: ${s['low']:,.0f}-${s['high']:,.0f})")
    if s["count"] < MIN_COMPS:
        print(f"  Warning: fewer than {MIN_COMPS} comps, so this estimate is shaky.")
    print(f"  Closest {min(SHOW_COMPS, s['count'])}:")
    for _, c in comps.head(SHOW_COMPS).iterrows():
        size = f"{c['bedrooms']:.0f}bd/{c['bathrooms']:g}ba"
        print(f"    {c['miles']:.2f} mi  {size:<10} {c['property_type']:<13}  ${c['monthly_income']:,.0f}/mo")
    print()


def main():
    parser = argparse.ArgumentParser(description="Compare Airbnb vs. long-term rent for a DC property.")
    parser.add_argument("--lat", type=float, required=True, help="latitude, e.g. 38.8899")
    parser.add_argument("--lon", type=float, required=True, help="longitude, e.g. -76.9905")
    parser.add_argument("--bedrooms", type=int, required=True, help="0 for a studio")
    args = parser.parse_args()

    airbnb = pd.read_csv(AIRBNB_CLEAN)
    rentals = pd.read_csv(RENTALS_CLEAN)

    print(f"\nProperty: {args.bedrooms} bedrooms at ({args.lat}, {args.lon})\n")

    airbnb_comps, airbnb_radius = find_comps(airbnb, args.lat, args.lon, args.bedrooms)
    rental_comps, rental_radius = find_comps(rentals, args.lat, args.lon, args.bedrooms)
    a = summarize(airbnb_comps, airbnb_radius)
    r = summarize(rental_comps, rental_radius)

    print_side("Airbnb", airbnb_comps, a)
    print_side("Long-term rental", rental_comps, r)

    if a["count"] and r["count"]:
        diff = a["median"] - r["median"]
        winner = "Airbnb" if diff > 0 else "Long-term rental"
        print(f"Before costs, {winner} earns about ${abs(diff):,.0f}/month more.")
        print("(Airbnb costs like cleaning, fees and furnishing aren't counted yet.)")


if __name__ == "__main__":
    main()
