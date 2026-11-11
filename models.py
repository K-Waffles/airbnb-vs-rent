"""The two ways we estimate a property's monthly income.

1. Baseline: the median income of nearby listings with the same bedroom count.
2. Local regression: fit a multiple linear regression on the nearest listings,
   then plug in the property's details.

Both work the same way on the Airbnb table and on the rentals table, and can
estimate any column ("target"): monthly income, or an Airbnb's nightly price.
estimate.py uses them for one property; evaluate.py tests how accurate they are.
"""
import numpy as np

# --- Baseline settings ---
# Start with a small search circle and widen it until we have enough comps.
RADII_MILES = [0.5, 1, 1.5, 2, 3]
MIN_COMPS = 10

# --- Regression settings ---
# How many nearby listings (of any size) to fit the regression on.
REGRESSION_NEIGHBORS = 100
# Property types counted as a "house"; everything else is an apartment/condo.
HOUSE_TYPES = {"Single Family", "Townhouse", "Multi-Family"}
FEATURES = ["base", "per bedroom", "house vs. apartment"]


def distance_miles(lat1, lon1, lat2, lon2):
    """Straight-line distance between points on the Earth (the haversine formula)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))  # 3958.8 = Earth's radius in miles


def with_distance(df, lat, lon):
    return df.assign(miles=distance_miles(lat, lon, df["latitude"], df["longitude"]))


# ---------- 1. Baseline ----------

def find_comps(df, lat, lon, bedrooms):
    """Listings with the same bedroom count, in the smallest circle that has enough of them.

    Returns (comps sorted by distance, radius used in miles).
    """
    same_beds = with_distance(df[df["bedrooms"] == bedrooms], lat, lon)
    for radius in RADII_MILES:
        comps = same_beds[same_beds["miles"] <= radius]
        if len(comps) >= MIN_COMPS:
            break
    # If even the largest circle is short of MIN_COMPS, we use what it has.
    return comps.sort_values("miles"), radius


def baseline_predict(df, lat, lon, bedrooms, target="monthly_income"):
    comps, _ = find_comps(df, lat, lon, bedrooms)
    return comps[target].median() if len(comps) else np.nan


def median_range(values, confidence=80, resamples=1000, seed=0):
    """How sure we are about the median of these values (a bootstrap interval).

    We resample the values many times (with replacement), take the median of
    each resample, and keep the middle `confidence`% of those medians. This is
    a range for the *typical* comparable listing, not for any single property.
    """
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    medians = np.median(rng.choice(values, (resamples, len(values))), axis=1)
    tail = (100 - confidence) / 2
    return np.percentile(medians, [tail, 100 - tail])


def booking_levels(nights, cap=None):
    """Low / typical / strong nights booked per year: the 25th, 50th, 75th percentiles."""
    levels = np.percentile(nights, [25, 50, 75])
    return np.minimum(levels, cap) if cap else levels


# ---------- 2. Local regression ----------

def feature_matrix(bedrooms, is_house):
    """One row per listing: [1, bedrooms, 1 if house else 0].

    The leading 1 lets the regression learn a base amount (the intercept).
    """
    bedrooms = np.atleast_1d(bedrooms).astype(float)
    return np.column_stack([
        np.ones(len(bedrooms)),
        bedrooms,
        np.atleast_1d(is_house).astype(float),
    ])


def fit_local_regression(df, lat, lon, target="monthly_income"):
    """Fit income = base + a*bedrooms + b*house on the nearest listings.

    Bathrooms used to be included. They helped this regression a little (rent: 14% vs. 17%
    typical miss without them) but not the main comps estimate, so the app no longer asks.

    Returns (coefficients, the listings it was fit on).
    """
    local = with_distance(df, lat, lon).nsmallest(REGRESSION_NEIGHBORS, "miles")
    X = feature_matrix(local["bedrooms"], local["property_type"].isin(HOUSE_TYPES))
    # Least squares: the coefficients that make predictions closest to actual income.
    coefficients, *_ = np.linalg.lstsq(X, local[target].to_numpy(dtype=float), rcond=None)
    return coefficients, local


def regression_predict(df, lat, lon, bedrooms, property_type, target="monthly_income"):
    coefficients, local = fit_local_regression(df, lat, lon, target)
    x = feature_matrix(bedrooms, property_type in HOUSE_TYPES)
    prediction = (x @ coefficients)[0]
    return max(prediction, 0), coefficients, local  # income can't be negative


# Property types a user can enter. Multi-Family (2-4 unit buildings) is left out:
# it's rare in the data, and someone renting one unit should describe that unit.
PROPERTY_TYPES_FOR_INPUT = ["Apartment", "Condo", "Townhouse", "Single Family"]
