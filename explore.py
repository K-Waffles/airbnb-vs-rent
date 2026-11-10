"""Step 1: get to know the Airbnb listings data."""
import pandas as pd

df = pd.read_csv("data/listings.csv")

print("Rows, columns:", df.shape)
print()

# How many listings of each type? We only want whole homes.
print("Room types:")
print(df["room_type"].value_counts())
print()

homes = df[df["room_type"] == "Entire home/apt"]
print("Whole-home listings:", len(homes))
print()

# The columns we plan to use
cols = ["latitude", "longitude", "bedrooms", "bathrooms_text", "accommodates",
        "property_type", "price", "estimated_occupancy_l365d", "estimated_revenue_l365d"]

print("Sample rows:")
print(homes[cols].head(5).to_string())
print()

# How many values are missing in each column?
print("Missing values (whole homes):")
print(homes[cols].isna().sum())
print()

print("Estimated yearly revenue (whole homes):")
print(homes["estimated_revenue_l365d"].describe())
