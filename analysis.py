"""The calculations behind the app, with no questions and no printing.

Both front ends use this file:
  - estimate.py asks questions in the terminal and prints the results.
  - app.py shows the same thing as a web page (Streamlit).

The usual flow:
    airbnb, rentals = load_data()
    prop = Property(lat=..., lon=..., setup="part", bedrooms=1, type="Apartment")
    basis = airbnb_basis(airbnb, prop)          # what we know before asking about nights
    result = analyze(prop, nights=None, a=defaults(), airbnb=airbnb, rentals=rentals, basis=basis)
"""
from dataclasses import dataclass

import pandas as pd

from costs import airbnb_break_even_nights, airbnb_lines, net, rental_lines
from models import booking_levels, find_comps, median_range, regression_predict, MIN_COMPS

AIRBNB_CLEAN = "data/clean/airbnb.csv"
RENTALS_CLEAN = "data/clean/rentals.csv"

VACATION_RENTAL_CAP = 90  # DC's yearly night cap for unhosted (whole-home) rentals
DISAGREE_PERCENT = 15      # flag the rent estimate if the two methods differ by more

SETUPS = {
    "part": "part of your home, while you live there (hosted: no night cap)",
    "whole": f"your whole home, while you're away (unhosted: max {VACATION_RENTAL_CAP} nights/year)",
}


@dataclass
class Property:
    lat: float
    lon: float
    setup: str       # "part" or "whole"
    bedrooms: int    # in the space available to guests; 0 = studio
    type: str        # one of models.PROPERTY_TYPES_FOR_INPUT
    place: str = ""  # the matched address, for display


def money(x):
    return f"${x:,.0f}"


def size_label(bedrooms):
    return "studio" if bedrooms == 0 else f"{bedrooms}-bedroom"


def load_data():
    return pd.read_csv(AIRBNB_CLEAN), pd.read_csv(RENTALS_CLEAN)


# ---------- Long-term rental ----------

def rent_analysis(rentals, prop, a):
    """Typical rent of similar nearby rentals, and the costs. None if no comps."""
    comps, radius = find_comps(rentals, prop.lat, prop.lon, prop.bedrooms)
    if comps.empty:
        return None
    rent = comps["monthly_income"]
    estimate = rent.median()
    check, _, _ = regression_predict(rentals, prop.lat, prop.lon, prop.bedrooms, prop.type)
    gap = (check - estimate) / estimate * 100
    lines = rental_lines(estimate, a)
    return {
        "comps": comps, "radius": radius,
        "estimate": estimate,
        "typical_range": median_range(rent),                      # 80% range for the typical comp
        "middle_half": (rent.quantile(0.25), rent.quantile(0.75)),  # spread of individual rentals
        "check": check, "check_gap": gap, "check_agrees": abs(gap) <= DISAGREE_PERCENT,
        "few_comps": len(comps) < MIN_COMPS,
        "lines": lines, "net": net(lines),
    }


# ---------- Airbnb ----------

def airbnb_basis(airbnb, prop):
    """Everything the Airbnb estimate needs before asking about nights. None if no comps."""
    # Nightly price: what similar listings nearby charge. Price depends on the
    # property, so every license type counts.
    comps, radius = find_comps(airbnb, prop.lat, prop.lon, prop.bedrooms)
    if comps.empty:
        return None

    # Nights booked: depends on the setup, because DC's rules differ.
    if prop.setup == "part":
        hosted, hosted_radius = find_comps(airbnb[airbnb["license_type"] == "hosted"],
                                           prop.lat, prop.lon, prop.bedrooms)
        cap = None
        levels = booking_levels(hosted["nights_booked"])
        source = f"{len(hosted)} hosted listings within {hosted_radius} mi"
    else:
        unhosted = airbnb[airbnb["license_type"] == "unhosted"]  # too few to use only nearby ones
        cap = VACATION_RENTAL_CAP
        levels = booking_levels(unhosted["nights_booked"], cap=cap)
        source = f"all {len(unhosted)} unhosted listings in DC"

    return {
        "comps": comps, "radius": radius, "cap": cap, "source": source,
        "price": comps["nightly_price"].median(),
        "price_range": median_range(comps["nightly_price"]),
        "low": levels[0], "typical": levels[1], "strong": levels[2],
    }


