"""Web page version of the app, built with Streamlit.

Run it with:
    .venv/bin/streamlit run app.py
It opens in your browser at a local address only you can see.

How Streamlit works: every time you change an input, Streamlit re-runs this
whole script from top to bottom and redraws the page. So the code reads like
a simple script: ask, then show. All the math lives in analysis.py.
"""
import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox

from analysis import (LEGAL_NOTES, SETUPS, VACATION_RENTAL_CAP, Property, airbnb_basis, analyze,
                      load_data, money, size_label)
from assumptions import defaults
from geocode import GeocodeError, coordinates, geocode, in_dc, suggest_addresses
from models import MIN_COMPS, PROPERTY_TYPES_FOR_INPUT

st.set_page_config(page_title="Airbnb vs. Rent in DC", page_icon="🏠")


# ---------- Data (loaded once, then reused) ----------

@st.cache_data
def cached_data():
    return load_data()


@st.cache_data(show_spinner="Looking up the address...")
def cached_geocode(address):
    return geocode(address)  # cached so the same address isn't sent twice


@st.cache_data(ttl="1d", show_spinner=False)
def cached_suggestions(text):
    return suggest_addresses(text)


def address_suggestions(text):
    """The dropdown under the address box: [(text shown, value returned when picked)].

    Matching addresses first, then always an option to use exactly what was
    typed, for addresses the suggestions miss and for coordinates.
    """
    text = text.strip()
    if not text:
        return []
    found = [] if coordinates(text) else cached_suggestions(text)
    return [(s["label"], s) for s in found] + [(f'Use "{text}" as typed', text)]


# ---------- Helpers for showing results ----------

def lines_table(lines):
    """Income and cost lines (skipping zeros), plus net income, as a table."""
    rows = [(label, amount) for label, amount in lines if round(amount)]
    rows.append(("Net income", sum(amount for _, amount in lines)))
    return pd.DataFrame(
        {"": [label for label, _ in rows],
         "Per month": [("-" if amount < 0 else "") + money(abs(amount)) for _, amount in rows]})


def comps_table(comps, columns):
    table = comps.head(10).copy()
    table["Distance"] = table["miles"].map(lambda m: f"{m:.2f} mi")
    table["Size"] = table.apply(lambda c: f"{c['bedrooms']:.0f} bd / {c['bathrooms']:g} ba", axis=1)
    table["Type"] = table["property_type"]
    for column, (title, fmt) in columns.items():
        table[title] = table[column].map(fmt)
    return table[["Distance", "Size", "Type"] + [title for title, _ in columns.values()]]


# ---------- The questions ----------

st.title("Airbnb vs. long-term rent in DC")
st.write("Estimate what a property in Washington, DC would earn each month as an Airbnb "
         "vs. a regular rental, after costs.")

airbnb, rentals = cached_data()

# 1. Location
# A dropdown of suggestions appears as you type. Picking a suggested address
# returns its details (a dict); picking 'Use "..." as typed' returns the text
# (a string). Nothing is looked up until something is picked.
choice = st_searchbox(
    address_suggestions,
    placeholder="Property address",
    debounce=300,          # wait for a pause in typing before looking up suggestions
    style_absolute=True,   # float the dropdown over the page instead of pushing it down
    style_overrides={"clear": {"clearable": "always"},
                     "searchbox": {"optionEmpty": "hidden"}},
    key="address",
)
if not choice:
    st.stop()  # nothing more to show until there's an address

suggested = choice if isinstance(choice, dict) else None
address = suggested["label"] if suggested else choice
coords = coordinates(address)
if coords:
    if not in_dc(coords):
        st.error("Those coordinates aren't in DC.")
        st.stop()
    lat, lon, place = coords[0], coords[1], f"({coords[0]}, {coords[1]})"
else:
    try:
        found = cached_geocode(address)
    except GeocodeError as e:
        st.error(f"{e} You can enter latitude, longitude instead.")
        st.stop()
    if found is None and suggested:
        # The Census doesn't know this suggestion; use the suggestion's own location.
        lat, lon, place = suggested["lat"], suggested["lon"], suggested["label"]
    elif found is None:
        st.error("Couldn't find that DC address. Include the house number and street, "
                 "e.g. 1600 Pennsylvania Ave NW.")
        st.stop()
    else:
        lat, lon, place = found["lat"], found["lon"], f"{found['address']} ({found['tract']})"

# 2. Setup
setup = st.radio(
    "What are you renting out?",
    options=list(SETUPS),
    format_func=lambda s: {"part": "Part of the home you live in (e.g. an English basement, "
                                   "a detached home)",
                           "whole": "The whole property"}[s],
)

# 3. Property type
prop_type = st.selectbox("Property type", PROPERTY_TYPES_FOR_INPUT)

# 4. Bedrooms
bedrooms = st.number_input("Bedrooms in the space available to guests (0 for a studio)",
                           min_value=0, max_value=6, value=1, step=1)

prop = Property(lat=lat, lon=lon, setup=setup, bedrooms=int(bedrooms), type=prop_type, place=place)
basis = airbnb_basis(airbnb, prop)

