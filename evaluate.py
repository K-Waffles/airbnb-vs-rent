"""Test which estimate is more accurate: the baseline or the local regression.

For a random sample of listings whose income we already know, we hide each
one, predict its income from the *other* listings, and compare the prediction
to the real number. A method that's closer on listings it hasn't seen should
be closer for a new property too.

    .venv/bin/python evaluate.py
"""
import numpy as np
import pandas as pd

from estimate import AIRBNB_CLEAN, RENTALS_CLEAN
from models import baseline_predict, regression_predict

SAMPLE_SIZE = 500
SEED = 42  # fixed, so every run tests the same listings


def test_dataset(name, df):
    sample = df.sample(min(SAMPLE_SIZE, len(df)), random_state=SEED)
    rows = []
    for idx, listing in sample.iterrows():
        others = df.drop(index=idx)  # hide the listing we're predicting
        base = baseline_predict(others, listing["latitude"], listing["longitude"], listing["bedrooms"])
        reg, _, _ = regression_predict(others, listing["latitude"], listing["longitude"],
                                       listing["bedrooms"], listing["bathrooms"], listing["property_type"])
        rows.append({"actual": listing["monthly_income"], "baseline": base, "regression": reg})
    results = pd.DataFrame(rows)

    print(f"{name}: tested on {len(results)} listings")
    print(f"  {'':<12}{'typical $ error':>16}{'typical % error':>17}{'within 20%':>12}")
    for method in ["baseline", "regression"]:
        error = (results[method] - results["actual"]).abs()
        pct = error / results["actual"] * 100
        dollars = f"${error.median():,.0f}"
        print(f"  {method:<12}{dollars:>16}{pct.median():>16.0f}%{(pct <= 20).mean() * 100:>11.0f}%")
    print()


def main():
    print("('typical' = median across the tested listings)\n")
    test_dataset("Airbnb", pd.read_csv(AIRBNB_CLEAN))
    test_dataset("Long-term rental", pd.read_csv(RENTALS_CLEAN))


if __name__ == "__main__":
    main()
