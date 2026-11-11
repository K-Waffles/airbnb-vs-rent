"""Test how accurate the estimates are.

For a random sample of listings whose numbers we already know, we hide each
one, estimate it from the *other* listings, and compare to the real number.
A method that's close on listings it hasn't seen should be close for a new
property too.

    .venv/bin/python evaluate.py

What it tests:
  Rentals:  monthly rent, comps (baseline) vs. regression
  Airbnb:   nightly price, comps vs. regression
            monthly income = comps' nightly price x the listing's real nights booked
              (how accurate the app is when the user's guess of nights is right)
"""
import numpy as np
import pandas as pd

from analysis import AIRBNB_CLEAN, RENTALS_CLEAN
from models import baseline_predict, regression_predict

SAMPLE_SIZE = 500
SEED = 42  # fixed, so every run tests the same listings


def print_scores(title, results):
    """results: a table with an 'actual' column plus one column per method."""
    print(title)
    print(f"  {'':<34}{'typical miss':>13}{'typical %':>11}{'within 20%':>12}")
    for method in results.columns.drop("actual"):
        miss = (results[method] - results["actual"]).abs()
        pct = miss / results["actual"] * 100
        print(f"  {method:<34}{'$' + format(miss.median(), ',.0f'):>13}"
              f"{pct.median():>10.0f}%{(pct <= 20).mean() * 100:>11.0f}%")
    print()


def predict_hidden(df, target, extra=None):
    """Hide each sampled listing and estimate `target` from the rest."""
    sample = df.sample(min(SAMPLE_SIZE, len(df)), random_state=SEED)
    rows = []
    for idx, l in sample.iterrows():
        others = df.drop(index=idx)
        row = {
            "actual": l[target],
            "comps": baseline_predict(others, l["latitude"], l["longitude"], l["bedrooms"], target),
            "regression": regression_predict(others, l["latitude"], l["longitude"], l["bedrooms"],
                                             l["property_type"], target)[0],
        }
        if extra:
            row.update(extra(others, l, row))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    print("('typical' = median across the tested listings)\n")

    rentals = pd.read_csv(RENTALS_CLEAN)
    print_scores(f"RENTALS: monthly rent ({min(SAMPLE_SIZE, len(rentals))} listings)",
                 predict_hidden(rentals, "monthly_income"))

    airbnb = pd.read_csv(AIRBNB_CLEAN)
    print_scores(f"AIRBNB: nightly price ({min(SAMPLE_SIZE, len(airbnb))} listings)",
                 predict_hidden(airbnb, "nightly_price"))

    # Monthly income the way the app computes it: estimated nightly price x nights.
    # Using the listing's real nights shows how good the estimate is when the
    # user's guess of nights is right.
    def split_estimate(others, l, row):
        return {"comps price x real nights": row["comps"] * l["nights_booked"] / 12}

    income = predict_hidden(airbnb, "nightly_price", split_estimate)
    income["actual"] = airbnb.sample(min(SAMPLE_SIZE, len(airbnb)), random_state=SEED)["monthly_income"].values
    print_scores("AIRBNB: monthly income, if the user's nights guess is right",
                 income[["actual", "comps price x real nights"]])


if __name__ == "__main__":
    main()