def airbnb_analysis(basis, prop, nights, a):
    """Income at each booking level, and costs at the chosen nights.

    nights: the user's estimate, or None to use the typical (median).
    """
    def lines_at(n):
        return airbnb_lines(basis["price"], n, prop.bedrooms, prop.setup, a)

    levels = [("Low bookings", basis["low"]), ("Typical bookings", basis["typical"]),
              ("Strong bookings", basis["strong"])]
    if basis["cap"]:
        levels.append(("Maximum allowed", basis["cap"]))
    if nights is not None:
        levels.append(("Your estimate", nights))

    chosen_level = "Your estimate" if nights is not None else "Typical bookings"
    chosen = nights if nights is not None else basis["typical"]
    rows = [{"level": name, "nights": n,
             "gross": lines_at(n)[0][1],  # nightly bookings only
             "net": net(lines_at(n)), "chosen": name == chosen_level}
            for name, n in levels]
    lines = lines_at(chosen)
    return {"rows": rows, "chosen_nights": chosen, "lines": lines, "net": net(lines)}


# ---------- Recommendation ----------

def recommendation(rent, airbnb, basis, prop, nights, a):
    """The verdict and supporting notes, as plain sentences."""
    if rent is None or airbnb is None:
        return {"winner": None, "headline": "Not enough comparable listings to compare.", "notes": []}

    based_on = "your estimate of nights" if nights is not None else "typical bookings"
    winner = "Airbnb" if airbnb["net"] > rent["net"] else "Long-term renting"
    headline = (f"With {based_on}: {winner} earns more "
                f"(Airbnb {money(airbnb['net'])} vs. rent {money(rent['net'])} per month, after costs).")

    # Break-even: how many nights Airbnb needs to match renting, after costs.
    break_even = airbnb_break_even_nights(basis["price"], prop.bedrooms, prop.setup, a, rent["net"])
    if basis["cap"] and break_even > basis["cap"]:
        break_even_note = (f"Even at DC's {basis['cap']}-night maximum, renting earns more. "
                           f"Airbnb would need about {break_even:.0f} nights.")
    elif break_even > 365:
        break_even_note = "Airbnb can't match renting here, even booked every night."
    else:
        break_even_note = f"Airbnb earns more than renting if booked more than about {break_even:.0f} nights a year."

    notes = []
    if prop.setup == "whole":
        notes.append("Keep in mind: renting long-term means moving out. A vacation rental earns money "
                     f"only while you're away, up to {VACATION_RENTAL_CAP} nights a year.")
    return {"winner": winner, "headline": headline, "break_even": break_even,
            "break_even_note": break_even_note,
            "not_counted_note": "Not counted: your own time hosting, and income tax (which applies to both).",
            "notes": notes}


LEGAL_NOTES = [
    "DC allows short-term rentals only in your primary residence, with a license.",
    "Rules change, so check with DC's Department of Licensing and Consumer Protection.",
]


def analyze(prop, nights, a, airbnb, rentals, basis=None):
    """Run everything for one property. Returns {"rent", "basis", "airbnb", "recommendation"}."""
    basis = basis if basis is not None else airbnb_basis(airbnb, prop)
    rent = rent_analysis(rentals, prop, a)
    airbnb_result = airbnb_analysis(basis, prop, nights, a) if basis else None
    return {
        "rent": rent, "basis": basis, "airbnb": airbnb_result,
        "recommendation": recommendation(rent, airbnb_result, basis, prop, nights, a),
    }
