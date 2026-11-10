"""Estimate a DC property's monthly income as an Airbnb vs. a long-term rental.

Shows two estimates for each option (see models.py for how they work):
  - Baseline: median income of nearby listings with the same bedroom count.
  - Regression: a multiple linear regression fit on the nearest listings.

Example (a 2-bedroom, 1-bath apartment on Capitol Hill):
    .venv/bin/python estimate.py --lat 38.8899 --lon -76.9905 --bedrooms 2 --bathrooms 1 --type Apartment

Uses the clean tables from clean_data.py, so run that first.
"""
import argparse

import pandas as pd

from models import (FEATURES, MIN_COMPS, PROPERTY_TYPES_FOR_INPUT, find_comps,
                    regression_predict)

AIRBNB_CLEAN = "data/clean/airbnb.csv"
RENTALS_CLEAN = "data/clean/rentals.csv"

SHOW_COMPS = 5  # how many of the closest comps to print


def print_baseline(comps, radius):
    income = comps["monthly_income"]
    print(f"  Baseline:   {len(comps)} comps with the same bedrooms within {radius} mi")
    if comps.empty:
        print("              No comparable listings found.")
        return
    print(f"              Median ${income.median():,.0f}/month   "
          f"(middle half: ${income.quantile(0.25):,.0f}-${income.quantile(0.75):,.0f})")
    if len(comps) < MIN_COMPS:
        print(f"              Warning: fewer than {MIN_COMPS} comps, so this estimate is shaky.")
    print(f"              Closest {min(SHOW_COMPS, len(comps))}:")
    for _, c in comps.head(SHOW_COMPS).iterrows():
        size = f"{c['bedrooms']:.0f}bd/{c['bathrooms']:g}ba"
        print(f"                {c['miles']:.2f} mi  {size:<10} {c['property_type']:<13}  "
              f"${c['monthly_income']:,.0f}/mo")


def print_regression(prediction, coefficients, local, bedrooms):
    print(f"  Regression: fit on the {len(local)} nearest listings (within {local['miles'].max():.2f} mi)")
    print(f"              Estimate ${prediction:,.0f}/month")
    print("              What it learned for this area:")
    for name, value in zip(FEATURES, coefficients):
        print(f"                {name:<20} {value:>+8,.0f}")
    if not local["bedrooms"].min() <= bedrooms <= local["bedrooms"].max():
        print("              Warning: no nearby listings this size, so this is a guess beyond the data.")


def main():
    parser = argparse.ArgumentParser(description="Compare Airbnb vs. long-term rent for a DC property.")
    parser.add_argument("--lat", type=float, required=True, help="latitude, e.g. 38.8899")
    parser.add_argument("--lon", type=float, required=True, help="longitude, e.g. -76.9905")
    parser.add_argument("--bedrooms", type=int, required=True, help="0 for a studio")
    parser.add_argument("--bathrooms", type=float, required=True, help="e.g. 1.5")
    parser.add_argument("--type", required=True, choices=PROPERTY_TYPES_FOR_INPUT)
    args = parser.parse_args()

    print(f"\nProperty: {args.bedrooms} bd / {args.bathrooms:g} ba {args.type} "
          f"at ({args.lat}, {args.lon})")

    for title, path in [("AIRBNB", AIRBNB_CLEAN), ("LONG-TERM RENTAL", RENTALS_CLEAN)]:
        df = pd.read_csv(path)
        print(f"\n{title}")
        comps, radius = find_comps(df, args.lat, args.lon, args.bedrooms)
        print_baseline(comps, radius)
        print()
        print_regression(*regression_predict(df, args.lat, args.lon, args.bedrooms,
                                             args.bathrooms, args.type), args.bedrooms)

    print("\n(Airbnb costs like cleaning, fees and furnishing aren't counted yet.)")


if __name__ == "__main__":
    main()