# 5. Nights (optional), worded for the setup
nights = None
if basis:
    if setup == "part":
        st.write("Since you'd live on-site, DC doesn't cap how many nights you can host. "
                 f"Similar hosted listings nearby are booked about **{basis['typical']:.0f} nights** a year.")
    else:
        st.write(f"DC caps whole-home vacation rentals at **{VACATION_RENTAL_CAP} nights** a year. "
                 f"Most book fewer: a typical one in DC is booked about **{basis['typical']:.0f} nights** a year.")
    nights = st.number_input(
        "How many nights a year do you expect guests to book? (optional)",
        min_value=1, max_value=basis["cap"] or 365, value=None, step=1,
        placeholder=f"Leave blank to use {basis['typical']:.0f}",
    )


# ---------- The results ----------

a = defaults()
result = analyze(prop, nights, a, airbnb, rentals, basis)
rent, ab, rec = result["rent"], result["airbnb"], result["recommendation"]

st.divider()
st.header("Results")

if rec["winner"] is None:
    st.warning(rec["headline"])
    st.stop()

# Headline numbers
left, right = st.columns(2)
left.metric("Airbnb, after costs", f"{money(ab['net'])}/mo",
            delta=f"{'+' if ab['net'] >= rent['net'] else '-'}{money(abs(ab['net'] - rent['net']))} vs. renting")
right.metric("Long-term rent, after costs", f"{money(rent['net'])}/mo")
(st.success if rec["winner"] == "Airbnb" else st.info)(rec["headline"])
for note in rec["notes"]:
    st.write(f"- {note}")

# Airbnb details
st.subheader("Airbnb")
low, high = basis["price_range"]
st.write(f"Nightly price: **{money(basis['price'])}** (80% sure the typical comp is "
         f"{money(low)}-{money(high)}), from {len(basis['comps'])} {size_label(prop.bedrooms)} "
         f"Airbnbs within {basis['radius']} mi. Nights booked come from {basis['source']}.")
levels = pd.DataFrame([{
    "Booking level": row["level"] + ("  ← used above" if row["chosen"] else ""),
    "Nights / year": f"{row['nights']:.0f}",
    "Gross / month": money(row["gross"]),
    "Net / month": money(row["net"]),
} for row in ab["rows"]])
st.dataframe(levels, hide_index=True, width="stretch")
with st.expander(f"Costs at {ab['chosen_nights']:.0f} nights a year"):
    st.dataframe(lines_table(ab["lines"]), hide_index=True, width="stretch")

# Rental details
st.subheader("Long-term rental")
low, high = rent["typical_range"]
st.write(f"Typical rent: **{money(rent['estimate'])}/month** (80% sure the typical comp is "
         f"{money(low)}-{money(high)}), from {len(rent['comps'])} {size_label(prop.bedrooms)} "
         f"rentals within {rent['radius']} mi.")
st.write(f"Individual rentals vary more: the middle half rent for "
         f"{money(rent['middle_half'][0])}-{money(rent['middle_half'][1])}.")
check_note = "agrees" if rent["check_agrees"] else "disagrees, so treat this estimate with caution"
st.caption(f"Cross-check (regression using property type too): {money(rent['check'])} "
           f"({rent['check_gap']:+.0f}%, {check_note})")
if rent["few_comps"]:
    st.warning(f"Fewer than {MIN_COMPS} comparable rentals, so this estimate is shaky.")
with st.expander("Costs"):
    st.dataframe(lines_table(rent["lines"]), hide_index=True, width="stretch")

# Comparable listings: map and tables
st.subheader("Comparable listings")
points = pd.concat([
    pd.DataFrame({"lat": [lat], "lon": [lon], "color": ["#d62728"], "size": [60]}),        # the property
    basis["comps"].assign(color="#ff5a5f", size=25)[["latitude", "longitude", "color", "size"]]
        .rename(columns={"latitude": "lat", "longitude": "lon"}),                             # Airbnbs
    rent["comps"].assign(color="#1f77b4", size=25)[["latitude", "longitude", "color", "size"]]
        .rename(columns={"latitude": "lat", "longitude": "lon"}),                             # rentals
])
st.map(points, latitude="lat", longitude="lon", color="color", size="size")
st.caption("Dark red: the property. Pink: comparable Airbnbs. Blue: comparable rentals.")
with st.expander("Closest comparable Airbnbs"):
    st.dataframe(comps_table(basis["comps"], {
        "nightly_price": ("Price / night", money),
        "nights_booked": ("Nights booked / year", lambda v: f"{v:.0f}"),
    }), hide_index=True, width="stretch")
with st.expander("Closest comparable rentals"):
    st.dataframe(comps_table(rent["comps"], {
        "monthly_income": ("Rent / month", money),
    }), hide_index=True, width="stretch")

st.divider()
for note in LEGAL_NOTES:
    st.caption(note)
st.caption("Data: Airbnb listings from Inside Airbnb (insideairbnb.com); rental listings from RentCast; "
           "address suggestions via Photon (© OpenStreetMap contributors); addresses located with the "
           "U.S. Census Bureau geocoder. Costs are assumptions; see assumptions.py.")
